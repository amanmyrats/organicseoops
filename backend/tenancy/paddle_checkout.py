"""Fixture-only Paddle Billing checkout shape; no provider request or paid entitlement."""

import re
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (AuditEvent, AuditEventType, Organization, OrganizationDeletionRun, OrganizationTrial,
                      PaddleCheckoutAttempt, PaddleSellerConfiguration,
                     PaddleSubscription, TrialState)
from .paddle_seller import paddle_seller_secrets
from .services import (Action, TRIAL_MEMBER_LIMIT, TRIAL_OFFER_VERSION, TRIAL_PROJECT_LIMIT,
                       TRIAL_UNIT_LIMIT, require_organization_action)


def _current_seller():
    seller = PaddleSellerConfiguration.objects.filter(environment=settings.PADDLE_ENVIRONMENT,
        state=PaddleSellerConfiguration.State.ACTIVE).first()
    if seller is None:
        return None
    try:
        paddle_seller_secrets(seller.environment)
    except ValidationError:
        return None
    return seller


def _recheckout_allowed(subscription):
    return (subscription is None or subscription.status == "canceled" and
            subscription.verified_at is not None and subscription.canceled_at is not None and
            subscription.canceled_at <= timezone.now() and
            subscription.environment == settings.PADDLE_ENVIRONMENT and
            PaddleCheckoutAttempt.objects.filter(organization=subscription.organization,
                paid_verified_at__isnull=False, paid_customer_id=subscription.customer_id,
                paid_subscription_id=subscription.subscription_id,
                state__in=[PaddleCheckoutAttempt.State.READY, PaddleCheckoutAttempt.State.SETTLED]).exists())


def checkout_transaction_body(*, organization_id, price_id, attempt_id):
    if (type(organization_id) is not int or organization_id < 1
        or type(attempt_id) is not int or attempt_id < 1
        or type(price_id) is not str or not re.fullmatch(r"pri_[a-z0-9]{26}", price_id)):
        raise ValidationError("A configured catalog price and organization are required.")
    return {"items": [{"price_id": price_id, "quantity": 1}],
            "collection_mode": "automatic",
            "custom_data": {"organization_id": str(organization_id), "offer_version": TRIAL_OFFER_VERSION,
                            "checkout_attempt_id": str(attempt_id)}}


def parse_checkout_transaction(*, attempt, response, expected_checkout_base):
    """Return only a scoped draft transaction and its approved link; never payment proof."""
    if type(response) is not dict or type(response.get("data")) is not dict:
        raise ValidationError("Provider transaction response is unavailable.")
    row = response["data"]
    transaction_id = row.get("id")
    checkout = row.get("checkout")
    items = row.get("items")
    if (type(transaction_id) is not str or not re.fullmatch(r"txn_[a-z0-9]{26}", transaction_id)
        or row.get("status") not in ("draft", "ready") or row.get("collection_mode") != "automatic"
        or type(row.get("custom_data")) is not dict
        or any(row["custom_data"].get(key) != value for key, value in
               checkout_transaction_body(organization_id=attempt.organization_id,
                   price_id=attempt.price_id, attempt_id=attempt.pk)["custom_data"].items())
        or type(items) is not list or len(items) != 1 or type(items[0]) is not dict
        or type(items[0].get("price")) is not dict or items[0]["price"].get("id") != attempt.price_id
        or type(items[0].get("quantity")) is not int or items[0]["quantity"] != 1
        or type(checkout) is not dict or type(checkout.get("url")) is not str
        or type(expected_checkout_base) is not str or not expected_checkout_base.startswith("https://")
        or "?" in expected_checkout_base or "#" in expected_checkout_base
        or checkout["url"] != f"{expected_checkout_base}?_ptxn={transaction_id}"):
        raise ValidationError("Provider checkout does not match this organization and configured payment page.")
    return {"transaction_id": transaction_id, "checkout_url": checkout["url"], "payment_confirmed": False}


def verify_agency_catalog_price(*, product_id, price_id, response):
    """Validate a single current Paddle `GET /prices/{id}?include=product` result."""
    if (type(response) is not dict or type(response.get("data")) is not dict
        or type(product_id) is not str or not re.fullmatch(r"pro_[a-z0-9]{26}", product_id)
        or type(price_id) is not str or not re.fullmatch(r"pri_[a-z0-9]{26}", price_id)):
        raise ValidationError("Catalog price is unavailable.")
    price = response["data"]
    product = price.get("product")
    cycle = price.get("billing_cycle")
    unit = price.get("unit_price")
    quantity = price.get("quantity")
    if (price.get("id") != price_id or price.get("product_id") != product_id
        or price.get("type") != "standard" or price.get("status") != "active"
        or type(product) is not dict or product.get("id") != product_id
        or product.get("type") != "standard" or product.get("status") != "active"
        or product.get("tax_category") != "saas"
        or type(cycle) is not dict or cycle.get("interval") != "month"
        or type(cycle.get("frequency")) is not int or cycle["frequency"] != 1
        or price.get("trial_period", False) is not None
        or type(unit) is not dict or unit.get("currency_code") != "USD"
        or unit.get("amount") != "14900" or price.get("unit_price_overrides") != []
        or type(quantity) is not dict or type(quantity.get("minimum")) is not int
        or type(quantity.get("maximum")) is not int
        or not quantity["minimum"] <= 1 <= quantity["maximum"]):
        raise ValidationError("Catalog does not match the accepted Agency offer.")
    return {"product_id": product_id, "price_id": price_id, "currency": "USD",
            "amount": "14900", "billing_cycle": "month", "trial_period": None}


