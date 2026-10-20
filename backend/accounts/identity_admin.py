"""Exact, CSRF-protected operator cleanup; public account closure remains independent."""
from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.template.response import TemplateResponse
from allauth.core import ratelimit

from .closure import erase_closed_account_identity
from .models import User
from .staff_access import require_staff_permissions


class IdentityCleanupForm(forms.Form):
    user_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    policy_reference = forms.RegexField(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$", max_length=64)
    acknowledge_account_only_cleanup = forms.BooleanField()


def identity_cleanup_view(admin_site, request):
    require_staff_permissions(request, permissions=("accounts.change_user",))
    context = {**admin_site.each_context(request), "title": "Clean one closed account identity",
               "scope_form": IdentityCleanupForm(), "error": "", "cleaned": False}
    status = 200
    try:
        if request.GET or request.method not in {"GET", "POST"}:
            raise ValidationError("Exact method required.")
        if request.method == "POST":
            form = IdentityCleanupForm(request.POST)
            if (request.content_type != "application/x-www-form-urlencoded" or len(request.body) > 4096
                or set(request.POST) != set(form.fields) | {"csrfmiddlewaretoken"}
                or any(len(request.POST.getlist(key)) != 1 for key in request.POST) or not form.is_valid()):
                raise ValidationError("Exact bounded cleanup form required.")
            if not ratelimit.consume(request, action="staff_identity_cleanup", user=request.user):
                context["error"], status = "Too many identity cleanup requests.", 429
            else:
                erase_closed_account_identity(request=request, user_id=form.cleaned_data["user_id"],
                                              policy_reference=form.cleaned_data["policy_reference"])
                context["cleaned"] = True
    except PermissionDenied:
        context["error"], status = "Current MFA and account change permission required.", 403
    except (ValidationError, User.DoesNotExist, ValueError, UnicodeError):
        context["error"], status = "Cleanup unavailable. Reconcile the closed account and configured reviewed policy.", 409
    response = TemplateResponse(request, "admin/accounts/identity_cleanup.html", context, status=status)
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    return response
