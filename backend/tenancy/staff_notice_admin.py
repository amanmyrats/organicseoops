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

from .models import OrganizationNotice
from .staff_notice_investigation import REASONS, inspect_staff_notice, require_notice_staff, require_staff_notice_delivery


class NoticeScopeForm(forms.Form):
    organization_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    notice_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    reason = forms.ChoiceField(choices=[(value, value.replace("_", " ")) for value in sorted(REASONS)])


@admin.register(OrganizationNotice)
class OrganizationNoticeAdmin(admin.ModelAdmin):
    def get_queryset(self, request): return super().get_queryset(request).none()
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

    def has_view_permission(self, request, obj=None):
        try: require_notice_staff(request)
        except PermissionDenied: return False
        return True

    def get_urls(self):
        return [path("scoped/", self.admin_site.admin_view(self.scoped_view), name="tenancy_organizationnotice_scoped")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        require_notice_staff(request)
        return HttpResponseRedirect(reverse("admin:tenancy_organizationnotice_scoped"))

    @sensitive_variables()
    @method_decorator(sensitive_post_parameters())
    def scoped_view(self, request):
        context = {**self.admin_site.each_context(request), "title": "Inspect an exact organization notice",
                   "scope_form": NoticeScopeForm(), "inspection": None, "error": ""}
        status = 200
        try:
            require_notice_staff(request)
            if request.GET or request.method not in {"GET", "POST"}: raise ValidationError("Exact method required.")
            if request.method == "POST":
                if request.content_type != "application/x-www-form-urlencoded" or len(request.body) > 4096:
                    raise ValidationError("Bounded form required.")
                form = NoticeScopeForm(request.POST)
                if (set(request.POST) != set(form.fields) | {"action", "csrfmiddlewaretoken"}
                    or request.POST.get("action") != "inspect" or any(len(request.POST.getlist(key)) != 1 for key in request.POST)
                    or not form.is_valid()):
                    raise ValidationError("Exact scope form required.")
                if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                    action="staff_notice_access", user=request.user) is None:
                    context["error"] = "Too many notice investigations."; status = 429
                else:
                    scope = form.cleaned_data
                    result = inspect_staff_notice(request=request, **scope)
                    context["inspection"] = result
                    context["scope_form"] = NoticeScopeForm(initial=scope)
                    response = TemplateResponse(request, "admin/tenancy/notice_investigation.html", context)
                    response.render()
                    require_staff_notice_delivery(request=request, organization_id=scope["organization_id"], original=result)
                    response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
                    return response
        except PermissionDenied:
            context["inspection"] = None; context["error"] = "Current scoped notice access is unavailable."; status = 403
        except (ValidationError, ValueError, UnicodeError):
            context["inspection"] = None; context["error"] = "Notice history needs review. Inspect the exact scope again."; status = 409
        response = TemplateResponse(request, "admin/tenancy/notice_investigation.html", context, status=status)
        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
        return response
