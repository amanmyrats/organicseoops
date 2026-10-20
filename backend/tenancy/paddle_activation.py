"""D141 current evidence and prospective immutable first active server observation."""
import re
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .billing_state import paid_access_state
from .models import (AuditEvent, AuditEventType, Organization, OrganizationDeletionRun, PaddleCheckoutAttempt,
                     PaddleFirstActiveObservation, PaddleSellerConfiguration,
                     PaddleStatus, PaddleSubscription, PaddleWebhookReceipt)
from .paddle_checkout import _current_seller
from .paddle_checkout_delivery import checkout_source_digest
from .services import Action, TRIAL_OFFER_VERSION, require_organization_action


def _current_active_source(*, organization, actor, attempt_id, receipt_id):
    organization = Organization.objects.get(pk=organization.pk)
    require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
    if OrganizationDeletionRun.objects.filter(organization=organization).exists():
        raise PermissionDenied
    attempt = PaddleCheckoutAttempt.objects.filter(pk=attempt_id, organization=organization,
        environment=settings.PADDLE_ENVIRONMENT, state=PaddleCheckoutAttempt.State.READY,
        paid_verified_at__isnull=False).exclude(paid_customer_id="").exclude(paid_subscription_id="").first()
    if attempt is None:
        raise PermissionDenied
    linked = PaddleSubscription.objects.filter(organization=organization, environment=attempt.environment,
        status=PaddleStatus.ACTIVE, customer_id=attempt.paid_customer_id,
        subscription_id=attempt.paid_subscription_id).first()
    if linked is None or paid_access_state(linked) not in {"paid_active", "cancellation_scheduled"}:
        raise PermissionDenied
    seller = _current_seller()
    if (seller is None or (attempt.environment, attempt.product_id, attempt.price_id, attempt.offer_version) !=
        (seller.environment, seller.product_id, seller.price_id, TRIAL_OFFER_VERSION)):
        raise PermissionDenied
    paid_audit = AuditEvent.objects.filter(organization=organization,
        event_type=AuditEventType.BILLING_PAYMENT_VERIFIED, details__checkout_attempt_id=attempt.pk,
        details__environment=attempt.environment).order_by("pk").first()
    active_audit = AuditEvent.objects.filter(organization=organization,
        event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED,
        details__environment=attempt.environment, details__subscription_id=linked.subscription_id).order_by("-pk").first()
    if (paid_audit is None or active_audit is None or paid_audit.actor_id != attempt.actor_id
        or active_audit.actor_id != attempt.actor_id or active_audit.details.get("state") != PaddleStatus.ACTIVE):
        raise PermissionDenied
    successful = PaddleWebhookReceipt.objects.filter(environment=attempt.environment,
        state=PaddleWebhookReceipt.State.SUCCEEDED, attempts__gte=1, claimed_at__isnull=False,
        processed_at__isnull=False, retry_after__isnull=True, error_category="")
    paid_receipt = successful.filter(event_id=paid_audit.details.get("event_id"), entity_id=attempt.transaction_id,
        event_type__in=["transaction.paid", "transaction.completed"]).first()
    active_receipt = successful.filter(pk=receipt_id, event_id=active_audit.details.get("event_id"),
        entity_id=linked.subscription_id, event_type__startswith="subscription.").first()
    if paid_receipt is None or active_receipt is None:
        raise PermissionDenied
    now = timezone.now()
    dates = (organization.created_at, attempt.created_at, attempt.sent_at, attempt.paid_verified_at,
        linked.verified_at, linked.period_starts_at, paid_audit.created_at, active_audit.created_at,
        seller.rotated_at, paid_receipt.occurred_at, paid_receipt.received_at, paid_receipt.claimed_at,
        paid_receipt.processed_at, active_receipt.occurred_at, active_receipt.received_at,
        active_receipt.claimed_at, active_receipt.processed_at)
    if (any(value is None or timezone.is_naive(value) or value > now for value in dates)
        or not organization.created_at <= attempt.created_at <= attempt.sent_at <= attempt.paid_verified_at
        or not attempt.paid_verified_at <= paid_audit.created_at <= paid_receipt.processed_at <= linked.verified_at
        or not linked.verified_at <= active_audit.created_at <= active_receipt.processed_at
        or not paid_receipt.received_at <= paid_receipt.claimed_at <= attempt.paid_verified_at
        or not active_receipt.received_at <= active_receipt.claimed_at <= linked.verified_at):
        raise ValidationError("Current paid reconciliation dates are unavailable.")
    def receipt_source(row, audit):
        return {"id": row.pk, "event_id": row.event_id, "event_type": row.event_type,
                "occurred_at": row.occurred_at.isoformat(), "received_at": row.received_at.isoformat(),
                "processed_at": row.processed_at.isoformat(), "audit_id": audit.pk,
                "audited_at": audit.created_at.isoformat()}
    source = {"method": "paid-active-reconciliation-source-v1", "organization_id": organization.pk,
        "actor_id": actor.pk, "attempt_id": attempt.pk, "request_actor_id": attempt.actor_id,
        "environment": attempt.environment, "offer_version": attempt.offer_version,
        "product_id": attempt.product_id, "price_id": attempt.price_id, "transaction_id": attempt.transaction_id,
        "attempt_created_at": attempt.created_at.isoformat(), "attempt_sent_at": attempt.sent_at.isoformat(),
        "payment_verified_at": attempt.paid_verified_at.isoformat(), "subscription_id": linked.pk,
        "provider_subscription_id": linked.subscription_id, "customer_id": linked.customer_id,
        "status": linked.status, "currency_code": linked.currency_code,
        "subscription_verified_at": linked.verified_at.isoformat(), "period_starts_at": linked.period_starts_at.isoformat(),
        "period_ends_at": linked.period_ends_at.isoformat(),
        "scheduled_cancel_at": linked.scheduled_cancel_at.isoformat() if linked.scheduled_cancel_at else None,
        "seller_id": seller.pk, "seller_rotated_at": seller.rotated_at.isoformat(),
        "payment_receipt": receipt_source(paid_receipt, paid_audit),
        "subscription_receipt": receipt_source(active_receipt, active_audit), "first_paid_activation_confirmed": False,
        "interpretation": "current_signed_reconciled_active_source_not_first_ever_paid_activation_or_occurrence_time_proof"}
    require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
    return source