def _current_checkout(organization, actor):
    require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
    if OrganizationDeletionRun.objects.filter(organization=organization).exists():
        raise ValidationError("Customer content deletion is underway; reconcile before another checkout.")
    trial = OrganizationTrial.objects.filter(organization=organization).first()
    linked = PaddleSubscription.objects.filter(organization=organization).first()
    if (trial is None or trial.state not in (TrialState.PENDING_REVIEW, TrialState.ACTIVE,
                                             TrialState.EXPIRED, TrialState.READ_ONLY)
        or (trial.started_at is None and trial.state != TrialState.PENDING_REVIEW)
        or (trial.offer_version, trial.project_limit, trial.member_limit, trial.unit_limit) !=
           (TRIAL_OFFER_VERSION, TRIAL_PROJECT_LIMIT, TRIAL_MEMBER_LIMIT, TRIAL_UNIT_LIMIT)
        or not _recheckout_allowed(linked)):
        raise ValidationError("Billing is unavailable for this organization.")
    environment = settings.PADDLE_ENVIRONMENT
    seller = PaddleSellerConfiguration.objects.select_for_update().filter(
        environment=environment, state=PaddleSellerConfiguration.State.ACTIVE).first()
    if seller is None or not seller.client_token:
        raise ValidationError("Seller is not configured for this environment.")
    # Reject missing/rotated bootstrap keys before reserving a durable attempt.
    paddle_seller_secrets(environment)
    return seller


def reserve_paddle_checkout(*, organization, actor, request_key):
    if type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key):
        raise ValidationError("Choose a bounded checkout request key.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        seller = _current_checkout(organization, actor)
        existing = PaddleCheckoutAttempt.objects.filter(organization=organization, request_key=request_key).first()
        if existing:
            if (existing.environment, existing.price_id, existing.product_id, existing.offer_version) != (
                seller.environment, seller.price_id, seller.product_id, TRIAL_OFFER_VERSION):
                raise ValidationError("Checkout settings changed; refresh before continuing.")
            return existing
        unresolved = list(PaddleCheckoutAttempt.objects.select_for_update().filter(organization=organization, state__in=(
            PaddleCheckoutAttempt.State.RESERVED, PaddleCheckoutAttempt.State.SENDING,
            PaddleCheckoutAttempt.State.READY, PaddleCheckoutAttempt.State.UNKNOWN))[:2])
        if unresolved:
            linked = PaddleSubscription.objects.select_for_update().filter(organization=organization).first()
            if (len(unresolved) != 1 or linked is None or linked.status != "canceled"
                or linked.verified_at is None or linked.canceled_at is None
                or linked.canceled_at > timezone.now()
                or unresolved[0].state != PaddleCheckoutAttempt.State.READY
                or unresolved[0].paid_verified_at is None
                or (unresolved[0].paid_customer_id, unresolved[0].paid_subscription_id) !=
                   (linked.customer_id, linked.subscription_id)):
                raise ValidationError("An existing checkout needs a billing status review.")
            unresolved[0].state = PaddleCheckoutAttempt.State.SETTLED
            unresolved[0].save(update_fields=["state", "updated_at"])
        attempt = PaddleCheckoutAttempt.objects.create(
            organization=organization, actor=actor, environment=seller.environment,
            offer_version=TRIAL_OFFER_VERSION, product_id=seller.product_id, price_id=seller.price_id,
            request_key=request_key)
        AuditEvent.objects.create(organization=organization, actor=actor,
            event_type=AuditEventType.BILLING_CHECKOUT_RESERVED,
            details={"checkout_attempt_id": attempt.pk, "environment": seller.environment})
        return attempt


def mark_paddle_checkout_sending(*, attempt, actor, catalog_response):
    """Commit this before any non-idempotent POST; a lost response must never trigger a repeat."""
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=attempt.organization_id)
        current = PaddleCheckoutAttempt.objects.select_for_update().get(pk=attempt.pk, organization=organization)
        seller = _current_checkout(organization, actor)
        if (current.state != PaddleCheckoutAttempt.State.RESERVED
            or (current.environment, current.product_id, current.price_id) !=
               (seller.environment, seller.product_id, seller.price_id)):
            raise ValidationError("Checkout has already been attempted or its catalog changed.")
        verify_agency_catalog_price(product_id=current.product_id, price_id=current.price_id,
                                    response=catalog_response)
        current.state = PaddleCheckoutAttempt.State.SENDING
        current.sent_at = timezone.now()
        current.save(update_fields=["state", "sent_at", "updated_at"])
        AuditEvent.objects.create(organization=organization, actor=actor,
            event_type=AuditEventType.BILLING_CHECKOUT_ATTEMPTED,
            details={"checkout_attempt_id": current.pk, "environment": current.environment})
        return current


