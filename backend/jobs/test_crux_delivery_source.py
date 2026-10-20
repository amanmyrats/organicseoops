from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.email_feedback import record_ses_feedback
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, Project
from . import crux_delivery_source as source, test_crux_threshold_policy as fixtures
from .crux_alert_preferences import set_project_crux_alert_preference
from .models import Artifact, JobRun, JobSchedule, PerformanceObservationSnapshot, ProjectCruxAlertPreference


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
                   GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
class ExactCruxDeliverySourceTests(TransactionTestCase):
    date_part = staticmethod(fixtures.MaterialCruxSourceTests.date_part)
    history = fixtures.MaterialCruxSourceTests.history
    all_metrics = fixtures.MaterialCruxSourceTests.all_metrics

    def setUp(self):
        self.assessed = timezone.now()
        self.end = self.assessed.replace(hour=0, minute=0, second=0, microsecond=0)
        self.start = self.end - timedelta(days=1)
        self.intent_at = self.start - timedelta(hours=1)
        with patch("django.utils.timezone.now", return_value=self.intent_at - timedelta(hours=1)):
            fixtures.MaterialCruxSourceTests.setUp(self)

    def enable(self):
        with patch("django.utils.timezone.now", return_value=self.intent_at):
            return set_project_crux_alert_preference(project=self.project, actor=self.owner, frequency="daily", expected_revision=0)

    def collect(self, key="exact-crux", *, at=None, payload=None):
        with patch("django.utils.timezone.now", return_value=at or self.start):
            return fixtures.MaterialCruxSourceTests.collect(self, payload or self.all_metrics(), key=key)

    def inspect(self, observation_id, *, project=None, recipient=None):
        with patch("django.utils.timezone.now", return_value=self.assessed):
            return source.current_exact_crux_delivery_source(project=project or self.project, recipient=recipient or self.owner,
                                                            observation_id=observation_id)

    def test_default_and_other_intent_avoid_source_io_then_genuine_current_eligibility_is_private_and_read_only(self):
        from .alert_preferences import set_project_alert_preference
        from .summary_preferences import set_project_summary_preference
        set_project_alert_preference(project=self.project, actor=self.owner, frequency="daily",
                                    source_families=["integration_health"], expected_revision=0)
        set_project_summary_preference(project=self.project, actor=self.owner, frequency="weekly", expected_revision=0)
        with CaptureQueriesContext(connection) as queries, patch("jobs.crux_delivery_source.history._source", side_effect=AssertionError("source")):
            self.assertEqual(self.inspect(99999)["state"], "unavailable_crux_intent")
        self.assertFalse(any('"jobs_performanceobservationsnapshot"' in query["sql"] for query in queries))
        self.assertFalse(ProjectCruxAlertPreference.objects.exists())
        self.enable(); row = self.collect()
        with CaptureQueriesContext(connection) as queries, patch("http.client.HTTPSConnection.request", side_effect=AssertionError("network")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")), \
                patch("jobs.services.dispatch_pending", side_effect=AssertionError("dispatch")):
            result = self.inspect(row.pk)
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries))
        self.assertEqual(result["state"], "eligible_current_material_source_not_sent")
        self.assertEqual(result["preference_revision"], 1)
        self.assertEqual((result["day_start"], result["day_end"], result["intent_updated_at"]),
                         (self.start.isoformat(), self.end.isoformat(), self.intent_at.isoformat()))
        self.assertEqual([item["metric"] for item in result["source"]["episodes"]], ["LCP", "INP", "CLS"])
        self.assertEqual(result["source_fingerprint"], self.inspect(row.pk)["source_fingerprint"])
        self.assessed += timedelta(microseconds=1)
        self.assertEqual(result["source_fingerprint"], self.inspect(row.pk)["source_fingerprint"])
        for private in (self.target, self.owner.email, row.raw_artifact.key, "performance_credential", "primary_address", "user_id"):
            self.assertNotIn(private, json.dumps(result))

    def test_actual_day_and_intent_microsecond_boundaries_and_exact_selection_never_fallback(self):
        self.enable()
        before = self.collect("before-day", at=self.start - timedelta(microseconds=1))
        first = self.collect("day-start", at=self.start)
        last = self.collect("day-last", at=self.end - timedelta(microseconds=1))
        after = self.collect("day-end", at=self.end)
        for row in (before, after):
            with patch("jobs.crux_history_source.read_private_artifact", side_effect=AssertionError("out-of-day raw")):
                result = self.inspect(row.pk)
            self.assertEqual(result["state"], "unavailable_source_day_or_intent"); self.assertIsNone(result["source"])
        for row in (first, last):
            self.assertEqual(self.inspect(row.pk)["state"], "eligible_current_material_source_not_sent")
        ProjectCruxAlertPreference.objects.filter(project=self.project).update(updated_at=self.start)
        self.assertEqual(self.inspect(first.pk)["state"], "eligible_current_material_source_not_sent")
        ProjectCruxAlertPreference.objects.filter(project=self.project).update(updated_at=self.start + timedelta(microseconds=1))
        with patch("jobs.crux_history_source.read_private_artifact", side_effect=AssertionError("pre-intent raw")):
            self.assertEqual(self.inspect(first.pk)["state"], "unavailable_source_day_or_intent")
        newer = self.collect("ineligible-newer", at=self.start + timedelta(hours=1),
                             payload=self.all_metrics(lcp=(2500, 2999), inp=(200, None), cls=("0.1", "0.11")))
        result = self.inspect(newer.pk)
        self.assertEqual(result["state"], "unavailable_no_material_candidate")
        self.assertEqual(result["source"]["episodes"], [])
        self.assertEqual(result["source"]["policy"]["source"]["observation_id"], newer.pk)
        PerformanceObservationSnapshot.objects.filter(pk=newer.pk).update(raw_sha256=None)
        with patch("jobs.crux_history_source.read_private_artifact", side_effect=AssertionError("legacy raw")):
            self.assertEqual(self.inspect(newer.pk)["source"]["episodes"], [])

    def test_current_reader_foreign_scope_safe_ids_and_synthetic_job_lineage_denials(self):
        self.enable(); row = self.collect()
        for invalid in (True, 0, -1, "1", 2**53):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError): self.inspect(invalid)
        foreign = deepcopy(self.project); foreign.organization_id += 10000
        with self.assertRaises(PermissionDenied): self.inspect(row.pk, project=foreign)
        different = Project.objects.create(organization=self.organization, name="Other source", canonical_origin="https://other-crux.example.invalid")
        with patch("django.utils.timezone.now", return_value=self.intent_at):
            set_project_crux_alert_preference(project=different, actor=self.owner, frequency="daily", expected_revision=0)
        with self.assertRaises(PermissionDenied): self.inspect(row.pk, project=different)
        # Current viewer recipient is permitted independently of the original source actor's launch role.
        viewer = get_user_model().objects.create_user("crux-viewer@example.invalid", password="fixture-password")
        EmailAddress.objects.create(user=viewer, email=viewer.email, verified=True, primary=True)
        OrganizationMembership.objects.create(organization=self.organization, user=viewer, role="viewer")
        with patch("django.utils.timezone.now", return_value=self.intent_at):
            set_project_crux_alert_preference(project=self.project, actor=viewer, frequency="daily", expected_revision=0)
        self.assertEqual(self.inspect(row.pk, recipient=viewer)["state"], "eligible_current_material_source_not_sent")
        schedule = JobSchedule.objects.create(organization=self.organization, project=self.project, actor=self.owner, handler="audit_performance")
        for fields in ({"schedule_id": schedule.pk, "scheduled_for": self.start}, {"retry_of_id": self.job.pk}):
            with self.subTest(fields=fields), transaction.atomic():
                JobRun.objects.filter(pk=row.job_id).update(**fields)
                with patch("jobs.crux_history_source.read_private_artifact", side_effect=AssertionError("lineage raw")):
                    self.assertEqual(self.inspect(row.pk)["state"], "unavailable_source_day_or_intent")
                transaction.set_rollback(True)
        JobRun.objects.filter(pk=self.job.pk).update(retry_of_id=row.job_id)
        self.assertEqual(self.inspect(row.pk)["state"], "unavailable_source_day_or_intent")

    def test_final_recipient_intent_primary_source_and_authority_loss_denies_after_actual_private_io(self):
        self.enable(); row = self.collect()
        trial = OrganizationTrial.objects.get(organization=self.organization)
        def off_on():
            set_project_crux_alert_preference(project=self.project, actor=self.owner, frequency="off", expected_revision=1)
            set_project_crux_alert_preference(project=self.project, actor=self.owner, frequency="daily", expected_revision=2)
        def primary():
            EmailAddress.objects.filter(user=self.owner).update(primary=False)
            get_user_model().objects.filter(pk=self.owner.pk).update(email="other-crux-primary@example.invalid")
            EmailAddress.objects.create(user=self.owner, email="other-crux-primary@example.invalid", primary=True, verified=True)
        changes = [off_on, primary, lambda: ProjectCruxAlertPreference.objects.filter(project=self.project).update(frequency="off", revision=2),
            lambda: record_ses_feedback(("crux-source-complaint-001", "complaint", (self.owner.email,))),
            lambda: EmailAddress.objects.filter(user=self.owner).update(verified=False),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).delete(),
            lambda: get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=self.assessed),
            lambda: OrganizationTrial.objects.filter(pk=trial.pk).update(ends_at=trial.started_at + timedelta(microseconds=1)),
            lambda: Artifact.objects.filter(pk=row.raw_artifact_id).update(created_at=row.raw_artifact.created_at + timedelta(microseconds=1)),
            lambda: Project.objects.filter(pk=self.project.pk).update(canonical_origin="https://changed-crux.example.invalid")]
        original = source.episodes.current_material_crux_episodes
        for change in changes:
            with self.subTest(change=change), transaction.atomic():
                def then_change(**kwargs):
                    result = original(**kwargs); change(); return result
                with patch("jobs.crux_delivery_source.episodes.current_material_crux_episodes", side_effect=then_change), \
                        self.assertRaises((PermissionDenied, ValidationError)):
                    self.inspect(row.pk)
                transaction.set_rollback(True)
        with patch("jobs.crux_history_source.read_private_artifact", return_value=b"corrupt"), self.assertRaises(ValidationError):
            self.inspect(row.pk)

    def test_fresh_exact_entitlement_expiry_and_day_rollover_cannot_use_frozen_assessment_as_authority(self):
        self.enable(); trial = OrganizationTrial.objects.get(organization=self.organization)
        rollover_row = self.collect()
        original_assessed, original_end = self.assessed, self.end
        # Real original periods stay in the provider's allowed calendar; only collection/assessment clocks move.
        payload = self.all_metrics()
        self.assessed = trial.ends_at - timedelta(microseconds=1)
        self.end = self.assessed.replace(hour=0, minute=0, second=0, microsecond=0)
        self.start = self.end - timedelta(days=1)
        row = self.collect("expiry-source", at=self.start, payload=payload)
        changed = False
        original = source.episodes.current_material_crux_episodes
        def delayed(**kwargs):
            nonlocal changed
            result = original(**kwargs); changed = True; return result
        def clock(): return trial.ends_at if changed else self.assessed
        with patch("django.utils.timezone.now", side_effect=clock), \
                patch("jobs.crux_delivery_source.episodes.current_material_crux_episodes", side_effect=delayed), \
                self.assertRaises(ValidationError):
            source.current_exact_crux_delivery_source(project=self.project, recipient=self.owner, observation_id=row.pk)
        self.assertTrue(changed)
        with patch("django.utils.timezone.now", return_value=trial.ends_at), self.assertRaises(ValidationError):
            source.current_exact_crux_delivery_source(project=self.project, recipient=self.owner, observation_id=row.pk)
        # Same current entitlement, but the eligible previous completed collection day changes at midnight.
        self.assessed, self.end = original_assessed, original_end; changed = False
        def rollover(): return self.end + timedelta(days=1) if changed else self.assessed
        with patch("django.utils.timezone.now", side_effect=rollover), \
                patch("jobs.crux_delivery_source.episodes.current_material_crux_episodes", side_effect=delayed), \
                self.assertRaises(PermissionDenied):
            source.current_exact_crux_delivery_source(project=self.project, recipient=self.owner, observation_id=rollover_row.pk)
        self.assertTrue(changed)
