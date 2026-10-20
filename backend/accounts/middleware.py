from urllib.parse import urlencode

from allauth.account.authentication import get_authentication_records
from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponseRedirect, JsonResponse


class StaffMFAMiddleware:
    authenticator_path = "/_allauth/browser/v1/account/authenticators"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(self.authenticator_path):
            if not request.user.is_authenticated or not request.user.is_staff:
                return JsonResponse({}, status=404)

        privileged = request.path.startswith("/admin/") or request.path.startswith("/api/platform/")
        if settings.STAFF_MFA_REQUIRED and privileged and request.user.is_authenticated and request.user.is_staff:
            from allauth.mfa.models import Authenticator
            from allauth.mfa.utils import is_mfa_enabled

            if not is_mfa_enabled(request.user, types=[Authenticator.Type.TOTP]):
                if request.path.startswith("/api/"):
                    return JsonResponse(
                        {"errors": [{"code": "mfa_required", "message": "Staff two-factor authentication is required."}]},
                        status=403,
                    )
                query = urlencode({"mfa": "required", "next": request.get_full_path()})
                return HttpResponseRedirect(f"{settings.FRONTEND_ORIGIN}/account/security?{query}")
            if not any(record.get("method") == "mfa" for record in get_authentication_records(request)):
                logout(request)
                if request.path.startswith("/api/"):
                    return JsonResponse(
                        {"errors": [{"code": "mfa_authentication_required", "message": "Sign in with two-factor authentication."}]},
                        status=403,
                    )
                query = urlencode({"mfa": "required", "next": request.get_full_path()})
                return HttpResponseRedirect(f"{settings.FRONTEND_ORIGIN}/account/login?{query}")

        return self.get_response(request)