def _checkout_base():
    base = settings.PADDLE_CHECKOUT_URL
    try:
        parsed, frontend = urlsplit(base), urlsplit(settings.FRONTEND_ORIGIN)
        if (parsed.scheme != "https" or parsed.netloc != frontend.netloc
            or not parsed.path.startswith("/account/") or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
            raise ValueError
    except (TypeError, ValueError):
        raise ValidationError("Hosted checkout is not configured.") from None
    return base


def _finalize_checkout(*, attempt, state, transaction_id=""):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=attempt.organization_id)
        row = PaddleCheckoutAttempt.objects.select_for_update().get(pk=attempt.pk, organization=organization)
        if row.state != PaddleCheckoutAttempt.State.SENDING or row.sent_at is None:
            raise ValidationError("Checkout request must be reconciled before a new attempt.")
        row.state = state
        row.transaction_id = transaction_id
        row.save(update_fields=["state", "transaction_id", "updated_at"])
        AuditEvent.objects.create(organization=organization, actor=row.actor,
            event_type=(AuditEventType.BILLING_CHECKOUT_READY if state == PaddleCheckoutAttempt.State.READY
                        else AuditEventType.BILLING_CHECKOUT_UNKNOWN),
            details={"checkout_attempt_id": row.pk, "environment": row.environment})
        return row


def start_paddle_checkout(*, organization, actor, request_key, catalog_get=None, transaction_create=None):
    """A single synchronous attempt. Provider POST is never retried after an uncertain outcome."""
    from .paddle_checkout_delivery import checkout_link_delivery_source
    from .paddle_transport import PaddleTransportError, paddle_price_get, paddle_transaction_create

    checkout_base = _checkout_base()
    attempt = reserve_paddle_checkout(organization=organization, actor=actor, request_key=request_key)
    if attempt.state == PaddleCheckoutAttempt.State.READY:
        return {"attempt_id": attempt.pk, "state": "ready", "checkout_url":
                checkout_link_delivery_source(organization=organization, actor=actor,
                    attempt_id=attempt.pk)["checkout_url"] if attempt.paid_verified_at is None else None,
                "payment_confirmed": False, "payment_captured": attempt.paid_verified_at is not None}
    if attempt.state != PaddleCheckoutAttempt.State.RESERVED:
        return {"attempt_id": attempt.pk, "state": attempt.state, "checkout_url": None,
                "payment_confirmed": False, "payment_captured": attempt.paid_verified_at is not None}
    api_key, _webhook_secret = paddle_seller_secrets(attempt.environment)
    catalog_get = catalog_get or paddle_price_get
    transaction_create = transaction_create or paddle_transaction_create
    try:
        catalog_response = catalog_get(environment=attempt.environment, price_id=attempt.price_id,
                                       api_key=api_key)
    except PaddleTransportError:
        # No non-idempotent POST occurred; the same reserved attempt can retry a catalog read.
        return {"attempt_id": attempt.pk, "state": "reserved", "checkout_url": None,
                "payment_confirmed": False, "payment_captured": False}
    attempt = mark_paddle_checkout_sending(attempt=attempt, actor=actor, catalog_response=catalog_response)
    try:
        response = transaction_create(environment=attempt.environment, api_key=api_key, attempt=attempt)
        parsed = parse_checkout_transaction(attempt=attempt, response=response,
                                            expected_checkout_base=checkout_base)
    except (PaddleTransportError, ValidationError, TimeoutError, OSError):
        # Even a provider 4xx or malformed response may have created a transaction.
        attempt = _finalize_checkout(attempt=attempt, state=PaddleCheckoutAttempt.State.UNKNOWN)
        return {"attempt_id": attempt.pk, "state": attempt.state, "checkout_url": None,
                "payment_confirmed": False, "payment_captured": False}
    try:
        attempt = _finalize_checkout(attempt=attempt, state=PaddleCheckoutAttempt.State.READY,
                                     transaction_id=parsed["transaction_id"])
    except (ValidationError, IntegrityError):
        attempt = _finalize_checkout(attempt=attempt, state=PaddleCheckoutAttempt.State.UNKNOWN)
        return {"attempt_id": attempt.pk, "state": attempt.state, "checkout_url": None,
                "payment_confirmed": False, "payment_captured": False}
    source = checkout_link_delivery_source(organization=organization, actor=actor, attempt_id=attempt.pk)
    return {"attempt_id": attempt.pk, "state": "ready", "checkout_url": source["checkout_url"],
            "payment_confirmed": False, "payment_captured": False}
