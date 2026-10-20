from unittest.mock import patch

from django.core.cache import cache
from django.db import transaction
from django.test import TransactionTestCase, override_settings

from config.test_foundations import TEST_STORAGES
from . import competitor_api as api, competitor_collection as lifecycle
from . import test_competitor_formats_structure as fixtures, test_competitor_reference_structure_api as api_fixtures
from .competitor_formats_structure import read_competitor_formats_structure
from .models import Artifact, JobCancellation, JobRun, JobStep, SourceCitation, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "formats-structure-api"}},
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorFormatsStructureApiTests(TransactionTestCase):
    setUp = fixtures.CompetitorFormatsStructureTests.setUp
    transport = fixtures.CompetitorFormatsStructureTests.transport
    fetcher = fixtures.CompetitorFormatsStructureTests.fetcher
    HTML = fixtures.CompetitorFormatsStructureTests.HTML
    collected = fixtures.CompetitorFormatsStructureTests.collected

    def pair(self):
        cache.clear()
        first, second = fixtures.CompetitorFormatsStructureTests.pair(self)
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/competitor-page-formats/structure/"
        self.query = f"?first_job_id={first.pk}&second_job_id={second.pk}"
        self.client.force_login(self.admin)
        return first, second

    test_bodyless_get_canonical_distinct_ids_exact_scope_and_methods = api_fixtures.CompetitorReferenceStructureApiTests.test_bodyless_get_canonical_distinct_ids_exact_scope_and_methods
    test_both_original_metadata_and_current_actor_caller_source_cancel_or_expiry_loss_after_serialization_withholds = api_fixtures.CompetitorReferenceStructureApiTests.test_both_original_metadata_and_current_actor_caller_source_cancel_or_expiry_loss_after_serialization_withholds
    test_first_cancellation_during_last_second_source_read_after_unchanged_api_metadata_withholds = api_fixtures.CompetitorReferenceStructureApiTests.test_first_cancellation_during_last_second_source_read_after_unchanged_api_metadata_withholds

    def test_genuine_original_private_packet_independent_reader_no_network_or_new_work(self):
        first, second = self.pair(); counts = [model.objects.count() for model in (JobRun, Artifact, UsageReservation)]
        with patch("socket.create_connection", side_effect=AssertionError("No new fetch")):
            response = self.client.get(self.base + self.query, secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(set(response.json()), {"organization_id", "project_id", "structure"})
        self.assertEqual(response.json()["structure"], read_competitor_formats_structure(project=self.project, actor=self.admin,
            first_job_id=first.pk, second_job_id=second.pk))
        self.assertEqual(response["Cache-Control"], "private, no-store"); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(response.json()["structure"]["selected_element_occurrences"], [[2, 1, 0, 0, 1, 0, 0, 0], [0, 0, 1, 1, 0, 1, 1, 1]])
        self.assertNotIn(b"private-contact", response.content)
        self.assertEqual([model.objects.count() for model in (JobRun, Artifact, UsageReservation)], counts)

    def test_existing_format_read_budget_and_dated_pair_contract_stay_separate(self):
        self.pair()
        with override_settings(ACCOUNT_RATE_LIMITS={"competitor_page_formats_read": "1/h/ip"}):
            self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)
            self.assertEqual(self.client.get(self.base.removesuffix("structure/"), secure=True).status_code, 429)
        cache.clear()
        self.assertEqual(self.client.get(self.base.replace("structure/", "comparison/") + self.query, secure=True).status_code, 400)
        dated = self.query.replace("first_job_id", "previous_job_id").replace("second_job_id", "current_job_id")
        self.assertEqual(self.client.get(self.base.replace("structure/", "comparison/") + dated, secure=True).status_code, 409)

    def test_empty_unknown_wrong_uri_origin_and_family_never_fabricate_element_rows(self):
        first, second = self.pair()
        empty = self.collected("/selected/empty", b"<h1>Empty</h1>", "elements-api-empty")
        unavailable = self.collected("/selected/unknown", b"<title>Unclosed", "elements-api-unknown")
        response = self.client.get(self.base + f"?first_job_id={empty.pk}&second_job_id={unavailable.pk}", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["structure"]["selected_element_occurrences"], [[0] * 8, [None] * 8])
        self.assertFalse(response.json()["structure"]["all_rows_observed"])
        same = self.collected("/selected/a", b"<p>Later</p>", "elements-api-same")
        other = self.collected("/selected/other", b"<p>Other</p>", "elements-api-other", origin="https://second.example.invalid")
        for job in (same, other):
            self.assertEqual(self.client.get(self.base + f"?first_job_id={first.pk}&second_job_id={job.pk}", secure=True).status_code, 409)
        JobRun.objects.filter(pk=second.pk).update(handler=lifecycle.HANDLER)
        response = self.client.get(self.base + self.query, secure=True)
        self.assertEqual(response.status_code, 403); self.assertNotIn("structure", response.json())

    def test_actual_last_api_pair_source_original_metadata_status_usage_and_cancellations_withhold(self):
        first, second = self.pair(); source = api._read_pair_sources
        for loss in ("artifact", "step", "citation", "status", "usage", "first-cancel", "second-cancel"):
            with self.subTest(loss=loss), transaction.atomic():
                calls = []
                def late(*args):
                    result = source(*args); calls.append(result)
                    if len(calls) == 3:
                        if loss == "artifact": Artifact.objects.filter(job=first).update(size_bytes=1)
                        elif loss == "step": JobStep.objects.filter(job=first).update(error_category="replacement")
                        elif loss == "citation": SourceCitation.objects.filter(job=first).update(source_title="replacement")
                        elif loss == "status": JobRun.objects.filter(pk=first.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=first).update(actual_units=2)
                        else: JobCancellation.objects.create(job=first if loss == "first-cancel" else second, requested_by=self.owner)
                    return result
                with patch.object(api, "_read_pair_sources", side_effect=late):
                    response = self.client.get(self.base + self.query, secure=True)
                self.assertEqual(len(calls), 3)
                self.assertIn(response.status_code, (403, 409), response.content)
                self.assertNotIn("structure", response.json())
                transaction.set_rollback(True)
        self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)

    def test_actual_final_per_original_source_after_api_metadata_preserves_raw_originals(self):
        first, second = self.pair(); metadata, source = api._metadata, lifecycle._read_source
        with patch.object(api, "_metadata", wraps=metadata) as healthy:
            self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)
        expected = [call.args[0] for call in healthy.call_args_list]
        self.assertEqual(expected, expected[:2] * 4)
        for loss in ("artifact", "step", "citation", "status", "usage", "first-cancel", "second-cancel"):
            with self.subTest(loss=loss), transaction.atomic():
                pins, checked, injected = [], [], []
                def pin(key):
                    value = metadata(key); pins.append(key); return value
                def late(job, project, actor):
                    value = source(job, project, actor)
                    if pins == expected:
                        checked.append(job.pk)
                        if job.pk == expected[-1]:
                            injected.append(loss)
                            if loss == "artifact": Artifact.objects.filter(job=first).update(size_bytes=1)
                            elif loss == "step": JobStep.objects.filter(job=first).update(error_category="replacement")
                            elif loss == "citation": SourceCitation.objects.filter(job=first).update(source_title="replacement")
                            elif loss == "status": JobRun.objects.filter(pk=first.pk).update(status="failed")
                            elif loss == "usage": UsageReservation.objects.filter(job=first).update(actual_units=2)
                            else: JobCancellation.objects.create(job=first if loss == "first-cancel" else second, requested_by=self.owner)
                    return value
                with patch.object(api, "_metadata", side_effect=pin), patch.object(lifecycle, "_read_source", side_effect=late):
                    response = self.client.get(self.base + self.query, secure=True)
                self.assertEqual(pins, expected); self.assertEqual(checked, expected[:2]); self.assertEqual(injected, [loss])
                self.assertIn(response.status_code, (403, 409), response.content); self.assertNotIn("structure", response.json())
                transaction.set_rollback(True)
        self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)
