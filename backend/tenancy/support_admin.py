from uuid import uuid4

from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit
from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from .models import SupportRequest
from .support_staff import REASONS, inspect_staff_support, require_support_staff, require_staff_support_delivery


class SupportScopeForm(forms.Form):
    organization_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    project_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    request_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    reason = forms.ChoiceField(choices=[(value, value.replace("_", " ")) for value in sorted(REASONS)])


class SupportResponseForm(SupportScopeForm):
    organization_id = forms.IntegerField(widget=forms.HiddenInput, min_value=1, max_value=2**53 - 1)
    project_id = forms.IntegerField(widget=forms.HiddenInput, min_value=1, max_value=2**53 - 1)
    request_id = forms.IntegerField(widget=forms.HiddenInput, min_value=1, max_value=2**53 - 1)
    reason = forms.ChoiceField(widget=forms.HiddenInput, choices=[(value, value) for value in sorted(REASONS)])
    request_key = forms.CharField(widget=forms.HiddenInput, min_length=8, max_length=64)
    expected_revision = forms.IntegerField(widget=forms.HiddenInput, min_value=0, max_value=2**31 - 2)
    status = forms.ChoiceField(choices=[("in_progress", "In progress"), ("resolved", "Resolved"), ("received", "Reopen as received")])
    response = forms.CharField(strip=False, max_length=2000, widget=forms.Textarea(attrs={"rows": 5, "maxlength": 2000}))


@admin.register(SupportRequest)
class SupportRequestAdmin(admin.ModelAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).none()  # Only the explicit audited scope form reads content.

    def has_view_permission(self, request, obj=None):
        try: require_support_staff(request)
        except PermissionDenied: return False
        return True

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

    def get_urls(self):
        return [path("scoped/", self.admin_site.admin_view(self.scoped_view), name="tenancy_supportrequest_scoped")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        require_support_staff(request)
        return HttpResponseRedirect(reverse("admin:tenancy_supportrequest_scoped"))

    @sensitive_variables()
    @method_decorator(sensitive_post_parameters())
    def scoped_view(self, request):
        context = {**self.admin_site.each_context(request), "title": "Inspect an exact scoped support request",
                   "scope_form": SupportScopeForm(), "support": None, "response_form": None, "error": ""}
        status = 200
        try:
            require_support_staff(request)
            if request.GET or request.method not in {"GET", "POST"}: raise ValidationError("Exact method required.")
            if request.method == "POST":
                if request.content_type != "application/x-www-form-urlencoded" or len(request.body) > 24 * 1024:
                    raise ValidationError("Bounded form required.")
                action = request.POST.get("action")
                form = SupportScopeForm(request.POST) if action == "inspect" else SupportResponseForm(request.POST)
                if (action not in {"inspect", "respond"} or set(request.POST) != set(form.fields) | {"action", "csrfmiddlewaretoken"}
                    or any(len(request.POST.getlist(key)) != 1 for key in request.POST) or not form.is_valid()):
                    raise ValidationError("Exact scope form required.")
                if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                    action="support_staff_access" if action == "inspect" else "support_staff_update", user=request.user) is None:
                    context["error"] = "Too many support actions."; status = 429
                else:
                    data = form.cleaned_data
                    scope = {key: data[key] for key in ("organization_id", "project_id", "request_id", "reason")}
                    command = {key: data[key] for key in ("request_key", "expected_revision", "status", "response")} if action == "respond" else None
                    result = inspect_staff_support(request=request, **scope, command=command)
                    context["support"] = result["request"]
                    context["scope_form"] = SupportScopeForm(initial=scope)
                    if self._can_respond(request):
                        context["response_form"] = SupportResponseForm(initial={**scope, "request_key": uuid4().hex,
                            "expected_revision": result["request"]["revision"], "status": "in_progress"})
                    response = TemplateResponse(request, "admin/tenancy/support_request.html", context)
                    response.render()
                    require_staff_support_delivery(request=request, organization_id=scope["organization_id"],
                        project_id=scope["project_id"], original=context["support"])
                    response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
                    return response
        except PermissionDenied:
            context["support"] = context["response_form"] = None
            context["error"] = "Current scoped support access is unavailable."; status = 403
        except (ValidationError, ValueError, UnicodeError):
            context["support"] = context["response_form"] = None
            context["error"] = "Support action needs review. Inspect the exact current request before an explicit retry."; status = 409
        response = TemplateResponse(request, "admin/tenancy/support_request.html", context, status=status)
        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
        return response

    def _can_respond(self, request):
        try: require_support_staff(request, change=True)
        except PermissionDenied: return False
        return True
