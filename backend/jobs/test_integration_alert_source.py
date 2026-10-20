import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from integrations import test_search_console_sync as fixtures
from integrations.google_oauth import RECONNECT_METHOD, revoke_google_grant
from integrations.google_tokens import GoogleTokenError
from integrations.models import GoogleOAuthGrant, IntegrationConnection
from integrations.search_console_sync import execute_search_console_sync
from tenancy.email_feedback import record_ses_feedback
from tenancy.models import AuditEvent, AuditEventType, Organization, OrganizationMembership, OrganizationTrial, Project, ProjectOriginVerification
from . import integration_alert_source
from .alert_preferences import set_project_alert_preference
from .models import ProjectAlertPreference


@override_settings(GOOGLE_OAUTH_CLIENT_ID="fixture-client", GOOGLE_OAUTH_CLIENT_SECRET="fixture-secret",
                   GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
class DailyIntegrationAlertSourceTests(TestCase):
    def setUp(self):
        self.assessed = timezone.now()
        self.end = self.assessed.replace(hour=0, minute=0, second=0, microsecond=0)
        self.start = self.end - timedelta(days=1)
        self.intent_at = self.start - timedelta(hours=1)
        with patch("django.utils.timezone.now", return_value=self.intent_at - timedelta(hours=1)):
            fixtures.SearchConsoleSyncTests.setUp(self)

    def enable(self, families=None):
        with patch("django.utils.timezone.now", return_value=self.intent_at):
            return set_project_alert_preference(project=self.project, actor=self.user, frequency="daily",
                source_families=families or ["integration_health"], expected_revision=0)

    def deny(self, *, at=None, key="reconnect"):
        with patch("django.utils.timezone.now", return_value=at or self.start):
            job = fixtures.SearchConsoleSyncTests.queue(self, key=key)
            def reject(**_): raise GoogleTokenError("authorization_rejected")
            self.assertTrue(execute_search_console_sync(job.pk, refresh=reject))
        self.grant.refresh_from_db()
        self.connection.refresh_from_db()
        return AuditEvent.objects.get(project=self.project, event_type=AuditEventType.GOOGLE_OAUTH_RECONNECT_REQUIRED)

    def inspect(self, project=None):
        with patch("django.utils.timezone.now", return_value=self.assessed):
            return integration_alert_source.current_daily_integration_alert_source(
                project=project or self.project, recipient=self.user)

    def test_off_other_family_then_actual_worker_candidate_is_minimized_read_only(self):
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.inspect()["state"], "unavailable_integration_alert_intent")
        self.assertFalse(any('"integrations_' in item["sql"] or '"tenancy_auditevent"' in item["sql"] for item in queries))
        self.enable(["crawl_failure"])
        self.assertEqual(self.inspect()["state"], "unavailable_integration_alert_intent")
        with patch("django.utils.timezone.now", return_value=self.intent_at):
            set_project_alert_preference(project=self.project, actor=self.user, frequency="daily",
                source_families=["crawl_failure", "integration_health"], expected_revision=1)
        self.assertEqual(self.inspect()["state"], "unavailable_no_reconnect_candidates")
        audit = self.deny()
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.summary_delivery.send_mail", side_effect=AssertionError("SMTP")), \
                patch("jobs.services.dispatch_pending", side_effect=AssertionError("dispatch")):
            result = self.inspect()
        self.assertEqual(result["rows"], [{"audit_id": audit.pk, "grant_id": self.grant.pk,
            "grant_revision": self.grant.revision, "connection_id": self.connection.pk,
            "source_method": RECONNECT_METHOD, "audit_created_at": audit.created_at.isoformat(),
            "reason": "provider_refresh_rejected"}])
        self.assertEqual((result["day_start"], result["day_end"], result["preference_revision"]),
                         (self.start.isoformat(), self.end.isoformat(), 2))
        self.assertEqual(result["state"], "available_reconnect_candidates_not_sent")
        self.assertFalse(result["has_more"])
        self.assertFalse(any(item["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for item in queries))
        self.assertFalse(any("encrypted_refresh_token" in item["sql"] for item in queries))
        for private in ("fixture", self.user.email, self.project.canonical_origin, "credential_reference", "selected_property"):
            self.assertNotIn(private, json.dumps(result))

    def test_actual_audit_day_and_intent_boundaries_ignore_mutable_grant_date(self):
        self.enable(); audit = self.deny(at=self.start)
        for date, eligible in [(self.start - timedelta(microseconds=1), False), (self.start, True),
                               (self.end - timedelta(microseconds=1), True), (self.end, False)]:
            with self.subTest(date=date), transaction.atomic():
                AuditEvent.objects.filter(pk=audit.pk).update(created_at=date)
                self.assertEqual(bool(self.inspect()["rows"]), eligible)
                transaction.set_rollback(True)
        for saved, eligible in [(self.start - timedelta(microseconds=1), True), (self.start, True),
                                (self.start + timedelta(microseconds=1), False)]:
            with self.subTest(saved=saved), transaction.atomic():
                ProjectAlertPreference.objects.filter(user=self.user).update(updated_at=saved)
                self.assertEqual(bool(self.inspect()["rows"]), eligible)
                transaction.set_rollback(True)
        GoogleOAuthGrant.objects.filter(pk=self.grant.pk).update(updated_at=self.assessed)
        self.assertEqual(self.inspect()["rows"][0]["audit_created_at"], audit.created_at.isoformat())
        foreign = Project.objects.create(organization=self.project.organization, name="Foreign reconnect",
            canonical_origin="https://foreign-reconnect.example.invalid")
        self.assertEqual(self.inspect(project=foreign)["state"], "unavailable_integration_alert_intent")

    def test_legacy_unknown_malformed_duplicate_or_changed_current_source_is_not_an_episode(self):
        self.enable(); audit = self.deny(); original = audit.details.copy()
        for details in ({key: value for key, value in original.items() if key != "method_version"},
                        {key: value for key, value in original.items() if key != "grant_revision"},
                        dict(original, method_version="unsupported-fixture")):
            with transaction.atomic():
                AuditEvent.objects.filter(pk=audit.pk).update(details=details)
                self.assertEqual(self.inspect()["state"], "unavailable_no_reconnect_candidates")
                transaction.set_rollback(True)
        for fields in ({"grant_revision": True}, {"connection_ids": [True]}, {"reason": "private raw error"},
                       {"connection_ids": [self.connection.pk, self.connection.pk]}, {"extra": "private"}):
            with transaction.atomic():
                AuditEvent.objects.filter(pk=audit.pk).update(details=dict(original, **fields))
                with self.assertRaises(ValidationError): self.inspect()
                transaction.set_rollback(True)
        with transaction.atomic():
            duplicate = AuditEvent.objects.create(organization=self.project.organization, project=self.project,
                event_type=AuditEventType.GOOGLE_OAUTH_RECONNECT_REQUIRED, details=original)
            AuditEvent.objects.filter(pk=duplicate.pk).update(created_at=self.start - timedelta(days=2))
            with self.assertRaises(ValidationError): self.inspect()
            transaction.set_rollback(True)
        changes = [(GoogleOAuthGrant, {"revision": self.grant.revision + 1}),
            (GoogleOAuthGrant, {"selected_property_id": "https://foreign.example.invalid"}),
            (GoogleOAuthGrant, {"selected_site_url": "https://foreign.example.invalid/"}),
            (GoogleOAuthGrant, {"scope": "unsupported-fixture"}),
            (GoogleOAuthGrant, {"state": "revocation_pending"}),
            (IntegrationConnection, {"state": "active"}), (IntegrationConnection, {"capabilities": ["csv_import"]}),
            (Project, {"canonical_origin": "https://changed.example.invalid"})]
        for model, fields in changes:
            with self.subTest(fields=fields), transaction.atomic():
                pk = self.grant.pk if model is GoogleOAuthGrant else self.connection.pk if model is IntegrationConnection else self.project.pk
                model.objects.filter(pk=pk).update(**fields)
                self.assertEqual(self.inspect()["rows"], [])
                transaction.set_rollback(True)
        with transaction.atomic():
            foreign = Project.objects.create(organization=self.project.organization, name="Foreign linkage",
                canonical_origin="https://foreign-linkage.example.invalid")
            source = IntegrationConnection.objects.create(project=foreign, provider="google_search_console",
                external_property_id=foreign.canonical_origin, capabilities=["csv_import"],
                available_dimensions=["query"], source_semantics="search_console_performance", source_semantics_version="csv-v1")
            AuditEvent.objects.filter(pk=audit.pk).update(details=dict(original, connection_ids=[self.connection.pk, source.pk]))
            self.assertEqual(self.inspect()["rows"], [])
            transaction.set_rollback(True)
        revoke_google_grant(grant=self.grant, user=self.user, expected_revision=self.grant.revision, remote_revoke=lambda **_: True)
        self.assertEqual(self.inspect()["rows"], [])

    def test_genuine_domain_denial_needs_current_verified_selected_intersection(self):
        verification = ProjectOriginVerification.objects.create(organization=self.project.organization, project=self.project,
            origin=self.project.canonical_origin, challenge_digest="a" * 64, state="verified", verified_at=self.intent_at)
        self.grant = GoogleOAuthGrant.objects.create(organization=self.project.organization, project=self.project, actor=self.user,
            scope=self.grant.scope, encrypted_refresh_token="v1:fixture", state="active", verified_at=self.intent_at,
            selected_property_id="sc-domain:sync.example", selected_site_url="sc-domain:sync.example",
            selected_origins=[self.project.canonical_origin])
        self.connection = IntegrationConnection.objects.create(project=self.project, provider="google_search_console",
            external_property_id=self.grant.selected_property_id, credential_reference=self.grant.credential_reference,
            capabilities=["api_sync", "page_metrics"], available_dimensions=["page"],
            source_semantics="search_console_domain_pages", source_semantics_version="gsc-domain-page-v1",
            timezone="America/Los_Angeles")
        self.enable()
        with patch("django.utils.timezone.now", return_value=self.start), patch("jobs.services.dispatch_pending"):
            from integrations.search_console_sync import queue_search_console_sync
            job = queue_search_console_sync(project=self.project, actor=self.user, connection=self.connection,
                grant=self.grant, day=self.day, dimensions=["page"], idempotency_key="domain-reconnect")
            def reject(**_): raise GoogleTokenError("authorization_rejected")
            self.assertTrue(execute_search_console_sync(job.pk, refresh=reject))
        self.assertEqual(self.inspect()["rows"][0]["connection_id"], self.connection.pk)
        with transaction.atomic():
            GoogleOAuthGrant.objects.filter(pk=self.grant.pk).update(selected_origins=["https://foreign.example.invalid"])
            self.assertEqual(self.inspect()["rows"], [])
            transaction.set_rollback(True)
        ProjectOriginVerification.objects.filter(pk=verification.pk).update(state="revoked", revoked_at=self.assessed)
        self.assertEqual(self.inspect()["rows"], [])

    def test_final_complete_source_and_recipient_losses_fail_closed(self):
        self.enable(); audit = self.deny()
        original_row = integration_alert_source._row
        trial = OrganizationTrial.objects.get(organization=self.project.organization)
        def off_on():
            set_project_alert_preference(project=self.project, actor=self.user, frequency="off",
                source_families=["integration_health"], expected_revision=1)
            set_project_alert_preference(project=self.project, actor=self.user, frequency="daily",
                source_families=["integration_health"], expected_revision=2)
        def change_primary():
            EmailAddress.objects.filter(user=self.user).update(primary=False)
            get_user_model().objects.filter(pk=self.user.pk).update(email="new-reconnect@example.invalid")
            EmailAddress.objects.create(user=self.user, email="new-reconnect@example.invalid", primary=True, verified=True)
        changes = [off_on,
            change_primary,
            lambda: ProjectAlertPreference.objects.filter(user=self.user).update(integration_health=False, crawl_failure=True, revision=2),
            lambda: EmailAddress.objects.filter(user=self.user).update(verified=False),
            lambda: record_ses_feedback(("reconnect-complaint-001", "complaint", (self.user.email,))),
            lambda: OrganizationMembership.objects.filter(user=self.user).delete(),
            lambda: get_user_model().objects.filter(pk=self.user.pk).update(is_active=False),
            lambda: Organization.objects.filter(pk=self.project.organization_id).update(is_suspended=True),
            lambda: Organization.objects.filter(pk=self.project.organization_id).update(is_suspended=True, closed_at=self.assessed),
            lambda: OrganizationTrial.objects.filter(pk=trial.pk).update(ends_at=trial.started_at + timedelta(microseconds=1)),
            lambda: AuditEvent.objects.filter(pk=audit.pk).update(details=dict(audit.details, reason="property_unavailable")),
            lambda: GoogleOAuthGrant.objects.filter(pk=self.grant.pk).update(revision=99),
            lambda: IntegrationConnection.objects.filter(pk=self.connection.pk).update(state="active"),
            lambda: Project.objects.filter(pk=self.project.pk).update(canonical_origin="https://lost.example.invalid")]
        for change in changes:
            with self.subTest(change=change), transaction.atomic():
                def mutate(*args):
                    row = original_row(*args); change(); return row
                with patch("jobs.integration_alert_source._row", side_effect=mutate), self.assertRaises((ValidationError, PermissionDenied)):
                    self.inspect()
                transaction.set_rollback(True)

    def test_natural_exact_expiry_after_projection_uses_fresh_clock(self):
        self.enable(); audit = self.deny()
        trial = OrganizationTrial.objects.get(organization=self.project.organization)
        end = trial.ends_at.replace(hour=0, minute=0, second=0, microsecond=0)
        AuditEvent.objects.filter(pk=audit.pk).update(created_at=end - timedelta(hours=23))
        ProjectAlertPreference.objects.filter(user=self.user).update(updated_at=end - timedelta(days=1))
        expired = False
        original = integration_alert_source._row
        def delay(*args):
            nonlocal expired
            row = original(*args); expired = True; return row
        def clock(): return trial.ends_at if expired else trial.ends_at - timedelta(microseconds=1)
        with patch("django.utils.timezone.now", side_effect=clock), patch("jobs.integration_alert_source._row", side_effect=delay), \
                self.assertRaises(ValidationError):
            integration_alert_source.current_daily_integration_alert_source(project=self.project, recipient=self.user)
        self.assertTrue(expired)

    def test_explicit_synthetic_audit_and_connection_coverage_bounds(self):
        self.enable(); audit = self.deny()
        # Synthetic unrelated revisions test inspection bounds only; none become another incident.
        extras = AuditEvent.objects.bulk_create([AuditEvent(organization=self.project.organization, project=self.project,
            event_type=AuditEventType.GOOGLE_OAUTH_RECONNECT_REQUIRED,
            details=dict(audit.details, grant_revision=index + 100)) for index in range(20)])
        AuditEvent.objects.filter(pk__in=[item.pk for item in extras]).update(created_at=self.start)
        result = self.inspect(); self.assertTrue(result["has_more"])
        self.assertEqual(result["rows"], [])  # Oldest tied-ID original is outside the explicit newest20 coverage.
        AuditEvent.objects.filter(pk=extras[-1].pk).delete()
        self.assertEqual(self.inspect()["rows"][0]["audit_id"], audit.pk)
        self.assertFalse(self.inspect()["has_more"])
        IntegrationConnection.objects.bulk_create([IntegrationConnection(project=self.project, provider="google_analytics_4",
            external_property_id=str(index), capabilities=["api_sync"], source_semantics="synthetic-bounds",
            source_semantics_version="synthetic-v1") for index in range(1, 51)])
        self.assertTrue(self.inspect()["has_more"])
        overflow = IntegrationConnection.objects.filter(project=self.project).order_by("pk")[50]
        original = integration_alert_source._row
        def remove_overflow(*args):
            row = original(*args); IntegrationConnection.objects.filter(pk=overflow.pk).delete(); return row
        with patch("jobs.integration_alert_source._row", side_effect=remove_overflow), self.assertRaises(ValidationError):
            self.inspect()
