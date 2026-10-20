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

from .models import JobRun
from .staff_job_investigation import REASONS, inspect_staff_job, require_job_staff, require_staff_job_delivery
from .staff_usage_investigation import inspect_staff_usage, require_usage_staff, require_staff_usage_delivery
from .staff_ai_usage_investigation import inspect_staff_ai_usage, require_ai_usage_staff, require_staff_ai_usage_delivery


class JobScopeForm(forms.Form):
    organization_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    project_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    job_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    reason = forms.ChoiceField(choices=[(value, value.replace("_", " ")) for value in sorted(REASONS)])


def _allowed(request, require):
    try: require(request)
    except PermissionDenied: return False
    return True


def _require_inspector(request):
    if not (_allowed(request, require_job_staff) or _allowed(request, require_usage_staff) or _allowed(request, require_ai_usage_staff)):
        raise PermissionDenied


@admin.register(JobRun)
class JobRunAdmin(admin.ModelAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).none()

    def has_view_permission(self, request, obj=None):
        try: _require_inspector(request)
        except PermissionDenied: return False
        return True

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

    def get_urls(self):
        return [path("scoped/", self.admin_site.admin_view(self.scoped_view), name="jobs_jobrun_scoped")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        _require_inspector(request)
        return HttpResponseRedirect(reverse("admin:jobs_jobrun_scoped"))

    @sensitive_variables()
    @method_decorator(sensitive_post_parameters())
    def scoped_view(self, request):
        context = {**self.admin_site.each_context(request), "title": "Inspect exact scoped job status",
                   "scope_form": JobScopeForm(), "investigation": None, "usage": None, "ai_usage": None, "error": "",
                   "can_job": _allowed(request, require_job_staff), "can_usage": _allowed(request, require_usage_staff),
                   "can_ai_usage": _allowed(request, require_ai_usage_staff)}
        status = 200
        try:
            _require_inspector(request)
            if request.GET or request.method not in {"GET", "POST"}: raise ValidationError("Exact method required.")
            if request.method == "POST":
                if request.content_type != "application/x-www-form-urlencoded" or len(request.body) > 4096:
                    raise ValidationError("Bounded form required.")
                form = JobScopeForm(request.POST)
                action = request.POST.get("action")
                if (set(request.POST) != set(form.fields) | {"action", "csrfmiddlewaretoken"}
                    or action not in {"inspect", "inspect_usage", "inspect_ai_usage"} or any(len(request.POST.getlist(key)) != 1 for key in request.POST)
                    or not form.is_valid()):
                    raise ValidationError("Exact scope form required.")
                if action == "inspect":
                    require, source, delivery, rate, slot = require_job_staff, inspect_staff_job, require_staff_job_delivery, "staff_job_access", "investigation"
                elif action == "inspect_usage":
                    require, source, delivery, rate, slot = require_usage_staff, inspect_staff_usage, require_staff_usage_delivery, "staff_usage_access", "usage"
                else:
                    require, source, delivery, rate, slot = require_ai_usage_staff, inspect_staff_ai_usage, require_staff_ai_usage_delivery, "staff_ai_usage_access", "ai_usage"
                require(request)  # Page discovery's alternative pair never authorizes this action.
                if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                    action=rate, user=request.user) is None:
                    context["error"] = "Too many job investigations."; status = 429
                else:
                    scope = form.cleaned_data
                    result = source(request=request, **scope)
                    context[slot] = result
                    context["scope_form"] = JobScopeForm(initial=scope)
                    response = TemplateResponse(request, "admin/jobs/job_investigation.html", context)
                    response.render()
                    delivery(request=request, organization_id=scope["organization_id"],
                        project_id=scope["project_id"], original=result)
                    response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
                    return response
        except PermissionDenied:
            context["investigation"] = context["usage"] = context["ai_usage"] = None
            context["error"] = "Current scoped job investigation is unavailable."; status = 403
        except (ValidationError, ValueError, UnicodeError):
            context["investigation"] = context["usage"] = context["ai_usage"] = None
            context["error"] = "Job status needs review. Inspect the exact current scope again."; status = 409
        response = TemplateResponse(request, "admin/jobs/job_investigation.html", context, status=status)
        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
        return response
