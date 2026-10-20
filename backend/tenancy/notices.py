"""Token-free, organization-owned trial notices. SMTP uncertainty is never replayed."""

from datetime import timedelta

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from accounts.staff_access import require_staff_permissions
from accounts.localization import product_email_language

from .models import (
    AuditEvent, AuditEventType, MembershipRole, NoticeKind, NoticeState, Organization, OrganizationMembership,
    OrganizationNotice, OrganizationTrial, PaddleCheckoutAttempt, PaddleStatus, PaddleSubscription,
    PaddleWebhookReceipt, TrialState,
)
from .billing_state import paid_access_state
from .email_feedback import is_email_suppressed
from .services import active_trial_for_policy


def _trial_units_used(trial):
    from jobs.models import UsageReservation
    from jobs.usage import _units_used

    return _units_used(UsageReservation.objects.filter(
        organization=trial.organization, created_at__gte=trial.started_at, created_at__lt=trial.ends_at,
    ))


def _paid_usage_window(subscription, now):
    state = paid_access_state(subscription, now=now)
    if state not in {"paid_active", "cancellation_scheduled", "payment_grace"}:
        return None
    start = subscription.grace_usage_starts_at or subscription.period_starts_at
    end = (subscription.failed_at + timedelta(days=7) if state == "payment_grace"
           else subscription.period_ends_at)
    if (not start or not end or not start <= now < end
        or not PaddleCheckoutAttempt.objects.filter(
            organization_id=subscription.organization_id, environment=subscription.environment,
            paid_verified_at__isnull=False, paid_customer_id=subscription.customer_id,
            paid_subscription_id=subscription.subscription_id,
        ).exists()):
        return None
    return start, end


def _paid_units_used(subscription, start, end):
    from jobs.models import UsageReservation
    from jobs.usage import _units_used

    return _units_used(UsageReservation.objects.filter(
        organization_id=subscription.organization_id, created_at__gte=start, created_at__lt=end,
    ))


def reserve_due_trial_notices(*, limit=20, now=None, kind=NoticeKind.TRIAL_ENDING):
    if type(limit) is not int or not 1 <= limit <= 20 or kind not in {
        NoticeKind.TRIAL_ENDING, NoticeKind.TRIAL_UNITS_EXHAUSTED,
    }:
        raise ValueError("Invalid notice batch limit.")
    now = now or timezone.now()
    candidates = OrganizationTrial.objects.filter(state=TrialState.ACTIVE, ends_at__gt=now)
    if kind == NoticeKind.TRIAL_ENDING:
        candidates = candidates.filter(ends_at__lte=now + timedelta(days=1))
    candidates = list(candidates.order_by("ends_at", "pk").values_list("organization_id", flat=True)[:limit])
    reserved = []
    for organization_id in candidates:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=organization_id)
            trial = active_trial_for_policy(organization=organization)
            if trial is None or (kind == NoticeKind.TRIAL_ENDING and not now < trial.ends_at <= now + timedelta(days=1)):
                continue
            if kind == NoticeKind.TRIAL_UNITS_EXHAUSTED and _trial_units_used(trial) < trial.unit_limit:
                continue
            owners = OrganizationMembership.objects.filter(
                organization=organization, role=MembershipRole.OWNER, user__is_active=True,
            ).order_by("pk").values_list("user_id", flat=True)[:limit - len(reserved)]
            for user_id in owners:
                if not EmailAddress.objects.filter(user_id=user_id, primary=True, verified=True).exists():
                    continue
                notice, created = OrganizationNotice.objects.get_or_create(
                    trial=trial, recipient_id=user_id, kind=kind,
                    trial_ends_at=trial.ends_at,
                    defaults={"organization": organization},
                )
                if created:
                    reserved.append(notice.pk)
        if len(reserved) >= limit:
            break
    return reserved


