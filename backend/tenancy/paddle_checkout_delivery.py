"""D140 prospective browser acknowledgment, independent of provider-page loading or payment."""
import hashlib
import json
import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import (AuditEvent, AuditEventType, Organization, OrganizationDeletionRun,
                     PaddleCheckoutAttempt, PaddleCheckoutLinkReceipt, PaddleSellerConfiguration, PaddleSubscription)
from .paddle_checkout import _checkout_base, _current_seller, _recheckout_allowed
from .services import Action, require_organization_action


RECEIPT_METHOD = "checkout-link-receipt-v1"
RECEIPT_SALT = "tenancy.checkout-link-receipt.v1"
RECEIPT_MAX_AGE = 300


def checkout_source_digest(source):
    return hashlib.sha256(json.dumps(source, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def checkout_link_delivery_source(*, organization, actor, attempt_id):
    """Actual current eligibility only; no writes, provider calls or receipt by inspection."""
    if type(attempt_id) is not int or not 1 <= attempt_id < 2**53:
        raise ValidationError("Choose one exact saved checkout attempt.")
    organization = Organization.objects.get(pk=organization.pk)
    require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
    if OrganizationDeletionRun.objects.filter(organization=organization).exists():
        raise PermissionDenied
    attempt = PaddleCheckoutAttempt.objects.filter(pk=attempt_id, organization=organization,
        environment=settings.PADDLE_ENVIRONMENT, state=PaddleCheckoutAttempt.State.READY,
        paid_verified_at__isnull=True, paid_customer_id="", paid_subscription_id="").first()
    if attempt is None:
        raise PermissionDenied
    if not _recheckout_allowed(PaddleSubscription.objects.filter(organization=organization).first()):
        raise PermissionDenied
    seller = _current_seller()
    if (seller is None or not seller.client_token
        or (attempt.environment, attempt.product_id, attempt.price_id, attempt.offer_version) !=
           (seller.environment, seller.product_id, seller.price_id, "agency-launch-v1")):
        raise PermissionDenied
    base = _checkout_base()
    now = timezone.now()
    if (attempt.sent_at is None or timezone.is_naive(attempt.sent_at) or timezone.is_naive(attempt.created_at)
        or not attempt.created_at <= attempt.sent_at <= now
        or seller.rotated_at is None or timezone.is_naive(seller.rotated_at) or seller.rotated_at > now):
        raise ValidationError("Current checkout source dates are unavailable.")
    source = {"method": "checkout-link-delivery-source-v1", "organization_id": organization.pk,
        "actor_id": actor.pk, "attempt_id": attempt.pk, "request_actor_id": attempt.actor_id,
        "environment": attempt.environment, "offer_version": attempt.offer_version,
        "product_id": attempt.product_id, "price_id": attempt.price_id, "transaction_id": attempt.transaction_id,
        "created_at": attempt.created_at.isoformat(), "sent_at": attempt.sent_at.isoformat(),
        "seller_id": seller.pk, "seller_rotated_at": seller.rotated_at.isoformat(),
        "checkout_url": f"{base}?_ptxn={attempt.transaction_id}", "payment_confirmed": False,
        "interpretation": "current_link_receipt_eligibility_not_delivered_link_or_provider_page_or_payment_proof"}
    require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
    return source


def checkout_link_receipt_challenge(*, organization, actor, attempt_id):
    """Read only: obtaining a proof never records a receipt."""
    source = checkout_link_delivery_source(organization=organization, actor=actor, attempt_id=attempt_id)
    issued = timezone.now()
    payload = {"method": RECEIPT_METHOD, "source": source, "issued_at": issued.isoformat()}
    proof = signing.dumps(payload, salt=RECEIPT_SALT)
    if len(proof) > 4096:
        raise ValidationError("Checkout receipt source exceeds its bound.")
    if checkout_link_delivery_source(organization=organization, actor=actor, attempt_id=attempt_id) != source:
        raise PermissionDenied
    return {"method": RECEIPT_METHOD, "source": source, "source_digest": checkout_source_digest(source),
            "proof": proof, "expires_at": (issued + timedelta(seconds=RECEIPT_MAX_AGE)).isoformat()}


def checkout_link_receipt_result(receipt):
    if (type(receipt.source) is not dict or receipt.source_digest != checkout_source_digest(receipt.source)
        or receipt.source.get("attempt_id") != receipt.attempt_id
        or receipt.source.get("actor_id") != receipt.actor_id
        or receipt.source.get("organization_id") != receipt.attempt.organization_id
        or receipt.acknowledged_at is None or timezone.is_naive(receipt.acknowledged_at)
        or receipt.acknowledged_at > timezone.now()):
        raise ValidationError("Saved checkout receipt needs billing review.")
    return {"method": RECEIPT_METHOD, "attempt_id": receipt.attempt_id,
            "source_digest": receipt.source_digest, "acknowledged_at": receipt.acknowledged_at.isoformat(),
            "state": "acknowledged", "payment_confirmed": False,
            "interpretation": "owner_browser_acknowledged_link_not_provider_page_or_payment_proof"}


def inspect_checkout_link_receipt(*, organization, actor, attempt_id):
    """Current-owner exact history; older paid/source-lost receipts remain historical only."""
    if type(attempt_id) is not int or not 1 <= attempt_id < 2**53:
        raise ValidationError("Choose one exact saved checkout attempt.")
    require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
    attempt = PaddleCheckoutAttempt.objects.filter(organization=organization, pk=attempt_id).first()
    if attempt is None:
        raise PermissionDenied
    saved = PaddleCheckoutLinkReceipt.objects.select_related("attempt").filter(attempt=attempt).first()
    receipt = checkout_link_receipt_result(saved) if saved else None
    challenge = None
    if receipt is None:
        try:
            challenge = checkout_link_receipt_challenge(organization=organization, actor=actor, attempt_id=attempt_id)
        except (PermissionDenied, ValidationError):
            pass  # Source-unavailable is not evidence of historical receipt or delivery.
    require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
    return {"method": RECEIPT_METHOD, "organization_id": organization.pk, "attempt_id": attempt.pk,
            "receipt": receipt, "challenge": challenge, "payment_confirmed": False}


def _checkout_link_proof(proof):
    if (type(proof) is not str or not 1 <= len(proof) <= 4096
        or not re.fullmatch(r"[A-Za-z0-9_:-]+", proof)):
        raise ValidationError("Check the bounded checkout receipt proof.")
    try:
        payload = signing.loads(proof, salt=RECEIPT_SALT, max_age=RECEIPT_MAX_AGE)
    except (signing.BadSignature, ValueError, TypeError, UnicodeError):
        raise ValidationError("Checkout receipt proof is invalid or expired.") from None
    if type(payload) is not dict or set(payload) != {"method", "source", "issued_at"} or payload["method"] != RECEIPT_METHOD:
        raise ValidationError("Check the checkout receipt purpose.")
    try:
        issued = parse_datetime(payload["issued_at"]) if type(payload["issued_at"]) is str else None
    except ValueError:
        issued = None
    if issued is None or timezone.is_naive(issued) or not timedelta(0) <= timezone.now() - issued <= timedelta(seconds=RECEIPT_MAX_AGE):
        raise ValidationError("Checkout receipt proof is invalid or expired.")
    return payload["source"], issued


def require_checkout_link_capture_delivery(*, organization, actor, attempt_id, proof, receipt):
    """Original capture fence only; historical reads do not require current eligibility."""
    source, issued = _checkout_link_proof(proof)
    fields = ("id", "attempt_id", "actor_id", "source", "source_digest", "acknowledged_at")
    expected = {field: getattr(receipt, field) for field in fields}
    if (receipt.attempt_id != attempt_id or receipt.actor_id != actor.pk
        or receipt.source != source or receipt.source_digest != checkout_source_digest(source)):
        raise ValidationError("Saved checkout receipt changed before delivery.")
    result = checkout_link_receipt_result(receipt)
    if checkout_link_delivery_source(organization=organization, actor=actor, attempt_id=attempt_id) != source:
        raise PermissionDenied
    if PaddleCheckoutLinkReceipt.objects.filter(pk=receipt.pk, attempt__organization_id=organization.pk).values(*fields).first() != expected:
        raise ValidationError("Saved checkout receipt changed before delivery.")
    if not timedelta(0) <= timezone.now() - issued <= timedelta(seconds=RECEIPT_MAX_AGE):
        raise ValidationError("Checkout receipt proof is invalid or expired.")
    require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
    return result


def acknowledge_checkout_link(*, organization, actor, attempt_id, proof):
    """Serialize one immutable first receipt. Repeats never replay a provider operation."""
    proof_source, issued = _checkout_link_proof(proof)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
        if type(attempt_id) is not int or not 1 <= attempt_id < 2**53:
            raise ValidationError("Choose one exact saved checkout attempt.")
        attempt = PaddleCheckoutAttempt.objects.select_for_update().filter(pk=attempt_id, organization=organization).first()
        if attempt is None:
            raise PermissionDenied
        # Existing mutations serialize on the org; staff seller rotation uses this row lock.
        PaddleSellerConfiguration.objects.select_for_update().filter(environment=settings.PADDLE_ENVIRONMENT).first()
        get_user_model().objects.select_for_update().get(pk=actor.pk)
        source = checkout_link_delivery_source(organization=organization, actor=actor, attempt_id=attempt_id)
        if proof_source != source:
            raise PermissionDenied
        digest = checkout_source_digest(source)
        existing = PaddleCheckoutLinkReceipt.objects.filter(attempt=attempt).first()
        if checkout_link_delivery_source(organization=organization, actor=actor, attempt_id=attempt_id) != source:
            raise PermissionDenied
        if not timedelta(0) <= timezone.now() - issued <= timedelta(seconds=RECEIPT_MAX_AGE):
            raise ValidationError("Checkout receipt proof is invalid or expired.")
        if existing:
            if existing.actor_id != actor.pk or existing.source_digest != digest or existing.source != source:
                raise ValidationError("An earlier receipt already exists; refresh billing history.")
            return require_checkout_link_capture_delivery(organization=organization, actor=actor,
                attempt_id=attempt_id, proof=proof, receipt=existing)
        receipt = PaddleCheckoutLinkReceipt.objects.create(attempt=attempt, actor=actor,
            source=source, source_digest=digest, acknowledged_at=timezone.now())
        AuditEvent.objects.create(organization=organization, actor=actor,
            event_type=AuditEventType.BILLING_CHECKOUT_LINK_ACKNOWLEDGED,
            details={"checkout_attempt_id": attempt.pk, "receipt_id": receipt.pk,
                     "environment": source["environment"], "source_digest": digest})
        return require_checkout_link_capture_delivery(organization=organization, actor=actor,
            attempt_id=attempt_id, proof=proof, receipt=receipt)
