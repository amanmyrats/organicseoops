from datetime import timedelta
import json
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, Project
from tenancy.services import create_organization, create_project
from . import crux_digest_history as history, test_crux_digest_delivery as fixtures
from .crux_alert_preferences import set_project_crux_alert_preference
from .models import ProjectCruxAlertDelivery, ProjectCruxEpisodeClaim, ProjectAlertDelivery


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
                   GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars", CRUX_ALERT_DELIVERY_ENABLED=True,
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CruxDigestHistoryTests(TransactionTestCase):
    date_part = staticmethod(fixtures.CruxDigestDeliveryTests.date_part)
    history = fixtures.CruxDigestDeliveryTests.history
    all_metrics = fixtures.CruxDigestDeliveryTests.all_metrics
    collect = fixtures.CruxDigestDeliveryTests.collect
    enable = fixtures.CruxDigestDeliveryTests.enable
    reserve = fixtures.CruxDigestDeliveryTests.reserve
    send = fixtures.CruxDigestDeliveryTests.send
    setUp = fixtures.CruxDigestDeliveryTests.setUp

    def inspect(self, **changes):
        with patch("django.utils.timezone.now", return_value=self.assessed):
            return history.own_daily_crux_delivery_history(**{**dict(project=self.project, actor=self.owner), **changes})

    def other_recipient(self, email="other-crux-history@example.invalid"):
        other = get_user_model().objects.create_user(email)
        EmailAddress.objects.create(user=other, email=other.email, verified=True, primary=True)
        OrganizationMembership.objects.create(organization=self.organization, user=other, role="viewer")
        with patch("django.utils.timezone.now", return_value=self.intent_at):
            set_project_crux_alert_preference(project=self.project, actor=other, frequency="daily", expected_revision=0)
        return other, self.reserve(recipient=other)

    def test_genuine_own_other_foreign_private_read_only_and_retained_history(self):
        self.assertEqual(self.inspect()["rows"], [])
        own_id = self.reserve(); other, other_id = self.other_recipient()
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.crux_digest_delivery.send_mail", side_effect=AssertionError("SMTP")), \
                patch("jobs.crux_digest_source.current_daily_crux_digest_source", side_effect=AssertionError("source")):
            result = self.inspect()
        self.assertEqual([row["id"] for row in result["rows"]], [own_id])
        self.assertEqual([row["id"] for row in self.inspect(actor=other)["rows"]], [other_id])
        self.assertFalse(any(q["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for q in queries))
        self.assertFalse(any(token in q["sql"] for q in queries for token in (
            "source_metadata", "source_fingerprint", "jobs_projectcruxepisodeclaim", "jobs_projectalertdelivery")))
        for private in (self.owner.email, self.target, "recipient_id", "primary_address_id", "source_metadata",
                        "source_fingerprint", "claimed_episodes", "preference_revision", "preference_id"):
            self.assertNotIn(private, json.dumps(result))
        with patch("django.utils.timezone.now", return_value=self.assessed):
            set_project_crux_alert_preference(project=self.project, actor=self.owner, frequency="off", expected_revision=1)
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        trial = OrganizationTrial.objects.get(organization=self.organization)
        OrganizationTrial.objects.filter(pk=trial.pk).update(ends_at=trial.started_at + timedelta(microseconds=1))
        with override_settings(CRUX_ALERT_DELIVERY_ENABLED=False):
            self.assertEqual(self.inspect(), result)
        with patch("django.utils.timezone.now", return_value=self.intent_at - timedelta(hours=1)):
            foreign_org = create_organization(user=other, name="Foreign CrUX history")
            foreign = create_project(organization=foreign_org, user=other, name="Foreign CrUX history project",
                                     canonical_origin="https://foreign-crux-history.example.invalid")
        with self.assertRaises(PermissionDenied): self.inspect(project=foreign)
        self.assertEqual(self.inspect(project=foreign, actor=other)["rows"], [])
        # Same recipient's genuine independent-project reservation cannot enter this history.
        original_project = self.project
        self.project = foreign; self.organization = foreign_org; self.owner = other
        self.target = foreign.canonical_origin + "/fixture"
        self.enable(); self.collect("foreign-history-source")
        foreign_id = self.reserve()
        self.assertIsNotNone(foreign_id)
        self.assertEqual([row["id"] for row in self.inspect()["rows"]], [foreign_id])
        self.assertEqual([row["id"] for row in self.inspect(project=original_project)["rows"]], [other_id])
        self.assertFalse(ProjectAlertDelivery.objects.exists())

    def test_genuine_transport_acceptance_unknown_and_skipped_fixed_categories(self):
        own_id = self.reserve()
        with patch("jobs.crux_digest_delivery.send_mail", return_value=1):
            self.assertEqual(self.send(own_id), "sent")
        row = self.inspect()["rows"][0]
        self.assertEqual((row["state"], row["error_category"]), ("transport_accepted", ""))
        self.assertIsNotNone(row["accepted_at"])
        self.assertIn("not_recipient_delivery_read_regression_or_current_eligibility", self.inspect()["scope"])
        other, other_id = self.other_recipient()
        with patch("jobs.crux_digest_delivery.send_mail", side_effect=OSError("private synthetic SMTP body")):
            self.assertEqual(self.send(other_id), "unknown")
        row = self.inspect(actor=other)["rows"][0]
        self.assertEqual((row["state"], row["error_category"], row["accepted_at"]), ("unknown", "delivery_uncertain", None))
        self.assertNotIn("retry", row)
        ProjectCruxAlertDelivery.objects.filter(pk=other_id).update(error_category="private synthetic SMTP body")
        with self.assertRaises(ValidationError): self.inspect(actor=other)
        # A separate genuine recipient reservation loses eligibility before attempting transport.
        third, third_id = self.other_recipient("skipped-crux-history@example.invalid")
        EmailAddress.objects.filter(user=third).update(verified=False)
        self.assertEqual(self.send(third_id), "skipped")
        row = self.inspect(actor=third)["rows"][0]
        self.assertEqual((row["state"], row["error_category"]), ("skipped", "current_source_or_recipient_changed"))

    def test_final_original_selection_or_current_reader_loss_denies(self):
        row_id = self.reserve(); original = history._row
        for change, error in ((lambda: OrganizationMembership.objects.filter(user=self.owner).delete(), PermissionDenied),
                (lambda: get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False), PermissionDenied),
                (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), PermissionDenied),
                (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=self.assessed), PermissionDenied),
                (lambda: (OrganizationMembership.objects.filter(user=self.owner).update(role="viewer"),
                          Project.objects.filter(pk=self.project.pk).update(access_restricted=True)), PermissionDenied),
                (lambda: ProjectCruxAlertDelivery.objects.filter(pk=row_id).update(created_at=self.assessed + timedelta(microseconds=1)), ValidationError)):
            with transaction.atomic():
                def mutate(row, assessed):
                    result = original(row, assessed); change(); return result
                with patch("jobs.crux_digest_history._row", side_effect=mutate), self.assertRaises(error): self.inspect()
                transaction.set_rollback(True)

    def test_explicit_synthetic_cap_order_sentinel_drift_and_date_status_corruption(self):
        original_id = self.reserve(); original = ProjectCruxAlertDelivery.objects.get(pk=original_id)
        # Retained-history occupancy only: clones certify no collection, claimed episode or SMTP event.
        with patch("django.utils.timezone.now", return_value=self.assessed):
            ProjectCruxAlertDelivery.objects.bulk_create([ProjectCruxAlertDelivery(project=self.project, recipient=self.owner,
                preference=original.preference, preference_revision=original.preference_revision,
                primary_address_id=original.primary_address_id, day_start=original.day_start - timedelta(days=index),
                source_metadata=original.source_metadata, source_fingerprint=original.source_fingerprint) for index in range(1, 21)])
        result = self.inspect()
        self.assertTrue(result["has_more"]); self.assertEqual(len(result["rows"]), 20)
        self.assertEqual([row["day_start"] for row in result["rows"]],
                         [(original.day_start - timedelta(days=index)).isoformat() for index in range(20)])
        sentinel = ProjectCruxAlertDelivery.objects.order_by("day_start").first(); projection = history._row
        def mutate_sentinel(row, assessed):
            result = projection(row, assessed)
            ProjectCruxAlertDelivery.objects.filter(pk=sentinel.pk).update(created_at=self.assessed + timedelta(microseconds=1))
            return result
        with transaction.atomic():
            with patch("jobs.crux_digest_history._row", side_effect=mutate_sentinel), self.assertRaises(ValidationError): self.inspect()
            transaction.set_rollback(True)
        for fields in ({"day_start": self.assessed.date()}, {"created_at": self.assessed + timedelta(microseconds=1)},
                       {"error_category": "raw private failure"}):
            with transaction.atomic():
                ProjectCruxAlertDelivery.objects.filter(pk=original.pk).update(**fields)
                with self.assertRaises(ValidationError): self.inspect()
                transaction.set_rollback(True)
        # Malformed projection-only shapes cannot be stored under SQL constraints.
        row = ProjectCruxAlertDelivery.objects.values("id", "day_start", "state", "error_category", "created_at", "attempted_at", "sent_at").get(pk=original.pk)
        for fields in ({"id": True}, {"id": 2**53}, {"state": "sent"}, {"attempted_at": self.assessed},
                       {"created_at": self.assessed.replace(tzinfo=None)}, {"state": "sending", "attempted_at": row["created_at"] - timedelta(microseconds=1)}):
            with self.assertRaises(ValidationError): history._row({**row, **fields}, self.assessed)
        self.assertEqual(ProjectCruxEpisodeClaim.objects.count(), 3)
