import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from integrations.models import GoogleOAuthGrant, IntegrationConnection
from tenancy.models import AuditEvent, OrganizationMembership, OrganizationTrial, Project
from . import alert_digest_source as digest, test_alert_delivery_source as crawl_fixtures
from . import test_integration_alert_source as reconnect_fixtures
from .alert_preferences import set_project_alert_preference
from .models import JobRun, ProjectAlertPreference


@override_settings(STORAGES=TEST_STORAGES, GOOGLE_OAUTH_CLIENT_ID="fixture-client",
    GOOGLE_OAUTH_CLIENT_SECRET="fixture-secret", GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
class DailyDigestSourceTests(TransactionTestCase):
    deny = reconnect_fixtures.DailyIntegrationAlertSourceTests.deny
    failed = crawl_fixtures.DailyCrawlAlertSourceTests.failed

    def setUp(self):
        reconnect_fixtures.DailyIntegrationAlertSourceTests.setUp(self)
        self.owner = self.user
        self.organization = self.project.organization
        self.intent_time, self.day_start, self.day_end = self.intent_at, self.start, self.end

    def enable(self, families=None):
        with patch("django.utils.timezone.now", return_value=self.intent_at):
            set_project_alert_preference(project=self.project, actor=self.user, frequency="daily",
                source_families=families or ["crawl_failure", "integration_health"], expected_revision=0)

    def inspect(self):
        with patch("django.utils.timezone.now", return_value=self.assessed):
            return digest.current_daily_digest_source(project=self.project, recipient=self.user)

    def genuine_sources(self):
        self.enable()
        return self.failed(), self.deny()

    def test_off_empty_selected_family_and_genuine_combined_pin_is_private_read_only(self):
        with CaptureQueriesContext(connection) as queries:
            self.assertIsNone(self.inspect())
        self.assertFalse(any('"jobs_jobrun"' in q["sql"] or '"integrations_' in q["sql"] for q in queries))
        self.enable(["crawl_failure"])
        with patch("jobs.integration_alert_source._snapshot", side_effect=AssertionError("unselected source")):
            self.assertIsNone(self.inspect())
            job = self.failed()
            self.assertEqual(self.inspect()["episodes"], [f"crawl:{job.pk}"])
        with patch("django.utils.timezone.now", return_value=self.intent_at):
            set_project_alert_preference(project=self.project, actor=self.user, frequency="daily",
                source_families=["crawl_failure", "integration_health"], expected_revision=1)
        audit = self.deny()
        with CaptureQueriesContext(connection) as queries, \
                patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")), \
                patch("jobs.services.dispatch_pending", side_effect=AssertionError("dispatch")):
            result = self.inspect()
        self.assertEqual(result["episodes"], [f"crawl:{job.pk}", f"reconnect:{self.grant.pk}:{self.grant.revision}"])
        self.assertEqual(result["sources"]["integration_health"]["rows"][0]["audit_id"], audit.pk)
        self.assertEqual(result["source_families"], ["crawl_failure", "integration_health"])
        self.assertEqual((result["day_start"], result["day_end"]), (self.start.isoformat(), self.end.isoformat()))
        self.assertEqual(len(result["source_fingerprint"]), 64)
        self.assertEqual(result, self.inspect())
        self.assertFalse(any(q["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for q in queries))
        self.assertFalse(any("encrypted_refresh_token" in q["sql"] for q in queries))
        for private in (self.user.email, self.project.canonical_origin, "fixture", "credential_reference", "assessed_at"):
            self.assertNotIn(private, json.dumps(result))

    def test_full_source_drift_changes_pin_even_when_minimized_rows_are_identical(self):
        job, _audit = self.genuine_sources()
        # These are explicit corruption/drift fixtures; positive candidates use real workers above.
        JobRun.objects.filter(pk=job.pk).update(error_category="private-error-A")
        original = self.inspect()
        changes = [(JobRun, job.pk, {"error_category": "private-error-B"}),
            (IntegrationConnection, self.connection.pk, {"currency": "TRY"}),
            (IntegrationConnection, self.connection.pk, {"timezone": "UTC"}),
            (GoogleOAuthGrant, self.grant.pk, {"selected_site_url": self.project.canonical_origin}),
            (GoogleOAuthGrant, self.grant.pk, {"updated_at": self.grant.updated_at + timedelta(microseconds=1)})]
        for model, pk, fields in changes:
            with self.subTest(fields=fields), transaction.atomic():
                model.objects.filter(pk=pk).update(**fields)
                changed = self.inspect()
                self.assertEqual(changed["sources"], original["sources"])
                self.assertNotEqual(changed["source_fingerprint"], original["source_fingerprint"])
                transaction.set_rollback(True)

    def test_canonical_digest_keeps_microseconds_and_rejects_invalid_or_overlarge_metadata(self):
        first = self.start.replace(microsecond=1)
        self.assertNotEqual(digest._fingerprint({"date": first}),
                            digest._fingerprint({"date": first + timedelta(microseconds=1)}))
        self.assertEqual(digest._fingerprint({"a": self.start.date(), "b": 1}),
                         digest._fingerprint({"b": 1, "a": self.start.date()}))
        for value in ({"bad": float("nan")}, {"bad": object()}, {"large": "x" * 131072}):
            with self.assertRaises(ValidationError): digest._fingerprint(value)
        self.genuine_sources()
        IntegrationConnection.objects.filter(pk=self.connection.pk).update(available_dimensions=["x" * 131072])
        with self.assertRaises(ValidationError): self.inspect()

    def test_complete_source_and_current_recipient_loss_after_projection_deny(self):
        job, audit = self.genuine_sources()
        trial = OrganizationTrial.objects.get(organization=self.organization)
        reader = digest._READERS["integration_health"]
        changes = [lambda: IntegrationConnection.objects.filter(pk=self.connection.pk).update(currency="TRY"),
            lambda: JobRun.objects.filter(pk=job.pk).update(error_category="crawl_deadline"),
            lambda: AuditEvent.objects.filter(pk=audit.pk).update(created_at=audit.created_at + timedelta(microseconds=1)),
            lambda: Project.objects.filter(pk=self.project.pk).update(canonical_origin="https://changed.example.invalid"),
            lambda: ProjectAlertPreference.objects.filter(user=self.user).update(frequency="off", revision=2),
            lambda: EmailAddress.objects.filter(user=self.user).update(verified=False),
            lambda: OrganizationMembership.objects.filter(user=self.user).delete(),
            lambda: OrganizationTrial.objects.filter(pk=trial.pk).update(ends_at=trial.started_at + timedelta(microseconds=1))]
        for change in changes:
            with self.subTest(change=change), transaction.atomic():
                def mutate(**kwargs):
                    source = reader(**kwargs); change(); return source
                with patch.dict(digest._READERS, integration_health=mutate), self.assertRaises((PermissionDenied, ValidationError)):
                    self.inspect()
                transaction.set_rollback(True)

    def test_independent_family_midnight_and_final_rollover_never_mix_days(self):
        self.genuine_sources()
        original = digest._READERS["crawl_failure"]
        rolled = False
        def clock(): return self.end + timedelta(days=1) if rolled else self.assessed
        def roll(**kwargs):
            nonlocal rolled
            source = original(**kwargs); rolled = True; return source
        with patch("django.utils.timezone.now", side_effect=clock), patch.dict(digest._READERS, crawl_failure=roll), \
                self.assertRaises(PermissionDenied):
            digest.current_daily_digest_source(project=self.project, recipient=self.user)
        rolled = False
        original = digest._READERS["integration_health"]
        with patch("django.utils.timezone.now", side_effect=clock), patch.dict(digest._READERS, integration_health=roll), \
                self.assertRaises(PermissionDenied):
            digest.current_daily_digest_source(project=self.project, recipient=self.user)

    def test_legacy_reconnect_absent_no_old_day_fallback_or_fabricated_episode(self):
        self.enable(["integration_health"]); audit = self.deny()
        AuditEvent.objects.filter(pk=audit.pk).update(details={key: value for key, value in audit.details.items()
                                                           if key != "grant_revision"})
        self.assertIsNone(self.inspect())
        AuditEvent.objects.filter(pk=audit.pk).update(details=audit.details, created_at=self.start - timedelta(microseconds=1))
        self.assertIsNone(self.inspect())
