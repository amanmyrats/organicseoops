"""Yandex-specific consent and credentials; never exported as customer content."""
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from tenancy.models import normalize_origin


class YandexOAuthApplication(models.Model):
    key = models.CharField(max_length=8, unique=True, default="primary", editable=False)
    client_id = models.CharField(max_length=128)
    redirect_uri = models.URLField(max_length=512)
    encrypted_secret = models.TextField(max_length=8192, editable=False)
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(key="primary", encrypted_secret__startswith="v1:"),
            name="integrations_yandex_app_valid")]

    def clean(self):
        from .yandex_oauth import callback_uri, credential
        credential(self.client_id, limit=128)
        callback_uri(self.redirect_uri)
        if self.key != "primary" or not self.encrypted_secret.startswith("v1:"):
            raise ValidationError("Yandex application credentials must be encrypted.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class YandexOAuthIntent(models.Model):
    organization = models.ForeignKey("tenancy.Organization", on_delete=models.PROTECT)
    project = models.ForeignKey("tenancy.Project", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    application = models.ForeignKey(YandexOAuthApplication, on_delete=models.PROTECT)
    app_revision = models.PositiveIntegerField()
    origin = models.URLField(max_length=512)
    state_digest = models.CharField(max_length=64, unique=True, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    session_digest = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    encrypted_verifier = models.TextField(max_length=8192, blank=True)
    device_id = models.UUIDField(default=uuid4, editable=False)
    status = models.CharField(max_length=12, default="pending", choices=[("pending", "Pending"), ("consumed", "Consumed"), ("denied", "Denied")])
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    user_reported_revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(status="pending", used_at__isnull=True, encrypted_verifier__startswith="v1:")
            | Q(status__in=["consumed", "denied"], used_at__isnull=False, encrypted_verifier=""),
            name="integrations_yandex_intent_valid")]

    def clean(self):
        if self.project_id and self.organization_id != self.project.organization_id:
            raise ValidationError("Yandex consent must stay within one organization and project.")
        if normalize_origin(self.origin) != self.origin or not timezone.is_aware(self.expires_at):
            raise ValidationError("Yandex consent requires an exact origin and aware expiry.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.get(pk=self.pk)
            if (previous.status != "pending" or self.status not in {"consumed", "denied"}
                or any(getattr(previous, field) != getattr(self, field) for field in (
                    "organization_id", "project_id", "actor_id", "application_id", "app_revision", "origin",
                    "state_digest", "session_digest", "device_id", "expires_at", "created_at"))):
                raise ValidationError("Consent identity and terminal outcome cannot change.")
        self.full_clean()
        return super().save(*args, **kwargs)


class YandexOAuthGrant(models.Model):
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        RECONNECT_REQUIRED = "reconnect_required", "Reconnect required"
        REVOCATION_PENDING = "revocation_pending", "Revocation pending"
        REVOKED = "revoked", "Revoked"

    organization = models.ForeignKey("tenancy.Organization", on_delete=models.PROTECT)
    project = models.ForeignKey("tenancy.Project", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    intent = models.OneToOneField(YandexOAuthIntent, on_delete=models.PROTECT)
    application = models.ForeignKey(YandexOAuthApplication, on_delete=models.PROTECT)
    connection = models.ForeignKey("integrations.IntegrationConnection", on_delete=models.PROTECT, null=True, blank=True)
    origin = models.URLField(max_length=512)
    user_id = models.CharField(max_length=20, blank=True)
    host_id = models.CharField(max_length=512, blank=True)
    encrypted_tokens = models.TextField(max_length=16384, blank=True)
    expires_at = models.DateTimeField()
    refresh_started_at = models.DateTimeField(null=True, blank=True)
    scope = models.CharField(max_length=128, default="webmaster:hostinfo")
    state = models.CharField(max_length=24, choices=State.choices, default=State.REVOCATION_PENDING)
    revision = models.PositiveIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(state__in=["active", "reconnect_required", "revocation_pending"],
                revoked_at__isnull=True, encrypted_tokens__startswith="v1:")
            | Q(state="revoked", revoked_at__isnull=False, encrypted_tokens="", user_id="", host_id=""),
            name="integrations_yandex_grant_valid")]

    def clean(self):
        if self.connection_id and (self.connection.project_id != self.project_id
            or self.connection.provider != "yandex_webmaster" or self.connection.external_property_id != self.origin):
            raise ValidationError("Yandex connection must match its exact project origin.")
        if self.organization_id != self.project.organization_id or (self.intent_id and any((
            self.intent.organization_id != self.organization_id, self.intent.project_id != self.project_id,
            self.intent.actor_id != self.actor_id, self.intent.application_id != self.application_id, self.intent.origin != self.origin))):
            raise ValidationError("Yandex grant identity must match its consumed consent.")
        if self.intent_id and self.intent.status != "consumed":
            raise ValidationError("Yandex grant requires consumed consent.")
        if self.scope != "webmaster:hostinfo" or normalize_origin(self.origin) != self.origin or not timezone.is_aware(self.expires_at):
            raise ValidationError("Yandex grants require exact-origin read-only scope and aware expiry.")
        if self.state == self.State.ACTIVE and (not self.user_id.isdecimal() or not self.host_id):
            raise ValidationError("Active Yandex grants require a verified exact host.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.get(pk=self.pk)
            if (previous.state == self.State.REVOKED or self.revision != previous.revision + 1
                or any(getattr(previous, field) != getattr(self, field) for field in (
                    "organization_id", "project_id", "actor_id", "intent_id", "application_id", "origin", "scope", "created_at"))):
                raise ValidationError("Yandex grant identity and revision cannot change.")
        self.full_clean()
        return super().save(*args, **kwargs)
