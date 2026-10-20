import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.mfa.models import Authenticator
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from jobs.models import JobRun, UsageReservation

from .models import (
    AuditEvent, AuditEventType, MembershipRole, NoticeKind, NoticeState, Organization, OrganizationMembership,
    OrganizationNotice, OrganizationTrial, PaddleCheckoutAttempt, PaddleSubscription, PaddleWebhookReceipt, Project,
    TrialState,
)
from .billing_state import paid_access_state
from .notices import (_verified_failed_subscription, deliver_organization_notice, recover_organization_notices,
                      reserve_due_payment_notices, reserve_due_trial_notices, reserve_exhausted_paid_notices)
from .services import TRIAL_DURATION, TRIAL_MEMBER_LIMIT, TRIAL_OFFER_VERSION, TRIAL_PROJECT_LIMIT, TRIAL_UNIT_LIMIT
from .tasks import schedule_organization_notices_task


def assure_staff(browser, user):
    Authenticator.objects.create(user=user, type=Authenticator.Type.TOTP, data={"secret": "unused-fixture"})
    session = browser.session
    session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa", "at": timezone.now().timestamp()}]; session.save()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   FRONTEND_ORIGIN="https://app.example.invalid")
class TrialNoticeTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(email="owner@example.invalid", password="Valid password 99!A")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, primary=True, verified=True)
        self.organization = Organization.objects.create(name="Trial notice fixture")
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.owner, role=MembershipRole.OWNER,
        )
        start = timezone.now() - TRIAL_DURATION + timedelta(hours=12)
        self.trial = OrganizationTrial.objects.create(
            organization=self.organization, offer_version=TRIAL_OFFER_VERSION, state=TrialState.ACTIVE,
            started_at=start, ends_at=start + TRIAL_DURATION, project_limit=TRIAL_PROJECT_LIMIT,
            member_limit=TRIAL_MEMBER_LIMIT, unit_limit=TRIAL_UNIT_LIMIT,
        )

    def _reserve_full_trial_usage(self):
        project = Project.objects.create(organization=self.organization, name="Usage fixture",
                                         canonical_origin="https://trial-notice.example.invalid")
        job = JobRun.objects.create(organization=self.organization, project=project, actor=self.owner,
                                    handler="diagnostic_probe", method_version="fixture-v1",
                                    input_snapshot={"fixture": True})
        return UsageReservation.objects.create(
            job=job, organization=self.organization, project=project, provider="diagnostic",
            period_start=timezone.now().date().replace(day=1), reserved_units=self.trial.unit_limit,
        )

    def _deliver_turkish_draft_to_new_owner(self, reserve):
        other = get_user_model().objects.create_user("locale-owner@example.invalid", "Safe password 99!")
        OrganizationMembership.objects.create(organization=self.organization, user=other, role=MembershipRole.OWNER)
        EmailAddress.objects.create(user=other, email=other.email, primary=True, verified=True)
        notice_id = reserve()[0]
        # Delivery uses the current recipient preference, even when it changed after queueing.
        other.product_language = "tr"
        other.save(update_fields=["product_language"])
        with override_settings(DEBUG=True):
            self.assertEqual(deliver_organization_notice(notice_id), NoticeState.SENT)
        self.assertEqual(mail.outbox[-1].to, [other.email])
        self.assertIn("Türkçe taslak", mail.outbox[-1].subject)
        self.assertIn(f"/app/billing/{self.organization.pk}", mail.outbox[-1].body)
        return mail.outbox[-1]

    def test_trial_allowance_notice_requires_current_exact_ledger_and_no_automatic_charge(self):
        self.assertEqual(reserve_due_trial_notices(kind=NoticeKind.TRIAL_UNITS_EXHAUSTED), [])
        self._reserve_full_trial_usage()
        ids = reserve_due_trial_notices(kind=NoticeKind.TRIAL_UNITS_EXHAUSTED)
        self.assertEqual(len(ids), 1)
        self.assertEqual(reserve_due_trial_notices(kind=NoticeKind.TRIAL_UNITS_EXHAUSTED), [])
        self.assertEqual(deliver_organization_notice(ids[0]), NoticeState.SENT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("No payment starts automatically", mail.outbox[0].body)
        draft = self._deliver_turkish_draft_to_new_owner(
            lambda: reserve_due_trial_notices(kind=NoticeKind.TRIAL_UNITS_EXHAUSTED))
        self.assertIn("Ödeme otomatik olarak başlamaz", draft.body)
        self.assertIn("yeni işler duraklatıldı", draft.body)

    def test_released_reservation_before_delivery_is_not_called_exhausted(self):
        reservation = self._reserve_full_trial_usage()
        notice_id = reserve_due_trial_notices(kind=NoticeKind.TRIAL_UNITS_EXHAUSTED)[0]
        reservation.state = UsageReservation.State.RELEASED
        reservation.settled_at = timezone.now()
        reservation.save(update_fields=["state", "settled_at"])
        self.assertEqual(deliver_organization_notice(notice_id), NoticeState.SKIPPED)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(PADDLE_ENVIRONMENT="sandbox")
    def test_paid_allowance_notice_requires_current_verified_period_and_one_monthly_ledger(self):
        now = timezone.now()
        customer, subscription_id = "ctm_" + "a" * 26, "sub_" + "b" * 26
        subscription = PaddleSubscription.objects.create(
            organization=self.organization, environment="sandbox", customer_id=customer,
            subscription_id=subscription_id, status="active", verified_at=now - timedelta(minutes=1),
            period_starts_at=now - timedelta(days=1), period_ends_at=now + timedelta(days=29),
            currency_code="USD",
        )
        self.assertEqual(reserve_exhausted_paid_notices(), [])
        PaddleCheckoutAttempt.objects.create(
            organization=self.organization, actor=self.owner, environment="sandbox",
            offer_version="agency-launch-v1", product_id="pro_" + "c" * 26, price_id="pri_" + "d" * 26,
            request_key="paid-usage-notice-01", state="ready", sent_at=now - timedelta(hours=2),
            transaction_id="txn_" + "e" * 26, paid_verified_at=now - timedelta(hours=1),
            paid_customer_id=customer, paid_subscription_id=subscription_id,
        )
        for index, units in enumerate((40, 40, 20)):
            project = Project.objects.create(organization=self.organization, name=f"Paid usage {index}",
                                             canonical_origin=f"https://paid-{index}.example.invalid")
            job = JobRun.objects.create(organization=self.organization, project=project, actor=self.owner,
                                        handler="diagnostic_probe", method_version="fixture-v1",
                                        input_snapshot={"fixture": index})
            UsageReservation.objects.create(job=job, organization=self.organization, project=project,
                provider=f"fixture_{index}", period_start=now.date().replace(day=1), reserved_units=units)
            if index < 2:
                self.assertEqual(reserve_exhausted_paid_notices(), [])
        ids = reserve_exhausted_paid_notices()
        self.assertEqual(len(ids), 1)
        self.assertEqual(reserve_exhausted_paid_notices(), [])
        self.assertEqual(deliver_organization_notice(ids[0]), NoticeState.SENT)
        self.assertIn("not an additional charge", mail.outbox[0].body)
        self.assertEqual(OrganizationNotice.objects.get(pk=ids[0]).paid_period_start, subscription.period_starts_at)
        draft = self._deliver_turkish_draft_to_new_owner(reserve_exhausted_paid_notices)
        self.assertIn("Bu ek bir ücret değildir", draft.body)
        other = get_user_model().objects.create_user("paid-usage-other@example.invalid", "Safe password 99!")
        OrganizationMembership.objects.create(organization=self.organization, user=other, role=MembershipRole.OWNER)
        EmailAddress.objects.create(user=other, email=other.email, primary=True, verified=True)
        queued = reserve_exhausted_paid_notices()[0]
        subscription.period_starts_at = now - timedelta(minutes=1)
        subscription.period_ends_at = now + timedelta(days=30)
        subscription.save(update_fields=["period_starts_at", "period_ends_at"])
        self.assertEqual(deliver_organization_notice(queued), NoticeState.SKIPPED)
        self.assertEqual(len(mail.outbox), 2)

    def test_one_notice_for_verified_current_owner_and_unknown_send_is_not_replayed(self):
        ids = reserve_due_trial_notices()
        self.assertEqual(len(ids), 1)
        self.assertEqual(reserve_due_trial_notices(), [])
        with patch("tenancy.notices.send_mail", side_effect=OSError("fixture provider response unknown")) as send:
            self.assertEqual(deliver_organization_notice(ids[0]), NoticeState.UNKNOWN)
            self.assertEqual(deliver_organization_notice(ids[0]), NoticeState.UNKNOWN)
        send.assert_called_once()
        notice = OrganizationNotice.objects.get(pk=ids[0])
        self.assertEqual(notice.error_category, "delivery_uncertain")
        self.assertEqual(recover_organization_notices(), [])
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizationNotice.objects.create(organization=self.organization, trial=self.trial,
                recipient=self.owner, kind=notice.kind, trial_ends_at=self.trial.ends_at)

    def test_revocation_and_missing_verified_email_skip_without_delivery(self):
        ids = reserve_due_trial_notices()
        self.membership.role = MembershipRole.VIEWER
        self.membership.save(update_fields=["role"])
        self.assertEqual(deliver_organization_notice(ids[0]), NoticeState.SKIPPED)
        self.assertEqual(len(mail.outbox), 0)
        self.membership.role = MembershipRole.OWNER
        self.membership.save(update_fields=["role"])
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        self.assertEqual(reserve_due_trial_notices(), [])
        self.assertEqual(deliver_organization_notice(ids[0]), NoticeState.SKIPPED)

    def test_success_and_stale_worker_claim_are_distinct(self):
        ids = reserve_due_trial_notices()
        self.assertEqual(deliver_organization_notice(ids[0]), NoticeState.SENT)
        self.assertEqual(deliver_organization_notice(ids[0]), NoticeState.SENT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("No payment starts automatically", mail.outbox[0].body)
        self.assertIn(f"/app/billing/{self.organization.pk}", mail.outbox[0].body)

        other = get_user_model().objects.create_user(email="other@example.invalid", password="Valid password 99!A")
        OrganizationMembership.objects.create(organization=self.organization, user=other, role=MembershipRole.OWNER)
        EmailAddress.objects.create(user=other, email=other.email, primary=True, verified=True)
        next_id = reserve_due_trial_notices()[0]
        OrganizationNotice.objects.filter(pk=next_id).update(
            state=NoticeState.SENDING, attempted_at=timezone.now() - timedelta(minutes=5),
        )
        self.assertEqual(recover_organization_notices(), [])
        self.assertEqual(deliver_organization_notice(next_id), NoticeState.UNKNOWN)
        self.assertEqual(len(mail.outbox), 1)
        draft = self._deliver_turkish_draft_to_new_owner(reserve_due_trial_notices)
        self.assertIn(f"{self.trial.ends_at:%Y-%m-%d %H:%M} UTC", draft.body)
        self.assertIn("Ödeme otomatik olarak başlamaz", draft.body)

    def test_broker_outage_leaves_queued_notice_for_bounded_recovery(self):
        with patch("tenancy.tasks.send_organization_notice_task.apply_async", side_effect=OSError("broker down")):
            schedule_organization_notices_task()
        notice = OrganizationNotice.objects.get()
        self.assertEqual(notice.state, NoticeState.QUEUED)
        with patch("tenancy.tasks.send_organization_notice_task.apply_async") as dispatch:
            schedule_organization_notices_task()
        dispatch.assert_called_once_with(args=[notice.pk], queue="default",
                                         task_id=f"organization-notice-{notice.pk}", retry=False)
        self.assertEqual(OrganizationNotice.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_staff_can_acknowledge_one_uncertain_reissue_only_while_recipient_current(self):
        cache.clear()
        notice = OrganizationNotice.objects.get(pk=reserve_due_trial_notices()[0])
        OrganizationNotice.objects.filter(pk=notice.pk).update(
            state=NoticeState.UNKNOWN, attempted_at=timezone.now(), error_category="delivery_uncertain",
        )
        staff = get_user_model().objects.create_superuser("notice-staff@example.invalid", "Valid password 99!A")
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(staff)
        browser.get("/_allauth/browser/v1/auth/session")
        path = f"/api/platform/notices/unknown/{notice.pk}/retry/"
        payload = {"reason": "Reviewed provider status; reissue may duplicate prior mail",
                   "acknowledge_possible_duplicate": True}
        headers = {"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value,
                   "HTTP_REFERER": "http://testserver/"}
        self.assertEqual(browser.post(path, data=json.dumps(payload), content_type="application/json").status_code, 403)
        with override_settings(STAFF_MFA_REQUIRED=True):
            self.assertEqual(browser.post(path, data=json.dumps(payload), content_type="application/json", **headers).status_code, 403)
        assure_staff(browser, staff)
        status = browser.get("/api/platform/notices/unknown/")
        self.assertEqual(status.status_code, 410)
        self.assertNotIn("notices", status.json())
        self.assertNotIn(self.owner.email, status.content.decode())
        self.assertEqual(status["Cache-Control"], "private, no-store")
        with patch("tenancy.notice_api.send_organization_notice_task.apply_async", side_effect=OSError("broker down")):
            self.assertEqual(browser.post(path, data=json.dumps(payload), content_type="application/json", **headers).status_code, 202)
        notice.refresh_from_db()
        self.assertEqual((notice.state, notice.manual_retries, notice.attempted_at), (NoticeState.QUEUED, 1, None))
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.NOTICE_RETRY_REQUESTED,
                                                   organization=self.organization).count(), 1)
        self.assertEqual(browser.post(path, data=json.dumps(payload), content_type="application/json", **headers).status_code, 409)
        self.assertEqual(deliver_organization_notice(notice.pk), NoticeState.SENT)
        self.assertEqual(len(mail.outbox), 1)

    def test_unknown_notice_cannot_reissue_after_owner_revoked_or_without_staff_right(self):
        cache.clear()
        notice = OrganizationNotice.objects.get(pk=reserve_due_trial_notices()[0])
        OrganizationNotice.objects.filter(pk=notice.pk).update(state=NoticeState.UNKNOWN, attempted_at=timezone.now())
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        self.assertEqual(browser.get("/api/platform/notices/unknown/").status_code, 403)
        staff = get_user_model().objects.create_superuser("review-staff@example.invalid", "Valid password 99!A")
        browser.force_login(staff)
        assure_staff(browser, staff)
        browser.get("/_allauth/browser/v1/auth/session")
        self.membership.role = MembershipRole.VIEWER
        self.membership.save(update_fields=["role"])
        self.assertEqual(browser.post(
            f"/api/platform/notices/unknown/{notice.pk}/retry/",
            data=json.dumps({"reason": "reviewed", "acknowledge_possible_duplicate": True}),
            content_type="application/json", HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value,
            HTTP_REFERER="http://testserver/",
        ).status_code, 409)
        notice.refresh_from_db()
        self.assertEqual((notice.state, notice.manual_retries), (NoticeState.UNKNOWN, 0))

    @override_settings(PADDLE_ENVIRONMENT="sandbox")
    def test_payment_failure_requires_signed_current_reconciled_identity_and_owner(self):
        now = timezone.now()
        customer, subscription, transaction_id = ("ctm_" + "a" * 26, "sub_" + "b" * 26, "txn_" + "c" * 26)
        attempt = PaddleCheckoutAttempt.objects.create(
            organization=self.organization, actor=self.owner, environment="sandbox",
            offer_version="agency-launch-v1", product_id="pro_" + "d" * 26,
            price_id="pri_" + "e" * 26, request_key="notice-paid-checkout", state="ready",
            sent_at=now - timedelta(hours=5), transaction_id=transaction_id,
            paid_verified_at=now - timedelta(hours=4), paid_customer_id=customer,
            paid_subscription_id=subscription,
        )
        linked = PaddleSubscription.objects.create(
            organization=self.organization, environment="sandbox", customer_id=customer,
            subscription_id=subscription, status="past_due", verified_at=now - timedelta(minutes=1),
            period_starts_at=now - timedelta(days=30), period_ends_at=now,
            failed_at=now - timedelta(hours=1), grace_usage_starts_at=now - timedelta(days=30),
            currency_code="USD",
        )
        receipt = PaddleWebhookReceipt.objects.create(
            environment="sandbox", event_id="evt_" + "f" * 26, notification_id="ntf_" + "g" * 26,
            event_type="transaction.payment_failed", entity_id=transaction_id,
            subscription_id=subscription, customer_id=customer, occurred_at=linked.failed_at,
            raw_digest="a" * 64, state=PaddleWebhookReceipt.State.SUCCEEDED,
            attempts=1, claimed_at=now, processed_at=now,
        )
        self.assertEqual(reserve_due_payment_notices(), [])
        AuditEvent.objects.create(
            organization=self.organization, event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED,
            details={"event_id": receipt.event_id, "environment": "sandbox", "subscription_id": subscription,
                     "state": "past_due"},
        )
        receipt.state = PaddleWebhookReceipt.State.FAILED
        receipt.save(update_fields=["state"])
        self.assertEqual(reserve_due_payment_notices(), [])
        receipt.state = PaddleWebhookReceipt.State.SUCCEEDED
        receipt.customer_id = "ctm_" + "z" * 26
        receipt.save(update_fields=["state", "customer_id"])
        self.assertEqual(reserve_due_payment_notices(), [])
        receipt.customer_id = customer
        receipt.save(update_fields=["customer_id"])
        self.assertEqual(paid_access_state(linked), "payment_grace")
        self.assertIsNotNone(_verified_failed_subscription(self.organization, receipt, timezone.now()))
        ids = reserve_due_payment_notices()
        self.assertEqual(len(ids), 1)
        self.assertEqual(reserve_due_payment_notices(), [])
        notice = OrganizationNotice.objects.get(pk=ids[0])
        self.assertIsNone(notice.trial_ends_at)
        notice.state = NoticeState.UNKNOWN
        notice.attempted_at = now
        notice.save(update_fields=["state", "attempted_at"])
        staff = get_user_model().objects.create_superuser("payment-mail-staff@example.invalid", "Safe password 99!")
        browser = Client()
        browser.force_login(staff)
        status = browser.get("/api/platform/notices/unknown/")
        self.assertEqual(status.status_code, 410)
        self.assertNotIn("notices", status.json())
        self.assertNotIn(customer, status.content.decode())
        notice.state = NoticeState.QUEUED
        notice.attempted_at = None
        notice.save(update_fields=["state", "attempted_at"])
        self.assertEqual(deliver_organization_notice(ids[0]), NoticeState.SENT)
        self.assertIn("payment recovery", mail.outbox[-1].body)
        self.assertNotIn(receipt.event_id, mail.outbox[-1].body)
        draft = self._deliver_turkish_draft_to_new_owner(reserve_due_payment_notices)
        self.assertIn("Yanıtınıza ödeme bilgisi eklemeyin", draft.body)
        self.assertNotIn(receipt.event_id, draft.body)

        # A second signed event observed after a current-provider recovery is not a new failure notice.
        newer = PaddleWebhookReceipt.objects.create(
            environment="sandbox", event_id="evt_" + "h" * 26, notification_id="ntf_" + "i" * 26,
            event_type="transaction.payment_failed", entity_id="txn_" + "j" * 26,
            subscription_id=subscription, customer_id=customer, occurred_at=now,
            raw_digest="b" * 64, state=PaddleWebhookReceipt.State.SUCCEEDED,
            attempts=1, claimed_at=now, processed_at=now,
        )
        AuditEvent.objects.create(organization=self.organization,
            event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED,
            details={"event_id": newer.event_id, "environment": "sandbox", "subscription_id": subscription,
                     "state": "past_due"})
        linked.status = "active"
        linked.failed_at = linked.grace_usage_starts_at = None
        linked.period_starts_at = now - timedelta(days=1)
        linked.period_ends_at = now + timedelta(days=29)
        linked.save()
        self.assertEqual(reserve_due_payment_notices(), [])
        self.assertEqual(OrganizationNotice.objects.filter(kind="payment_failed").count(), 2)
