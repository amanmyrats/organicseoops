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
from .repository_models import RepositoryApplication, RepositoryConsent, RepositoryGrant
from .repository_oauth import credential, lock_application, seal


def require_idle_application():
    if (RepositoryGrant.objects.exclude(state="revoked").exists()
        or RepositoryConsent.objects.filter(Q(status="pending", expires_at__gt=timezone.now())
            | Q(status="consumed", used_at__gt=timezone.now() - timedelta(minutes=10))
            | Q(status="consumed", repositorygrant__isnull=True, user_reported_revoked_at__isnull=True)).exists()):
        raise ValidationError("Disconnect repository grants and resolve pending/unknown consent before changing the GitHub application.")


class RepositoryApplicationForm(forms.ModelForm):
    client_secret = forms.CharField(required=False, max_length=512, strip=False, widget=forms.PasswordInput(render_value=False))
    webhook_secret = forms.CharField(required=False, min_length=32, max_length=512, strip=False, widget=forms.PasswordInput(render_value=False),
        help_text="Both fields are write-only. Leave both blank to preserve them. GitHub App must grant only Contents:read and Metadata:read.")

    class Meta:
        model = RepositoryApplication
        fields = ("app_id", "client_id", "redirect_uri", "client_secret", "webhook_secret")

    def clean(self):
        data = super().clean()
        require_idle_application()
        secret, webhook = data.get("client_secret"), data.get("webhook_secret")
        if secret or webhook:
            if not secret or not webhook:
                raise ValidationError("Enter both operator secrets together.")
            self.instance.encrypted_secrets = seal("application", {"client_secret": credential(secret, limit=512),
                "webhook_secret": credential(webhook, limit=512)})
        elif not self.instance.pk:
            raise ValidationError("Configure private PROVIDER_ENCRYPTION_KEYS, then enter both GitHub App secrets.")
        return data


@admin.register(RepositoryApplication)
class RepositoryApplicationAdmin(admin.ModelAdmin):
    form = RepositoryApplicationForm
    readonly_fields = ("revision", "updated_at")
    fields = ("app_id", "client_id", "redirect_uri", "client_secret", "webhook_secret", "revision", "updated_at")
    list_display = ("key", "app_id", "revision", "updated_at")

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not RepositoryApplication.objects.exists()

    @method_decorator(sensitive_post_parameters("client_secret", "webhook_secret"))
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            lock_application()
            _require_permission(request.user, "integrations.change_repositoryapplication" if change else "integrations.add_repositoryapplication")
            current = RepositoryApplication.objects.select_for_update().filter(key="primary").first()
            require_idle_application()
            if (change and (current is None or current.pk != obj.pk or current.revision != obj.revision)
                or not change and current is not None):
                raise ValidationError("Application changed; reload before saving.")
            obj.revision = current.revision + 1 if current else 1
            obj.save()
            AuditEvent.objects.create(actor=request.user, event_type=AuditEventType.PLATFORM_CREDENTIAL_UPDATED,
                details={"kind": "repository_github_application", "revision": obj.revision})


@admin.register(RepositoryConsent)
class RepositoryConsentAdmin(InspectOnlyAdmin):
    fields = ("organization", "project", "actor", "repository", "repository_id", "commit_sha", "status", "expires_at", "used_at", "user_reported_revoked_at")


@admin.register(RepositoryGrant)
class RepositoryGrantAdmin(InspectOnlyAdmin):
    fields = ("organization", "project", "actor", "repository", "repository_id", "commit_sha", "state", "revision", "expires_at", "revoked_at")