def paid_activation_source(*, organization, actor, attempt_id, receipt_id):
    """Unregistered exact current evidence for later prospective capture; no writes or provider call."""
    if any(type(value) is not int or not 1 <= value < 2**53 for value in (attempt_id, receipt_id)):
        raise ValidationError("Choose an exact paid checkout and subscription reconciliation receipt.")
    source = _current_active_source(organization=organization, actor=actor, attempt_id=attempt_id, receipt_id=receipt_id)
    if _current_active_source(organization=organization, actor=actor, attempt_id=attempt_id, receipt_id=receipt_id) != source:
        raise PermissionDenied
    return source


OBSERVATION_METHOD = "first-active-observation-v1"
OBSERVATION_FIELDS = ("id", "organization_id", "attempt_id", "receipt_id", "observed_at", "source", "source_digest")


def _observation_receipt_source(row):
    return {"id": row.pk, "event_id": row.event_id, "event_type": row.event_type, "entity_id": row.entity_id,
            "raw_digest": row.raw_digest, "occurred_at": row.occurred_at.isoformat(),
            "received_at": row.received_at.isoformat(), "claimed_at": row.claimed_at.isoformat(),
            "processed_at": row.processed_at.isoformat()}


def first_active_observation_source(*, organization, attempt, receipt, observed_at):
    """Internal atomic worker source. Billing authority is independent of current customer roles."""
    organization = Organization.objects.get(pk=organization.pk)
    attempt = PaddleCheckoutAttempt.objects.get(pk=attempt.pk)
    receipt = PaddleWebhookReceipt.objects.get(pk=receipt.pk)
    if (organization.paid_activation_tracking != OBSERVATION_METHOD or organization.is_suspended
        or organization.closed_at is not None or OrganizationDeletionRun.objects.filter(organization=organization).exists()
        or attempt.organization_id != organization.pk or attempt.environment != settings.PADDLE_ENVIRONMENT
        or attempt.state != attempt.State.READY or attempt.paid_verified_at is None
        or receipt.environment != attempt.environment or receipt.state != receipt.State.SUCCEEDED
        or receipt.attempts < 1 or receipt.retry_after is not None or receipt.error_category
        or observed_at != receipt.processed_at):
        raise ValidationError("Prospective first active source is unavailable.")
    linked = PaddleSubscription.objects.filter(organization=organization, environment=attempt.environment,
        customer_id=attempt.paid_customer_id, subscription_id=attempt.paid_subscription_id).first()
    seller = _current_seller()
    if (linked is None or paid_access_state(linked, now=observed_at) not in {"paid_active", "cancellation_scheduled"}
        or seller is None or (attempt.environment, attempt.product_id, attempt.price_id, attempt.offer_version) !=
        (seller.environment, seller.product_id, seller.price_id, TRIAL_OFFER_VERSION)):
        raise ValidationError("Prospective first active source is unavailable.")
    audit = AuditEvent.objects.filter(organization=organization,
        event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED,
        details__environment=attempt.environment, details__subscription_id=linked.subscription_id).order_by("-pk").first()
    payment_audit = AuditEvent.objects.filter(organization=organization,
        event_type=AuditEventType.BILLING_PAYMENT_VERIFIED, details__checkout_attempt_id=attempt.pk,
        details__environment=attempt.environment).order_by("pk").first()
    if (audit is None or payment_audit is None or audit.actor_id != attempt.actor_id
        or payment_audit.actor_id != attempt.actor_id or audit.details.get("event_id") != receipt.event_id
        or audit.details.get("state") != PaddleStatus.ACTIVE):
        raise ValidationError("Prospective first active audit is unavailable.")
    if AuditEvent.objects.filter(organization=organization,
        event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED, details__state=PaddleStatus.ACTIVE).exclude(pk=audit.pk).exists():
        # A pre-capture worker or unsupported direct path may have observed active service already.
        # Even a prior expired/future-period snapshot cannot establish complete first-active coverage.
        raise ValidationError("Earlier active reconciliation has unknown tracking coverage.")
    payment = PaddleWebhookReceipt.objects.filter(environment=attempt.environment,
        event_id=payment_audit.details.get("event_id"), entity_id=attempt.transaction_id,
        event_type__in=["transaction.paid", "transaction.completed"], state="succeeded",
        attempts__gte=1, retry_after__isnull=True, error_category="").first()
    if (payment is None or not (receipt.event_type.startswith("subscription.") and receipt.entity_id == linked.subscription_id
        or receipt.event_type in {"transaction.paid", "transaction.completed", "transaction.payment_failed", "transaction.past_due"}
        and receipt.entity_id.startswith("txn_"))):
        raise ValidationError("Prospective first active receipts are unavailable.")
    dates = (organization.created_at, attempt.created_at, attempt.sent_at, attempt.paid_verified_at,
        linked.verified_at, audit.created_at, payment_audit.created_at, seller.rotated_at,
        receipt.occurred_at, receipt.received_at, receipt.claimed_at, receipt.processed_at,
        payment.occurred_at, payment.received_at, payment.claimed_at, payment.processed_at, observed_at)
    if (any(value is None or timezone.is_naive(value) or value > timezone.now() for value in dates)
        or not organization.created_at <= attempt.created_at <= attempt.sent_at <= attempt.paid_verified_at
        or not payment.received_at <= payment.claimed_at <= attempt.paid_verified_at <= payment_audit.created_at <= payment.processed_at
        or not payment.processed_at <= linked.verified_at <= audit.created_at <= observed_at
        or not receipt.claimed_at <= linked.verified_at
        or not receipt.received_at <= receipt.claimed_at):
        raise ValidationError("Prospective first active dates are unavailable.")
    return {"method": OBSERVATION_METHOD, "organization_id": organization.pk,
        "tracking_started_at": organization.created_at.isoformat(), "attempt_id": attempt.pk,
        "attempt_created_at": attempt.created_at.isoformat(), "attempt_sent_at": attempt.sent_at.isoformat(),
        "request_actor_id": attempt.actor_id, "environment": attempt.environment,
        "offer_version": attempt.offer_version, "product_id": attempt.product_id, "price_id": attempt.price_id,
        "transaction_id": attempt.transaction_id, "customer_id": linked.customer_id,
        "provider_subscription_id": linked.subscription_id, "currency_code": linked.currency_code,
        "payment_verified_at": attempt.paid_verified_at.isoformat(), "payment_audit_id": payment_audit.pk,
        "payment_audited_at": payment_audit.created_at.isoformat(), "payment_receipt": _observation_receipt_source(payment),
        "subscription_verified_at": linked.verified_at.isoformat(), "subscription_audit_id": audit.pk,
        "subscription_audited_at": audit.created_at.isoformat(), "reconciliation_receipt": _observation_receipt_source(receipt),
        "period_starts_at": linked.period_starts_at.isoformat(), "period_ends_at": linked.period_ends_at.isoformat(),
        "observed_at": observed_at.isoformat(),
        "interpretation": "first_prospectively_tracked_active_server_observation_not_provider_activation_time"}


