import json

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters

from providers.services import _provider_cipher, _require_permission
from tenancy.models import AuditEvent, AuditEventType
from .serp_models import SerpConfiguration


class SerpConfigurationForm(forms.ModelForm):
    api_login = forms.CharField(required=False, max_length=256, widget=forms.PasswordInput(render_value=False))
    api_password = forms.CharField(required=False, max_length=512, strip=False, widget=forms.PasswordInput(render_value=False),
        help_text="Both credential fields are write only. Leave both blank to preserve them.")

    class Meta:
        model = SerpConfiguration
        fields = ("api_login", "api_password", "enabled", "locations", "languages", "estimated_task_cost_usd",
            "monthly_exposure_usd", "reviewed_until")

    def clean(self):
        data = super().clean()
        login, password = data.get("api_login"), data.get("api_password")
        if login or password:
            if (not login or not password or ":" in login
                or any(ord(c) < 33 or ord(c) > 126 for c in login + password)):
                raise ValidationError("Enter both API login and password using printable credential characters.")
            self.instance.encrypted_credentials = "v1:" + _provider_cipher().encrypt(
                json.dumps([login, password], separators=(",", ":")).encode()).decode()
        elif not self.instance.pk:
            raise ValidationError("Configure private PROVIDER_ENCRYPTION_KEYS, then enter both API credentials.")
        return data


@admin.register(SerpConfiguration)
class SerpConfigurationAdmin(admin.ModelAdmin):
    form = SerpConfigurationForm
    readonly_fields = ("revision", "updated_at", "budget_month", "reserved_exposure_usd")
    list_display = ("key", "enabled", "revision", "reviewed_until")

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not SerpConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @method_decorator(sensitive_post_parameters("api_login", "api_password"))
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        from django.db import connection
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [1740174332])
            _require_permission(request.user, "integrations.change_serpconfiguration" if change else "integrations.add_serpconfiguration")
            current = SerpConfiguration.objects.select_for_update().filter(key="primary").first()
            if (change and (current is None or current.pk != obj.pk or current.revision != obj.revision)
                or not change and current is not None):
                raise ValidationError("Configuration changed; reload before saving.")
            obj.revision = current.revision + 1 if current else 1
            if current:
                obj.budget_month, obj.reserved_exposure_usd = current.budget_month, current.reserved_exposure_usd
            obj.save()
            AuditEvent.objects.create(actor=request.user, event_type=AuditEventType.PLATFORM_CREDENTIAL_UPDATED,
                details={"kind": "dataforseo_serp", "revision": obj.revision})