def _verified_failed_subscription(organization, receipt, now):
    if (receipt is None or receipt.state != PaddleWebhookReceipt.State.SUCCEEDED
        or receipt.event_type not in {"transaction.payment_failed", "transaction.past_due"}
        or receipt.environment != settings.PADDLE_ENVIRONMENT
        or receipt.processed_at is None or receipt.occurred_at > now
        or receipt.occurred_at < now - timedelta(days=7)):
        return None
    subscription = PaddleSubscription.objects.filter(
        organization=organization, environment=receipt.environment, verified_at__isnull=False,
    ).first()
    if (subscription is None or subscription.status != PaddleStatus.PAST_DUE
        or subscription.failed_at != receipt.occurred_at
        or (receipt.subscription_id and receipt.subscription_id != subscription.subscription_id)
        or (receipt.customer_id and receipt.customer_id != subscription.customer_id)
        or paid_access_state(subscription, now=now) != "payment_grace"):
        return None
    if not AuditEvent.objects.filter(
        organization=organization, event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED,
        details__event_id=receipt.event_id, details__subscription_id=subscription.subscription_id,
        details__environment=receipt.environment, details__state=PaddleStatus.PAST_DUE,
    ).exists():
        return None
    if not PaddleCheckoutAttempt.objects.filter(
        organization=organization, environment=receipt.environment,
        paid_verified_at__isnull=False, paid_customer_id=subscription.customer_id,
        paid_subscription_id=subscription.subscription_id,
    ).exists():
        return None
    return subscription


def reserve_due_payment_notices(*, limit=20, now=None):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Invalid notice batch limit.")
    now = now or timezone.now()
    if settings.PADDLE_ENVIRONMENT not in {"sandbox", "live"}:
        return []
    candidates = list(PaddleWebhookReceipt.objects.filter(
        environment=settings.PADDLE_ENVIRONMENT, state=PaddleWebhookReceipt.State.SUCCEEDED,
        event_type__in=["transaction.payment_failed", "transaction.past_due"],
        occurred_at__gte=now - timedelta(days=7), occurred_at__lte=now,
    ).order_by("-occurred_at", "-pk").values_list("pk", "event_id")[:100])
    reserved = []
    for receipt_id, event_id in candidates:
        organization_id = AuditEvent.objects.filter(
            event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED,
            details__event_id=event_id, details__environment=settings.PADDLE_ENVIRONMENT,
            details__state=PaddleStatus.PAST_DUE,
        ).values_list("organization_id", flat=True).first()
        if organization_id is None:
            continue
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=organization_id)
            receipt = PaddleWebhookReceipt.objects.get(pk=receipt_id)
            if organization.is_suspended or not _verified_failed_subscription(organization, receipt, now):
                continue
            owners = OrganizationMembership.objects.filter(
                organization=organization, role=MembershipRole.OWNER, user__is_active=True,
            ).order_by("pk").values_list("user_id", flat=True)[:limit - len(reserved)]
            for user_id in owners:
                if not EmailAddress.objects.filter(user_id=user_id, primary=True, verified=True).exists():
                    continue
                notice, created = OrganizationNotice.objects.get_or_create(
                    source_receipt=receipt, recipient_id=user_id, kind=NoticeKind.PAYMENT_FAILED,
                    defaults={"organization": organization},
                )
                if created:
                    reserved.append(notice.pk)
        if len(reserved) >= limit:
            break
    return reserved


def reserve_exhausted_paid_notices(*, limit=20, now=None):
    from .services import PAID_UNIT_LIMIT

    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Invalid notice batch limit.")
    now = now or timezone.now()
    if settings.PADDLE_ENVIRONMENT not in {"sandbox", "live"}:
        return []
    candidates = list(PaddleSubscription.objects.filter(
        environment=settings.PADDLE_ENVIRONMENT, verified_at__isnull=False,
        status__in=[PaddleStatus.ACTIVE, PaddleStatus.PAST_DUE],
    ).order_by("pk").values_list("organization_id", flat=True)[:limit])
    reserved = []
    for organization_id in candidates:
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=organization_id)
            subscription = PaddleSubscription.objects.filter(organization=organization,
                environment=settings.PADDLE_ENVIRONMENT).first()
            window = _paid_usage_window(subscription, now) if subscription and not organization.is_suspended else None
            if window is None or _paid_units_used(subscription, *window) < PAID_UNIT_LIMIT:
                continue
            owners = OrganizationMembership.objects.filter(
                organization=organization, role=MembershipRole.OWNER, user__is_active=True,
            ).order_by("pk").values_list("user_id", flat=True)[:limit - len(reserved)]
            for user_id in owners:
                if not EmailAddress.objects.filter(user_id=user_id, primary=True, verified=True).exists():
                    continue
                notice, created = OrganizationNotice.objects.get_or_create(
                    subscription=subscription, recipient_id=user_id, kind=NoticeKind.PAID_UNITS_EXHAUSTED,
                    paid_period_start=window[0], defaults={"organization": organization},
                )
                if created:
                    reserved.append(notice.pk)
        if len(reserved) >= limit:
            break
    return reserved


