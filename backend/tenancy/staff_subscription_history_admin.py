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

from .models import PaddleSubscriptionHistory
from .staff_subscription_history_investigation import (REASONS, inspect_staff_subscription_history,
    require_staff_subscription_history_delivery, require_subscription_history_staff)


class SubscriptionHistoryScopeForm(forms.Form):
    organization_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    history_id = forms.IntegerField(min_value=1, max_value=2**53 - 1, label="Local archived subscription record ID")
    reason = forms.ChoiceField(choices=[(value, value.replace("_", " ")) for value in sorted(REASONS)])


@admin.register(PaddleSubscriptionHistory)
class PaddleSubscriptionHistoryAdmin(admin.ModelAdmin):
    def get_queryset(self, request): return super().get_queryset(request).none()
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

    def has_view_permission(self, request, obj=None):
        if obj is not None: return False
        try: require_subscription_history_staff(request)
        except PermissionDenied: return False
        return True

    def has_module_permission(self, request): return self.has_view_permission(request)

    def get_urls(self):
        return [path("scoped/", self.admin_site.admin_view(self.scoped_view), name="tenancy_paddlesubscriptionhistory_scoped")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        require_subscription_history_staff(request)
        return HttpResponseRedirect(reverse("admin:tenancy_paddlesubscriptionhistory_scoped"))

    @sensitive_variables()
    @method_decorator(sensitive_post_parameters())
    def scoped_view(self, request):
        context = {**self.admin_site.each_context(request), "title": "Inspect exact retained archived subscription",
                   "scope_form": SubscriptionHistoryScopeForm(), "inspection": None, "error": ""}
        status = 200
        try:
            actor = require_subscription_history_staff(request)
            if request.GET or request.method not in {"GET", "POST"}: raise ValidationError("Exact method required.")
            if request.method == "POST":
                if request.content_type != "application/x-www-form-urlencoded" or len(request.body) > 4096:
                    raise ValidationError("Bounded form required.")
                form = SubscriptionHistoryScopeForm(request.POST)
                if (set(request.POST) != set(form.fields) | {"action", "csrfmiddlewaretoken"}
                    or request.POST.get("action") != "inspect" or any(len(request.POST.getlist(key)) != 1 for key in request.POST)
                    or not form.is_valid()):
                    raise ValidationError("Exact local archive scope required.")
                if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                    action="staff_subscription_history_access", user=actor) is None:
                    context["error"] = "Too many archived subscription investigations."; status = 429
                else:
                    with transaction.atomic():
                        result = inspect_staff_subscription_history(request=request, **form.cleaned_data)
                        context["inspection"] = result
                        context["scope_form"] = SubscriptionHistoryScopeForm(initial=form.cleaned_data)
                        response = TemplateResponse(request, "admin/tenancy/subscription_history_investigation.html", context)
                        response.render()
                        require_staff_subscription_history_delivery(request=request, original=result)
                        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
                        return response
        except PermissionDenied:
            context["inspection"] = None; context["error"] = "Current exact archived subscription inspection access is unavailable."; status = 403
        except (ValidationError, ValueError, UnicodeError):
            context["inspection"] = None; context["error"] = "Retained archived subscription needs review. Inspect the exact record again."; status = 409
        response = TemplateResponse(request, "admin/tenancy/subscription_history_investigation.html", context, status=status)
        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
        return response
