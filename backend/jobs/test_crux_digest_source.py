from copy import deepcopy
from datetime import date, timedelta
import json
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from config.test_foundations import TEST_STORAGES
from tenancy.email_feedback import record_ses_feedback
from tenancy.models import OrganizationMembership, OrganizationTrial, Project
from . import crux_digest_source as digest, test_crux_delivery_source as fixtures
from .crux_alert_preferences import set_project_crux_alert_preference
from .models import Artifact, JobRun, JobSchedule, PerformanceObservationSnapshot, ProjectCruxAlertPreference


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
                   GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
class CruxDigestSourceTests(TransactionTestCase):
    setUp = fixtures.ExactCruxDeliverySourceTests.setUp
    date_part = staticmethod(fixtures.ExactCruxDeliverySourceTests.date_part)
    history = fixtures.ExactCruxDeliverySourceTests.history
    all_metrics = fixtures.ExactCruxDeliverySourceTests.all_metrics
    enable = fixtures.ExactCruxDeliverySourceTests.enable

    def collect(self, key="digest-crux", *, at=None, payload=None, grain="page", strategy="mobile"):
        with patch("django.utils.timezone.now", return_value=at or self.start):
            return fixtures.fixtures.MaterialCruxSourceTests.collect(
                self, payload or self.all_metrics(), key=key, grain=grain, strategy=strategy)

    def inspect(self, *, project=None, recipient=None):
        with patch("django.utils.timezone.now", return_value=self.assessed):
            return digest.current_daily_crux_digest_source(project=project or self.project, recipient=recipient or self.owner)

    def selected_ids(self, result):
        return [item["source"]["policy"]["source"]["observation_id"] for item in result["sources"] if item["source"] is not None]

    def test_no_intent_empty_and_genuine_newest_collection_then_id_read_only_private_stable_pin(self):
        with CaptureQueriesContext(connection) as queries, patch("jobs.crux_digest_source._ids", side_effect=AssertionError("scan")):
            self.assertEqual(self.inspect()["state"], "unavailable_crux_intent")
        self.assertFalse(any('"jobs_performanceobservationsnapshot"' in query["sql"] for query in queries))
        self.assertFalse(ProjectCruxAlertPreference.objects.exists())
        self.enable()
        self.assertEqual(self.inspect()["state"], "unavailable_no_current_material_candidate")
        first = self.collect("first", at=self.start + timedelta(hours=1))
        second = self.collect("second", at=self.start + timedelta(hours=1))
        with CaptureQueriesContext(connection) as queries, patch("http.client.HTTPSConnection.request", side_effect=AssertionError("network")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("mail")), \
                patch("jobs.services.dispatch_pending", side_effect=AssertionError("dispatch")):
            result = self.inspect()
        self.assertEqual(self.selected_ids(result), [second.pk])
        self.assertEqual(len(result["episodes"]), 3)
        self.assertEqual(result["state"], "eligible_current_material_digest_not_sent")
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries))
        self.assessed += timedelta(microseconds=1)
        self.assertEqual(result["source_fingerprint"], self.inspect()["source_fingerprint"])
        for private in (self.target, self.owner.email, first.raw_artifact.key, "observed_key", "performance_credential", "user_id"):
            self.assertNotIn(private, json.dumps(result))
        # Collection time, rather than job creation or larger ID, is authoritative.
        third = self.collect("larger-id-older-collection", at=self.start)
        self.assertGreater(third.pk, second.pk)
        self.assertEqual(self.selected_ids(self.inspect()), [second.pk])

    def test_newer_ineligible_missing_legacy_corrupt_and_current_day_never_promote_old_eligible(self):
        self.enable(); self.collect("old")
        newer = self.collect("new", at=self.start + timedelta(hours=1),
                             payload=self.all_metrics(lcp=(2500, 2999), inp=(200, None), cls=("0.1", "0.11")))
        result = self.inspect()
        self.assertEqual(self.selected_ids(result), [newer.pk]); self.assertEqual(result["episodes"], [])
        self.assertEqual(result["state"], "unavailable_no_current_material_candidate")
        PerformanceObservationSnapshot.objects.filter(pk=newer.pk).update(raw_sha256=None)
        result = self.inspect()
        self.assertEqual(result["state"], "unavailable_original_raw_integrity")
        self.assertEqual(result["sources"], []); self.assertEqual(result["episodes"], [])
        # Restore actual capture, then demonstrate final same-key current-day correction, not a day-only scan.
        PerformanceObservationSnapshot.objects.filter(pk=newer.pk).update(raw_sha256=newer.raw_sha256)
        latest = self.collect("current-day", at=self.end)
        result = self.inspect()
        self.assertEqual(result["episodes"], [])
        self.assertEqual(result["sources"][0]["state"], "unavailable_source_day_or_intent")
        with patch("jobs.crux_history_source.read_private_artifact", return_value=b"corrupt"), self.assertRaises(ValidationError):
            self.inspect()
        self.assertGreater(latest.collected_at, newer.collected_at)

    def test_genuine_fallback_direct_origin_and_normalized_page_group_equivalence(self):
        self.enable()
        payload = self.all_metrics(); payload["record"]["key"] = {"origin": self.project.canonical_origin, "formFactor": "PHONE"}
        self.collect("fallback", payload=payload)
        direct = self.collect("direct", payload=payload, grain="origin", at=self.start + timedelta(hours=1))
        literal = self.collect("literal", at=self.start + timedelta(hours=2))
        observed = self.target; self.target = self.project.canonical_origin + "/variant"
        payload = self.all_metrics(); payload["record"]["key"]["url"] = observed
        payload["urlNormalizationDetails"] = {"originalUrl": self.target, "normalizedUrl": observed}
        normalized = self.collect("normalized", payload=payload, at=self.start + timedelta(hours=3))
        result = self.inspect()
        self.assertEqual(self.selected_ids(result), [normalized.pk, direct.pk])
        self.assertEqual(len(result["episodes"]), 6)
        self.assertNotIn(literal.pk, self.selected_ids(result))

    def test_device_target_scope_distinctions_and_period_pair_is_not_a_new_group(self):
        self.enable(); old = self.collect("old-period")
        payload = self.all_metrics()
        for period in payload["record"]["collectionPeriods"]:
            for key in ("firstDate", "lastDate"):
                value = period[key]
                period[key] = self.date_part(date(value["year"], value["month"], value["day"]) - timedelta(days=7))
        changed = self.collect("new-period", at=self.start + timedelta(hours=1), payload=payload)
        old_keys = digest.exact.current_exact_crux_delivery_source
        with patch("django.utils.timezone.now", return_value=self.assessed):
            first_keys = old_keys(project=self.project, recipient=self.owner, observation_id=old.pk)["source"]["episodes"]
        payload = self.all_metrics(); payload["record"]["key"]["formFactor"] = "DESKTOP"
        desktop = self.collect("desktop", strategy="desktop", payload=payload, at=self.start + timedelta(hours=2))
        self.target = self.project.canonical_origin + "/different"
        target = self.collect("target", at=self.start + timedelta(hours=3))
        result = self.inspect()
        self.assertEqual(self.selected_ids(result), [target.pk, desktop.pk, changed.pk])
        self.assertEqual(len(set(result["episodes"])), 9)
        self.assertTrue(set(item["episode_key"] for item in first_keys).isdisjoint(result["episodes"]))
        foreign = deepcopy(self.project); foreign.organization_id += 10000
        with self.assertRaises(PermissionDenied): self.inspect(project=foreign)
        other = Project.objects.create(organization=self.organization, name="Independent", canonical_origin="https://other-crux.example.invalid")
        with patch("django.utils.timezone.now", return_value=self.intent_at):
            set_project_crux_alert_preference(project=other, actor=self.owner, frequency="daily", expected_revision=0)
        self.assertEqual(self.inspect(project=other)["sources"], [])
        # Current viewer recipient is independent of original source launch actor.
        viewer = get_user_model().objects.create_user("digest-viewer@example.invalid", password="fixture-password")
        EmailAddress.objects.create(user=viewer, email=viewer.email, verified=True, primary=True)
        OrganizationMembership.objects.create(organization=self.organization, user=viewer, role="viewer")
        with patch("django.utils.timezone.now", return_value=self.intent_at):
            set_project_crux_alert_preference(project=self.project, actor=viewer, frequency="daily", expected_revision=0)
        self.assertEqual(self.inspect(recipient=viewer)["episodes"], result["episodes"])

    def test_day_intent_and_actual_lineage_gates_apply_after_newest_selection(self):
        self.enable(); self.collect("older"); newest = self.collect("newest", at=self.end - timedelta(microseconds=1))
        self.assertEqual(self.selected_ids(self.inspect()), [newest.pk])
        schedule = JobSchedule.objects.create(organization=self.organization, project=self.project, actor=self.owner, handler="audit_performance")
        changes = [{"schedule_id": schedule.pk, "scheduled_for": self.start}, {"retry_of_id": self.job.pk},
                   {"created_at": self.intent_at - timedelta(microseconds=1)}]
        for fields in changes:
            with self.subTest(fields=fields), transaction.atomic():
                JobRun.objects.filter(pk=newest.job_id).update(**fields)
                result = self.inspect()
                self.assertEqual(result["episodes"], [])
                self.assertEqual(result["sources"][0]["state"], "unavailable_source_day_or_intent")
                transaction.set_rollback(True)
        JobRun.objects.filter(pk=self.job.pk).update(retry_of_id=newest.job_id)
        self.assertEqual(self.inspect()["episodes"], [])

    def test_complete_collection_overflow_queries_actual_database_and_never_reads_partial_sources(self):
        self.enable(); original = self.collect()
        with transaction.atomic(), patch("jobs.crux_digest_source.COLLECTION_LIMIT", 2):
            self.collect("boundary-two")
            self.assertEqual(self.inspect()["state"], "eligible_current_material_digest_not_sent")
            self.collect("overflow-three")
            with patch("jobs.crux_digest_source.history._source", side_effect=AssertionError("incomplete")):
                self.assertEqual(self.inspect()["state"], "unavailable_collection_overflow")
            transaction.set_rollback(True)
        # Explicit synthetic occupancy: only SQL selection/overflow is asserted, not genuine raw-source validity.
        job_fields = {field.attname: getattr(original.job, field.attname) for field in JobRun._meta.concrete_fields if not field.primary_key}
        jobs = JobRun.objects.bulk_create([JobRun(**{**job_fields, "idempotency_key": f"overflow-{index}"}) for index in range(100)])
        fields = {field.attname: getattr(original, field.attname) for field in PerformanceObservationSnapshot._meta.concrete_fields if not field.primary_key}
        PerformanceObservationSnapshot.objects.bulk_create([PerformanceObservationSnapshot(**{**fields, "job_id": job.pk}) for job in jobs])
        self.assertEqual(PerformanceObservationSnapshot.objects.count(), 101)
        with patch("jobs.crux_digest_source.history._source", side_effect=AssertionError("partial source")):
            result = self.inspect()
        self.assertEqual(result["collection_limit"], 100)
        self.assertEqual(result["state"], "unavailable_collection_overflow")
        self.assertIsNone(result["source_fingerprint"])
        self.assertEqual(result["sources"], []); self.assertEqual(result["episodes"], [])

    def test_full_unselected_original_metadata_pin_and_final_collection_raw_and_selection_drift(self):
        self.enable(); old = self.collect("old"); new = self.collect("new", at=self.start + timedelta(hours=1))
        # Give artifact metadata an actual valid microsecond interval within this synthetic frozen clock.
        later = old.collected_at + timedelta(microseconds=2)
        PerformanceObservationSnapshot.objects.filter(pk=old.pk).update(collected_at=later)
        JobRun.objects.filter(pk=old.job_id).update(updated_at=later)
        result = self.inspect()
        Artifact.objects.filter(pk=old.raw_artifact_id).update(created_at=old.raw_artifact.created_at + timedelta(microseconds=1))
        changed = self.inspect()
        self.assertEqual(result["sources"], changed["sources"])
        self.assertNotEqual(result["source_fingerprint"], changed["source_fingerprint"])
        original = digest.exact.current_exact_crux_delivery_source
        mutations = [lambda: Artifact.objects.filter(pk=old.raw_artifact_id).update(size_bytes=old.raw_artifact.size_bytes + 1),
                     lambda: PerformanceObservationSnapshot.objects.filter(pk=old.pk).update(collected_at=old.collected_at + timedelta(microseconds=1)),
                     lambda: self.collect("late-row", at=self.start + timedelta(hours=2)),
                     lambda: JobRun.objects.filter(pk=self.job.pk).update(retry_of_id=new.job_id)]
        for mutate in mutations:
            with self.subTest(mutate=mutate), transaction.atomic():
                def delayed(**kwargs):
                    value = original(**kwargs); mutate(); return value
                with patch("jobs.crux_digest_source.exact.current_exact_crux_delivery_source", side_effect=delayed), \
                        self.assertRaises((PermissionDenied, ValidationError)):
                    self.inspect()
                transaction.set_rollback(True)

    def test_final_current_recipient_binding_natural_expiry_and_completed_day_rollover(self):
        self.enable(); self.collect()
        original = digest._snapshot
        mutations = [lambda: ProjectCruxAlertPreference.objects.filter(project=self.project).update(frequency="off", revision=2),
                     lambda: EmailAddress.objects.filter(user=self.owner).update(primary=False),
                     lambda: OrganizationMembership.objects.filter(user=self.owner, organization=self.organization).delete(),
                     lambda: record_ses_feedback(("digest-complaint-001", "complaint", (self.owner.email,)))]
        for mutate in mutations:
            with self.subTest(mutate=mutate), transaction.atomic():
                calls = 0
                def then_change(*args):
                    nonlocal calls
                    value = original(*args); calls += 1
                    if calls == 2: mutate()
                    return value
                with patch("jobs.crux_digest_source._snapshot", side_effect=then_change), self.assertRaises((PermissionDenied, ValidationError)):
                    self.inspect()
                transaction.set_rollback(True)
        trial = OrganizationTrial.objects.get(organization=self.organization)
        payload = self.all_metrics()
        self.assessed = trial.ends_at - timedelta(microseconds=1)
        self.end = self.assessed.replace(hour=0, minute=0, second=0, microsecond=0)
        self.start = self.end - timedelta(days=1)
        self.collect("expiry", payload=payload)
        for final, error in [(trial.ends_at, ValidationError), (self.end + timedelta(days=1), (PermissionDenied, ValidationError))]:
            calls = 0
            def delayed(*args):
                nonlocal calls
                value = original(*args); calls += 1; return value
            def clock(): return final if calls == 2 else self.assessed
            with patch("django.utils.timezone.now", side_effect=clock), patch("jobs.crux_digest_source._snapshot", side_effect=delayed), self.assertRaises(error):
                digest.current_daily_crux_digest_source(project=self.project, recipient=self.owner)
            self.assertEqual(calls, 2)
