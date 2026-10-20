from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from providers.adapters import ProviderResponse
from tenancy.models import OrganizationMembership, MembershipRole
from . import test_visibility_entities as entity_fixtures
from .models import JobStep
from .visibility_history import observation_history
from .visibility_prompts import review_prompt_set


@override_settings(STORAGES=TEST_STORAGES, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class VisibilityHistoryTests(TestCase):
    fixture_project = entity_fixtures.VisibilityEntityTests.fixture_project
    queue = entity_fixtures.VisibilityEntityTests.queue
    execute = entity_fixtures.VisibilityEntityTests.execute
    sample = entity_fixtures.VisibilityEntityTests.sample
    review = entity_fixtures.VisibilityEntityTests.review

    def setUp(self): entity_fixtures.fixture(self)

    def test_like_for_like_keys_annotation_and_unknown_referrals_do_not_claim_improvement(self):
        first = self.sample("Synthetic Brand.", "history-first")
        self.review(first)
        second = self.sample("Synthetic Brand.", "history-second")
        self.review(second)
        history = observation_history(project=self.project, actor=self.owner)
        self.assertEqual(len(history["comparison_groups"]), 1)
        self.assertEqual(history["observations"][0]["evaluation"], "human_evaluated")
        self.assertEqual(history["observations"][0]["changes_from_prior_page_observation"], [])
        JobStep.objects.all().update(created_at=timezone.now() - timedelta(hours=25))
        changed = self.queue("history-lower-token-cap", max_output_tokens=80)
        self.execute(changed, lambda **_: ProviderResponse("Synthetic Brand.", None, (), "req_ok", "resp_ok", 12, 5, "fixture-model"))
        changed.refresh_from_db(); self.review(changed)
        history = observation_history(project=self.project, actor=self.owner)
        self.assertEqual(len(history["comparison_groups"]), 2)
        self.assertEqual(history["observations"][0]["changes_from_prior_page_observation"], ["max_output_tokens"])
        self.assertIsNone(history["referrals"]["visits"])
        self.assertNotIn("improvement", history["observations"][0])
        self.assertEqual(history["observations"][0]["reviewed_at"], changed.visibility_reviews.get().created_at.isoformat())

    def test_keyset_pagination_and_foreign_actor_preserve_exact_scope(self):
        first = self.sample("Unreviewed sample one", "page-first")
        second = self.sample("Unreviewed sample two", "page-second")
        page = observation_history(project=self.project, actor=self.owner, limit=1)
        self.assertEqual([row["id"] for row in page["observations"]], [second.pk])
        self.assertEqual(page["next_before_id"], second.pk)
        older = observation_history(project=self.project, actor=self.owner, limit=1, before_id=page["next_before_id"])
        self.assertEqual([row["id"] for row in older["observations"]], [first.pk])
        self.assertFalse(older["has_more"])
        self.assertEqual(older["observations"][0]["prior_context"], "not_loaded")
        with self.assertRaises(PermissionDenied): observation_history(project=self.project, actor=self.other)
        with self.assertRaises(ValidationError): observation_history(project=self.project, actor=self.owner, before_id=True)

    def test_prompt_requested_returned_model_and_retrospective_entity_context_changes_split_groups(self):
        from .visibility_entities import review_answer
        from tenancy.services import update_project_configuration
        first = self.sample("Synthetic Brand.", "original-method-context")
        self.review(first)
        revised = review_prompt_set(project=self.project, actor=self.owner, **{**self.data,
            "request_key": "history-prompt-correction", "set_id": self.prompt_set.set_id, "expected_revision": 2,
            "prompts": [{**row, "text": row["text"] + " Please explain."} for row in self.prompts]})
        self.model.identifier = "changed-fixture-model"; self.model.save()
        JobStep.objects.all().update(created_at=timezone.now() - timedelta(hours=25))
        changed = self.queue("changed-method-context", prompt_set_id=revised.pk)
        self.execute(changed, lambda **_: ProviderResponse("Synthetic Brand.", None, (), "req_ok", "resp_ok", 12, 5, "changed-returned-model"))
        changed.refresh_from_db(); self.review(changed)
        report = observation_history(project=self.project, actor=self.owner)
        fields = report["observations"][0]["changes_from_prior_page_observation"]
        self.assertTrue({"set_revision", "prompt_sha256", "requested_model", "model_revision", "returned_model"} <= set(fields))
        self.assertEqual(len(report["comparison_groups"]), 2)
        collected_at = report["observations"][0]["collected_at"]
        previous_key = report["observations"][0]["comparison_key"]
        update_project_configuration(project=self.project, user=self.owner, expected_revision=2,
            changes={"competitor_origins": []})
        review_answer(project=self.project, actor=self.owner, job_id=changed.pk, request_key="history-retrospective-review",
            expected_revision=1, expected_configuration_revision=3, matches=[], evaluated=False,
            review_note="Changed entity configuration; retrospective correction only, no improvement claim.", factual_notes=[])
        report = observation_history(project=self.project, actor=self.owner)
        self.assertEqual(report["observations"][0]["collected_at"], collected_at)
        self.assertNotEqual(report["observations"][0]["comparison_key"], previous_key)
        self.assertEqual(report["observations"][0]["evaluation"], "unevaluated")
        self.assertIn("entity_context_sha256", report["observations"][0]["changes_from_prior_page_observation"])

    def test_no_store_read_only_history_api_viewer_empty_foreign_and_bad_cursor(self):
        path = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/visibility-history/"
        browser = Client()
        self.assertEqual(browser.get(path).status_code, 401)
        browser.force_login(self.other); self.assertEqual(browser.get(path).status_code, 404)
        OrganizationMembership.objects.create(organization=self.project.organization, user=self.other, role=MembershipRole.VIEWER)
        response = browser.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response.json()["observations"], [])
        self.assertEqual(response.json()["referrals"]["status"], "unavailable")
        self.assertEqual(browser.get(path + "?before=0").status_code, 400)
        self.assertEqual(browser.get(path + "?before=invalid").status_code, 400)
        self.assertEqual(browser.post(path, {}).status_code, 405)
