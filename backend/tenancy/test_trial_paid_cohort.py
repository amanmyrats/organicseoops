from django.test import TransactionTestCase
import json
from datetime import datetime, timedelta, timezone as utc_timezone
from unittest.mock import patch

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import test_trial_paid_window as fixtures
from .deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
from .models import AuditEvent, AuditEventType, Organization, OrganizationMembership, PaddleCheckoutAttempt, PaddleFirstActiveObservation
from .paddle_checkout import mark_paddle_checkout_sending, reserve_paddle_checkout
from .paddle_jobs import execute_paddle_receipt
from .paddle_webhooks import record_paddle_notification
from .services import approve_organization_trial, create_organization
from .test_paddle_attempt import catalog
from .test_paddle_webhooks import header
from .trial_paid_cohort import COUNT_FIELDS, _retained_originals, inspect_retained_trial_paid_cohort
from .trial_paid_window import WINDOW


@override_settings(**fixtures.OriginalTrialPaidWindowTests._overridden_settings, STAFF_MFA_REQUIRED=True)
class RetainedTrialPaidCohortTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        cache.clear()
        fixtures.OriginalTrialPaidWindowTests.setUp(self)
        self.assessed = self.started + WINDOW
        with patch("django.utils.timezone.now", return_value=self.assessed):
            self.client.force_login(self.staff)
        Authenticator.objects.create(user=self.staff, type=Authenticator.Type.TOTP, data={"secret": "unused-fixture"})
        session = self.client.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa", "at": self.assessed.timestamp()}]
        with patch("django.utils.timezone.now", return_value=self.assessed):
            session.save()
        self.request = RequestFactory().get("/api/platform/acquisition/unused-source-fixture/")
        self.request.user, self.request.session = self.staff, self.client.session
        self.serial = 0

    def inspect(self, at=None, month="2026-09"):
        with patch("django.utils.timezone.now", return_value=at or self.assessed):
            return inspect_retained_trial_paid_cohort(request=self.request, month=month)

    def organization_at(self, started):
        self.serial += 1
        with patch("django.utils.timezone.now", return_value=started):
            owner = get_user_model().objects.create_user(f"cohort-{self.serial}@example.invalid", None)
            EmailAddress.objects.create(user=owner, email=owner.email, primary=True, verified=True)
            organization = create_organization(user=owner, name=f"Synthetic cohort {self.serial}")
        return organization, owner

    def five(self, started=None):
        return [(self.organization, self.owner)] + [self.organization_at(started or self.started) for _ in range(4)]

    def paid_at(self, organization, owner, observed, letter):
        """Actual signed transaction/subscription worker transitions; no fabricated observation."""
        transaction_id, subscription_id, customer_id = (prefix + letter * 26 for prefix in ("txn_", "sub_", "ctm_"))
        with patch("django.utils.timezone.now", return_value=observed):
            if organization.pk == self.organization.pk:
                attempt = self.attempt  # Reuse the real unresolved READY fixture; never bypass recheckout review.
            else:
                attempt = reserve_paddle_checkout(organization=organization, actor=owner, request_key=f"cohort-paid-{letter}")
                mark_paddle_checkout_sending(attempt=attempt, actor=owner, catalog_response=catalog())
            PaddleCheckoutAttempt.objects.filter(pk=attempt.pk).update(state="ready", transaction_id=transaction_id)
            def receipt(event_type, entity_id, event_suffix):
                raw = json.dumps({"event_id": "evt_" + event_suffix, "notification_id": "ntf_" + event_suffix,
                    "event_type": event_type, "occurred_at": observed.isoformat(), "data": {"id": entity_id}}).encode()
                return record_paddle_notification(environment="sandbox", raw_body=raw,
                    signature=header(raw, when=observed), now=observed)[0]
            custom = {"organization_id": str(organization.pk), "checkout_attempt_id": str(attempt.pk), "offer_version": "agency-launch-v1"}
            payment = fixtures.fixtures.SignedPaymentEvidenceTests.provider_response(self)
            payment["data"].update(id=transaction_id, subscription_id=subscription_id, customer_id=customer_id, custom_data=custom)
            transaction = receipt("transaction.completed", transaction_id, letter * 26)
            self.assertEqual(execute_paddle_receipt(transaction.pk, transaction_get=lambda **_: payment), "succeeded")
            subscription = fixtures.fixtures.SignedPaymentEvidenceTests.subscription_response(self)
            subscription["data"].update(id=subscription_id, customer_id=customer_id, custom_data=custom,
                current_billing_period={"starts_at": observed.isoformat(), "ends_at": (observed + timedelta(days=30)).isoformat()})
            active = receipt("subscription.created", subscription_id, "n" + letter * 25)
            self.assertEqual(execute_paddle_receipt(active.pk, subscription_get=lambda **_: subscription), "succeeded")
        self.assertTrue(PaddleFirstActiveObservation.objects.filter(organization=organization).exists())

    def test_complete_genuine_five_organization_mature_source_has_no_writes_network_ids_or_rate(self):
        self.five()
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.inspect()
        self.assertEqual((result["state"], result["eligible_organizations"], result["mature_organizations"]), ("available", 5, 5))
        self.assertEqual((result["observed_within_window"], result["not_observed_within_window"]), (0, 5))
        self.assertFalse(result["rates_available"])
        self.assertEqual(result["assessed_at"], self.assessed.isoformat())
        self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
        for private in ("organization_id", "actor_id", "attempt_id", "source_digest", "observed_at", "reason", self.owner.email):
            self.assertNotIn(private, json.dumps(result))

    def test_actual_signed_payment_mature_half_open_end_and_complementary_small_cells_suppress_all_counts(self):
        organizations = self.five()
        for (organization, owner), letter in zip(organizations, "hijkl"):
            self.paid_at(organization, owner, self.started + WINDOW - timedelta(microseconds=1), letter)
        before = self.inspect(self.assessed - timedelta(microseconds=1))
        self.assertEqual((before["state"], before["mature_organizations"], before["immature_organizations"]), ("available", 0, 5))
        mature = self.inspect()
        self.assertEqual((mature["state"], mature["observed_within_window"], mature["mature_organizations"]), ("available", 5, 5))
        extra, owner = self.organization_at(self.started)
        self.paid_at(extra, owner, self.assessed, "m")
        suppressed = self.inspect()
        self.assertEqual(suppressed["state"], "suppressed")
        self.assertTrue(all(suppressed[key] is None for key in COUNT_FIELDS))

    def test_calendar_range_uses_original_trial_start_not_birth_pending_audit_time_or_duplicate_memberships(self):
        organizations = self.five(datetime(2026, 9, 1, tzinfo=utc_timezone.utc))
        outside, _ = self.organization_at(datetime(2026, 10, 1, tzinfo=utc_timezone.utc))
        OrganizationMembership.objects.create(organization=self.organization, user=self.staff, role="viewer")
        with patch("django.utils.timezone.now", return_value=datetime(2026, 8, 31, tzinfo=utc_timezone.utc)):
            pending = create_organization(user=self.owner, name="Synthetic earlier birth")
        with patch("django.utils.timezone.now", return_value=datetime(2026, 9, 1, tzinfo=utc_timezone.utc)):
            approve_organization_trial(organization=pending, actor=self.staff, reason="Synthetic cohort approval", request=self.request)
        result = self.inspect()
        self.assertEqual((result["state"], result["eligible_organizations"], result["mature_organizations"]), ("available", 6, 6))
        self.assertEqual(result["not_observed_within_window"], 6)
        self.assertEqual(result["unassigned_unknown_trial"], 0)
        self.assertEqual(self.inspect(month=None)["month"], "2026-10")
        for month in (True, 202609, "2026-9", "2026-00", "0000-09", "2026-11", "2026-12", "2026-09?secret"):
            with self.subTest(month=month), self.assertRaises(ValidationError): self.inspect(month=month)

    def test_genuine_later_staff_approved_trials_then_signed_workers_supply_the_same_retained_denominator(self):
        self.five()
        for letter in "opqrs":
            with patch("django.utils.timezone.now", return_value=self.started):
                organization = create_organization(user=self.owner, name=f"Synthetic staff cohort {letter}")
            with patch("django.utils.timezone.now", return_value=self.started + timedelta(days=1)):
                approve_organization_trial(organization=organization, actor=self.staff, reason="Synthetic cohort review", request=self.request)
            self.paid_at(organization, self.owner, self.started + timedelta(days=2), letter)
        result = self.inspect(self.assessed + timedelta(days=1))
        self.assertEqual((result["state"], result["mature_organizations"], result["observed_within_window"],
                          result["not_observed_within_window"]), ("available", 10, 5, 5))
        saved = PaddleFirstActiveObservation.objects.first()
        PaddleFirstActiveObservation.objects.filter(pk=saved.pk).update(observed_at=saved.observed_at + timedelta(microseconds=1))
        with self.assertRaises(ValidationError): self.inspect(self.assessed + timedelta(days=1))

    def test_mixed_mature_immature_unknown_coverage_and_globally_unassigned_are_separate_complete_exclusions(self):
        self.five()
        for _ in range(5):
            unknown, _ = self.organization_at(self.started + timedelta(days=2))
            Organization.objects.filter(pk=unknown.pk).update(paid_activation_tracking=None)
            self.organization_at(self.started + timedelta(days=2))
            with patch("django.utils.timezone.now", return_value=self.started):
                create_organization(user=self.owner, name="Synthetic unassigned pending original")
        result = self.inspect()
        self.assertEqual(result["state"], "available")
        self.assertEqual([result[key] for key in COUNT_FIELDS], [15, 5, 0, 5, 5, 5, 5])
        empty = self.inspect(month="2026-08")
        self.assertEqual((empty["state"], empty["mature_organizations"], empty["observed_within_window"]), ("available", 0, 0))
        self.assertFalse(empty["rates_available"])

    def test_missing_originals_and_unknown_paid_coverage_are_excluded_without_fabricating_outcomes(self):
        organizations = self.five()
        Organization.objects.filter(pk__in=[org.pk for org, _ in organizations]).update(paid_activation_tracking=None)
        result = self.inspect()
        self.assertEqual((result["state"], result["unknown_paid_coverage"], result["mature_organizations"]), ("available", 5, 0))
        self.assertEqual(result["observed_within_window"], 0)
        AuditEvent.objects.filter(event_type=AuditEventType.TRIAL_GRANTED).delete()
        result = self.inspect()
        self.assertEqual((result["state"], result["eligible_organizations"], result["unassigned_unknown_trial"]), ("available", 0, 5))

    def test_complete_scan_overflow_is_unavailable_never_truncated_and_empty_denominator_has_no_percentage(self):
        # No proof on these manager fixtures: they remain globally unassigned, not forged trial starts.
        Organization.objects.bulk_create([Organization(name=f"Synthetic capacity {index}") for index in range(499)])
        result = self.inspect()
        self.assertEqual((result["state"], result["unassigned_unknown_trial"]), ("suppressed", None))
        Organization.objects.create(name="Synthetic overflow")
        result = self.inspect()
        self.assertEqual(result["state"], "capacity_exceeded")
        self.assertTrue(all(result[key] is None for key in COUNT_FIELDS))
        self.assertFalse(result["rates_available"])

    def test_source_tamper_collection_changes_and_staff_totp_session_loss_deny_including_cached_request(self):
        self.five()
        audit = AuditEvent.objects.get(organization=self.organization, event_type=AuditEventType.TRIAL_GRANTED)
        AuditEvent.objects.filter(pk=audit.pk).update(details={"reason": "PRIVATE_TAMPER"})
        with self.assertRaises(ValidationError): self.inspect()
        AuditEvent.objects.filter(pk=audit.pk).update(details=audit.details)
        for change in (lambda: Organization.objects.create(name="Synthetic collection change"),
                       lambda: AuditEvent.objects.filter(pk=audit.pk).delete(),
                       lambda: Organization.objects.filter(pk=self.organization.pk).update(paid_activation_tracking=None),
                       lambda: get_user_model().objects.filter(pk=self.staff.pk).update(is_active=False),
                       lambda: get_user_model().objects.filter(pk=self.staff.pk).update(is_superuser=False),
                       lambda: Authenticator.objects.filter(user=self.staff).delete(),
                       lambda: self.request.session.delete()):
            def read_then_change():
                originals = _retained_originals()
                if read_then_change.calls == 0: change()
                read_then_change.calls += 1
                return originals
            read_then_change.calls = 0
            with transaction.atomic():
                with patch("tenancy.trial_paid_cohort._retained_originals", side_effect=read_then_change):
                    with self.assertRaises((PermissionDenied, ValidationError)): self.inspect()
                transaction.set_rollback(True)  # Restore genuine originals after each negative, never reconstruct proof.
        self.request.user = self.owner
        with self.assertRaises(PermissionDenied): self.inspect()

    def test_customer_erasure_and_current_owner_loss_do_not_erase_restricted_original_cohort_history(self):
        organizations = self.five()
        before = self.inspect()
        organization, owner = organizations[1]
        OrganizationMembership.objects.filter(organization=organization, user=owner).update(role="viewer")
        with patch("django.utils.timezone.now", return_value=self.assessed):
            Organization.objects.filter(pk=organization.pk).update(is_suspended=True, closed_at=self.assessed)
            organization.refresh_from_db()
            run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=organization))
            self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertEqual(self.inspect(), before)

    def test_shared_assessment_remains_frozen_when_source_reads_cross_maturity(self):
        self.five()
        calls = 0
        def clock():
            nonlocal calls
            calls += 1
            # First clock read occurs in persisted-session expiry lookup; second freezes assessment.
            return self.assessed - timedelta(microseconds=1) if calls <= 2 else self.assessed + timedelta(microseconds=1)
        with patch("django.utils.timezone.now", side_effect=clock):
            result = inspect_retained_trial_paid_cohort(request=self.request, month="2026-09")
        self.assertEqual((result["mature_organizations"], result["immature_organizations"]), (0, 5))
        self.assertEqual(result["assessed_at"], (self.assessed - timedelta(microseconds=1)).isoformat())

    def test_actual_private_staff_cohort_get_is_strict_mfa_scoped_minimized_and_read_only(self):
        self.five()
        path = "/api/platform/acquisition/trial-paid-cohorts/2026-09/"
        with patch("django.utils.timezone.now", return_value=self.assessed):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), self.inspect())
            self.assertFalse(any(row["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for row in queries))
            for status, result in ((400, self.client.get(path + "?source=private")),
                                   (400, self.client.generic("GET", path, data=b"{}", content_type="application/json")),
                                   (405, self.client.post(path)), (400, self.client.get(path.replace("2026-09", "2026-9"))),
                                   (409, self.client.get(path.replace("2026-09", "2026-11")))):
                self.assertEqual(result.status_code, status)
                self.assertEqual(result["Cache-Control"], "private, no-store")
                self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
            default = self.client.get("/api/platform/acquisition/trial-paid-cohorts/")
            self.assertEqual(default.status_code, 200)
            self.assertEqual(default.json()["month"], "2026-10")
            Authenticator.objects.filter(user=self.staff).delete()
            self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.client.logout()
        self.assertEqual(self.client.get(path).status_code, 401)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(path).status_code, 403)

    def test_cohort_reads_share_actual_budget_across_month_paths_and_do_not_leak_original_review_errors(self):
        self.five()
        prefix = "/api/platform/acquisition/trial-paid-cohorts/"
        with patch("django.utils.timezone.now", return_value=self.assessed):
            for index in range(5):
                self.assertEqual(self.client.get(prefix + ("2026-09/" if index % 2 else "")).status_code, 200)
            response = self.client.get(prefix + "2026-08/")
            self.assertEqual(response.status_code, 429)
            cache.clear()
            AuditEvent.objects.filter(organization=self.organization, event_type=AuditEventType.TRIAL_GRANTED).update(details={"reason": "PRIVATE_COHORT_REVIEW"})
            response = self.client.get(prefix + "2026-09/")
            self.assertEqual(response.status_code, 409)
            self.assertNotIn("PRIVATE_COHORT_REVIEW", response.content.decode())
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
