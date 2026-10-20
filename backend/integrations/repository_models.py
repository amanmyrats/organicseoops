"""Explicit repository source authorization, never execution permission."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class RepositoryApplication(models.Model):
    key = models.CharField(max_length=8, default="primary", unique=True, editable=False)
    app_id = models.PositiveBigIntegerField()
    client_id = models.CharField(max_length=128)
    redirect_uri = models.URLField(max_length=512)
    encrypted_secrets = models.TextField(editable=False)
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        from .repository_oauth import callback_uri, credential
        credential(self.client_id, limit=128)
        import re
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", self.client_id):
            raise ValidationError("Use the GitHub App's exact client identifier.")
        callback_uri(self.redirect_uri)
        if (self.key != "primary" or type(self.app_id) is not int or not 0 < self.app_id < 2**53
            or not self.encrypted_secrets.startswith("v1:")):
            raise ValidationError("Configure an exact GitHub App and encrypted operator secrets.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class RepositoryConsent(models.Model):
    organization = models.ForeignKey("tenancy.Organization", on_delete=models.PROTECT)
    project = models.ForeignKey("tenancy.Project", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    application = models.ForeignKey(RepositoryApplication, on_delete=models.PROTECT)
    app_revision = models.PositiveIntegerField()
    repository = models.CharField(max_length=140)
    repository_id = models.PositiveBigIntegerField()
    commit_sha = models.CharField(max_length=40)
    state_digest = models.CharField(max_length=64, unique=True)
    session_digest = models.CharField(max_length=64)
    encrypted_verifier = models.TextField(blank=True)
    status = models.CharField(max_length=12, default="pending")
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    user_reported_revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(status="pending", used_at__isnull=True, encrypted_verifier__startswith="v1:")
            | Q(status__in=["consumed", "denied"], used_at__isnull=False, encrypted_verifier=""), name="integrations_repository_consent_state")]

    def clean(self):
        from .repository_oauth import source_selection
        source_selection(self.repository, self.repository_id, self.commit_sha)
        if self.project.organization_id != self.organization_id or not timezone.is_aware(self.expires_at):
            raise ValidationError("Repository consent must stay in its project with an aware expiry.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.get(pk=self.pk)
            if (previous.status != "pending" or self.status not in {"consumed", "denied"}
                or any(getattr(self, field) != getattr(previous, field) for field in (
                    "organization_id", "project_id", "actor_id", "application_id", "app_revision", "repository", "repository_id",
                    "commit_sha", "state_digest", "session_digest", "expires_at", "created_at"))):
                raise ValidationError("Consent identity is immutable and single-use.")
        self.full_clean()
        return super().save(*args, **kwargs)


class RepositoryGrant(models.Model):
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOCATION_PENDING = "revocation_pending", "Revocation pending"
        REVOKED = "revoked", "Revoked"

    organization = models.ForeignKey("tenancy.Organization", on_delete=models.PROTECT)
    project = models.ForeignKey("tenancy.Project", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    application = models.ForeignKey(RepositoryApplication, on_delete=models.PROTECT)
    consent = models.OneToOneField(RepositoryConsent, on_delete=models.PROTECT)
    repository = models.CharField(max_length=140)
    repository_id = models.PositiveBigIntegerField()
    commit_sha = models.CharField(max_length=40)
    github_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    installation_id = models.PositiveBigIntegerField(null=True, blank=True)
    encrypted_tokens = models.TextField(blank=True)
    expires_at = models.DateTimeField()
    state = models.CharField(max_length=24, choices=State.choices, default=State.REVOCATION_PENDING)
    revision = models.PositiveIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_evidence = models.CharField(max_length=48, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(state__in=["active", "revocation_pending"],
            encrypted_tokens__startswith="v1:", revoked_at__isnull=True)
            | Q(state="revoked", encrypted_tokens="", revoked_at__isnull=False), name="integrations_repository_grant_state")]

    def clean(self):
        from .repository_oauth import source_selection
        source_selection(self.repository, self.repository_id, self.commit_sha)
        consent = self.consent
        if (self.project.organization_id != self.organization_id or consent.status != "consumed"
            or any(getattr(self, field) != getattr(consent, field) for field in (
                "organization_id", "project_id", "actor_id", "application_id", "repository", "repository_id", "commit_sha"))
            or not timezone.is_aware(self.expires_at)):
            raise ValidationError("Repository grant must match its exact consumed source selection.")
        if self.state == "active" and (not self.github_user_id or not self.installation_id or not self.revision):
            raise ValidationError("Active read-only grants need verified provider identity and installation.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.get(pk=self.pk)
            if (previous.state == "revoked" or self.revision != previous.revision + 1
                or any(getattr(self, field) != getattr(previous, field) for field in (
                    "organization_id", "project_id", "actor_id", "application_id", "consent_id", "repository", "repository_id", "commit_sha", "created_at"))):
                raise ValidationError("Repository grant identity is immutable; use a fresh consent for another revision.")
        self.full_clean()
        return super().save(*args, **kwargs)