def _current_notice(notice, now):
    if notice.kind in {NoticeKind.TRIAL_ENDING, NoticeKind.TRIAL_UNITS_EXHAUSTED}:
        if notice.trial is None or notice.trial.organization_id != notice.organization_id:
            return None
        trial = active_trial_for_policy(organization=notice.organization)
        if trial is None or trial.pk != notice.trial_id or trial.ends_at != notice.trial_ends_at:
            return None
        if notice.kind == NoticeKind.TRIAL_ENDING and not now < trial.ends_at <= now + timedelta(days=1):
            return None
        if notice.kind == NoticeKind.TRIAL_UNITS_EXHAUSTED and _trial_units_used(trial) < trial.unit_limit:
            return None
    elif notice.kind == NoticeKind.PAYMENT_FAILED:
        if not _verified_failed_subscription(notice.organization, notice.source_receipt, now):
            return None
    elif notice.kind == NoticeKind.PAID_UNITS_EXHAUSTED:
        from .services import PAID_UNIT_LIMIT

        window = _paid_usage_window(notice.subscription, now) if notice.subscription else None
        if (window is None or notice.subscription.organization_id != notice.organization_id
            or window[0] != notice.paid_period_start
            or _paid_units_used(notice.subscription, *window) < PAID_UNIT_LIMIT):
            return None
    else:
        return None
    if notice.organization.is_suspended:
        return None
    if not notice.recipient.is_active or not OrganizationMembership.objects.filter(
        organization=notice.organization, user=notice.recipient, role=MembershipRole.OWNER,
    ).exists():
        return None
    email = EmailAddress.objects.filter(
        user=notice.recipient, primary=True, verified=True, email=notice.recipient.email,
    ).values_list("email", flat=True).first()
    return email if email and not is_email_suppressed(email) else None


def deliver_organization_notice(notice_id):
    organization_id = OrganizationNotice.objects.filter(pk=notice_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return "missing"
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization_id)
        notice = OrganizationNotice.objects.select_for_update(of=("self",)).select_related("trial", "source_receipt", "subscription", "recipient").get(
            pk=notice_id, organization=organization,
        )
        if notice.state != NoticeState.QUEUED:
            return notice.state
        notice.attempted_at = timezone.now()
        email = _current_notice(notice, notice.attempted_at)
        notice.state = NoticeState.SENDING if email else NoticeState.SKIPPED
        notice.error_category = "" if email else "recipient_or_trial_changed"
        notice.save(update_fields=["attempted_at", "state", "error_category"])
    if not email:
        return NoticeState.SKIPPED
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization_id)
        notice = OrganizationNotice.objects.select_for_update(of=("self",)).select_related("trial", "source_receipt", "subscription", "recipient").get(pk=notice_id)
        if notice.state != NoticeState.SENDING:
            return notice.state
        notice.recipient = get_user_model().objects.select_for_update().get(pk=notice.recipient_id)
        email = _current_notice(notice, timezone.now())
        if email is None:
            notice.state = NoticeState.SKIPPED
            notice.error_category = "recipient_or_trial_changed"
        else:
            link = f"{settings.FRONTEND_ORIGIN}/app/billing/{organization.pk}"
            if notice.kind == NoticeKind.TRIAL_ENDING:
                subject = "[OrganicSEOOps] Your trial is ending"
                body = (f"Your organization's trial ends on {notice.trial_ends_at:%Y-%m-%d %H:%M} UTC. "
                        f"Your owner can review access and billing at {link}. No payment starts automatically.")
            elif notice.kind == NoticeKind.TRIAL_UNITS_EXHAUSTED:
                subject = "[OrganicSEOOps] Trial work allowance reached"
                body = ("Your organization's trial has used its included work units. New paid-unit work is paused. "
                        f"An owner can review usage and billing at {link}. No payment starts automatically.")
            elif notice.kind == NoticeKind.PAID_UNITS_EXHAUSTED:
                subject = "[OrganicSEOOps] Included monthly work units used"
                body = ("Your organization's current verified paid period has used its included work units. "
                        f"New paid-unit work is paused. An owner can review billing and usage at {link}. "
                        "This is not an additional charge.")
            else:
                subject = "[OrganicSEOOps] Billing recovery needed"
                body = ("A verified renewal payment failed and billing needs attention. "
                        f"An owner can review payment recovery and current access at {link}. "
                        "New paid work can stop after the grace period. Do not reply with payment details.")
            if product_email_language(notice.recipient) == "tr":
                if notice.kind == NoticeKind.TRIAL_ENDING:
                    subject = "[OrganicSEOOps] Deneme süreniz sona eriyor (Türkçe taslak)"
                    body = (f"Kuruluşunuzun deneme süresi {notice.trial_ends_at:%Y-%m-%d %H:%M} UTC tarihinde sona erer. "
                            f"Kuruluş sahibi erişimi ve faturalandırmayı {link} adresinde inceleyebilir. Ödeme otomatik olarak başlamaz.")
                elif notice.kind == NoticeKind.TRIAL_UNITS_EXHAUSTED:
                    subject = "[OrganicSEOOps] Deneme çalışma kotasına ulaşıldı (Türkçe taslak)"
                    body = ("Kuruluşunuz denemeye dahil çalışma birimlerini kullandı. Ücretli birim tüketen yeni işler duraklatıldı. "
                            f"Kuruluş sahibi kullanımı ve faturalandırmayı {link} adresinde inceleyebilir. Ödeme otomatik olarak başlamaz.")
                elif notice.kind == NoticeKind.PAID_UNITS_EXHAUSTED:
                    subject = "[OrganicSEOOps] Aylık çalışma birimleri kullanıldı (Türkçe taslak)"
                    body = ("Kuruluşunuzun doğrulanmış ücretli dönemine dahil çalışma birimleri kullanıldı. "
                            f"Ücretli birim tüketen yeni işler duraklatıldı. Kuruluş sahibi faturalandırmayı ve kullanımı {link} adresinde inceleyebilir. "
                            "Bu ek bir ücret değildir.")
                else:
                    subject = "[OrganicSEOOps] Ödeme için işlem gerekiyor (Türkçe taslak)"
                    body = ("Doğrulanmış bir yenileme ödemesi başarısız oldu; faturalandırma için işlem gerekiyor. "
                            f"Kuruluş sahibi ödeme işlemlerini ve mevcut erişimi {link} adresinde inceleyebilir. "
                            "Ek süreden sonra yeni ücretli işler durabilir. Yanıtınıza ödeme bilgisi eklemeyin.")
            try:
                sent = send_mail(
                    subject, body, None, [email], fail_silently=False,
                )
            except Exception:
                notice.state = NoticeState.UNKNOWN
                notice.error_category = "delivery_uncertain"
            else:
                if sent == 1:
                    notice.state = NoticeState.SENT
                    notice.sent_at = timezone.now()
                else:
                    notice.state = NoticeState.UNKNOWN
                    notice.error_category = "delivery_uncertain"
        notice.save(update_fields=["state", "sent_at", "error_category"])
        return notice.state


