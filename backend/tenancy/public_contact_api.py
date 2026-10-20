"""Fixed anonymous CONTACT intake; a receipt proves storage only."""
import json
import math
import re
import secrets
import time

from django.conf import settings
from django.core import signing
from django.core.exceptions import DisallowedHost, ValidationError
from django.middleware.csrf import get_token
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from integrations.google_tokens import _reject_constant, _unique_object
from .public_analytics_api import response
from .public_contact import MAX_BODY, parse_contact_command
from .public_contact_store import browser_key_hash, create_contact_request, own_contact_receipt

PREFIX = "/api/public-contact/"
PATHS = {PREFIX + "csrf/": "GET", PREFIX + "create/": "POST", PREFIX + "receipt/": "POST"}
COOKIE = "public_contact_capability"
SALT = "tenancy.public-contact.browser-v1"
ERROR = "Contact request unavailable."


class PublicContactRequestGuard:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info.startswith("/admin/tenancy/publiccontactrequest/"):
            result = self.get_response(request)
            if result.status_code >= 400:
                result = response({"message": ERROR}, result.status_code)
            result["Cache-Control"] = "private, no-store"
            result["X-Robots-Tag"] = "noindex, nofollow"
            return result
        if not request.path_info.startswith(PREFIX):
            return self.get_response(request)
        method = PATHS.get(request.path_info)
        if method is None:
            return response({"message": ERROR}, 404)
        if request.method != method:
            result = response({"message": ERROR}, 405)
            result["Allow"] = method
            return result
        try:
            same_host = request.build_absolute_uri("/").rstrip("/") == settings.FRONTEND_ORIGIN
        except DisallowedHost:
            same_host = False
        origin = request.headers.get("Origin")
        if (not same_host or origin is not None and origin != settings.FRONTEND_ORIGIN
            or method == "POST" and origin != settings.FRONTEND_ORIGIN
            or request.headers.get("Sec-Fetch-Site") not in {None, "same-origin"}):
            return response({"message": ERROR}, 403)
        if request.META.get("QUERY_STRING") or request.headers.get("Content-Encoding"):
            return response({"message": ERROR}, 400)
        length = request.META.get("CONTENT_LENGTH", "")
        if method == "POST":
            if (request.content_type != "application/json" or not re.fullmatch(r"[0-9]{1,5}", length)
                or not 1 <= int(length) <= MAX_BODY):
                return response({"message": ERROR}, 413)
        elif length not in {"", "0"}:
            return response({"message": ERROR}, 400)
        result = self.get_response(request)
        # Framework CSRF/host/debug errors must never expose contact body or cookie authority.
        if result.status_code >= 400:
            result = response({"message": ERROR}, result.status_code)
        result["Cache-Control"] = "private, no-store"
        result["X-Robots-Tag"] = "noindex, nofollow"
        return result


def _capability(request, days):
    raw = request.COOKIES.get(COOKIE)
    if type(raw) is not str or not 1 <= len(raw) <= 1024:
        raise ValidationError(ERROR)
    try:
        data = signing.loads(raw, salt=SALT, max_age=days * 86400)
    except (signing.BadSignature, ValueError, TypeError, UnicodeError):
        raise ValidationError(ERROR) from None
    if (type(data) is not dict or set(data) != {"key", "expires", "days", "origin"}
        or type(data["expires"]) is not int or not time.time() < data["expires"] <= time.time() + days * 86400
        or type(data["days"]) is not int or data["days"] != days or data["origin"] != settings.FRONTEND_ORIGIN):
        raise ValidationError(ERROR)
    browser_key_hash(data["key"])
    return data


@sensitive_post_parameters()
@sensitive_variables()
def public_contact_intake(request, action):
    from allauth.account import app_settings
    from allauth.core.internal import ratelimit as bounded_ratelimit
    days = getattr(settings, "PUBLIC_CONTACT_RETENTION_DAYS", None)
    if (getattr(settings, "PUBLIC_CONTACT_ENABLED", False) is not True
        or type(days) is not int or not 1 <= days <= 365):
        return response({"message": ERROR}, 503)
    try:
        name = "public_contact_" + action
        rates = bounded_ratelimit.parse_rates(app_settings.RATE_LIMITS.get(name))
        if (not rates or any(rate.per != "ip" or rate.amount <= 0
                             or not math.isfinite(rate.duration) or rate.duration <= 0 for rate in rates)):
            return response({"message": ERROR}, 503)
        limit = bounded_ratelimit.consume(request, config=app_settings.RATE_LIMITS, limit_get=True, action=name)
    except Exception:
        return response({"message": ERROR}, 503)
    if limit is None:
        return response({"message": ERROR}, 429)
    try:
        if action == "csrf":
            if request.body:
                return response({"message": ERROR}, 400)
            if COOKIE in request.COOKIES:
                capability = _capability(request, days)
                raw = request.COOKIES[COOKIE]
            else:
                capability = {"key": secrets.token_urlsafe(32), "expires": math.floor(time.time()) + days * 86400,
                              "days": days, "origin": settings.FRONTEND_ORIGIN}
                raw = signing.dumps(capability, salt=SALT)
            result = response({"csrfToken": get_token(request), "expires_at": capability["expires"],
                               "scope_hint": browser_key_hash(capability["key"])})
            result.set_cookie(COOKIE, raw, max_age=max(1, math.floor(capability["expires"] - time.time())),
                              path=PREFIX, secure=settings.FRONTEND_ORIGIN.startswith("https://"),
                              httponly=True, samesite="Strict")
            return result
        capability = _capability(request, days)
        if not secrets.compare_digest(request.headers.get("X-Contact-Scope", ""), browser_key_hash(capability["key"])):
            raise ValidationError(ERROR)
        if action == "create":
            result = create_contact_request(browser_key=capability["key"], command=parse_contact_command(request.body))
        else:
            if not 1 <= len(request.body) <= MAX_BODY:
                raise ValueError
            data = json.loads(request.body.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if type(data) is not dict or set(data) != {"request_key"}:
                raise ValueError
            result = {"receipt": own_contact_receipt(browser_key=capability["key"], request_key=data["request_key"])}
    except (UnicodeError, ValueError, TypeError, RecursionError):
        return response({"message": ERROR}, 400)
    except ValidationError:
        return response({"message": ERROR}, 409)
    return response(result)
