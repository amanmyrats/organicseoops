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

from .models import EmailFeedbackReceipt, EmailSuppression
from .staff_feedback_investigation import REASONS, inspect_staff_email_feedback, require_email_feedback_staff, require_staff_email_feedback_delivery


class FeedbackScopeForm(forms.Form):
    user_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    email_address_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    suppression_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    reason = forms.ChoiceField(choices=[(value, value.replace("_", " ")) for value in sorted(REASONS)])


@admin.register(EmailSuppression)
class EmailSuppressionAdmin(admin.ModelAdmin):
    def get_queryset(self, request): return super().get_queryset(request).none()
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

    def has_view_permission(self, request, obj=None):
        try: require_email_feedback_staff(request)
        except PermissionDenied: return False
        return True

    def get_urls(self):
        return [path("scoped/", self.admin_site.admin_view(self.scoped_view), name="tenancy_emailsuppression_scoped")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        require_email_feedback_staff(request)
        return HttpResponseRedirect(reverse("admin:tenancy_emailsuppression_scoped"))

    @sensitive_variables()
    @method_decorator(sensitive_post_parameters())
    def scoped_view(self, request):
        context = {**self.admin_site.each_context(request), "title": "Inspect exact retained suppression and first feedback",
                   "scope_form": FeedbackScopeForm(), "inspection": None, "error": ""}
        status = 200
        try:
            require_email_feedback_staff(request)
            if request.GET or request.method not in {"GET", "POST"}: raise ValidationError("Exact method required.")
            if request.method == "POST":
                if request.content_type != "application/x-www-form-urlencoded" or len(request.body) > 4096:
                    raise ValidationError("Bounded form required.")
                form = FeedbackScopeForm(request.POST)
                if (set(request.POST) != set(form.fields) | {"action", "csrfmiddlewaretoken"}
                    or request.POST.get("action") != "inspect" or any(len(request.POST.getlist(key)) != 1 for key in request.POST)
                    or not form.is_valid()):
                    raise ValidationError("Exact scope form required.")
                if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                    action="staff_email_feedback_access", user=request.user) is None:
                    context["error"] = "Too many feedback investigations."; status = 429
                else:
                    scope = form.cleaned_data
                    result = inspect_staff_email_feedback(request=request, **scope)
                    context["inspection"] = result
                    context["scope_form"] = FeedbackScopeForm(initial=scope)
                    response = TemplateResponse(request, "admin/tenancy/feedback_investigation.html", context)
                    response.render()
                    require_staff_email_feedback_delivery(request=request, original=result)
                    response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
                    return response
        except PermissionDenied:
            context["inspection"] = None; context["error"] = "Current scoped feedback access is unavailable."; status = 403
        except (ValidationError, ValueError, UnicodeError):
            context["inspection"] = None; context["error"] = "Retained feedback history needs review. Inspect the exact scope again."; status = 409
        response = TemplateResponse(request, "admin/tenancy/feedback_investigation.html", context, status=status)
        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
        return response


@admin.register(EmailFeedbackReceipt)
class EmailFeedbackReceiptAdmin(admin.ModelAdmin):
    def get_queryset(self, request): return super().get_queryset(request).none()
    def has_module_permission(self, request): return False
    def has_view_permission(self, request, obj=None): return False
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
