"""Exact Admin commands over the existing audited trial services; no new entitlement policy."""
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

from accounts.staff_access import require_staff_permissions
from .models import Organization, OrganizationTrial
from .services import (_finish_trial_correction, _trial_correction_source,
                       approve_organization_trial, extend_organization_trial)
from .staff_trial_investigation import REASONS, inspect_staff_trial, require_staff_trial_delivery, require_trial_staff


def require_trial_change_staff(request):
    return require_staff_permissions(request, permissions=("tenancy.change_organizationtrial",))


class TrialCorrectionForm(forms.Form):
    organization_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    action = forms.ChoiceField(choices=[("approve", "Approve pending trial once (30 days)"),
                                      ("extend", "Extend eligible trial once (original start +37 days)")])
    reason = forms.CharField(min_length=1, max_length=250, widget=forms.Textarea(attrs={"rows": 3}))
    confirm_action = forms.BooleanField(label="I reviewed this exact organization and explicitly confirm the selected correction")


class TrialScopeForm(forms.Form):
    organization_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    trial_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    reason = forms.ChoiceField(choices=[(value, value.replace("_", " ")) for value in sorted(REASONS)])


@admin.register(OrganizationTrial)
class OrganizationTrialAdmin(admin.ModelAdmin):
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

    def has_view_permission(self, request, obj=None):
        if obj is not None:
            return False
        for require in (require_trial_staff, require_trial_change_staff):
            try: require(request)
            except PermissionDenied: continue
            return True  # Independent form discovery only; neither authority grants generic reads.
        return False

    def has_module_permission(self, request): return self.has_view_permission(request)

    def get_queryset(self, request):
        return super().get_queryset(request).none()

    def get_urls(self):
        return [path("scoped/", self.admin_site.admin_view(self.scoped_view), name="tenancy_organizationtrial_scoped"),
                path("corrections/", self.admin_site.admin_view(self.corrections_view), name="tenancy_organizationtrial_corrections")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        try: require_trial_staff(request)
        except PermissionDenied:
            require_trial_change_staff(request)
            return HttpResponseRedirect(reverse("admin:tenancy_organizationtrial_corrections"))
        return HttpResponseRedirect(reverse("admin:tenancy_organizationtrial_scoped"))

    @sensitive_variables()
    @method_decorator(sensitive_post_parameters())
    def scoped_view(self, request):
        context = {**self.admin_site.each_context(request), "title": "Inspect one exact retained organization trial",
                   "scope_form": TrialScopeForm(), "inspection": None, "error": ""}
        status = 200
        try:
            actor = require_trial_staff(request)
            if request.GET or request.method not in {"GET", "POST"}: raise ValidationError("Exact method required.")
            if request.method == "POST":
                if request.content_type != "application/x-www-form-urlencoded" or len(request.body) > 4096:
                    raise ValidationError("Bounded form required.")
                form = TrialScopeForm(request.POST)
                if (set(request.POST) != set(form.fields) | {"action", "csrfmiddlewaretoken"}
                    or request.POST.get("action") != "inspect" or any(len(request.POST.getlist(key)) != 1 for key in request.POST)
                    or not form.is_valid()):
                    raise ValidationError("Exact trial scope required.")
                if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                    action="staff_trial_access", user=actor) is None:
                    context["error"] = "Too many trial investigations."; status = 429
                else:
                    with transaction.atomic():
                        result = inspect_staff_trial(request=request, **form.cleaned_data)
                        context["inspection"] = result
                        context["scope_form"] = TrialScopeForm(initial=form.cleaned_data)
                        response = TemplateResponse(request, "admin/tenancy/trial_investigation.html", context)
                        response.render()
                        require_staff_trial_delivery(request=request, original=result)
                        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
                        return response
        except PermissionDenied:
            context["inspection"] = None; context["error"] = "Current exact trial inspection access is unavailable."; status = 403
        except (ValidationError, ValueError, UnicodeError):
            context["inspection"] = None; context["error"] = "Retained trial needs review. Inspect the exact record again."; status = 409
        response = TemplateResponse(request, "admin/tenancy/trial_investigation.html", context, status=status)
        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @sensitive_variables()
    @method_decorator(sensitive_post_parameters())
    def corrections_view(self, request):
        context = {**self.admin_site.each_context(request), "title": "Correct one exact organization trial",
                   "correction_form": TrialCorrectionForm(), "corrected": None, "error": ""}
        status = 200
        try:
            actor = require_trial_change_staff(request)
            if request.GET or request.method not in {"GET", "POST"}: raise ValidationError("Exact method required.")
            if request.method == "POST":
                if request.content_type != "application/x-www-form-urlencoded" or len(request.body) > 4096:
                    raise ValidationError("Bounded form required.")
                form = TrialCorrectionForm(request.POST)
                if (set(request.POST) != set(form.fields) | {"csrfmiddlewaretoken"}
                    or request.POST.get("confirm_action") != "on"
                    or any(len(request.POST.getlist(key)) != 1 for key in request.POST) or not form.is_valid()):
                    raise ValidationError("Exact confirmed correction required.")
                if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                    action="platform_trial", user=actor) is None:
                    context["error"] = "Too many trial corrections."; status = 429
                else:
                    command = form.cleaned_data
                    with transaction.atomic():
                        organization = Organization.objects.select_for_update().filter(pk=command["organization_id"]).only("id").first()
                        if organization is None: raise PermissionDenied
                        trial = OrganizationTrial.objects.select_for_update().filter(organization=organization).first()
                        if trial is None: raise PermissionDenied
                        expected = _trial_correction_source(trial)
                        handler = approve_organization_trial if command["action"] == "approve" else extend_organization_trial
                        trial = handler(organization=organization, actor=actor, reason=command["reason"], request=request,
                            request_id=getattr(request, "request_id", ""))
                        expected["trial"].update(state=trial.state, started_at=trial.started_at,
                            ends_at=trial.ends_at, updated_at=trial.updated_at)
                        context["corrected"] = {"organization_id": organization.pk, "trial_id": trial.pk,
                            "state": trial.state, "started_at": trial.started_at.isoformat(), "ends_at": trial.ends_at.isoformat()}
                        response = TemplateResponse(request, "admin/tenancy/trial_correction.html", context)
                        response.render()
                        _finish_trial_correction(request=request, actor=actor, trial=trial, expected=expected)
                        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
                        return response
        except PermissionDenied:
            context["corrected"] = None; context["error"] = "Current exact trial correction access is unavailable."; status = 403
        except (ValidationError, ValueError, UnicodeError):
            context["corrected"] = None; context["error"] = "Trial correction was not confirmed. Review the exact organization and current policy again."; status = 409
        response = TemplateResponse(request, "admin/tenancy/trial_correction.html", context, status=status)
        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
        return response
