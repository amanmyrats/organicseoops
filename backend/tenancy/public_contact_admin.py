"""Explicit MFA-audited discovery/inspection of retained anonymous enquiries."""
import math

from allauth.account import app_settings
from allauth.core.internal import ratelimit
from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from accounts.staff_access import require_staff_permissions
from .models import AuditEvent, AuditEventType, PublicContactRequest
from .public_contact import CATEGORIES
from .support_staff import REASONS


def require_contact_staff(request):
    return require_staff_permissions(request, permissions=("tenancy.view_publiccontactrequest",))


class ContactScopeForm(forms.Form):
    action = forms.ChoiceField(choices=[("list", "List newest retained identifiers"), ("inspect", "Inspect one exact request")])
    request_id = forms.IntegerField(label="Exact request ID / list before ID (optional for first page)", required=False, min_value=1, max_value=2**53 - 1)
    reason = forms.ChoiceField(choices=[(value, value.replace("_", " ")) for value in sorted(REASONS)])


def _identifiers(before_id=None):
    now = timezone.now()
    queryset = PublicContactRequest.objects.filter(expires_at__gt=now, created_at__lte=now)
    if before_id is not None: queryset = queryset.filter(pk__lt=before_id)
    rows = list(queryset.order_by("-pk").values("id", "category", "language", "created_at", "expires_at")[:21])
    if any(row["category"] not in CATEGORIES or row["language"] not in {"en", "tr"}
           or not row["created_at"] < row["expires_at"] for row in rows):
        raise ValidationError("Contact identifiers need review.")
    return {"rows": rows[:20], "has_more": len(rows) > 20, "next_before_id": rows[19]["id"] if len(rows) > 20 else None}


def _content(identity, *, locked=False):
    queryset = PublicContactRequest.objects
    if locked: queryset = queryset.select_for_update()
    row = queryset.filter(pk=identity, expires_at__gt=timezone.now()).first()
    if row is None: raise PermissionDenied
    row.clean()
    return {key: getattr(row, key) for key in ("id", "category", "language", "reply_email", "question", "created_at", "expires_at")}


@admin.register(PublicContactRequest)
class PublicContactRequestAdmin(admin.ModelAdmin):
    def get_queryset(self, request): return super().get_queryset(request).none()
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

    def has_view_permission(self, request, obj=None):
        try: require_contact_staff(request)
        except PermissionDenied: return False
        return True

    def get_urls(self):
        return [path("scoped/", self.admin_site.admin_view(self.scoped_view),
                     name="tenancy_publiccontactrequest_scoped")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        require_contact_staff(request)
        return HttpResponseRedirect(reverse("admin:tenancy_publiccontactrequest_scoped"))

    @sensitive_variables()
    @method_decorator(sensitive_post_parameters())
    def scoped_view(self, request):
        context = {**self.admin_site.each_context(request), "title": "Inspect retained anonymous contact",
                   "scope_form": ContactScopeForm(), "identifiers": None, "contact": None, "error": ""}
        status = 200
        try:
            actor = require_contact_staff(request)
            if request.GET or request.method not in {"GET", "POST"}: raise ValidationError("Exact method required.")
            if request.method == "POST":
                if request.content_type != "application/x-www-form-urlencoded" or len(request.body) > 4096:
                    raise ValidationError("Bounded form required.")
                form = ContactScopeForm(request.POST)
                if (set(request.POST) != set(form.fields) | {"csrfmiddlewaretoken"}
                    or any(len(request.POST.getlist(key)) != 1 for key in request.POST) or not form.is_valid()):
                    raise ValidationError("Exact scope required.")
                data = form.cleaned_data
                if data["action"] == "inspect" and data["request_id"] is None:
                    raise ValidationError("Exact contact ID required only for inspection.")
                try:
                    rates = ratelimit.parse_rates(app_settings.RATE_LIMITS.get("public_contact_staff"))
                    if (not rates or not any(rate.per == "ip" for rate in rates)
                        or any(rate.per not in {"user", "ip"} or rate.amount <= 0
                               or not math.isfinite(rate.duration) or rate.duration <= 0 for rate in rates)):
                        raise ValueError
                    usage = ratelimit.consume(request, config=app_settings.RATE_LIMITS, limit_get=True,
                        action="public_contact_staff", user=actor)
                except Exception:
                    context["error"] = "Contact access budget unavailable."; status = 503
                else:
                    if usage is None:
                        context["error"] = "Too many contact inspections."; status = 429
                    else:
                        with transaction.atomic():
                            if data["action"] == "inspect": context["contact"] = _content(data["request_id"], locked=True)
                            else: context["identifiers"] = _identifiers(data["request_id"])
                            require_contact_staff(request)
                            AuditEvent.objects.create(actor=actor, event_type=AuditEventType.SUPPORT_REQUEST_ACCESSED,
                                details={"scope": "public_contact", "action": data["action"], "reason": data["reason"],
                                         **({"request_id": data["request_id"]} if data["action"] == "inspect"
                                            else {"count": len(context["identifiers"]["rows"]), "before_id": data["request_id"]})})
                        result = TemplateResponse(request, "admin/tenancy/public_contact.html", context)
                        result.render()
                        require_contact_staff(request)
                        current = _content(data["request_id"]) if data["action"] == "inspect" else _identifiers(data["request_id"])
                        if current != (context["contact"] if data["action"] == "inspect" else context["identifiers"]):
                            raise ValidationError("Contact changed before delivery.")
                        require_contact_staff(request)
                        result["Cache-Control"] = "private, no-store"; result["X-Robots-Tag"] = "noindex, nofollow"
                        return result
        except PermissionDenied:
            context["contact"] = context["identifiers"] = None
            context["error"] = "Current contact access unavailable."; status = 403
        except (ValidationError, ValueError, UnicodeError):
            context["contact"] = context["identifiers"] = None
            context["error"] = "Contact inspection needs review."; status = 409
        result = TemplateResponse(request, "admin/tenancy/public_contact.html", context, status=status)
        result["Cache-Control"] = "private, no-store"; result["X-Robots-Tag"] = "noindex, nofollow"
        return result
