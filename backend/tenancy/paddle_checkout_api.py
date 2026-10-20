import json
import re
from http import HTTPStatus

from allauth.core import ratelimit
from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit as receipt_ratelimit
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .models import Organization, PaddleCheckoutAttempt, PaddleCheckoutLinkReceipt, PaddleSubscription
from .paddle_checkout import _checkout_base, _current_seller, _recheckout_allowed, start_paddle_checkout
from .paddle_portal import create_organization_portal
from .paddle_transport import PaddleTransportError, _reject_constant, _unique_object
from .paddle_checkout_delivery import (acknowledge_checkout_link, checkout_link_delivery_source,
                                       inspect_checkout_link_receipt, require_checkout_link_capture_delivery)
from .billing_state import paid_access_state
from .paddle_activation import inspect_first_active_observation, inspect_first_active_observation_timing
from .trial_activation import inspect_trial_activation
from .trial_paid_timing import inspect_trial_paid_timing
from .trial_paid_window import inspect_trial_paid_window
from .services import Action, require_organization_action


def _response(data, status=HTTPStatus.OK):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def organization_paid_observation_timing(request, organization_id, history_kind="paid_timing"):
    if request.method != "GET":
        result = _response({"message": "Inspect original billing history with GET."}, HTTPStatus.METHOD_NOT_ALLOWED)
        result["Allow"] = "GET"
        return result
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if request.META.get("QUERY_STRING") or request.body or not 1 <= organization_id < 2**53:
        return _response({"message": "Choose one exact organization without additional input."}, HTTPStatus.BAD_REQUEST)
    organization = Organization.objects.for_user(request.user).filter(pk=organization_id).first()
    if organization is None:
        return _response({"message": "Organization unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_organization_action(organization=organization, user=request.user, action=Action.MANAGE_BILLING)
        if receipt_ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                action="billing_checkout_receipt_read", user=request.user) is None:
            return _response({"message": "Too many historical billing inspections."}, HTTPStatus.TOO_MANY_REQUESTS)
        # Fixed URL defaults select the source; no client query/body chooses another history kind.
        inspect, field = {
            "paid_timing": (inspect_first_active_observation_timing, "timing"),
            "trial_activation": (inspect_trial_activation, "trial_activation"),
            "trial_paid_timing": (inspect_trial_paid_timing, "timing"),
            "trial_paid_window": (inspect_trial_paid_window, "window"),
        }[history_kind]
        history = inspect(organization=organization, actor=request.user)
    except PermissionDenied:
        return _response({"message": "Owner billing history access required."}, HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _response({"message": "Original billing history needs review."}, HTTPStatus.CONFLICT)
    return _response({"organization_id": organization_id, field: history})


@require_http_methods(["GET", "POST"])
def organization_checkout(request, organization_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    organization = Organization.objects.for_user(request.user).filter(pk=organization_id).first()
    if organization is None:
        return _response({"message": "Organization not found."}, HTTPStatus.NOT_FOUND)
    try:
        require_organization_action(organization=organization, user=request.user, action=Action.MANAGE_BILLING)
    except PermissionDenied:
        return _response({"message": "Owner billing access required."}, HTTPStatus.FORBIDDEN)
    if request.method == "GET":
        portal_seller = _current_seller()
        seller = portal_seller if portal_seller and portal_seller.client_token else None
        current_link = PaddleSubscription.objects.filter(organization=organization).first()
        subscription = (current_link if current_link and
            current_link.environment == settings.PADDLE_ENVIRONMENT else None)
        linked = current_link is not None
        try:
            base = _checkout_base() if seller else None
        except ValidationError:
            base = None
        if linked and not _recheckout_allowed(current_link):
            base = None
        attempts = PaddleCheckoutAttempt.objects.filter(organization=organization).order_by("-id")[:20]
        unresolved = list(PaddleCheckoutAttempt.objects.filter(organization=organization, state__in=[
            PaddleCheckoutAttempt.State.RESERVED, PaddleCheckoutAttempt.State.SENDING,
            PaddleCheckoutAttempt.State.READY, PaddleCheckoutAttempt.State.UNKNOWN]).order_by("-id")[:2])
        can_start = bool(base) and (not unresolved or len(unresolved) == 1 and current_link is not None
            and _recheckout_allowed(current_link) and unresolved[0].state == PaddleCheckoutAttempt.State.READY
            and unresolved[0].paid_verified_at is not None
            and (unresolved[0].paid_customer_id, unresolved[0].paid_subscription_id) ==
                (current_link.customer_id, current_link.subscription_id))
        history = []
        for row in attempts:
            try:
                link = checkout_link_delivery_source(organization=organization, actor=request.user,
                    attempt_id=row.pk)["checkout_url"]
            except (PermissionDenied, ValidationError):
                link = None
            history.append({"id": row.pk, "state": row.state, "environment": row.environment,
                "created_at": row.created_at.isoformat(), "payment_confirmed": False,
                "payment_captured": row.paid_verified_at is not None, "checkout_url": link})
        try:
            first_paid_observation = inspect_first_active_observation(organization=organization, actor=request.user)
            require_organization_action(organization=organization, user=request.user, action=Action.MANAGE_BILLING)
        except PermissionDenied:
            return _response({"message": "Owner billing access required."}, HTTPStatus.FORBIDDEN)
        except ValidationError:
            return _response({"message": "Saved paid observation needs billing review."}, HTTPStatus.CONFLICT)
        return _response({"seller_configured": bool(base), "offer_version": "agency-launch-v1",
                          "can_start_new_checkout": can_start,
                          "client_token": seller.client_token if base else "",
                          "subscription_linked": linked,
                          "billing_access_state": paid_access_state(subscription) if subscription else "unverified",
                           "portal_available": bool(subscription and portal_seller),
                           "first_paid_observation": first_paid_observation,
                           "attempts": history})
    if not ratelimit.consume(request, action="billing_checkout", user=request.user):
        return _response({"message": "Too many checkout requests."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if len(request.body) > 1024:
            raise ValueError
        data = json.loads(request.body)
        if type(data) is not dict or set(data) != {"request_key"}:
            raise ValueError
        result = start_paddle_checkout(organization=organization, actor=request.user,
                                       request_key=data["request_key"])
    except PermissionDenied:
        return _response({"message": "Owner billing access required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, IntegrityError, TypeError, ValueError, UnicodeError):
        return _response({"message": "Checkout is unavailable or needs a billing status review."}, HTTPStatus.CONFLICT)
    return _response(result, HTTPStatus.OK if result["state"] == "ready" else HTTPStatus.ACCEPTED)


@require_http_methods(["POST"])
def organization_portal(request, organization_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    organization = Organization.objects.for_user(request.user).filter(pk=organization_id).first()
    if organization is None:
        return _response({"message": "Organization not found."}, HTTPStatus.NOT_FOUND)
    try:
        require_organization_action(organization=organization, user=request.user, action=Action.MANAGE_BILLING)
    except PermissionDenied:
        return _response({"message": "Owner billing access required."}, HTTPStatus.FORBIDDEN)
    if len(request.body) > 16 or request.body.strip() != b"{}":
        return _response({"message": "Check the portal request."}, HTTPStatus.BAD_REQUEST)
    if not ratelimit.consume(request, action="billing_portal", user=request.user):
        return _response({"message": "Too many billing portal requests."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        url = create_organization_portal(organization=organization, actor=request.user)
    except PermissionDenied:
        return _response({"message": "Owner billing access required."}, HTTPStatus.FORBIDDEN)
    except (PaddleTransportError, ValidationError, IntegrityError, TypeError, ValueError, UnicodeError):
        return _response({"message": "Billing portal is unavailable; refresh billing status."}, HTTPStatus.CONFLICT)
    return _response({"portal_url": url})


@require_http_methods(["GET"])
def checkout_page_resolution(request):
    """Resolve a Paddle payment-page transaction to its current authenticated owner."""
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    transaction_id = request.GET.get("transaction_id")
    if (list(request.GET) != ["transaction_id"] or len(request.GET.getlist("transaction_id")) != 1
        or type(transaction_id) is not str
        or not re.fullmatch(r"txn_[a-z0-9]{26}", transaction_id)):
        return _response({"message": "Checkout not found."}, HTTPStatus.NOT_FOUND)
    attempt = PaddleCheckoutAttempt.objects.select_related("organization").filter(
        transaction_id=transaction_id, environment=settings.PADDLE_ENVIRONMENT,
        state=PaddleCheckoutAttempt.State.READY, paid_verified_at__isnull=True).first()
    if attempt is None:
        return _response({"message": "Checkout not found."}, HTTPStatus.NOT_FOUND)
    try:
        require_organization_action(organization=attempt.organization, user=request.user, action=Action.MANAGE_BILLING)
    except PermissionDenied:
        return _response({"message": "Checkout not found."}, HTTPStatus.NOT_FOUND)
    seller = _current_seller()
    try:
        source = checkout_link_delivery_source(organization=attempt.organization, actor=request.user, attempt_id=attempt.pk)
    except (PermissionDenied, ValidationError):
        return _response({"message": "Checkout not found."}, HTTPStatus.NOT_FOUND)
    if (seller is None or not seller.client_token or seller.pk != source["seller_id"]
        or seller.rotated_at.isoformat() != source["seller_rotated_at"]):
        return _response({"message": "Checkout not found."}, HTTPStatus.NOT_FOUND)
    return _response({"organization_id": attempt.organization_id, "attempt_id": attempt.pk,
                      "environment": attempt.environment, "client_token": seller.client_token,
                      "transaction_id": attempt.transaction_id, "checkout_url": source["checkout_url"],
                      "payment_confirmed": False})


@require_http_methods(["GET", "POST"])
def organization_checkout_link_receipt(request, organization_id, attempt_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    organization = Organization.objects.for_user(request.user).filter(pk=organization_id).first()
    if organization is None:
        return _response({"message": "Organization not found."}, HTTPStatus.NOT_FOUND)
    try:
        require_organization_action(organization=organization, user=request.user, action=Action.MANAGE_BILLING)
    except PermissionDenied:
        return _response({"message": "Owner billing access required."}, HTTPStatus.FORBIDDEN)
    if request.GET or not 1 <= attempt_id < 2**53:
        return _response({"message": "Choose one exact saved checkout attempt."}, HTTPStatus.BAD_REQUEST)
    if not PaddleCheckoutAttempt.objects.filter(pk=attempt_id, organization=organization).exists():
        return _response({"message": "Checkout not found."}, HTTPStatus.NOT_FOUND)
    # The public allauth wrapper deliberately skips GET; explicitly include these proof reads.
    if receipt_ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
            action="billing_checkout_receipt_read" if request.method == "GET" else "billing_checkout_receipt",
            user=request.user) is None:
        return _response({"message": "Too many checkout receipt requests."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if request.method == "GET":
            result = inspect_checkout_link_receipt(organization=organization, actor=request.user, attempt_id=attempt_id)
        else:
            if request.content_type != "application/json" or len(request.body) > 6144:
                raise ValueError
            data = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if type(data) is not dict or set(data) != {"receipt_proof", "acknowledge_link_received"} or data["acknowledge_link_received"] is not True:
                raise ValueError
            with transaction.atomic():
                result = acknowledge_checkout_link(organization=organization, actor=request.user,
                    attempt_id=attempt_id, proof=data["receipt_proof"])
                receipt = PaddleCheckoutLinkReceipt.objects.select_related("attempt").filter(
                    attempt_id=attempt_id, attempt__organization_id=organization.pk).first()
                if receipt is None or result != require_checkout_link_capture_delivery(
                    organization=organization, actor=request.user, attempt_id=attempt_id,
                    proof=data["receipt_proof"], receipt=receipt):
                    raise ValidationError("Saved checkout receipt changed before delivery.")
                response = _response(result)
                require_checkout_link_capture_delivery(organization=organization, actor=request.user,
                    attempt_id=attempt_id, proof=data["receipt_proof"], receipt=receipt)
                return response
    except PermissionDenied:
        return _response({"message": "Current owner checkout source is unavailable."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, IntegrityError, TypeError, ValueError, UnicodeError, RecursionError):
        return _response({"message": "Receipt could not be confirmed. Inspect this saved attempt before another acknowledgment."}, HTTPStatus.CONFLICT)
    return _response(result)
