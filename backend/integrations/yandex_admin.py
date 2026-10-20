from datetime import timedelta

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters

from providers.services import _require_permission
from tenancy.admin import InspectOnlyAdmin
from tenancy.models import AuditEvent, AuditEventType
from .yandex_models import YandexOAuthApplication, YandexOAuthGrant, YandexOAuthIntent
from .yandex_oauth import callback_uri, credential, lock_application, seal


def _require_idle_application():
    now = timezone.now()
    if (YandexOAuthGrant.objects.exclude(state="revoked").exists()
        or YandexOAuthIntent.objects.filter(Q(status="pending", expires_at__gt=now)
            | Q(status="consumed", used_at__gt=now - timedelta(minutes=10))
            | Q(status="consumed", yandexoauthgrant__isnull=True, user_reported_revoked_at__isnull=True)).exists()):
        raise ValidationError("Disconnect grants and resolve pending or unknown consent before rotating the application.")


class YandexApplicationForm(forms.ModelForm):
    client_secret = forms.CharField(required=False, max_length=512, strip=False,
        widget=forms.PasswordInput(render_value=False), help_text="Write only. Leave blank to preserve the current secret.")

    class Meta:
        model = YandexOAuthApplication
        fields = ("client_id", "redirect_uri", "client_secret")

    def clean(self):
        data = super().clean()
        _require_idle_application()
        if data.get("client_id"):
            credential(data["client_id"], limit=128)
        if data.get("redirect_uri"):
            callback_uri(data["redirect_uri"])
        secret = data.get("client_secret")
        if secret:
            from .yandex_transport import YandexError
            try:
                self.instance.encrypted_secret = seal("application", credential(secret, limit=512))
            except YandexError:
                raise ValidationError("Configure the private Yandex encryption key before entering the client secret.") from None
        elif not self.instance.pk:
            raise ValidationError("Enter a Yandex client secret; configure the private encryption key first.")
        return data


@admin.register(YandexOAuthApplication)
class YandexApplicationAdmin(admin.ModelAdmin):
    form = YandexApplicationForm
    fields = ("client_id", "redirect_uri", "client_secret", "revision", "updated_at")
    readonly_fields = ("revision", "updated_at")
    list_display = ("key", "revision", "updated_at")

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not YandexOAuthApplication.objects.exists()

    @method_decorator(sensitive_post_parameters("client_secret"))
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            lock_application()
            _require_permission(request.user, "integrations.change_yandexoauthapplication" if change else "integrations.add_yandexoauthapplication")
            current = YandexOAuthApplication.objects.select_for_update().filter(key="primary").first()
            _require_idle_application()
            if (change and (current is None or current.pk != obj.pk or current.revision != obj.revision)
                or not change and current is not None):
                raise ValidationError("Application changed; reload before saving.")
            obj.revision = current.revision + 1 if current else 1
            obj.save()
            AuditEvent.objects.create(actor=request.user, event_type=AuditEventType.PLATFORM_CREDENTIAL_UPDATED,
                details={"kind": "yandex_oauth_application", "revision": obj.revision})


@admin.register(YandexOAuthIntent)
class YandexIntentAdmin(InspectOnlyAdmin):
    fields = ("organization", "project", "actor", "origin", "status", "expires_at", "used_at", "user_reported_revoked_at", "created_at")
    list_display = ("id", "organization_id", "project_id", "status", "created_at")


@admin.register(YandexOAuthGrant)
class YandexGrantAdmin(InspectOnlyAdmin):
    fields = ("organization", "project", "actor", "origin", "scope", "state", "revision", "expires_at", "revoked_at")
    list_display = ("id", "organization_id", "project_id", "state", "revision")
