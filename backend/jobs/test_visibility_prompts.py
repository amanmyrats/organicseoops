from unittest.mock import patch
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from threading import Barrier
from zipfile import ZipFile

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, ProjectConfiguration, OrganizationMembership, MembershipRole
from tenancy.services import create_organization, create_project, update_project_configuration
from .intent_mapping import review_intent_cluster
from .models import AIVisibilityPromptSet, JobRun, UsageReservation
from .visibility_prompts import current_prompt_set, review_prompt_set


@override_settings(STORAGES=TEST_STORAGES,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class VisibilityPromptTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        cache.clear()
        users = get_user_model().objects
        self.owner = users.create_user("visibility-owner@example.invalid", "test-password")
        self.other = users.create_user("visibility-other@example.invalid", "test-password")
        for actor in (self.owner, self.other):
            EmailAddress.objects.create(user=actor, email=actor.email, verified=True, primary=True)
        self.project, self.mapping = self.fixture_project(self.owner, "visibility.example.invalid")
        self.foreign_project, self.foreign_mapping = self.fixture_project(self.other, "foreign-visibility.example.invalid")
        self.prompts = [
            {"key": "neutral-service", "kind": "neutral", "text": "What should a buyer consider for a service in Turkey?", "intent_review_id": self.mapping.pk},
            {"key": "branded-service", "kind": "branded", "text": "What can you tell me about Synthetic Brand services in Turkey?", "intent_review_id": self.mapping.pk},
        ]
        self.data = {"request_key": "prompt-review-1", "label": "Human service intent sample", "language": "en",
            "prompts": self.prompts, "review_note": "Reviewed genuine service questions; brand prompts are a separate leading group, not unbiased discovery.",
            "max_output_tokens": 128, "max_cost_usd": "0.05", "acknowledge_api_limits": True}

    def fixture_project(self, actor, host):
        org = create_organization(user=actor, name="Synthetic visibility org")
        project = create_project(organization=org, user=actor, name="Synthetic visibility project", canonical_origin="https://" + host)
        update_project_configuration(project=project, user=actor, expected_revision=0, changes={
            "target_country": "Turkey", "target_languages": ["en"], "brand_aliases": ["Synthetic Brand"], "seed_topics": ["service questions"]})
        mapping = review_intent_cluster(project=project, actor=actor, request_key="intent-visibility-1",
            label="Service questions", source_finding_ids=[], manual_topics=["service questions"], intent="commercial",
            page_kind="unmapped", preferred_page="", reason="Human seed; no measured demand or page relationship.", language="en")
        return project, mapping

    def review(self, **changes):
        return review_prompt_set(project=self.project, actor=self.owner, **{**self.data, **changes})

    def test_immutable_revision_current_intent_context_and_idempotency_do_not_collect(self):
        row = self.review()
        self.assertEqual(self.review().pk, row.pk)
        self.assertEqual(row.prompts, self.prompts)
        self.assertEqual(row.policy["surface"], "openai_responses_text")
        self.assertEqual(row.policy["citation_measurement"], "unavailable")
        self.assertEqual(row.policy["location_control"], "unsupported")
        self.assertEqual(row.policy["repeat_minimum_hours"], 24)
        row.label = "Cannot overwrite"
        with self.assertRaises(ValidationError): row.save()
        row.refresh_from_db()
        next_row = self.review(request_key="prompt-review-2", set_id=row.set_id, expected_revision=1, label="Reviewed correction")
        self.assertEqual(next_row.revision, 2)
        with self.assertRaises(ValidationError): self.review()
        with self.assertRaises(ValidationError):
            self.review(request_key="prompt-review-3", set_id=row.set_id, expected_revision=1)
        self.assertFalse(JobRun.objects.exists()); self.assertFalse(UsageReservation.objects.exists())
        update_project_configuration(project=self.project, user=self.owner, expected_revision=1, changes={"brand_aliases": ["Changed Brand"]})
        with self.assertRaises(ValidationError): current_prompt_set(project=self.project, actor=self.owner, row=next_row)

    def test_neutral_branded_duplicate_foreign_source_and_budget_guards(self):
        bad = []
        for change in ({"kind": "neutral"}, {"intent_review_id": self.foreign_mapping.pk}, {"text": "x" * 501}, {"kind": []}):
            rows = deepcopy(self.prompts); rows[1].update(change); bad.append(rows)
        bad.append(self.prompts * 3)
        rows = deepcopy(self.prompts); rows[0]["text"] += " visibility.example.invalid"; bad.append(rows)
        for prompts in bad:
            with self.subTest(prompts=prompts), self.assertRaises((ValidationError, PermissionDenied)):
                self.review(prompts=prompts)
        for changes in ({"max_output_tokens": True}, {"max_output_tokens": 257}, {"max_cost_usd": "NaN"}, {"acknowledge_api_limits": False}):
            with self.assertRaises(ValidationError): self.review(**changes)
        row = self.review()
        forged = AIVisibilityPromptSet(project=self.project, actor=self.owner, label=row.label, language=row.language,
            market=row.market, review_note=row.review_note, policy=row.policy, context=row.context,
            request_key="forged-method-1", prompts=[{**prompt, "intent_review_id": self.foreign_mapping.pk} for prompt in self.prompts])
        with self.assertRaises(PermissionDenied): forged.save()
        ProjectConfiguration.objects.filter(project=self.project).update(seed_topics=[])
        with self.assertRaises(ValidationError): current_prompt_set(project=self.project, actor=self.owner, row=row)
        with self.assertRaises(PermissionDenied):
            review_prompt_set(project=self.project, actor=self.other, **self.data)

    def test_private_api_csrf_role_scope_history_and_honest_unavailable_collection(self):
        path = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/visibility-prompts/"
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.get(path).status_code, 401)
        browser.force_login(self.other); self.assertEqual(browser.get(path).status_code, 404)
        browser.force_login(self.owner)
        self.assertEqual(browser.post(path, json.dumps(self.data), content_type="application/json").status_code, 403)
        browser.get("/_allauth/browser/v1/auth/session", secure=True)
        response = browser.post(path, json.dumps(self.data), content_type="application/json", secure=True,
            HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value, HTTP_REFERER="https://testserver/")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertTrue(response.json()["prompt_set"]["collection_available"])
        set_id = response.json()["prompt_set"]["set_id"]
        self.assertEqual(browser.get(path + set_id + "/").status_code, 200)
        OrganizationMembership.objects.create(organization=self.project.organization, user=self.other, role=MembershipRole.VIEWER)
        browser.force_login(self.other)
        browser.get("/_allauth/browser/v1/auth/session", secure=True)
        denied = browser.post(path, json.dumps(self.data), content_type="application/json", secure=True,
            HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value, HTTP_REFERER="https://testserver/")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(browser.get(path).json()["prompt_sets"][0]["set_id"], set_id)

    def test_owner_export_and_registry_deletion_include_only_scoped_customer_methodology(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        own = self.review()
        foreign_prompts = [{**row, "intent_review_id": self.foreign_mapping.pk} for row in self.prompts]
        foreign = review_prompt_set(project=self.foreign_project, actor=self.other, **{**self.data, "prompts": foreign_prompts})
        archive = complete_bounded_customer_archive(organization=self.project.organization, actor=self.owner)
        with ZipFile(BytesIO(archive)) as zipped:
            rows = json.loads(zipped.read("records/jobs/AIVisibilityPromptSet.json"))
        self.assertEqual([row["id"] for row in rows], [own.pk])
        self.assertEqual(rows[0]["prompts"], self.prompts)
        Organization.objects.filter(pk=self.project.organization_id).update(is_suspended=True, closed_at=timezone.now())
        run = prepare_customer_data_deletion(organization=self.project.organization)
        run = sweep_customer_artifact_versions(run=run)
        delete_customer_database_records(run=run)
        self.assertFalse(AIVisibilityPromptSet.objects.filter(pk=own.pk).exists())
        self.assertTrue(AIVisibilityPromptSet.objects.filter(pk=foreign.pk).exists())


@override_settings(STORAGES=TEST_STORAGES,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class VisibilityRevisionConcurrencyTests(TransactionTestCase):
    fixture_project = VisibilityPromptTests.fixture_project

    def setUp(self):
        VisibilityPromptTests.setUp(self)

    def test_two_connections_cannot_correct_the_same_reviewed_revision(self):
        first = review_prompt_set(project=self.project, actor=self.owner, **self.data)
        barrier = Barrier(2)
        def correct(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    review_prompt_set(project=self.project, actor=self.owner, **{**self.data,
                        "request_key": f"race-review-{index}", "label": f"Human correction {index}",
                        "set_id": first.set_id, "expected_revision": 1})
                    return "saved"
                except ValidationError:
                    return "changed"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(correct, index) for index in (1, 2)]
            self.assertEqual(sorted(future.result(timeout=30) for future in futures), ["changed", "saved"])
        self.assertEqual(list(AIVisibilityPromptSet.objects.filter(set_id=first.set_id).order_by("revision")
            .values_list("revision", flat=True)), [1, 2])
