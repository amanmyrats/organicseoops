from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
import json
from threading import Barrier
from unittest.mock import patch
from zipfile import ZipFile

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from providers.adapters import ProviderResponse
from tenancy.models import Organization, ProjectConfiguration, OrganizationMembership, MembershipRole
from tenancy.services import update_project_configuration
from . import test_visibility_collection as collection_fixtures
from .models import AIVisibilityAnswerReview, JobStep
from .visibility_collection import queue_visibility_sample
from .visibility_entities import METHOD, candidates, entity_context, review_answer, sample_rates
from .visibility_prompts import review_prompt_set


def fixture(test):
    collection_fixtures.fixture(test)
    update_project_configuration(project=test.project, user=test.owner, expected_revision=1,
        changes={"competitor_origins": ["https://competitor.example.invalid"]})
    test.prompt_set = review_prompt_set(project=test.project, actor=test.owner, **{**test.data, "request_key": "competitor-context",
        "set_id": test.prompt_set.set_id, "expected_revision": 1})
    test.sample_data["prompt_set_id"] = test.prompt_set.pk


@override_settings(STORAGES=TEST_STORAGES, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class VisibilityEntityTests(TransactionTestCase):
    fixture_project = collection_fixtures.VisibilityCollectionTests.fixture_project
    queue = collection_fixtures.VisibilityCollectionTests.queue
    execute = collection_fixtures.VisibilityCollectionTests.execute

    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        fixture(self)

    def sample(self, text, key="entities-sample"):
        JobStep.objects.all().update(created_at=timezone.now() - timedelta(hours=25))
        job = self.queue(key)
        self.execute(job, lambda **_: ProviderResponse(text, None, (), "req_ok", "resp_ok", 12, 5, "fixture-model"))
        job.refresh_from_db(); return job

    def review(self, job, **changes):
        context = entity_context(job, ProjectConfiguration.objects.get(project=self.project))
        rows = candidates(job.output["answer"], context)["matches"]
        rows = [{**row, "decision": "confirmed", "note": "Human checked the exact entity in the full answer."} for row in rows]
        return review_answer(project=self.project, actor=self.owner, job_id=job.pk, request_key="entity-review-" + str(job.pk),
            expected_revision=0, expected_configuration_revision=2, matches=rows, evaluated=True,
            review_note="Reviewed complete answer and every match; absence is a human evaluated sample, not global visibility.", factual_notes=[], **changes)

    def test_unicode_spans_duplicate_aliases_suffix_spoofs_and_unsafe_links_are_explicit(self):
        answer = '😀 Straße STRASSE; https://brand.example.invalid/a https://brand.example.invalid.evil/a https://127.0.0.1/a javascript:evil'
        context = {"brand_aliases": ["STRASSE", "Straße"], "project_domains": ["brand.example.invalid"],
            "competitor_domains": [], "business_facts": "unavailable_no_approved_fact_registry"}
        report = candidates(answer, context)
        brand = [row for row in report["matches"] if row["kind"] == "brand"]
        self.assertEqual([answer[row["start"]:row["end"]] for row in brand], ["Straße", "STRASSE"])
        spoof = answer.index("https://brand.example.invalid.evil")
        self.assertFalse(any(row["kind"] == "project_domain" and row["start"] >= spoof for row in report["matches"]))
        self.assertFalse(report["links"][-1]["safe_syntax"])
        self.assertTrue(all(row["decision"] == "uncertain" for row in report["matches"]))
        self.assertEqual(report["citation_measurement"], "unavailable")

    def test_corrections_are_immutable_scoped_idempotent_and_bind_actual_answer(self):
        job = self.sample("Synthetic Brand is mentioned twice: Synthetic Brand.")
        first = self.review(job); self.assertEqual(self.review(job).pk, first.pk)
        self.assertEqual(first.answer_sha256, sha256(job.output["answer"].encode()).hexdigest())
        with self.assertRaises(ValidationError): first.save()
        with self.assertRaises(PermissionDenied):
            review_answer(project=self.foreign_project, actor=self.other, job_id=job.pk, request_key="foreign-review",
                expected_revision=0, expected_configuration_revision=1, matches=[], evaluated=True, review_note="Foreign", factual_notes=[])
        correction = review_answer(project=self.project, actor=self.owner, job_id=job.pk, request_key="corrected-review",
            expected_revision=1, expected_configuration_revision=2, matches=[{**row, "decision": "uncertain"} for row in first.matches],
            evaluated=True, review_note="Ambiguous same-name reference; retain uncertainty.", factual_notes=[])
        self.assertEqual(correction.revision, 2)
        with self.assertRaises(ValidationError): self.review(job)
        report = sample_rates(project=self.project, actor=self.owner, prompt_set_id=self.prompt_set.pk)
        self.assertEqual(report["groups"][0]["mention_rate"]["denominator"], 0)
        self.assertEqual(report["groups"][0]["exclusions"], {"uncertain_entity": 1})

    def test_rates_count_each_answer_once_and_neutral_branded_citations_denominators_are_separate(self):
        positive = self.sample("Synthetic Brand and Synthetic Brand. https://visibility.example.invalid/a https://visibility.example.invalid/b")
        self.review(positive)
        negative = self.sample("An answer with no configured entity.", "negative-sample")
        self.review(negative)
        report = sample_rates(project=self.project, actor=self.owner, prompt_set_id=self.prompt_set.pk)
        group = report["groups"][0]
        self.assertEqual(group["mention_rate"], {"numerator": 1, "denominator": 2, "percent": "50.00", "state": "sampled_human_evaluated"})
        self.assertEqual(group["neutral_branded_rates"]["branded"]["denominator"], 0)
        self.assertIsNone(group["citation_rate"]["numerator"]); self.assertIsNone(group["citation_rate"]["percent"])
        self.assertEqual(set(group["eligible_sample_ids"]), {positive.pk, negative.pk})
        self.assertEqual(group["competitor_mention_rates"]["competitor.example.invalid"]["numerator"], 0)

    def test_human_competitor_alias_and_factual_uncertainty_are_not_provider_verified(self):
        job = self.sample("Competitor Alpha says a service costs 15 units.")
        row = review_answer(project=self.project, actor=self.owner, job_id=job.pk, request_key="competitor-alias-review",
            expected_revision=0, expected_configuration_revision=2, matches=[{"kind": "competitor", "entity": "competitor.example.invalid",
                "start": 0, "end": 16, "decision": "confirmed", "note": "Human resolved name to configured competitor, not provider identity proof."}],
            evaluated=True, review_note="Reviewed full sample; competitor name only, project brand absent.",
            factual_notes=[{"start": 34, "end": 42, "note": "Unverified price; no approved business-fact evidence exists."}])
        self.assertEqual(row.context["business_facts"], "unavailable_no_approved_fact_registry")
        group = sample_rates(project=self.project, actor=self.owner, prompt_set_id=self.prompt_set.pk)["groups"][0]
        self.assertEqual(group["competitor_mention_rates"]["competitor.example.invalid"]["numerator"], 1)
        self.assertEqual(group["mention_rate"]["numerator"], 0)

    def test_review_export_deletion_and_foreign_project_survive(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        job = self.sample("Synthetic Brand."); row = self.review(job)
        archive = complete_bounded_customer_archive(organization=self.project.organization, actor=self.owner)
        with ZipFile(BytesIO(archive)) as zipped:
            records = json.loads(zipped.read("records/jobs/AIVisibilityAnswerReview.json"))
        self.assertEqual([record["id"] for record in records], [row.pk])
        Organization.objects.filter(pk=self.project.organization_id).update(is_suspended=True, closed_at=timezone.now())
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.project.organization))
        delete_customer_database_records(run=run)
        self.assertFalse(AIVisibilityAnswerReview.objects.filter(pk=row.pk).exists())
        self.assertTrue(type(self.foreign_project).objects.filter(pk=self.foreign_project.pk).exists())

    def test_private_api_csrf_viewer_foreign_and_exact_revision_guards(self):
        job = self.sample("Synthetic Brand.")
        path = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/visibility-samples/{job.pk}/entities/"
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.get(path).status_code, 401)
        browser.force_login(self.other); self.assertEqual(browser.get(path).status_code, 404)
        browser.force_login(self.owner)
        preview = browser.get(path)
        self.assertEqual(preview["Cache-Control"], "private, no-store")
        data = {"request_key": "browser-review", "expected_revision": 0, "expected_configuration_revision": 2,
            "matches": [{**row, "decision": "confirmed"} for row in preview.json()["candidates"]["matches"]],
            "evaluated": True, "review_note": "Full human review of exact answer", "factual_notes": []}
        self.assertEqual(browser.post(path, json.dumps(data), content_type="application/json").status_code, 403)
        browser.get("/_allauth/browser/v1/auth/session", secure=True)
        headers = {"secure": True, "HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value, "HTTP_REFERER": "https://testserver/"}
        response = browser.post(path, json.dumps(data), content_type="application/json", **headers)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["rates"]["groups"][0]["mention_rate"]["denominator"], 1)
        data["request_key"] = "stale-browser-review"
        self.assertEqual(browser.post(path, json.dumps(data), content_type="application/json", **headers).status_code, 409)
        OrganizationMembership.objects.create(organization=self.project.organization, user=self.other, role=MembershipRole.VIEWER)
        browser.force_login(self.other); browser.get("/_allauth/browser/v1/auth/session", secure=True)
        headers["HTTP_X_CSRFTOKEN"] = browser.cookies["csrftoken"].value
        self.assertEqual(browser.get(path).status_code, 200)
        self.assertEqual(browser.post(path, json.dumps(data), content_type="application/json", **headers).status_code, 403)

    def test_unsafe_invalid_duplicate_partial_and_truncated_reviews_never_count_as_negatives(self):
        job = self.sample("Synthetic Brand.")
        config = ProjectConfiguration.objects.get(project=self.project)
        data = {"project": self.project, "actor": self.owner, "job_id": job.pk, "request_key": "invalid-spans",
            "expected_revision": 0, "expected_configuration_revision": 2, "evaluated": True, "review_note": "Human review", "factual_notes": []}
        valid = candidates(job.output["answer"], entity_context(job, config))["matches"][0]
        for matches in ([{**valid, "start": True}], [{**valid, "end": 10000}], [valid, valid],
            [{**valid, "kind": "project_domain", "entity": "127.0.0.1"}], [{**valid, "entity": "foreign_brand"}]):
            with self.subTest(matches=matches), self.assertRaises(ValidationError): review_answer(**data, matches=matches)
        partial = self.sample("Synthetic Brand.", "partial-reviewed")
        # Simulate already-collected incomplete/failed evidence; model save protects real terminal snapshots.
        type(partial).objects.filter(pk=partial.pk).update(status="failed", output={**partial.output, "collection_eligible": False})
        with self.assertRaises(ValidationError): review_answer(**{**data, "job_id": partial.pk}, matches=[])
        truncated = self.sample("Synthetic Brand. " * 110, "truncated-reviewed")
        with self.assertRaises(ValidationError): review_answer(**{**data, "job_id": truncated.pk}, matches=[])
        self.assertFalse(AIVisibilityAnswerReview.objects.exists())
        report = sample_rates(project=self.project, actor=self.owner, prompt_set_id=self.prompt_set.pk)
        self.assertTrue(all(group["mention_rate"]["percent"] is None for group in report["groups"]))


@override_settings(STORAGES=TEST_STORAGES, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class VisibilityEntityConcurrencyTests(TransactionTestCase):
    fixture_project = VisibilityEntityTests.fixture_project

    def setUp(self):
        fixture(self)
        with patch("jobs.services.dispatch_pending"):
            self.job = queue_visibility_sample(project=self.project, actor=self.owner, data=self.sample_data, idempotency_key="review-race-sample")
        collection_fixtures.VisibilityCollectionTests.execute(self, self.job)

    def test_two_connections_cannot_evaluate_same_review_revision(self):
        barrier = Barrier(2)
        def review(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    review_answer(project=self.project, actor=self.owner, job_id=self.job.pk, request_key=f"review-race-{index}",
                        expected_revision=0, expected_configuration_revision=2, matches=[], evaluated=True, review_note="Full human review", factual_notes=[])
                    return "saved"
                except ValidationError: return "changed"
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(review, index) for index in (1, 2)]
            self.assertEqual(sorted(item.result(timeout=40) for item in futures), ["changed", "saved"])