def capture_first_active_observation(*, organization, attempt, receipt, worker_confirmed):
    """Called inside organization-first reconciliation/success transaction, never a read/backfill route."""
    if not connection.in_atomic_block:
        raise RuntimeError("First active capture requires atomic reconciliation.")
    if (organization.paid_activation_tracking != OBSERVATION_METHOD
        or PaddleFirstActiveObservation.objects.filter(organization=organization).exists()):
        return
    linked = PaddleSubscription.objects.filter(organization=organization).first()
    if paid_access_state(linked) not in {"paid_active", "cancellation_scheduled"}:
        return
    source = None
    if worker_confirmed:
        # Rotation serializes on the seller row; customer role changes do not gate server billing truth.
        PaddleSellerConfiguration.objects.select_for_update().filter(environment=settings.PADDLE_ENVIRONMENT).first()
        try:
            source = first_active_observation_source(organization=organization, attempt=attempt,
                receipt=receipt, observed_at=receipt.processed_at)
        except ValidationError:
            pass
    if source is None:
        # An observed active state without complete fenced proof is a coverage gap, never later backfill.
        Organization.objects.filter(pk=organization.pk).update(paid_activation_tracking=None)
        organization.paid_activation_tracking = None
        return
    PaddleFirstActiveObservation.objects.create(organization=organization, attempt=attempt, receipt=receipt,
        observed_at=receipt.processed_at, source=source, source_digest=checkout_source_digest(source))


