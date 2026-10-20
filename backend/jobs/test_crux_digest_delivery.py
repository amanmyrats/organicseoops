from tenancy.customer_artifact_barrier import project_artifact_barrier
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import json
from threading import Event, Lock
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import close_old_connections, connection, IntegrityError, transaction
from django.test import RequestFactory, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.email_feedback import record_ses_feedback
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, Project
from tenancy.services import create_organization, create_project
from . import crux_digest_delivery as delivery, test_crux_digest_source as fixtures, test_summary_delivery as weekly
from .crux_alert_preferences import set_project_crux_alert_preference
from .models import (Artifact, ProjectCruxAlertDelivery, ProjectCruxEpisodeClaim, ProjectCruxAlertPreference,
                     ProjectAlertDelivery, ProjectAlertEpisodeClaim, ProjectSummaryDelivery)


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
                   GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars", CRUX_ALERT_DELIVERY_ENABLED=True,
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CruxDigestDeliveryTests(TransactionTestCase):
    date_part = staticmethod(fixtures.CruxDigestSourceTests.date_part)
    history = fixtures.CruxDigestSourceTests.history
    all_metrics = fixtures.CruxDigestSourceTests.all_metrics
    collect = fixtures.CruxDigestSourceTests.collect
    enable = fixtures.CruxDigestSourceTests.enable

    def setUp(self):
        fixtures.CruxDigestSourceTests.setUp(self)
        self.enable(); self.observation = self.collect()

    def parallel(self, function):
        # Restore the shared clock only after both worker patch contexts have exited.
        with patch("django.utils.timezone.now", return_value=self.assessed):
            return weekly.WeeklyDeliveryTests.parallel(self, function)

    def reserve(self, *, project=None, recipient=None):
        with patch("django.utils.timezone.now", return_value=self.assessed):
            return delivery.reserve_daily_crux_digest(project=project or self.project, recipient=recipient or self.owner)

    def send(self, row_id):
        with patch("django.utils.timezone.now", return_value=self.assessed):
            return delivery.deliver_daily_crux_digest(row_id)

    def test_parallel_clock_restored_after_overlapping_worker_patches(self):
        original_now = timezone.now
        self.addCleanup(setattr, timezone, "now", original_now)
        first_entered, second_entered, first_finished = Event(), Event(), Event()
        identities, lock = iter((0, 1)), Lock()

        def overlapping():
            with lock:
                index = next(identities)
            if index == 1:
                self.assertTrue(first_entered.wait(timeout=10))
            with patch("django.utils.timezone.now", return_value=self.assessed):
                if index == 0:
                    first_entered.set()
                    self.assertTrue(second_entered.wait(timeout=10))
                else:
                    second_entered.set()
                    self.assertTrue(first_finished.wait(timeout=10))
            if index == 0:
                first_finished.set()
            return index

        self.assertEqual(sorted(self.parallel(overlapping)), [0, 1])
        self.assertIs(timezone.now, original_now)

    @override_settings(DEBUG=True)
    def test_current_recipient_gets_private_turkish_draft_without_changing_source_or_replay(self):
        row_id = self.reserve()
        row = ProjectCruxAlertDelivery.objects.get(pk=row_id)
        original_source = (row.source_metadata, row.source_fingerprint)
        # Preference changes after queue reservation are read from the locked recipient at send time.
        get_user_model().objects.filter(pk=self.owner.pk).update(product_language="tr")
        with patch("jobs.crux_digest_delivery.send_mail", return_value=1) as smtp, \
                patch("socket.create_connection", side_effect=AssertionError("network")):
            self.assertEqual(self.send(row_id), "sent")
            self.assertEqual(self.send(row_id), "sent")
        smtp.assert_called_once()
        subject, body, sender, addresses = smtp.call_args.args
        self.assertEqual(addresses, [self.owner.email])
        self.assertIn("Türkçe taslak", subject)
        for text in ('İsteğe bağlı belirgin CrUX adayları', '3 metrik-dönem adayı', '%20', '500ms LCP', '50ms INP', '0.05 CLS', 'istatistiksel anlamlılık bilinmiyor', 'yeni analiz çalıştırılmadı'):
            self.assertIn(text, subject + body)
        self.assertIn(f"/app/reports/{self.project.organization_id}/{self.project.pk}", body)
        for private in (self.target, self.project.name, self.owner.email, "/shared/"):
            self.assertNotIn(private, subject + body)
        row.refresh_from_db()
        self.assertEqual((row.source_metadata, row.source_fingerprint), original_source)

    @override_settings(DEBUG=False)
    def test_default_off_sql_source_scope_and_concurrent_once_only_transport(self):
        get_user_model().objects.filter(pk=self.owner.pk).update(product_language="tr")
        with override_settings(CRUX_ALERT_DELIVERY_ENABLED=False), self.assertNumQueries(0), \
                patch("jobs.crux_digest_delivery.send_mail", side_effect=AssertionError("SMTP")):
            self.assertIsNone(self.reserve()); self.assertEqual(self.send(99999), "disabled")
        self.assertFalse(ProjectCruxAlertDelivery.objects.exists())
        foreign = deepcopy(self.project); foreign.organization_id += 9999
        with self.assertRaises(PermissionDenied): self.reserve(project=foreign)
        ids = self.parallel(self.reserve)
        self.assertEqual(ids[0], ids[1]); row = ProjectCruxAlertDelivery.objects.get()
        self.assertEqual(row.day_start, self.start.date()); self.assertEqual(ProjectCruxEpisodeClaim.objects.count(), 3)
        self.assertEqual(len(row.source_metadata["claimed_episodes"]), 3)
        for private in (self.target, self.owner.email, "observed_key", "performance_credential", "assessed_at"):
            self.assertNotIn(private, json.dumps(row.source_metadata))
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ProjectCruxAlertDelivery.objects.create(project=self.project, recipient=self.owner, preference=row.preference,
                preference_revision=1, primary_address_id=row.primary_address_id, day_start=row.day_start,
                source_metadata=row.source_metadata, source_fingerprint=row.source_fingerprint)
        for fields in ({"state": "invalid"}, {"preference_revision": 0}, {"state": "sent"}):
            with transaction.atomic(), self.assertRaises(IntegrityError):
                ProjectCruxAlertDelivery.objects.filter(pk=row.pk).update(**fields)
        for key in (row.source_metadata["claimed_episodes"][0], "crawl:1", "crux:" + "g" * 64):
            with transaction.atomic(), self.assertRaises(IntegrityError):
                ProjectCruxEpisodeClaim.objects.create(project=self.project, recipient=self.owner, delivery=row, episode_key=key)
        def accepted(subject, body, sender, addresses, **kwargs):
            self.assertEqual(ProjectCruxAlertDelivery.objects.get(pk=row.pk).state, "sending")
            self.assertEqual(addresses, [self.owner.email])
            for text in ("3 metric-period candidates", "20%", "500ms LCP", "50ms INP", "0.05 CLS", "significance are unknown",
                         "not confirmed SEO regressions", "No new analysis", f"/app/reports/{self.organization.pk}/{self.project.pk}"):
                self.assertIn(text, body)
            for private in (self.target, self.project.name, self.owner.email, "/shared/"):
                self.assertNotIn(private, subject + body)
            return 1
        with patch("jobs.crux_digest_delivery.send_mail", side_effect=accepted) as smtp, patch("socket.create_connection", side_effect=AssertionError("network")):
            states = self.parallel(lambda: self.send(row.pk))
        self.assertIn("sent", states); self.assertLessEqual(set(states), {"sent", "sending"})
        self.assertEqual(smtp.call_count, 1); self.assertEqual(self.reserve(), row.pk)
        self.assertFalse(ProjectAlertDelivery.objects.exists()); self.assertFalse(ProjectAlertEpisodeClaim.objects.exists())
        self.assertFalse(ProjectSummaryDelivery.objects.exists())

    def test_atomic_claim_loss_rolls_back_then_unknown_transport_never_replays(self):
        original = ProjectCruxEpisodeClaim.objects.bulk_create
        def inserted_then_off(rows, *args, **kwargs):
            result = original(rows, *args, **kwargs)
            ProjectCruxAlertPreference.objects.filter(user=self.owner).update(frequency="off", revision=2)
            return result
        with patch.object(ProjectCruxEpisodeClaim.objects, "bulk_create", side_effect=inserted_then_off), self.assertRaises(PermissionDenied):
            self.reserve()
        self.assertFalse(ProjectCruxAlertDelivery.objects.exists()); self.assertFalse(ProjectCruxEpisodeClaim.objects.exists())
        self.assertEqual(ProjectCruxAlertPreference.objects.get().revision, 1)
        row_id = self.reserve()
        for outcome in (0, OSError("private provider failure")):
            with patch("jobs.crux_digest_delivery.send_mail", side_effect=outcome if isinstance(outcome, Exception) else None,
                       return_value=outcome) as smtp:
                self.assertEqual(self.send(row_id), "unknown"); self.assertEqual(self.send(row_id), "unknown")
                self.assertEqual(smtp.call_count, 1)
            self.assertEqual(ProjectCruxAlertDelivery.objects.get().error_category, "delivery_uncertain")
            self.assertEqual(self.reserve(), row_id); self.assertEqual(ProjectCruxEpisodeClaim.objects.count(), 3)
            if outcome == 0:
                # Separate synthetic transport case; production recovery never releases claims.
                ProjectCruxEpisodeClaim.objects.all().delete(); ProjectCruxAlertDelivery.objects.all().delete()
                row_id = self.reserve()

    def test_durable_sending_crash_caller_transaction_and_bounded_stale_recovery(self):
        row_id = self.reserve()
        with transaction.atomic(), self.assertRaises(RuntimeError): self.send(row_id)
        transaction.set_autocommit(False)
        try:
            with self.assertRaises(RuntimeError): self.send(row_id)
        finally:
            transaction.rollback(); transaction.set_autocommit(True)
        def crash(*args, **kwargs):
            def committed():
                close_old_connections()
                try: return ProjectCruxAlertDelivery.objects.get(pk=row_id).state
                finally: connection.close()
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertEqual(pool.submit(committed).result(timeout=10), "sending")
            raise SystemExit("synthetic external-attempt interruption")
        with patch("jobs.crux_digest_delivery.send_mail", side_effect=crash), self.assertRaises(SystemExit): self.send(row_id)
        row = ProjectCruxAlertDelivery.objects.get(); self.assertEqual(row.state, "sending")
        with patch("django.utils.timezone.now", return_value=row.attempted_at + timedelta(minutes=3)), override_settings(CRUX_ALERT_DELIVERY_ENABLED=False):
            self.assertEqual(delivery.recover_daily_crux_digests(), [])
        row.refresh_from_db(); self.assertEqual(row.state, "unknown"); self.assertEqual(row.error_category, "worker_outcome_unknown")
        with patch("jobs.crux_digest_delivery.send_mail", side_effect=AssertionError("replay")):
            self.assertEqual(self.send(row_id), "unknown"); self.assertEqual(self.reserve(), row_id)
        self.assertEqual(ProjectCruxEpisodeClaim.objects.count(), 3)
        with self.assertRaises(ValueError): delivery.recover_daily_crux_digests(limit=21)

    def test_recollection_correction_off_on_and_skipped_claims_dedupe_across_days_but_new_periods_do_not(self):
        row_id = self.reserve()
        self.assessed += timedelta(days=1)
        self.assertEqual(self.send(row_id), "skipped")
        self.assertEqual(ProjectCruxEpisodeClaim.objects.count(), 3)
        self.assertIsNone(self.reserve())
        payload = self.all_metrics(lcp=(2500, 3500), inp=(200, 300), cls=("0.1", "0.2"))
        # Keep the exact original provider periods while collecting on the following day.
        original_periods = self.observation.output["collection_periods"]
        payload["record"]["collectionPeriods"] = [{"firstDate": self.date_part(date.fromisoformat(item["start"])),
            "lastDate": self.date_part(date.fromisoformat(item["end"]))} for item in original_periods]
        self.collect("next-day-same-period", at=self.end, payload=payload)
        self.assertIsNone(self.reserve())
        with patch("django.utils.timezone.now", return_value=self.intent_at + timedelta(microseconds=1)):
            set_project_crux_alert_preference(project=self.project, actor=self.owner, frequency="off", expected_revision=1)
            set_project_crux_alert_preference(project=self.project, actor=self.owner, frequency="daily", expected_revision=2)
        self.assertIsNone(self.reserve())
        for period in payload["record"]["collectionPeriods"]:
            for key in ("firstDate", "lastDate"):
                item = period[key]; period[key] = self.date_part(date(item["year"], item["month"], item["day"]) - timedelta(days=7))
        self.collect("different-period", at=self.end + timedelta(hours=1), payload=payload)
        next_id = self.reserve(); self.assertNotEqual(next_id, row_id)
        self.assertEqual(ProjectCruxEpisodeClaim.objects.count(), 6)
        with patch("jobs.crux_digest_delivery.send_mail", return_value=1) as smtp:
            self.assertEqual(self.send(next_id), "sent"); self.assertEqual(self.send(next_id), "sent")
        self.assertEqual(smtp.call_count, 1)

    def test_final_source_claim_recipient_and_rollout_loss_retains_skipped_reservation(self):
        changes = [lambda: ProjectCruxAlertPreference.objects.filter(user=self.owner).update(frequency="off", revision=2),
            lambda: EmailAddress.objects.filter(user=self.owner).update(verified=False),
            lambda: record_ses_feedback(("crux-kernel-complaint-001", "complaint", (self.owner.email,))),
            lambda: OrganizationMembership.objects.filter(user=self.owner).delete(),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=self.assessed),
            lambda: Artifact.objects.filter(pk=self.observation.raw_artifact_id).update(size_bytes=self.observation.raw_artifact.size_bytes + 1),
            lambda: self.collect("later-correction", at=self.start + timedelta(hours=1)),
            lambda: ProjectCruxEpisodeClaim.objects.filter(pk=ProjectCruxEpisodeClaim.objects.first().pk).update(episode_key="crux:" + "f" * 64)]
        original = delivery._message
        for index, change in enumerate(changes):
            row_id = self.reserve()
            def changed(*args):
                result = original(*args); change(); return result
            with self.subTest(index=index), patch("jobs.crux_digest_delivery._message", side_effect=changed), \
                    patch("jobs.crux_digest_delivery.send_mail", side_effect=AssertionError("SMTP")):
                self.assertEqual(self.send(row_id), "skipped")
            self.assertEqual(ProjectCruxEpisodeClaim.objects.count(), 3)
            self.assertEqual(ProjectCruxAlertDelivery.objects.get().error_category, "current_source_or_recipient_changed")
            self._fixture_teardown(); self._fixture_setup(); self.setUp()
        row_id = self.reserve(); switch = override_settings(CRUX_ALERT_DELIVERY_ENABLED=False)
        def disable(*args):
            result = original(*args); switch.enable(); return result
        try:
            with patch("jobs.crux_digest_delivery._message", side_effect=disable), patch("jobs.crux_digest_delivery.send_mail", side_effect=AssertionError("disabled")):
                self.assertEqual(self.send(row_id), "skipped")
        finally: switch.disable()

    def test_fresh_natural_entitlement_expiry_and_midnight_loss_after_sending_commit(self):
        row_id = self.reserve(); advanced = False; original = delivery._message
        def midnight(): return self.end + timedelta(days=1) if advanced else self.assessed
        def rollover(*args):
            nonlocal advanced
            result = original(*args); advanced = True; return result
        with patch("django.utils.timezone.now", side_effect=midnight), patch("jobs.crux_digest_delivery._message", side_effect=rollover), \
                patch("jobs.crux_digest_delivery.send_mail", side_effect=AssertionError("old day SMTP")):
            self.assertEqual(delivery.deliver_daily_crux_digest(row_id), "skipped")
        self.assertTrue(advanced); self.assertEqual(ProjectCruxEpisodeClaim.objects.count(), 3)
        self._fixture_teardown(); self._fixture_setup(); self.setUp()
        trial = OrganizationTrial.objects.get(organization=self.organization)
        payload = self.all_metrics()
        self.assessed = trial.ends_at - timedelta(microseconds=1)
        self.end = self.assessed.replace(hour=0, minute=0, second=0, microsecond=0)
        self.start = self.end - timedelta(days=1)
        self.collect("natural-expiry", payload=payload)
        row_id = self.reserve(); expired = False; original = delivery._message
        def clock(): return trial.ends_at if expired else self.assessed
        def expire(*args):
            nonlocal expired
            result = original(*args); expired = True; return result
        with patch("django.utils.timezone.now", side_effect=clock), patch("jobs.crux_digest_delivery._message", side_effect=expire), \
                patch("jobs.crux_digest_delivery.send_mail", side_effect=AssertionError("expired SMTP")):
            self.assertEqual(delivery.deliver_daily_crux_digest(row_id), "skipped")
        self.assertTrue(expired); self.assertEqual(ProjectCruxEpisodeClaim.objects.count(), 3)

    def test_customer_export_child_first_erasure_and_personal_close_preserve_other_recipient(self):
        from accounts.closure import close_personal_access
        from tenancy.customer_export import project_customer_rows, _reviewed_fields
        from tenancy.customer_inventory import require_complete_ownership_map
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        from .performance_job import _finish
        own_id = self.reserve()
        other = get_user_model().objects.create_user("other-crux-digest@example.invalid", password="fixture-password")
        EmailAddress.objects.create(user=other, email=other.email, verified=True, primary=True)
        with patch("django.utils.timezone.now", return_value=self.intent_at):
            other_org = create_organization(user=other, name="Other CrUX org")
            other_project = create_project(organization=other_org, user=other, name="Independent", canonical_origin="https://independent-crux.example.invalid")
            OrganizationMembership.objects.create(organization=self.organization, user=other, role="viewer")
            set_project_crux_alert_preference(project=self.project, actor=other, frequency="daily", expected_revision=0)
        other_id = self.reserve(recipient=other)
        require_complete_ownership_map()
        for label, through in (("jobs.ProjectCruxAlertDelivery", other_id),
                               ("jobs.ProjectCruxEpisodeClaim", ProjectCruxEpisodeClaim.objects.latest("pk").pk)):
            _reviewed_fields(label)
            exported = project_customer_rows(organization=self.organization, actor=self.owner, model_label=label, after_id=0, through_id=through)
            self.assertEqual({item["recipient_id"] for item in exported["rows"]}, {self.owner.pk, other.pk})
            self.assertNotIn(self.owner.email, json.dumps(exported, cls=DjangoJSONEncoder))
        # The reused parser fixture also owns an unrelated running lab job/reservation; finish it honestly.
        self.assertTrue(_finish(self.job.pk, error="fixture_cleanup"))
        with project_artifact_barrier(self.organization.pk, shared=True), transaction.atomic():
            Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=self.assessed)
            run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
            delete_customer_database_records(run=run)
            self.assertFalse(ProjectCruxAlertDelivery.objects.filter(project=self.project).exists())
            self.assertFalse(ProjectCruxEpisodeClaim.objects.filter(project=self.project).exists())
            self.assertTrue(Project.objects.filter(pk=other_project.pk).exists())
            transaction.set_rollback(True)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=self.assessed)
        request = RequestFactory().post("/api/account/close/"); request.user = self.owner
        with patch("tenancy.services.did_recently_authenticate", return_value=True):
            close_personal_access(actor=self.owner, request=request)
        self.assertFalse(ProjectCruxAlertDelivery.objects.filter(pk=own_id).exists())
        self.assertFalse(ProjectCruxEpisodeClaim.objects.filter(recipient=self.owner).exists())
        self.assertTrue(ProjectCruxAlertDelivery.objects.filter(pk=other_id).exists())
        self.assertEqual(ProjectCruxEpisodeClaim.objects.filter(recipient=other).count(), 3)