def recover_organization_notices(*, limit=20):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Invalid notice batch limit.")
    cutoff = timezone.now() - timedelta(minutes=2)
    for notice_id in OrganizationNotice.objects.filter(
        state=NoticeState.SENDING, attempted_at__lte=cutoff,
    ).order_by("attempted_at", "pk").values_list("pk", flat=True)[:limit]:
        OrganizationNotice.objects.filter(pk=notice_id, state=NoticeState.SENDING).update(
            state=NoticeState.UNKNOWN, error_category="worker_outcome_unknown",
        )
    return list(OrganizationNotice.objects.filter(state=NoticeState.QUEUED).order_by("pk")
                .values_list("pk", flat=True)[:limit])


def requeue_unknown_organization_notice(*, notice, actor, reason, request):
    current = require_staff_permissions(request, permissions=("tenancy.change_organizationnotice",))
    if actor.pk != current.pk:
        raise PermissionDenied
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 250:
        raise ValidationError("Provide a review reason.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=notice.organization_id)
        notice = OrganizationNotice.objects.select_for_update(of=("self",)).select_related("trial", "source_receipt", "subscription", "recipient").get(
            pk=notice.pk, organization=organization,
        )
        if notice.state != NoticeState.UNKNOWN or notice.manual_retries or not _current_notice(notice, timezone.now()):
            raise ValidationError("Unknown delivery cannot be reissued for this trial and recipient.")
        notice.state = NoticeState.QUEUED
        notice.manual_retries = 1
        notice.attempted_at = None
        notice.error_category = ""
        notice.save(update_fields=["state", "manual_retries", "attempted_at", "error_category"])
        AuditEvent.objects.create(
            organization=organization, actor=current, subject_user=notice.recipient,
            event_type=AuditEventType.NOTICE_RETRY_REQUESTED,
            details={"notice_id": notice.pk, "kind": notice.kind, "reason": reason.strip()},
        )
        require_staff_permissions(request, permissions=("tenancy.change_organizationnotice",))
    return notice
