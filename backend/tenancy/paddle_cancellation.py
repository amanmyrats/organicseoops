"""Closure billing: commit one attempted cancellation before contacting Paddle."""
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (AuditEvent, AuditEventType, Organization, OrganizationBillingCancellation,
                     PaddleStatus, PaddleSubscription)
from .paddle_reconcile import _provider_datetime
from .paddle_seller import paddle_seller_secrets
from .paddle_transport import PaddleTransportError, paddle_subscription_cancel, paddle_subscription_get
from .services import Action, require_organization_action


def require_confirmed_closed_billing(organization):
    """Never erase a paid tenant's content while its cancellation is uncertain."""
    subscription = PaddleSubscription.objects.filter(organization=organization).first()
    if subscription is None:
        return
    if subscription.verified_at is None or subscription.environment != settings.PADDLE_ENVIRONMENT:
        raise ValidationError("Reconcile the current paid subscription before deleting customer content.")
    if subscription.status == PaddleStatus.CANCELED and subscription.canceled_at is not None:
        return
    confirmed = OrganizationBillingCancellation.objects.filter(
        organization=organization, subscription=subscription,
        environment=subscription.environment, customer_id=subscription.customer_id,
        provider_subscription_id=subscription.subscription_id,
        state=OrganizationBillingCancellation.State.CONFIRMED).first()
    if confirmed is None or subscription.verified_at > confirmed.confirmed_at:
        raise ValidationError("Confirm current provider cancellation before deleting customer content.")


def prepare_billing_cancellation(*, organization, actor):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
        subscription = PaddleSubscription.objects.select_for_update().filter(organization=organization).first()
        if subscription is None:
            return None  # Trial-only organizations need no provider cancellation.
        if (subscription.verified_at is None or subscription.environment != settings.PADDLE_ENVIRONMENT
            or subscription.status == PaddleStatus.CANCELED and subscription.canceled_at is None):
            raise ValidationError("Reconcile the linked provider subscription before closing.")
        if subscription.status == PaddleStatus.CANCELED:
            return None
        paddle_seller_secrets(subscription.environment)
        existing = OrganizationBillingCancellation.objects.filter(organization=organization).first()
        if existing:
            if existing.subscription_id != subscription.pk:
                raise ValidationError("The provider subscription changed during closure preparation.")
            return existing
        attempt = OrganizationBillingCancellation.objects.create(
            organization=organization, subscription=subscription, actor=actor,
            environment=subscription.environment, customer_id=subscription.customer_id,
            provider_subscription_id=subscription.subscription_id)
        AuditEvent.objects.create(organization=organization, actor=actor,
            event_type=AuditEventType.BILLING_CANCELLATION_PREPARED,
            details={"attempt_id": attempt.pk})
        return attempt


def _observed_cancellation(attempt, response):
    row = response.get("data") if type(response) is dict else None
    if (type(row) is not dict or row.get("id") != attempt.provider_subscription_id
        or row.get("customer_id") != attempt.customer_id or row.get("status") != PaddleStatus.CANCELED):
        raise ValidationError("Provider cancellation is not confirmed.")
    canceled_at = _provider_datetime(row.get("canceled_at"))
    if canceled_at > timezone.now():
        raise ValidationError("Provider cancellation time is not confirmed.")
    return canceled_at


def _record_cancellation_result(attempt, *, response=None, category=""):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=attempt.organization_id)
        current = OrganizationBillingCancellation.objects.select_for_update().get(pk=attempt.pk, organization=organization)
        if current.state == current.State.CONFIRMED:
            return current
        if current.state not in {current.State.SENDING, current.State.UNKNOWN} or organization.closed_at is None:
            raise PermissionDenied
        previous_state, previous_error = current.state, current.error_category
        try:
            canceled_at = _observed_cancellation(current, response)
        except ValidationError:
            current.state = current.State.UNKNOWN
            current.error_category = category or "provider_unconfirmed"
            current.save(update_fields=["state", "error_category"])
        else:
            current.state = current.State.CONFIRMED
            current.confirmed_at = canceled_at
            current.error_category = ""
            current.save(update_fields=["state", "confirmed_at", "error_category"])
        if (current.state, current.error_category) != (previous_state, previous_error):
            AuditEvent.objects.create(organization=organization, actor=current.actor,
                event_type=(AuditEventType.BILLING_CANCELLATION_CONFIRMED
                            if current.state == current.State.CONFIRMED
                            else AuditEventType.BILLING_CANCELLATION_UNKNOWN),
                details={"attempt_id": current.pk, "error_category": current.error_category})
        return current


def execute_billing_cancellation(attempt, *, cancel=paddle_subscription_cancel):
    # Read credentials before claiming an irreversible POST; failed configuration is retryable.
    api_key = paddle_seller_secrets(attempt.environment)[0]
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=attempt.organization_id)
        current = OrganizationBillingCancellation.objects.select_for_update().select_related("subscription").get(
            pk=attempt.pk, organization=organization)
        if current.state != current.State.RESERVED or organization.closed_at is None or not organization.is_suspended:
            return current  # Never automatically repeat an attempted provider POST.
        current.state = current.State.SENDING
        current.attempted_at = timezone.now()
        current.save(update_fields=["state", "attempted_at"])
        AuditEvent.objects.create(organization=organization, actor=current.actor,
            event_type=AuditEventType.BILLING_CANCELLATION_ATTEMPTED, details={"attempt_id": current.pk})
    try:
        response = cancel(attempt=current, api_key=api_key)
    except PaddleTransportError as error:
        return _record_cancellation_result(current, category=error.category)
    except (OSError, TimeoutError):
        return _record_cancellation_result(current, category="network_error")
    return _record_cancellation_result(current, response=response)


def reconcile_billing_cancellation(attempt, *, subscription_get=paddle_subscription_get):
    current = OrganizationBillingCancellation.objects.select_related("organization").get(pk=attempt.pk)
    if current.state == current.State.CONFIRMED:
        return current
    if current.state not in {current.State.SENDING, current.State.UNKNOWN} or current.organization.closed_at is None:
        raise PermissionDenied
    api_key = paddle_seller_secrets(current.environment)[0]
    try:
        response = subscription_get(environment=current.environment,
            subscription_id=current.provider_subscription_id, api_key=api_key)
    except PaddleTransportError as error:
        return _record_cancellation_result(current, category=error.category)
    return _record_cancellation_result(current, response=response)
