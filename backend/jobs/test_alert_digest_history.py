import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial
from tenancy.services import create_organization, create_project
from . import alert_digest_history as history, test_alert_digest_delivery as fixtures
from .alert_digest_delivery import reserve_daily_alert_digest, deliver_daily_alert_digest
from .alert_preferences import set_project_alert_preference
from .models import ProjectAlertDelivery


@override_settings(STORAGES=TEST_STORAGES, ALERT_DIGEST_DELIVERY_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", GOOGLE_OAUTH_CLIENT_ID="fixture-client",
    GOOGLE_OAUTH_CLIENT_SECRET="fixture-secret", GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
class DailyDigestHistoryTests(TransactionTestCase):
    captureOnCommitCallbacks = fixtures.DailyDigestDeliveryTests.captureOnCommitCallbacks
    failed = fixtures.DailyDigestDeliveryTests.failed
    deny = fixtures.DailyDigestDeliveryTests.deny
    enable = fixtures.DailyDigestDeliveryTests.enable

    def setUp(self):
        fixtures.DailyDigestDeliveryTests.setUp(self)

    def inspect(self, **changes):
        return history.own_daily_alert_delivery_history(**{**dict(project=self.project, actor=self.user), **changes})

    def other_recipient(self):
        other = get_user_model().objects.create_user("other-daily-history@example.invalid")
        EmailAddress.objects.create(user=other, email=other.email, verified=True, primary=True)
        OrganizationMembership.objects.create(organization=self.organization, user=other, role="viewer")
        with patch("django.utils.timezone.now", return_value=self.intent_at):
            set_project_alert_preference(project=self.project, actor=other, frequency="daily",
                source_families=["crawl_failure", "integration_health"], expected_revision=0)
        return other, reserve_daily_alert_digest(project=self.project, recipient=other)

    def test_genuine_own_other_foreign_private_read_only_and_retained_expiry_off(self):
        self.assertEqual(self.inspect()["rows"], [])
        own_id = reserve_daily_alert_digest(project=self.project, recipient=self.user)
        other, other_id = self.other_recipient()
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.alert_digest_delivery.send_mail", side_effect=AssertionError("SMTP")):
            result = self.inspect()
        self.assertEqual([row["id"] for row in result["rows"]], [own_id])
        self.assertEqual([row["id"] for row in self.inspect(actor=other)["rows"]], [other_id])
        self.assertFalse(any(q["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for q in queries))
        self.assertFalse(any("source_metadata" in q["sql"] or "source_fingerprint" in q["sql"] for q in queries))
        for private in (self.user.email, self.project.canonical_origin, "recipient_id", "primary_address_id",
                        "source_metadata", "source_fingerprint", "claimed_episodes", "preference_revision"):
            self.assertNotIn(private, json.dumps(result))
        EmailAddress.objects.filter(user=self.user).update(verified=False)
        trial = OrganizationTrial.objects.get(organization=self.organization)
        OrganizationTrial.objects.filter(pk=trial.pk).update(ends_at=trial.started_at + timedelta(microseconds=1))
        with override_settings(ALERT_DIGEST_DELIVERY_ENABLED=False):
            self.assertEqual(self.inspect(), result)
        foreign_org = create_organization(user=other, name="Foreign daily history")
        foreign = create_project(organization=foreign_org, user=other, name="Foreign daily history project",
                                 canonical_origin="https://foreign-daily-history.example.invalid")
        with self.assertRaises(PermissionDenied): self.inspect(project=foreign)
        self.assertEqual(self.inspect(project=foreign, actor=other)["rows"], [])

    def test_genuine_transport_acceptance_and_uncertainty_never_delivery_or_retry_authority(self):
        own_id = reserve_daily_alert_digest(project=self.project, recipient=self.user)
        with patch("jobs.alert_digest_delivery.send_mail", return_value=1):
            self.assertEqual(deliver_daily_alert_digest(own_id), "sent")
        own = self.inspect()["rows"][0]
        self.assertEqual(own["state"], "transport_accepted")
        self.assertIsNotNone(own["accepted_at"])
        self.assertIn("not_recipient_delivery_read_incident_or_current_eligibility", self.inspect()["scope"])
        other, other_id = self.other_recipient()
        with patch("jobs.alert_digest_delivery.send_mail", side_effect=OSError("private synthetic SMTP body")):
            self.assertEqual(deliver_daily_alert_digest(other_id), "unknown")
        row = self.inspect(actor=other)["rows"][0]
        self.assertEqual((row["state"], row["error_category"], row["accepted_at"]), ("unknown", "delivery_uncertain", None))
        self.assertNotIn("retry", row)
        ProjectAlertDelivery.objects.filter(pk=other_id).update(error_category="private synthetic SMTP body")
        with self.assertRaises(ValidationError): self.inspect(actor=other)

    def test_final_original_selection_or_current_reader_loss_denies(self):
        row_id = reserve_daily_alert_digest(project=self.project, recipient=self.user)
        original = history._row
        for change, error in ((lambda: OrganizationMembership.objects.filter(user=self.user).delete(), PermissionDenied),
                (lambda: get_user_model().objects.filter(pk=self.user.pk).update(is_active=False), PermissionDenied),
                (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), PermissionDenied),
                (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now()), PermissionDenied),
                (lambda: ProjectAlertDelivery.objects.filter(pk=row_id).update(created_at=timezone.now()), ValidationError)):
            with transaction.atomic():
                def mutate(row, assessed):
                    result = original(row, assessed); change(); return result
                with patch("jobs.alert_digest_history._row", side_effect=mutate), self.assertRaises(error): self.inspect()
                transaction.set_rollback(True)

    def test_explicit_synthetic_history_cap_order_and_date_corruption_only(self):
        reserve_daily_alert_digest(project=self.project, recipient=self.user)
        original = ProjectAlertDelivery.objects.get()
        # Retained-cap fixture only: these clones certify no source, SMTP or historical incidents.
        ProjectAlertDelivery.objects.bulk_create([ProjectAlertDelivery(project=self.project, recipient=self.user,
            preference=original.preference, preference_revision=original.preference_revision,
            primary_address_id=original.primary_address_id, day_start=original.day_start - timedelta(days=index),
            source_metadata=original.source_metadata, source_fingerprint=original.source_fingerprint) for index in range(1, 21)])
        result = self.inspect()
        self.assertTrue(result["has_more"]); self.assertEqual(len(result["rows"]), 20)
        self.assertEqual([row["day_start"] for row in result["rows"]],
                         [(original.day_start - timedelta(days=index)).isoformat() for index in range(20)])
        for fields in ({"day_start": timezone.now().date()}, {"created_at": timezone.now() + timedelta(seconds=1)}):
            with transaction.atomic():
                ProjectAlertDelivery.objects.filter(pk=original.pk).update(**fields)
                with self.assertRaises(ValidationError): self.inspect()
                transaction.set_rollback(True)
