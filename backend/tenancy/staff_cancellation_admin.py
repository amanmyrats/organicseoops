from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit
from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from .models import OrganizationBillingCancellation
from .staff_cancellation_investigation import (REASONS, inspect_staff_cancellation,
    require_staff_cancellation_delivery, require_cancellation_staff)


class CancellationScopeForm(forms.Form):
    organization_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    cancellation_id = forms.IntegerField(min_value=1, max_value=2**53 - 1, label="Local closure cancellation record ID")
    reason = forms.ChoiceField(choices=[(value, value.replace("_", " ")) for value in sorted(REASONS)])


@admin.register(OrganizationBillingCancellation)
class OrganizationBillingCancellationAdmin(admin.ModelAdmin):
    def get_queryset(self, request): return super().get_queryset(request).none()
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

    def has_view_permission(self, request, obj=None):
        if obj is not None: return False
        try: require_cancellation_staff(request)
        except PermissionDenied: return False
        return True

    def has_module_permission(self, request): return self.has_view_permission(request)

    def get_urls(self):
        return [path("scoped/", self.admin_site.admin_view(self.scoped_view), name="tenancy_organizationbillingcancellation_scoped")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        require_cancellation_staff(request)
        return HttpResponseRedirect(reverse("admin:tenancy_organizationbillingcancellation_scoped"))

    @sensitive_variables()
    @method_decorator(sensitive_post_parameters())
    def scoped_view(self, request):
        context = {**self.admin_site.each_context(request), "title": "Inspect exact retained closure cancellation",
                   "scope_form": CancellationScopeForm(), "inspection": None, "error": ""}
        status = 200
        try:
            actor = require_cancellation_staff(request)
            if request.GET or request.method not in {"GET", "POST"}: raise ValidationError("Exact method required.")
            if request.method == "POST":
                if request.content_type != "application/x-www-form-urlencoded" or len(request.body) > 4096:
                    raise ValidationError("Bounded form required.")
                form = CancellationScopeForm(request.POST)
                if (set(request.POST) != set(form.fields) | {"action", "csrfmiddlewaretoken"}
                    or request.POST.get("action") != "inspect" or any(len(request.POST.getlist(key)) != 1 for key in request.POST)
                    or not form.is_valid()):
                    raise ValidationError("Exact local cancellation scope required.")
                if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                    action="staff_cancellation_access", user=actor) is None:
                    context["error"] = "Too many cancellation investigations."; status = 429
                else:
                    with transaction.atomic():
                        result = inspect_staff_cancellation(request=request, **form.cleaned_data)
                        context["inspection"] = result
                        context["scope_form"] = CancellationScopeForm(initial=form.cleaned_data)
                        response = TemplateResponse(request, "admin/tenancy/cancellation_investigation.html", context)
                        response.render()
                        require_staff_cancellation_delivery(request=request, original=result)
                        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
                        return response
        except PermissionDenied:
            context["inspection"] = None; context["error"] = "Current exact cancellation inspection access is unavailable."; status = 403
        except (ValidationError, ValueError, UnicodeError):
            context["inspection"] = None; context["error"] = "Retained closure cancellation needs review. Inspect the exact record again."; status = 409
        response = TemplateResponse(request, "admin/tenancy/cancellation_investigation.html", context, status=status)
        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
        return response
