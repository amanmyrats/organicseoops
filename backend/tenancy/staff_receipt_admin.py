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

from .models import PaddleWebhookReceipt
from .staff_receipt_investigation import REASONS, inspect_staff_receipt, require_receipt_staff, require_staff_receipt_delivery
from accounts.staff_access import require_staff_permissions
from .paddle_jobs import dispatch_paddle_receipt
from .paddle_webhooks import RETRY_FIELDS, RETRY_RESET, _require_receipt_retry_delivery, requeue_paddle_receipt


def require_receipt_change_staff(request):
    return require_staff_permissions(request, permissions=("tenancy.change_paddlewebhookreceipt",))


class ReceiptScopeForm(forms.Form):
    receipt_id = forms.IntegerField(min_value=1, max_value=2**53 - 1)
    reason = forms.ChoiceField(choices=[(value, value.replace("_", " ")) for value in sorted(REASONS)])


class ReceiptRetryForm(forms.Form):
    receipt_id = forms.IntegerField(min_value=1, max_value=2**53 - 1, label="Local signed receipt ID")
    reason = forms.CharField(min_length=1, max_length=250, widget=forms.Textarea(attrs={"rows": 3}))
    confirm_action = forms.BooleanField(label="I reviewed this exact receipt and confirm current-provider reconciliation, without replaying payment")


@admin.register(PaddleWebhookReceipt)
class PaddleWebhookReceiptAdmin(admin.ModelAdmin):
    def get_queryset(self, request): return super().get_queryset(request).none()
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

    def has_view_permission(self, request, obj=None):
        if obj is not None: return False
        for require in (require_receipt_staff, require_receipt_change_staff):
            try: require(request)
            except PermissionDenied: continue
            return True  # Independent command/inspection navigation only, never generic discovery.
        return False

    def has_module_permission(self, request): return self.has_view_permission(request)

    def get_urls(self):
        return [path("scoped/", self.admin_site.admin_view(self.scoped_view), name="tenancy_paddlewebhookreceipt_scoped"),
                path("retry/", self.admin_site.admin_view(self.retry_view), name="tenancy_paddlewebhookreceipt_retry")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        try: require_receipt_staff(request)
        except PermissionDenied:
            require_receipt_change_staff(request)
            return HttpResponseRedirect(reverse("admin:tenancy_paddlewebhookreceipt_retry"))
        return HttpResponseRedirect(reverse("admin:tenancy_paddlewebhookreceipt_scoped"))

    @sensitive_variables()
    @method_decorator(sensitive_post_parameters())
    def scoped_view(self, request):
        context = {**self.admin_site.each_context(request), "title": "Inspect exact retained billing receipt",
                   "scope_form": ReceiptScopeForm(), "inspection": None, "error": ""}
        status = 200
        try:
            require_receipt_staff(request)
            if request.GET or request.method not in {"GET", "POST"}: raise ValidationError("Exact method required.")
            if request.method == "POST":
                if request.content_type != "application/x-www-form-urlencoded" or len(request.body) > 4096:
                    raise ValidationError("Bounded form required.")
                form = ReceiptScopeForm(request.POST)
                if (set(request.POST) != set(form.fields) | {"action", "csrfmiddlewaretoken"}
                    or request.POST.get("action") != "inspect" or any(len(request.POST.getlist(key)) != 1 for key in request.POST)
                    or not form.is_valid()):
                    raise ValidationError("Exact receipt form required.")
                if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                    action="staff_billing_receipt_access", user=request.user) is None:
                    context["error"] = "Too many billing investigations."; status = 429
                else:
                    with transaction.atomic():
                        scope = form.cleaned_data
                        result = inspect_staff_receipt(request=request, **scope)
                        context["inspection"] = result
                        context["scope_form"] = ReceiptScopeForm(initial=scope)
                        response = TemplateResponse(request, "admin/tenancy/receipt_investigation.html", context)
                        response.render()
                        require_staff_receipt_delivery(request=request, original=result)
                        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
                        return response
        except PermissionDenied:
            context["inspection"] = None; context["error"] = "Current exact receipt access is unavailable."; status = 403
        except (ValidationError, ValueError, UnicodeError):
            context["inspection"] = None; context["error"] = "Retained billing receipt needs review. Inspect the exact record again."; status = 409
        response = TemplateResponse(request, "admin/tenancy/receipt_investigation.html", context, status=status)
        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @sensitive_variables()
    @method_decorator(sensitive_post_parameters())
    def retry_view(self, request):
        context = {**self.admin_site.each_context(request), "title": "Retry one exact signed billing receipt",
                   "retry_form": ReceiptRetryForm(), "queued_receipt_id": None, "error": ""}
        status = 200
        try:
            actor = require_receipt_change_staff(request)
            if request.GET or request.method not in {"GET", "POST"}: raise ValidationError("Exact method required.")
            if request.method == "POST":
                if request.content_type != "application/x-www-form-urlencoded" or len(request.body) > 4096:
                    raise ValidationError("Bounded form required.")
                form = ReceiptRetryForm(request.POST)
                if (set(request.POST) != set(form.fields) | {"csrfmiddlewaretoken"}
                    or request.POST.get("confirm_action") != "on"
                    or any(len(request.POST.getlist(key)) != 1 for key in request.POST) or not form.is_valid()):
                    raise ValidationError("Exact confirmed receipt command required.")
                if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
                    action="platform_provider_secret", user=actor) is None:
                    context["error"] = "Too many billing changes."; status = 429
                else:
                    command = form.cleaned_data
                    with transaction.atomic():
                        receipt = PaddleWebhookReceipt.objects.select_for_update().filter(pk=command["receipt_id"]).first()
                        if receipt is None: raise PermissionDenied
                        expected = {field: getattr(receipt, field) for field in RETRY_FIELDS}
                        requeue_paddle_receipt(receipt=receipt, actor=actor, reason=command["reason"], request=request)
                        expected.update(RETRY_RESET)
                        receipt_id = receipt.pk
                        transaction.on_commit(lambda: dispatch_paddle_receipt(receipt_id))
                        context["queued_receipt_id"] = receipt_id
                        response = TemplateResponse(request, "admin/tenancy/receipt_retry.html", context)
                        response.render()
                        _require_receipt_retry_delivery(request=request, actor=actor, expected=expected)
                        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
                        return response
        except PermissionDenied:
            context["queued_receipt_id"] = None; context["error"] = "Current exact receipt retry access is unavailable."; status = 403
        except (ValidationError, ValueError, UnicodeError):
            context["queued_receipt_id"] = None; context["error"] = "Receipt retry was not confirmed. Review current MFA, receipt state, environment and age."; status = 409
        response = TemplateResponse(request, "admin/tenancy/receipt_retry.html", context, status=status)
        response["Cache-Control"] = "private, no-store"; response["X-Robots-Tag"] = "noindex, nofollow"
        return response