def first_active_observation_result(saved):
    """Minimized immutable history; current subscription/catalog/role are not historical evidence."""
    source, attempt, receipt = saved.source, saved.attempt, saved.receipt
    try:
        dates = {key: parse_datetime(source[key]) for key in ("tracking_started_at", "observed_at",
            "subscription_verified_at", "subscription_audited_at", "period_starts_at", "period_ends_at")}
        payment = PaddleWebhookReceipt.objects.get(pk=source["payment_receipt"]["id"], environment=attempt.environment)
        audit = AuditEvent.objects.get(pk=source["subscription_audit_id"], organization_id=saved.organization_id,
            actor_id=attempt.actor_id, event_type=AuditEventType.BILLING_SUBSCRIPTION_RECONCILED)
        paid_audit = AuditEvent.objects.get(pk=source["payment_audit_id"], organization_id=saved.organization_id,
            actor_id=attempt.actor_id, event_type=AuditEventType.BILLING_PAYMENT_VERIFIED)
        if (source["method"] != OBSERVATION_METHOD or saved.source_digest != checkout_source_digest(source)
            or source["organization_id"] != saved.organization_id or attempt.organization_id != saved.organization_id
            or source["attempt_id"] != attempt.pk or source["request_actor_id"] != attempt.actor_id
            or source["environment"] != attempt.environment or source["offer_version"] != attempt.offer_version
            or source["transaction_id"] != attempt.transaction_id or source["customer_id"] != attempt.paid_customer_id
            or source["provider_subscription_id"] != attempt.paid_subscription_id
            or source["payment_verified_at"] != attempt.paid_verified_at.isoformat()
            or source["payment_receipt"] != _observation_receipt_source(payment)
            or source["reconciliation_receipt"] != _observation_receipt_source(receipt)
            or receipt.state != "succeeded" or payment.state != "succeeded"
            or source["subscription_audited_at"] != audit.created_at.isoformat()
            or source["payment_audited_at"] != paid_audit.created_at.isoformat()
            or audit.details != {"event_id": receipt.event_id, "environment": attempt.environment,
                "subscription_id": source["provider_subscription_id"], "state": "active"}
            or paid_audit.details != {"event_id": payment.event_id, "environment": attempt.environment,
                "checkout_attempt_id": attempt.pk}
            or any(value is None or timezone.is_naive(value) for value in dates.values())
            or dates["tracking_started_at"] != saved.organization.created_at
            or dates["observed_at"] != saved.observed_at or saved.observed_at != receipt.processed_at
            or not dates["tracking_started_at"] <= dates["subscription_verified_at"] <= dates["subscription_audited_at"] <= saved.observed_at <= timezone.now()
            or not dates["period_starts_at"] <= saved.observed_at < dates["period_ends_at"]
            or not re.fullmatch(r"[A-Z]{3}", source["currency_code"])):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError, PaddleWebhookReceipt.DoesNotExist, AuditEvent.DoesNotExist):
        raise ValidationError("Saved first active observation needs billing review.") from None
    return {"attempt_id": saved.attempt_id, "source_digest": saved.source_digest,
        "observed_at": saved.observed_at.isoformat(), "provider_occurred_at": receipt.occurred_at.isoformat(),
        "environment": source["environment"], "offer_version": source["offer_version"], "currency_code": source["currency_code"],
        "interpretation": "historical_first_active_server_observation_not_current_access_or_provider_activation_time"}


