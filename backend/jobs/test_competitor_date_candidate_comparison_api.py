from unittest.mock import patch

from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, ProjectConfiguration
from . import competitor_api as api, competitor_collection as lifecycle
from . import test_competitor_dates_comparison_api as fixtures, test_competitor_comparison_api as boundary_fixtures
from .competitor_date_candidate_comparison import compare_competitor_date_candidates
from .models import Artifact, JobCancellation, JobRun, JobStep, SourceCitation, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "date-candidate-pair-api"}},
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorDateCandidateComparisonApiTests(TransactionTestCase):
    setUp = fixtures.CompetitorDatesComparisonApiTests.setUp
    queue = fixtures.CompetitorDatesComparisonApiTests.queue
    transport = fixtures.CompetitorDatesComparisonApiTests.transport
    collected = fixtures.CompetitorDatesComparisonApiTests.collected

    def pair(self):
        before, after = fixtures.CompetitorDatesComparisonApiTests.pair(self)
        self.base = self.base.replace("comparison/", "candidates/comparison/")
        return before, after

    test_bodyless_canonical_distinct_query_only_and_current_scoped_source_denials = boundary_fixtures.CompetitorComparisonApiTests.test_bodyless_canonical_distinct_query_only_and_current_scoped_source_denials
    test_post_serialization_first_record_source_caller_cancellation_and_expiry_loss_withholds_pair = boundary_fixtures.CompetitorComparisonApiTests.test_post_serialization_first_record_source_caller_cancellation_and_expiry_loss_withholds_pair
    test_first_original_cancellation_during_last_post_serialization_second_source_read_withholds_response = boundary_fixtures.CompetitorComparisonApiTests.test_first_original_cancellation_during_last_post_serialization_second_source_read_withholds_response

    def test_genuine_original_private_pair_independent_reader_unchanged_old_contract_no_writes_network_or_new_work(self):
        before, after = self.pair()
        counts = [model.objects.count() for model in (JobRun, Artifact, UsageReservation)]
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.base+self.query, secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual([model.objects.count() for model in (JobRun, Artifact, UsageReservation)], counts)
        packet = response.json()["comparison"]
        self.assertEqual(packet, compare_competitor_date_candidates(project=self.project, actor=self.owner,
            previous_job_id=before.pk, current_job_id=after.pk))
        old = self.client.get(self.base.replace("candidates/comparison/", "comparison/")+self.query, secure=True)
        self.assertEqual(old.status_code, 200, old.content)
        self.assertEqual(packet["comparison"], old.json()["comparison"])
        self.assertEqual(packet["declaration_pair_candidates"][0]["calendar_day_delta"], 0)
        other = Client(); other.force_login(self.admin)
        self.assertEqual(other.get(self.base+self.query, secure=True).json(), response.json())
        self.assertEqual(response["Cache-Control"], "private, no-store"); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertNotIn(self.owner.email.encode(), response.content)
        cache.clear()
        with override_settings(ACCOUNT_RATE_LIMITS={"competitor_page_dates_read": "1/h/ip"}):
            self.assertEqual(self.client.get(self.base+self.query, secure=True).status_code, 200)
            self.assertEqual(other.get(self.base.replace("candidates/comparison/", ""), secure=True).status_code, 429)

    def test_whole_unknown_vs_empty_and_wrong_family_scope_or_private_bytes_are_closed(self):
        before, after = self.pair()
        empty = self.collected("candidate-empty", b"<p>No declarations</p>")
        unknown = self.collected("candidate-unknown", b"<title>Unclosed")
        response = self.client.get(self.base+f"?previous_job_id={empty.pk}&current_job_id={unknown.pk}", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        packet = response.json()["comparison"]
        self.assertEqual(packet["previous_candidates"], []); self.assertIsNone(packet["current_candidates"])
        self.assertIsNone(packet["declaration_pair_candidates"])
        with transaction.atomic():
            JobRun.objects.filter(pk=after.pk).update(handler="collect_competitor_page_formats")
            self.assertEqual(self.client.get(self.base+self.query, secure=True).status_code, 403)
            transaction.set_rollback(True)
        with patch.object(lifecycle, "read_project_artifact", return_value=b"{}"):
            response = self.client.get(self.base+self.query, secure=True)
        self.assertEqual(response.status_code, 409); self.assertNotIn("comparison", response.json())

    def test_actual_last_api_metadata_and_final_original_source_return_losses_withhold_complete_pair(self):
        before, after = self.pair(); self.client.force_login(self.admin)
        metadata, reader = api._metadata, lifecycle._read_source
        with patch.object(api, "_metadata", wraps=metadata) as healthy:
            self.assertEqual(self.client.get(self.base+self.query, secure=True).status_code, 200)
        expected = [call.args[0] for call in healthy.call_args_list]
        self.assertEqual(set(expected[:2]), {before.pk, after.pk})
        self.assertEqual(expected, expected[:2]*4)
        for boundary, losses in (("metadata", ("actor", "caller", "configuration")),
            ("source", ("artifact", "step", "citation", "status", "usage", "first_cancel", "second_cancel"))):
            for loss in losses:
                with self.subTest(boundary=boundary, loss=loss), transaction.atomic():
                    pins, injected = [], [False]
                    def mutate():
                        injected[0] = True
                        if loss == "actor": OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
                        elif loss == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                        elif loss == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                        elif loss == "artifact": Artifact.objects.filter(job=before).update(size_bytes=1)
                        elif loss == "step": JobStep.objects.filter(job=before).update(error_category="replacement")
                        elif loss == "citation": SourceCitation.objects.filter(job=before).update(source_title="replacement")
                        elif loss == "status": JobRun.objects.filter(pk=before.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=before).update(actual_units=2)
                        else: JobCancellation.objects.create(job=before if loss == "first_cancel" else after, requested_by=self.owner)
                    def pin(key):
                        result = metadata(key); pins.append(key)
                        if pins == expected and boundary == "metadata": mutate()
                        return result
                    def source_changed(*args):
                        result = reader(*args)
                        if pins == expected and boundary == "source" and not injected[0]: mutate()
                        return result
                    with patch.object(api, "_metadata", side_effect=pin), patch.object(lifecycle, "_read_source", side_effect=source_changed):
                        response = self.client.get(self.base+self.query, secure=True)
                    self.assertTrue(injected[0]); self.assertEqual(pins, expected)
                    self.assertIn(response.status_code, (403, 409)); self.assertNotIn("comparison", response.json())
                    transaction.set_rollback(True)
        self.assertEqual(self.client.get(self.base+self.query, secure=True).status_code, 200)
