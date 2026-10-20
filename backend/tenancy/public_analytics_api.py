"""Fixed anonymous capability intake, independent of account/customer authentication."""
import json
import re

from django.conf import settings
from django.core.exceptions import DisallowedHost, ValidationError
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from .public_analytics import (ERROR, issue_public_analytics_epoch, record_public_observation,
                               retained_public_observation_counts, withdraw_public_analytics_epoch)
from .public_analytics_policy import _nonfinite, _object

PREFIX = "/api/public-analytics/"
PATHS = {PREFIX + "csrf/": "GET", **{PREFIX + action + "/": "POST" for action in ("grant", "receipt", "withdraw")}}
MAX_BODY = 2048
STAFF_PATH = "/api/platform/acquisition/public-observations/"


def response(data, status=200):
    result = JsonResponse(data, status=status)
    result["Cache-Control"] = "private, no-store"
    result["X-Robots-Tag"] = "noindex, nofollow"
    return result


class PublicAnalyticsRequestGuard:
    """Before CSRF/body parsing; also fence headers on framework rejection responses."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info == STAFF_PATH or request.path_info.startswith("/api/platform/acquisition/trial-paid-cohorts/"):
            result = self.get_response(request)
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
            if (request.content_type != "application/json" or not re.fullmatch(r"[0-9]{1,4}", length)
                or not 1 <= int(length) <= MAX_BODY):
                return response({"message": ERROR}, 413)
        elif length not in {"", "0"}:
            return response({"message": ERROR}, 400)
        result = self.get_response(request)
        result["Cache-Control"] = "private, no-store"
        result["X-Robots-Tag"] = "noindex, nofollow"
        return result


@sensitive_post_parameters()
@sensitive_variables()
def public_analytics_intake(request, action):
    # IP limits live only in the maintained short-lived rate cache, never analytics rows.
    from allauth.account import app_settings
    from allauth.core.internal import ratelimit as bounded_ratelimit
    try:
        limit = bounded_ratelimit.consume(request, config=app_settings.RATE_LIMITS, limit_get=True,
                                         action="public_analytics_" + action)
    except Exception:
        return response({"message": ERROR}, 503)
    if limit is None:
        return response({"message": ERROR}, 429)
    if action == "csrf":
        if request.body:
            return response({"message": ERROR}, 400)
        return response({"csrfToken": get_token(request)})
    try:
        if not 1 <= len(request.body) <= MAX_BODY:
            raise ValueError
        data = json.loads(request.body.decode("utf-8"), object_pairs_hook=_object, parse_constant=_nonfinite)
        keys = {"grant": {"allowed", "consent_version"}, "receipt": {"receipt_proof", "candidate"},
                "withdraw": {"receipt_proof"}}[action]
        if type(data) is not dict or set(data) != keys:
            raise ValueError
        if action == "grant":
            result = issue_public_analytics_epoch(**data)
        elif action == "receipt":
            result = record_public_observation(**data)
        else:
            result = withdraw_public_analytics_epoch(**data)
    except (UnicodeError, ValueError, TypeError, RecursionError):
        return response({"message": ERROR}, 400)
    except ValidationError:
        return response({"message": ERROR}, 409)
    return response(result)


def platform_public_analytics_observations(request):
    if request.method != "GET":
        result = response({"message": ERROR}, 405)
        result["Allow"] = "GET"
        return result
    if not request.user.is_authenticated or not request.user.is_active:
        return response({"message": "Authentication required."}, 401)
    if not request.user.is_staff or not request.user.is_superuser:
        return response({"message": "Platform permission required."}, 403)
    if request.META.get("QUERY_STRING") or request.body:
        return response({"message": ERROR}, 400)
    from allauth.account import app_settings
    from allauth.core.internal import ratelimit as bounded_ratelimit
    if bounded_ratelimit.consume(request, config=app_settings.RATE_LIMITS, limit_get=True,
            action="public_analytics_staff_read", user=request.user) is None:
        return response({"message": ERROR}, 429)
    try:
        result = retained_public_observation_counts()
    except ValidationError:
        return response({"message": ERROR}, 409)
    return response(result)