def _first_active_history_dependencies(saved):
    """Pin the same retained evidence the original historical validator already reads."""
    if saved is None: return None
    return (PaddleCheckoutAttempt.objects.filter(pk=saved.attempt_id).values().first(),
        list(PaddleWebhookReceipt.objects.filter(pk__in=[saved.receipt_id, saved.source["payment_receipt"]["id"]]).order_by("pk").values()),
        list(AuditEvent.objects.filter(pk__in=[saved.source["subscription_audit_id"], saved.source["payment_audit_id"]]).order_by("pk").values()))


def _first_active_observation_history(organization):
    """Internal historical integrity; callers must enforce their own read authority."""
    organization = Organization.objects.get(pk=organization.pk)
    original_org = {"created_at": organization.created_at, "paid_activation_tracking": organization.paid_activation_tracking}
    saved = PaddleFirstActiveObservation.objects.select_related("attempt", "receipt", "organization").filter(organization=organization).first()
    original = {field: getattr(saved, field) for field in OBSERVATION_FIELDS} if saved else None
    result = first_active_observation_result(saved) if saved else None
    current = PaddleFirstActiveObservation.objects.select_related("attempt", "receipt", "organization").filter(organization=organization).first()
    if ({field: getattr(current, field) for field in OBSERVATION_FIELDS} if current else None) != original:
        raise ValidationError("Original first active observation changed during inspection.")
    dependencies = _first_active_history_dependencies(current)
    if (first_active_observation_result(current) if current else None) != result:
        raise ValidationError("Original first active evidence changed during inspection.")
    if (PaddleFirstActiveObservation.objects.filter(organization=organization).values(*OBSERVATION_FIELDS).first() != original
        or _first_active_history_dependencies(current) != dependencies
        or Organization.objects.filter(pk=organization.pk).values(*original_org).first() != original_org):
        raise ValidationError("Original first active history changed before delivery.")
    return {"method": OBSERVATION_METHOD, "organization_id": organization.pk,
        "state": "recorded" if result else "not_observed" if organization.paid_activation_tracking == OBSERVATION_METHOD else "unknown",
        "observation": result}


def inspect_first_active_observation(*, organization, actor):
    organization = Organization.objects.get(pk=organization.pk)
    require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
    result = _first_active_observation_history(organization)
    require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
    return result


def inspect_first_active_observation_timing(*, organization, actor):
    """D153 original organization age, never provider activation time or a cohort rate."""
    history = inspect_first_active_observation(organization=organization, actor=actor)
    result = {"method": "first-active-observation-timing-v1", "state": history["state"],
              "precision": "whole_milliseconds_rounded_down", "tracking_started_at": None,
              "observed_at": None, "source_digest": None, "elapsed_milliseconds": None,
              "interpretation": "organization_age_at_first_paid_server_observation_not_provider_activation_trial_or_cohort"}
    if history["observation"] is not None:
        born = Organization.objects.get(pk=organization.pk).created_at
        observed = parse_datetime(history["observation"]["observed_at"])
        if observed is None or timezone.is_naive(born) or timezone.is_naive(observed) or not born <= observed:
            raise ValidationError("Original paid timing needs billing review.")
        elapsed = observed - born
        milliseconds = (elapsed.days * 86400 + elapsed.seconds) * 1000 + elapsed.microseconds // 1000
        if not 0 <= milliseconds < 2**53:
            raise ValidationError("Original paid timing needs billing review.")
        result.update(tracking_started_at=born.isoformat(), observed_at=observed.isoformat(),
                      source_digest=history["observation"]["source_digest"], elapsed_milliseconds=milliseconds)
    if inspect_first_active_observation(organization=organization, actor=actor) != history:
        raise PermissionDenied
    return result
