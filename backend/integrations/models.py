import hashlib
import json
import re
from datetime import datetime
from uuid import uuid4
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from tenancy.artifacts import project_artifact_scope
from tenancy.models import Project, ProjectOriginVerification, normalize_origin


class IntegrationCapability(models.TextChoices):
    CSV_IMPORT = "csv_import", "CSV import"
    API_SYNC = "api_sync", "API synchronization"
    QUERY_METRICS = "query_metrics", "Query metrics"
    PAGE_METRICS = "page_metrics", "Page metrics"
    INDEXING_STATUS = "indexing_status", "Indexing status"
    SITEMAPS = "sitemaps", "Sitemaps"
    LANDING_METRICS = "landing_metrics", "Landing metrics"


class SourceDimension(models.TextChoices):
    DATE = "date", "Date"
    QUERY = "query", "Query"
    PAGE = "page", "Page"
    COUNTRY = "country", "Country"
    DEVICE = "device", "Device"
    SEARCH_TYPE = "search_type", "Search type"
    SEARCH_APPEARANCE = "search_appearance", "Search appearance"
    HOSTNAME = "hostname", "Hostname"
    LANDING_PAGE = "landing_page", "Landing page"


PROVIDER_CONTRACTS = {
    "yandex_webmaster": {
        "capabilities": frozenset({"api_sync"}),
        "dimensions": frozenset({"date"}),
    },
    "google_search_console": {
        "capabilities": frozenset({"csv_import", "api_sync", "query_metrics", "page_metrics", "indexing_status", "sitemaps"}),
        "dimensions": frozenset({"date", "query", "page", "country", "device", "search_type", "search_appearance"}),
    },
    "google_analytics_4": {
        "capabilities": frozenset({"api_sync", "landing_metrics"}),
        "dimensions": frozenset({"hostname", "landing_page"}),
    },
}


def _choice_list(value, choices, label):
    if (
        type(value) is not list
        or len(value) > len(choices)
        or any(not isinstance(item, str) or item not in choices for item in value)
        or len(value) != len(set(value))
    ):
        raise ValidationError({label: f"Choose unique supported {label.replace('_', ' ')}."})
    return sorted(value)


def _bounded_json_object(value, field):
    if type(value) is not dict:
        raise ValidationError({field: "Enter a JSON object."})
    try:
        encoded = json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        raise ValidationError({field: "Enter valid JSON values."}) from None
    if len(encoded.encode()) > 4096:
        raise ValidationError({field: "Keep this value within 4 KiB."})
    return json.loads(encoded)


_DOMAIN_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def _domain_site(value):
    if not isinstance(value, str) or not value.startswith("sc-domain:"):
        raise ValidationError("Search Console domain property identity is unavailable.")
    name = value.removeprefix("sc-domain:")
    labels = name.split(".")
    if (not 3 <= len(name) <= 253 or len(labels) < 2
        or name != name.lower() or any(not _DOMAIN_LABEL.fullmatch(label) for label in labels)):
        raise ValidationError("Search Console domain property identity is unavailable.")
    return name


def verified_domain_origins(project, site_url, *, verified_origins=None):
    domain = _domain_site(site_url)
    configured = {project.canonical_origin, *project.domain_aliases.values_list("origin", flat=True)}
    if verified_origins is None:
        verified_origins = ProjectOriginVerification.objects.filter(
            project=project, organization_id=project.organization_id, origin__in=configured,
            state=ProjectOriginVerification.State.VERIFIED, verified_at__isnull=False, revoked_at__isnull=True,
        ).values_list("origin", flat=True)
    return sorted(origin for origin in verified_origins if origin in configured and (
        (host := urlsplit(origin).hostname) == domain or host.endswith("." + domain)
    ))


def _normalize_google_search_console_property(value):
    if not isinstance(value, str):
        raise ValidationError("Enter a Search Console property.")
    value = value.strip()
    if value.startswith("sc-domain:"):
        return "sc-domain:" + _domain_site(value)
    try:
        return normalize_origin(value)
    except ValidationError:
        raise ValidationError("Enter an origin-level Search Console URL-prefix property.") from None


def normalize_external_property(provider, value):
    if provider == "yandex_webmaster":
        return normalize_origin(value)
    if provider == "google_search_console":
        return _normalize_google_search_console_property(value)
    if provider == "google_analytics_4":
        if type(value) is not str or not re.fullmatch(r"[1-9][0-9]{0,19}", value):
            raise ValidationError("Enter one numeric GA4 property ID.")
        return value
    raise ValidationError({"provider": "This integration provider is not supported."})


def property_matches_project(connection):
    if not connection.project_id:
        return False
    origins = {
        connection.project.canonical_origin,
        *connection.project.domain_aliases.values_list("origin", flat=True),
    }
    if connection.provider == "google_search_console" and connection.external_property_id.startswith("sc-domain:"):
        return bool(connection.credential_reference and verified_domain_origins(connection.project,
                                                                                 connection.external_property_id))
    if connection.provider == "google_analytics_4":
        return bool(connection.credential_reference and GA4OAuthGrant.objects.filter(
            project=connection.project, organization_id=connection.project.organization_id,
            credential_reference=connection.credential_reference, property_id=connection.external_property_id,
            state=GA4OAuthGrant.State.ACTIVE).filter(selected_origins__contained_by=list(origins)).exclude(
                selected_origins=[]).exists())
    return connection.external_property_id in origins


class IntegrationConnection(models.Model):
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        DISCONNECTED = "disconnected", "Disconnected"
        UNAVAILABLE = "unavailable", "Unavailable"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="integration_connections")
    provider = models.CharField(
        max_length=32,
        validators=[RegexValidator(r"^[a-z][a-z0-9_]{1,31}$", "Enter a valid provider key.")],
    )
    external_property_id = models.CharField(max_length=512)
    credential_reference = models.UUIDField(null=True, blank=True, editable=False)
    capabilities = models.JSONField(default=list)
    available_dimensions = models.JSONField(default=list)
    source_semantics = models.CharField(max_length=80)
    source_semantics_version = models.CharField(max_length=40)
    timezone = models.CharField(max_length=64, default="UTC")
    currency = models.CharField(
        max_length=3,
        blank=True,
        validators=[RegexValidator(r"^[A-Z]{3}$", "Use a three-letter uppercase currency code.")],
    )
    backfill_limit_days = models.PositiveSmallIntegerField(default=90)
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "provider", "external_property_id"],
                name="integrations_unique_project_provider_property",
            ),
            models.CheckConstraint(
                condition=Q(backfill_limit_days__gte=1, backfill_limit_days__lte=3660),
                name="integrations_connection_backfill_limit_valid",
            ),
            models.CheckConstraint(
                condition=Q(state__in=["active", "disconnected", "unavailable"]),
                name="integrations_connection_state_valid",
            ),
        ]
        ordering = ["project_id", "provider", "external_property_id", "id"]

    def clean_fields(self, exclude=None):
        if isinstance(self.provider, str):
            self.provider = self.provider.strip().lower()
        if isinstance(self.source_semantics, str):
            self.source_semantics = self.source_semantics.strip()
        if isinstance(self.source_semantics_version, str):
            self.source_semantics_version = self.source_semantics_version.strip()
        if isinstance(self.timezone, str):
            self.timezone = self.timezone.strip()
        if isinstance(self.currency, str):
            self.currency = self.currency.strip().upper()
        self.external_property_id = normalize_external_property(self.provider, self.external_property_id)
        super().clean_fields(exclude=exclude)

    def clean(self):
        contract = PROVIDER_CONTRACTS.get(self.provider)
        if contract is None:
            raise ValidationError({"provider": "This integration provider is not supported."})
        self.capabilities = _choice_list(self.capabilities, contract["capabilities"], "capabilities")
        self.available_dimensions = _choice_list(
            self.available_dimensions,
            contract["dimensions"],
            "available_dimensions",
        )
        if not self.capabilities:
            raise ValidationError({"capabilities": "Declare at least one supported capability."})
        if not self.source_semantics or not self.source_semantics_version:
            raise ValidationError("Source semantics and their version are required.")
        if self.provider == "yandex_webmaster":
            if (self.timezone != "source_timestamp_offset" or self.source_semantics != "yandex_site_history"
                or self.source_semantics_version != "yandex-site-history-v1" or self.capabilities != ["api_sync"]
                or self.available_dimensions != ["date"] or self.state == self.State.ACTIVE and not self.credential_reference):
                raise ValidationError("Yandex site history preserves provider timestamp offsets and aggregate-date scope.")
        else:
            try:
                ZoneInfo(self.timezone)
            except (ValueError, ZoneInfoNotFoundError):
                raise ValidationError({"timezone": "Enter a valid IANA timezone."}) from None
        if not 1 <= self.backfill_limit_days <= 3660:
            raise ValidationError({"backfill_limit_days": "Backfill limits must be between 1 and 3660 days."})
        if self.project_id and not property_matches_project(self):
            raise ValidationError({"external_property_id": "Property must match the project's exact origin scope."})
        if self.external_property_id.startswith("sc-domain:") and (
            set(self.capabilities) not in (
                {IntegrationCapability.API_SYNC, IntegrationCapability.PAGE_METRICS},
                {IntegrationCapability.API_SYNC, IntegrationCapability.PAGE_METRICS,
                 IntegrationCapability.INDEXING_STATUS, IntegrationCapability.SITEMAPS},
            )
            or self.available_dimensions != [SourceDimension.PAGE]
            or self.source_semantics != "search_console_domain_pages"
        ):
            raise ValidationError("Domain properties support only scoped page observations.")
        if self.provider == "google_analytics_4" and (
            set(self.capabilities) != {IntegrationCapability.API_SYNC, IntegrationCapability.LANDING_METRICS}
            or self.available_dimensions != [SourceDimension.HOSTNAME, SourceDimension.LANDING_PAGE]
            or self.source_semantics != "ga4_landing_pages" or self.source_semantics_version != "ga4-data-v1"
            or not self.credential_reference or not self.currency
        ):
            raise ValidationError("GA4 sources require a scoped Analytics grant and landing-page definitions.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = IntegrationConnection.objects.get(pk=self.pk)
            immutable = (
                "project_id", "provider", "external_property_id", "source_semantics", "source_semantics_version",
                "timezone", "currency",
            )
            if any(getattr(self, field) != getattr(previous, field) for field in immutable):
                raise ValidationError("Connection identity and source semantics are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class GoogleOAuthIntent(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONSUMED = "consumed", "Consumed"
        DENIED = "denied", "Denied"

    organization = models.ForeignKey("tenancy.Organization", on_delete=models.PROTECT, related_name="google_oauth_intents")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="google_oauth_intents")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="google_oauth_intents")
    state_digest = models.CharField(max_length=64, unique=True, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    session_digest = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    redirect_uri = models.URLField(max_length=512)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(status="pending", used_at__isnull=True)
                | Q(status__in=["consumed", "denied"], used_at__isnull=False),
                name="integrations_google_oauth_intent_status_valid",
            ),
        ]

    def clean(self):
        if self.project_id and self.organization_id and self.project.organization_id != self.organization_id:
            raise ValidationError("OAuth intent must stay within its project organization.")
        if self.expires_at and not timezone.is_aware(self.expires_at):
            raise ValidationError("OAuth intent expiry must be timezone-aware.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = GoogleOAuthIntent.objects.get(pk=self.pk)
            if any(getattr(self, field) != getattr(previous, field) for field in (
                "organization_id", "project_id", "actor_id", "state_digest", "session_digest", "redirect_uri",
                "expires_at", "created_at",
            )) or previous.status != self.Status.PENDING or self.status not in {self.Status.CONSUMED, self.Status.DENIED}:
                raise ValidationError("OAuth intent identity and final outcome cannot change.")
        self.full_clean()
        return super().save(*args, **kwargs)


class GoogleOAuthGrant(models.Model):
    class State(models.TextChoices):
        PENDING_SELECTION = "pending_selection", "Pending property selection"
        ACTIVE = "active", "Active"
        RECONNECT_REQUIRED = "reconnect_required", "Reconnect required"
        REVOCATION_PENDING = "revocation_pending", "Revocation pending"
        REVOKED = "revoked", "Revoked"

    organization = models.ForeignKey("tenancy.Organization", on_delete=models.PROTECT, related_name="google_oauth_grants")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="google_oauth_grants")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="google_oauth_grants")
    credential_reference = models.UUIDField(default=uuid4, unique=True, editable=False)
    encrypted_refresh_token = models.TextField(max_length=8192, blank=True)
    scope = models.CharField(max_length=128)
    selectable_sites = models.JSONField(default=list, blank=True)
    selected_property_id = models.CharField(max_length=512, blank=True)
    selected_site_url = models.CharField(max_length=512, blank=True)
    selected_origins = models.JSONField(default=list, blank=True)
    state = models.CharField(max_length=24, choices=State.choices, default=State.PENDING_SELECTION)
    revision = models.PositiveIntegerField(default=0)
    verified_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(state__in=["pending_selection", "active", "reconnect_required", "revocation_pending"], revoked_at__isnull=True)
                | Q(state="revoked", revoked_at__isnull=False, encrypted_refresh_token=""),
                name="integrations_google_oauth_grant_state_valid",
            ),
        ]

    def clean(self):
        if self.project_id and self.organization_id and self.project.organization_id != self.organization_id:
            raise ValidationError("OAuth grant must stay within one project organization.")
        if self.state in {self.State.PENDING_SELECTION, self.State.ACTIVE, self.State.REVOCATION_PENDING} and not self.encrypted_refresh_token:
            raise ValidationError("An enabled OAuth grant requires an encrypted refresh credential.")
        if self.encrypted_refresh_token and not self.encrypted_refresh_token.startswith("v1:"):
            raise ValidationError("OAuth credentials must use versioned encryption.")
        if self.state == self.State.ACTIVE and (not self.selected_property_id or not self.selected_site_url):
            raise ValidationError("Active OAuth grants require a selected exact-scope property.")
        if self.state == self.State.REVOKED and (self.selected_property_id or self.selected_site_url
                                                 or self.selectable_sites or self.selected_origins):
            raise ValidationError("Revoked OAuth grants cannot retain property access evidence.")
        if (type(self.selected_origins) is not list or len(self.selected_origins) > 20
            or any(type(origin) is not str or len(origin) > 512 for origin in self.selected_origins)
            or len(self.selected_origins) != len(set(self.selected_origins))):
            raise ValidationError("Selected origins must be a bounded unique list.")
        if self.state == self.State.ACTIVE:
            if self.selected_property_id.startswith("sc-domain:"):
                if (not self.selected_origins or self.selected_site_url != self.selected_property_id
                    or any(normalize_origin(origin) != origin for origin in self.selected_origins)):
                    raise ValidationError("Domain grants require exact approved origins.")
                domain = _domain_site(self.selected_property_id)
                if any((host := urlsplit(origin).hostname) != domain and not host.endswith("." + domain)
                       for origin in self.selected_origins):
                    raise ValidationError("Domain grant origins must match the selected property.")
            elif self.selected_origins:
                raise ValidationError("URL-prefix grants cannot carry domain-wide origins.")
        if type(self.selectable_sites) is not list or len(self.selectable_sites) > 50:
            raise ValidationError("OAuth property selection must be bounded.")
        try:
            encoded = json.dumps(self.selectable_sites, allow_nan=False, separators=(",", ":")).encode()
        except (TypeError, ValueError):
            raise ValidationError("OAuth property selection must be valid JSON.") from None
        if len(encoded) > 65536:
            raise ValidationError("OAuth property selection exceeds 64 KiB.")
        if self.scope != "https://www.googleapis.com/auth/webmasters.readonly":
            raise ValidationError("OAuth grants require Search Console read-only scope.")
        if self.verified_at and not timezone.is_aware(self.verified_at):
            raise ValidationError("OAuth property verification time must be timezone-aware.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = GoogleOAuthGrant.objects.get(pk=self.pk)
            if any(getattr(self, field) != getattr(previous, field) for field in (
                "organization_id", "project_id", "actor_id", "credential_reference", "scope", "created_at",
            )) or previous.state == self.State.REVOKED or self.revision != previous.revision + 1:
                raise ValidationError("OAuth grant identity or revision cannot change.")
        self.full_clean()
        return super().save(*args, **kwargs)


class GA4OAuthIntent(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONSUMED = "consumed", "Consumed"
        DENIED = "denied", "Denied"

    organization = models.ForeignKey("tenancy.Organization", on_delete=models.PROTECT)
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    state_digest = models.CharField(max_length=64, unique=True, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    session_digest = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    redirect_uri = models.URLField(max_length=512)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=Q(status="pending", used_at__isnull=True)
            | Q(status__in=["consumed", "denied"], used_at__isnull=False),
            name="integrations_ga4_oauth_intent_status_valid",
        )]

    def clean(self):
        if self.project_id and self.organization_id and self.project.organization_id != self.organization_id:
            raise ValidationError("GA4 OAuth intent must stay within its project organization.")
        if self.expires_at and not timezone.is_aware(self.expires_at):
            raise ValidationError("GA4 OAuth expiry must be timezone-aware.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = GA4OAuthIntent.objects.get(pk=self.pk)
            if (any(getattr(self, field) != getattr(previous, field) for field in (
                "organization_id", "project_id", "actor_id", "state_digest", "session_digest",
                "redirect_uri", "expires_at", "created_at"))
                or previous.status != self.Status.PENDING
                or self.status not in {self.Status.CONSUMED, self.Status.DENIED}):
                raise ValidationError("GA4 OAuth intent identity and final state cannot change.")
        self.full_clean()
        return super().save(*args, **kwargs)


class GA4OAuthGrant(models.Model):
    class State(models.TextChoices):
        PENDING_SELECTION = "pending_selection", "Pending selection"
        ACTIVE = "active", "Active"
        RECONNECT_REQUIRED = "reconnect_required", "Reconnect required"
        REVOCATION_PENDING = "revocation_pending", "Revocation pending"
        REVOKED = "revoked", "Revoked"

    organization = models.ForeignKey("tenancy.Organization", on_delete=models.PROTECT)
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    credential_reference = models.UUIDField(default=uuid4, unique=True, editable=False)
    encrypted_refresh_token = models.TextField(max_length=8192, blank=True)
    scope = models.CharField(max_length=128)
    property_id = models.CharField(max_length=20, blank=True)
    selected_origins = models.JSONField(default=list, blank=True)
    state = models.CharField(max_length=24, choices=State.choices, default=State.PENDING_SELECTION)
    revision = models.PositiveIntegerField(default=0)
    verified_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=Q(state__in=["pending_selection", "active", "reconnect_required", "revocation_pending"],
                        revoked_at__isnull=True)
            | Q(state="revoked", revoked_at__isnull=False, encrypted_refresh_token=""),
            name="integrations_ga4_oauth_grant_state_valid",
        )]

    def clean(self):
        if self.project_id and self.organization_id and self.project.organization_id != self.organization_id:
            raise ValidationError("GA4 grant must stay within one project organization.")
        if self.verified_at and not timezone.is_aware(self.verified_at):
            raise ValidationError("GA4 property selection timestamp must be timezone-aware.")
        if self.scope != "https://www.googleapis.com/auth/analytics.readonly":
            raise ValidationError("GA4 grants require Analytics read-only scope.")
        if self.state != self.State.REVOKED and not self.encrypted_refresh_token.startswith("v1:"):
            raise ValidationError("GA4 grants require a separately encrypted refresh credential.")
        if (type(self.selected_origins) is not list or len(self.selected_origins) > 20
            or any(type(origin) is not str or len(origin) > 512 for origin in self.selected_origins)
            or len(self.selected_origins) != len(set(self.selected_origins))):
            raise ValidationError("GA4 grant origins must be a bounded unique list.")
        if self.state == self.State.ACTIVE:
            if (not re.fullmatch(r"[1-9][0-9]{0,19}", self.property_id) or not self.selected_origins
                or any(type(origin) is not str or normalize_origin(origin) != origin
                       or urlsplit(origin).scheme != "https" for origin in self.selected_origins)):
                raise ValidationError("Active GA4 grants require one scoped property and HTTPS origins.")
        if self.state == self.State.REVOKED and (self.encrypted_refresh_token or self.property_id or self.selected_origins):
            raise ValidationError("Revoked GA4 grants must scrub credentials and property scope.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = GA4OAuthGrant.objects.get(pk=self.pk)
            if (any(getattr(self, field) != getattr(previous, field) for field in (
                "organization_id", "project_id", "actor_id", "credential_reference", "scope", "created_at"))
                or previous.state == self.State.REVOKED or self.revision != previous.revision + 1):
                raise ValidationError("GA4 grant identity and revision cannot change.")
        self.full_clean()
        return super().save(*args, **kwargs)


class BusinessProfileOAuthIntent(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONSUMED = "consumed", "Consumed"
        DENIED = "denied", "Denied"

    organization = models.ForeignKey("tenancy.Organization", on_delete=models.PROTECT)
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    state_digest = models.CharField(max_length=64, unique=True, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    session_digest = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    app_revision = models.DateTimeField()
    redirect_uri = models.URLField(max_length=512)
    selection = models.JSONField()
    authority = models.JSONField()
    policy_version = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=Q(status="pending", used_at__isnull=True)
            | Q(status__in=["consumed", "denied"], used_at__isnull=False),
            name="integrations_gbp_intent_state_valid")]

    def clean(self):
        from .business_profile import POLICY_VERSION, validate_business_selection
        from .business_profile_tokens import configured_business_redirect_uri
        validate_business_selection(self.selection)
        configured_business_redirect_uri(self.redirect_uri)
        if self.project.organization_id != self.organization_id or self.policy_version != POLICY_VERSION:
            raise ValidationError("Business consent must retain its exact project and policy.")
        if (type(self.authority) is not dict or set(self.authority) != {"assessment_id", "assessment_revision",
            "configuration_revision", "verification_id", "verified_at"}
            or any(type(self.authority[key]) is not int or self.authority[key] < 0 for key in (
                "assessment_id", "assessment_revision", "configuration_revision", "verification_id"))
            or self.authority["assessment_id"] != self.selection["assessment_id"]
            or self.authority["configuration_revision"] != self.selection["configuration_revision"]):
            raise ValidationError("Business consent accepts only declared authority metadata.")
        try:
            if type(self.authority["verified_at"]) is not str or timezone.is_naive(datetime.fromisoformat(self.authority["verified_at"])):
                raise ValueError
        except (ValueError, TypeError):
            raise ValidationError("Business authority requires an aware verification time.") from None
        if any(value is None or timezone.is_naive(value) for value in (self.expires_at, self.app_revision)):
            raise ValidationError("Business consent times must be timezone-aware.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.get(pk=self.pk)
            immutable = [field.attname for field in self._meta.concrete_fields
                         if field.name not in {"status", "used_at"}]
            if (any(getattr(self, field) != getattr(previous, field) for field in immutable)
                or previous.status != self.Status.PENDING or self.status not in {self.Status.CONSUMED, self.Status.DENIED}):
                raise ValidationError("Business consent identity and terminal state are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class BusinessProfileOAuthGrant(models.Model):
    class State(models.TextChoices):
        PENDING_SELECTION = "pending_selection", "Disabled until provider validation"
        ACTIVE = "active", "Active"
        REVOCATION_PENDING = "revocation_pending", "Revocation pending"
        REVOKED = "revoked", "Revoked"

    organization = models.ForeignKey("tenancy.Organization", on_delete=models.PROTECT)
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    intent = models.OneToOneField(BusinessProfileOAuthIntent, on_delete=models.PROTECT)
    encrypted_refresh_token = models.TextField(max_length=8192, blank=True, editable=False)
    encrypted_extra_token = models.TextField(max_length=8192, blank=True, editable=False)
    scope = models.CharField(max_length=128)
    state = models.CharField(max_length=24, choices=State.choices, default=State.PENDING_SELECTION)
    revision = models.PositiveIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=Q(state__in=["pending_selection", "active", "revocation_pending"],
                        revoked_at__isnull=True, encrypted_refresh_token__startswith="v1:")
            | Q(state="revoked", revoked_at__isnull=False, encrypted_refresh_token=""),
            name="integrations_gbp_grant_state_valid"), models.CheckConstraint(
            condition=Q(encrypted_extra_token="") | Q(state="revocation_pending", encrypted_extra_token__startswith="v1:"),
            name="integrations_gbp_extra_token_disabled")]

    def clean(self):
        from .business_profile import SCOPE
        if (self.scope != SCOPE or self.project.organization_id != self.organization_id
            or self.intent.status != BusinessProfileOAuthIntent.Status.CONSUMED
            or any(getattr(self, field) != getattr(self.intent, field) for field in (
                "organization_id", "project_id", "actor_id"))):
            raise ValidationError("Business grant requires its own consumed project consent and scope.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = type(self).objects.get(pk=self.pk)
            if (any(getattr(self, field) != getattr(previous, field) for field in (
                "organization_id", "project_id", "actor_id", "intent_id", "scope", "created_at"))
                or previous.state == self.State.REVOKED or self.revision != previous.revision + 1
                or previous.state == self.State.REVOCATION_PENDING and self.state not in {self.State.REVOCATION_PENDING, self.State.REVOKED}):
                raise ValidationError("Business grant identity, revocation and revision are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class ImportRun(models.Model):
    class SourceFormat(models.TextChoices):
        SEARCH_CONSOLE_CSV = "search_console_csv", "Search Console CSV"

    class Status(models.TextChoices):
        SUCCEEDED = "succeeded", "Succeeded"
        PARTIALLY_SUCCEEDED = "partially_succeeded", "Partially succeeded"
        FAILED = "failed", "Failed"
        UNAVAILABLE = "unavailable", "Unavailable"

    class CoverageState(models.TextChoices):
        COMPLETE = "complete", "Complete"
        PARTIAL = "partial", "Partial"
        UNAVAILABLE = "unavailable", "Unavailable"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="import_runs")
    connection = models.ForeignKey(IntegrationConnection, on_delete=models.PROTECT, related_name="import_runs")
    job = models.OneToOneField("jobs.JobRun", on_delete=models.PROTECT, related_name="import_run")
    source_artifact = models.ForeignKey("jobs.Artifact", on_delete=models.PROTECT, related_name="import_runs")
    source_format = models.CharField(max_length=32, choices=SourceFormat.choices)
    source_checksum = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    provider = models.CharField(max_length=32)
    external_property_id = models.CharField(max_length=512)
    source_semantics = models.CharField(max_length=80)
    source_semantics_version = models.CharField(max_length=40)
    date_start = models.DateField()
    date_end = models.DateField()
    observation_dimensions = models.JSONField(default=list, blank=True)
    source_timezone = models.CharField(max_length=64)
    source_currency = models.CharField(max_length=3, blank=True)
    coverage_state = models.CharField(max_length=16, choices=CoverageState.choices)
    coverage = models.JSONField(default=dict)
    fresh_through = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices)
    rows_seen = models.PositiveIntegerField(default=0)
    rows_imported = models.PositiveIntegerField(default=0)
    row_errors = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "source_format", "source_checksum"],
                name="integrations_unique_connection_import_source",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["succeeded", "partially_succeeded", "failed", "unavailable"]),
                name="integrations_import_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(coverage_state__in=["complete", "partial", "unavailable"]),
                name="integrations_import_coverage_valid",
            ),
            models.CheckConstraint(
                condition=Q(rows_imported__lte=models.F("rows_seen") - models.F("row_errors")),
                name="integrations_import_row_counts_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="succeeded", coverage_state="complete", row_errors=0, rows_imported=models.F("rows_seen"))
                    | Q(status="partially_succeeded", coverage_state="partial", rows_imported__gt=0)
                    | Q(status="failed", coverage_state__in=["partial", "unavailable"], rows_imported=0, fresh_through__isnull=True)
                    | Q(
                        status="unavailable", coverage_state="unavailable", rows_seen=0, rows_imported=0,
                        row_errors=0, fresh_through__isnull=True,
                    )
                ),
                name="integrations_import_outcome_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    Q(fresh_through__isnull=True)
                    | Q(fresh_through__gte=models.F("date_start"), fresh_through__lte=models.F("date_end"))
                ),
                name="integrations_import_freshness_valid",
            ),
        ]
        ordering = ["-created_at", "-id"]

    def clean(self):
        if self.connection_id and self.project_id and self.connection.project_id != self.project_id:
            raise ValidationError("Import connection must stay within its project.")
        if self.connection_id and any((
            self.provider != self.connection.provider,
            self.external_property_id != self.connection.external_property_id,
            self.source_semantics != self.connection.source_semantics,
            self.source_semantics_version != self.connection.source_semantics_version,
        )):
            raise ValidationError("Import source identity must match its connection snapshot.")
        if self.job_id and self.project_id and self.job.project_id != self.project_id:
            raise ValidationError("Import job must stay within its project.")
        if self.job_id and self.job.handler != "import_search_console_csv":
            raise ValidationError("Import provenance requires a Search Console import job.")
        expected_job_status = {
            self.Status.SUCCEEDED: "succeeded",
            self.Status.PARTIALLY_SUCCEEDED: "partially_succeeded",
            self.Status.FAILED: "failed",
            self.Status.UNAVAILABLE: "failed",
        }.get(self.status)
        if self.job_id and self.job.status != expected_job_status:
            raise ValidationError("Import provenance status must match its completed job.")
        if self.source_artifact_id and self.job_id and (
            self.source_artifact.project_id != self.project_id or self.source_artifact.job_id != self.job_id
        ):
            raise ValidationError("Import source artifact must belong to the same project and job.")
        if self.connection_id and IntegrationCapability.CSV_IMPORT not in self.connection.capabilities:
            raise ValidationError("This connection does not support CSV imports.")
        if self.connection_id:
            self.observation_dimensions = _choice_list(
                self.observation_dimensions,
                set(self.connection.available_dimensions),
                "observation_dimensions",
            )
            if self.status in {self.Status.SUCCEEDED, self.Status.PARTIALLY_SUCCEEDED} and not self.observation_dimensions:
                raise ValidationError({"observation_dimensions": "Successful imports require a complete observation grain."})
            if (
                SourceDimension.QUERY in self.observation_dimensions
                and IntegrationCapability.QUERY_METRICS not in self.connection.capabilities
            ):
                raise ValidationError("Query-grained imports require query metric capability.")
            if (
                SourceDimension.PAGE in self.observation_dimensions
                and IntegrationCapability.PAGE_METRICS not in self.connection.capabilities
            ):
                raise ValidationError("Page-grained imports require page metric capability.")
            if not {
                IntegrationCapability.QUERY_METRICS,
                IntegrationCapability.PAGE_METRICS,
            } & set(self.connection.capabilities):
                raise ValidationError("Search metric imports require query or page metric capability.")
        if self.date_start and self.date_end:
            days = (self.date_end - self.date_start).days + 1
            if days < 1 or (self.connection_id and days > self.connection.backfill_limit_days):
                raise ValidationError("Import date range exceeds this connection's bounded window.")
        try:
            source_zone = ZoneInfo(self.source_timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValidationError({"source_timezone": "Enter a valid source timezone."}) from None
        if self.date_end and self.date_end > timezone.now().astimezone(source_zone).date():
            raise ValidationError("Import observations cannot be dated in the future.")
        if isinstance(self.source_currency, str):
            self.source_currency = self.source_currency.strip().upper()
        if self.source_currency and (
            len(self.source_currency) != 3 or not self.source_currency.isascii() or not self.source_currency.isupper()
        ):
            raise ValidationError({"source_currency": "Use a three-letter uppercase currency code."})
        self.coverage = _bounded_json_object(self.coverage, "coverage")
        if not 0 <= self.rows_imported <= self.rows_seen or not 0 <= self.row_errors <= self.rows_seen - self.rows_imported:
            raise ValidationError("Import row counts are inconsistent.")
        expected_coverage = {
            self.Status.SUCCEEDED: self.CoverageState.COMPLETE,
            self.Status.PARTIALLY_SUCCEEDED: self.CoverageState.PARTIAL,
            self.Status.UNAVAILABLE: self.CoverageState.UNAVAILABLE,
        }.get(self.status)
        if expected_coverage and self.coverage_state != expected_coverage:
            raise ValidationError("Import status and coverage state are inconsistent.")
        if self.status == self.Status.SUCCEEDED and (self.row_errors or self.rows_imported != self.rows_seen):
            raise ValidationError("Successful imports must account for every row without errors.")
        if self.status == self.Status.PARTIALLY_SUCCEEDED and self.rows_imported == 0:
            raise ValidationError("Partial imports must preserve at least one imported row.")
        if self.status == self.Status.FAILED and (
            self.coverage_state == self.CoverageState.COMPLETE or self.rows_imported or self.fresh_through
        ):
            raise ValidationError("Failed imports cannot claim complete, imported, or fresh data.")
        if self.status == self.Status.UNAVAILABLE and any((
            self.coverage_state != self.CoverageState.UNAVAILABLE,
            self.rows_seen,
            self.rows_imported,
            self.row_errors,
            self.fresh_through,
        )):
            raise ValidationError("Unavailable imports cannot claim observed data.")
        if self.fresh_through and not self.date_start <= self.fresh_through <= self.date_end:
            raise ValidationError("Import freshness must stay within the observed date range.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Import provenance is immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class ImportRowError(models.Model):
    import_run = models.ForeignKey(ImportRun, on_delete=models.PROTECT, related_name="errors")
    source_row = models.PositiveIntegerField()
    category = models.CharField(
        max_length=64,
        validators=[RegexValidator(r"^[a-z][a-z0-9_]{1,63}$", "Enter a valid error category.")],
    )
    field = models.CharField(
        max_length=32,
        blank=True,
        validators=[RegexValidator(r"^[a-z][a-z0-9_]{1,31}$", "Enter a valid field name.")],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["import_run", "source_row"],
                name="integrations_unique_import_row_error",
            ),
            models.CheckConstraint(
                condition=Q(source_row__gte=1),
                name="integrations_import_row_error_source_valid",
            ),
        ]
        ordering = ["source_row", "id"]

    def clean(self):
        if self.import_run_id and not 1 <= self.source_row <= self.import_run.rows_seen:
            raise ValidationError("Import error row must be present in its source file.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Import row errors are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class PendingArtifactCleanup(models.Model):
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="pending_integration_artifact_cleanups")
    key = models.CharField(max_length=512, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def clean(self):
        if self.project_id and not self.key.startswith(project_artifact_scope(self.project) + "/"):
            raise ValidationError("Pending artifact cleanup must stay within its project namespace.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Pending artifact cleanup records are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class ImportExecutionState(models.Model):
    job = models.OneToOneField("jobs.JobRun", on_delete=models.PROTECT, related_name="search_console_import_state")
    storage_failures = models.PositiveSmallIntegerField(default=0)
    retry_after = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(storage_failures__lte=3),
                name="integrations_import_storage_failures_bounded",
            ),
        ]

    def clean(self):
        if self.job_id and self.job.handler != "import_search_console_csv":
            raise ValidationError("Import execution state requires a Search Console import job.")
        if not 0 <= self.storage_failures <= 3:
            raise ValidationError("Import storage failures exceed the retry limit.")
        if self.storage_failures in {0, 3} and self.retry_after is not None:
            raise ValidationError("Initial and exhausted import states cannot retain a retry time.")
        if (
            0 < self.storage_failures < 3
            and self.job_id
            and self.job.status == "queued"
            and self.retry_after is None
        ):
            raise ValidationError("Retryable import storage failures require a retry time.")
        if self.job_id and self.job.status != "queued" and self.retry_after is not None:
            raise ValidationError("Completed import execution states cannot retain a retry time.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SearchMetricObservation(models.Model):
    class TimeGranularity(models.TextChoices):
        DAY = "day", "Day"
        RANGE = "range", "Date range"

    class SearchType(models.TextChoices):
        WEB = "web", "Web"
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        NEWS = "news", "News"
        DISCOVER = "discover", "Discover"
        GOOGLE_NEWS = "google_news", "Google News"

    import_run = models.ForeignKey(ImportRun, on_delete=models.PROTECT, related_name="search_metrics")
    source_row = models.PositiveIntegerField()
    date_start = models.DateField()
    date_end = models.DateField()
    time_granularity = models.CharField(max_length=8, choices=TimeGranularity.choices)
    search_type = models.CharField(max_length=16, choices=SearchType.choices, default=SearchType.WEB)
    query = models.CharField(max_length=1000, blank=True)
    page = models.URLField(max_length=2048, blank=True)
    country = models.CharField(max_length=128, blank=True)
    device = models.CharField(max_length=32, blank=True)
    search_appearance = models.CharField(max_length=128, blank=True)
    clicks = models.PositiveBigIntegerField(null=True, blank=True)
    impressions = models.PositiveBigIntegerField(null=True, blank=True)
    ctr = models.DecimalField(max_digits=13, decimal_places=12, null=True, blank=True)
    position = models.DecimalField(max_digits=16, decimal_places=8, null=True, blank=True)
    unavailable_metrics = models.JSONField(default=list, blank=True)
    grain_hash = models.CharField(max_length=64, editable=False, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["grain_hash"],
                name="integrations_unique_search_metric_grain",
            ),
            models.UniqueConstraint(
                fields=["import_run", "source_row"],
                name="integrations_unique_search_metric_source_row",
            ),
            models.CheckConstraint(
                condition=Q(source_row__gte=1),
                name="integrations_search_metric_source_row_valid",
            ),
            models.CheckConstraint(
                condition=Q(search_type__in=["web", "image", "video", "news", "discover", "google_news"]),
                name="integrations_search_metric_type_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        time_granularity="day", date_start=models.F("date_end"), query="", page="", country="",
                        device="", search_appearance="",
                    )
                    | Q(
                        time_granularity="range", query__gt="", page="", country="", device="",
                        search_appearance="",
                    )
                    | Q(
                        time_granularity="range", query="", page__gt="", country="", device="",
                        search_appearance="",
                    )
                    | Q(
                        time_granularity="range", query="", page="", country__gt="", device="",
                        search_appearance="",
                    )
                    | Q(
                        time_granularity="range", query="", page="", country="", device__gt="",
                        search_appearance="",
                    )
                    | Q(
                        time_granularity="range", query="", page="", country="", device="",
                        search_appearance__gt="",
                    )
                ),
                name="integrations_search_metric_grain_valid",
            ),
            models.CheckConstraint(
                condition=Q(date_end__gte=models.F("date_start")),
                name="integrations_search_metric_dates_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(clicks__isnull=True)
                    | Q(impressions__isnull=True)
                    | Q(clicks__lte=models.F("impressions"))
                ),
                name="integrations_search_metric_clicks_valid",
            ),
            models.CheckConstraint(
                condition=Q(ctr__isnull=True) | Q(ctr__gte=0, ctr__lte=1),
                name="integrations_search_metric_ctr_valid",
            ),
            models.CheckConstraint(
                condition=Q(position__isnull=True) | Q(position__gte=0),
                name="integrations_search_metric_position_valid",
            ),
        ]
        ordering = ["date_start", "id"]

    @property
    def dimension(self):
        if self.time_granularity == self.TimeGranularity.DAY:
            return SourceDimension.DATE
        for field, dimension in (
            ("query", SourceDimension.QUERY),
            ("page", SourceDimension.PAGE),
            ("country", SourceDimension.COUNTRY),
            ("device", SourceDimension.DEVICE),
            ("search_appearance", SourceDimension.SEARCH_APPEARANCE),
        ):
            if getattr(self, field):
                return dimension
        return ""

    @staticmethod
    def hash_grain(connection_id, values):
        value = json.dumps(
            [
                connection_id,
                values["date_start"].isoformat() if values.get("date_start") else "",
                values["date_end"].isoformat() if values.get("date_end") else "",
                values.get("time_granularity", ""),
                values.get("search_type", ""),
                values.get("query", ""),
                values.get("page", ""),
                values.get("country", ""),
                values.get("device", ""),
                values.get("search_appearance", ""),
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(value.encode()).hexdigest()

    def calculate_grain_hash(self):
        return self.hash_grain(
            self.import_run.connection_id if self.import_run_id else None,
            {
                "date_start": self.date_start,
                "date_end": self.date_end,
                "time_granularity": self.time_granularity,
                "search_type": self.search_type,
                "query": self.query,
                "page": self.page,
                "country": self.country,
                "device": self.device,
                "search_appearance": self.search_appearance,
            },
        )

    def clean(self):
        if self.import_run_id and self.date_start and self.date_end and not (
            self.import_run.date_start <= self.date_start <= self.date_end <= self.import_run.date_end
        ):
            raise ValidationError("Search metric dates must stay within the import range.")
        dimensions = [self.query, self.page, self.country, self.device, self.search_appearance]
        if self.time_granularity == self.TimeGranularity.DAY:
            if self.date_start != self.date_end or any(dimensions):
                raise ValidationError("Daily observations require only the date dimension.")
        elif self.time_granularity == self.TimeGranularity.RANGE:
            if sum(bool(value) for value in dimensions) != 1:
                raise ValidationError("Aggregate observations require exactly one exported dimension.")
        if self.import_run_id and self.dimension not in self.import_run.observation_dimensions:
            raise ValidationError("Search metric dimension must match its import provenance.")
        if self.clicks is not None and self.impressions is not None and self.clicks > self.impressions:
            raise ValidationError("Clicks cannot exceed impressions.")
        if self.ctr is not None and not 0 <= self.ctr <= 1:
            raise ValidationError("CTR must be a ratio between zero and one.")
        if self.position is not None and self.position < 0:
            raise ValidationError("Position cannot be negative.")
        metric_names = {"clicks", "impressions", "ctr", "position"}
        if (
            type(self.unavailable_metrics) is not list
            or len(self.unavailable_metrics) != len(set(self.unavailable_metrics))
            or not set(self.unavailable_metrics) <= metric_names
        ):
            raise ValidationError({"unavailable_metrics": "Choose unique known metric names."})
        expected_hash = self.calculate_grain_hash()
        if self.grain_hash and self.grain_hash != expected_hash:
            raise ValidationError("Search metric grain hash does not match its dimensions.")
        self.grain_hash = expected_hash

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Search metric observations are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class SearchAnalyticsPageSnapshot(models.Model):
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="search_analytics_pages")
    connection = models.ForeignKey(IntegrationConnection, on_delete=models.PROTECT, related_name="search_analytics_pages")
    grant = models.ForeignKey(GoogleOAuthGrant, on_delete=models.PROTECT, related_name="search_analytics_pages")
    job = models.ForeignKey("jobs.JobRun", on_delete=models.PROTECT, related_name="search_analytics_pages")
    external_property_id = models.CharField(max_length=512)
    day = models.DateField()
    dimension = models.CharField(max_length=8, choices=[("date", "Date"), ("query", "Query"), ("page", "Page")])
    start_row = models.PositiveSmallIntegerField()
    result = models.JSONField()
    collected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "dimension", "start_row"], name="integrations_unique_api_page"),
            models.CheckConstraint(condition=Q(start_row__in=[0, 100]), name="integrations_api_page_offset_valid"),
            models.CheckConstraint(condition=Q(dimension__in=["date", "query", "page"]), name="integrations_api_page_dimension_valid"),
        ]

    def clean(self):
        if (self.connection_id and self.project_id and self.connection.project_id != self.project_id
            or self.grant_id and self.project_id and self.grant.project_id != self.project_id
            or self.job_id and self.project_id and self.job.project_id != self.project_id):
            raise ValidationError("Search Analytics evidence must stay in one project.")
        if self.job_id and self.job.handler != "sync_search_console":
            raise ValidationError("Search Analytics evidence requires an API sync job.")
        if self.connection_id and self.external_property_id != self.connection.external_property_id:
            raise ValidationError("Search Analytics evidence must retain its source property.")
        domain = self.external_property_id.startswith("sc-domain:")
        if domain and self.dimension != "page":
            raise ValidationError("Domain evidence is limited to scoped pages.")
        if type(self.result) is not dict or any(self.result.get(field) != value for field, value in (
            ("dimension", self.dimension), ("day", self.day.isoformat()), ("start_row", self.start_row),
            ("aggregation", "byPage" if self.dimension == "page" else "byProperty"),
            ("source_coverage", "top_rows_only_domain_page_filtered" if domain else "top_rows_only"),
        )):
            raise ValidationError("Search Analytics evidence must retain its report grain and coverage.")
        if domain and (type(self.result.get("approved_origins")) is not list
                       or not self.result["approved_origins"]
                       or any(type(origin) is not str for origin in self.result["approved_origins"])
                       or not set(self.result["approved_origins"]) <= set(self.grant.selected_origins)):
            raise ValidationError("Domain evidence must retain only the selected verified origin scope.")
        try:
            encoded = json.dumps(self.result, allow_nan=False, separators=(",", ":")).encode()
        except (ValueError, TypeError):
            raise ValidationError("Search Analytics evidence must be valid JSON.") from None
        if len(encoded) > 256 * 1024:
            raise ValidationError("Search Analytics evidence exceeds its page limit.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Search Analytics page evidence is immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class SearchAnalyticsQueryPageSnapshot(models.Model):
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="search_analytics_query_pages")
    connection = models.ForeignKey(IntegrationConnection, on_delete=models.PROTECT)
    grant = models.ForeignKey(GoogleOAuthGrant, on_delete=models.PROTECT)
    job = models.ForeignKey("jobs.JobRun", on_delete=models.PROTECT, related_name="search_analytics_query_pages")
    grant_revision = models.PositiveIntegerField()
    external_property_id = models.CharField(max_length=512)
    day = models.DateField()
    start_row = models.PositiveSmallIntegerField()
    result = models.JSONField()
    result_sha256 = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    collected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "start_row"], name="integrations_unique_query_page"),
            models.CheckConstraint(condition=Q(start_row__in=[0, 100]), name="integrations_query_page_offset"),
        ]
        ordering = ["job_id", "start_row", "id"]

    def clean(self):
        from .search_console_analytics import validate_query_page_snapshot
        validate_query_page_snapshot(self, current=self._state.adding)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Paired Search Analytics evidence is immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class GA4LandingPageSnapshot(models.Model):
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="ga4_landing_pages")
    connection = models.ForeignKey(IntegrationConnection, on_delete=models.PROTECT, related_name="ga4_landing_pages")
    grant = models.ForeignKey(GA4OAuthGrant, on_delete=models.PROTECT, related_name="ga4_landing_pages")
    job = models.ForeignKey("jobs.JobRun", on_delete=models.PROTECT, related_name="ga4_landing_pages")
    property_id = models.CharField(max_length=20)
    hostname = models.CharField(max_length=253)
    day = models.DateField()
    offset = models.PositiveSmallIntegerField()
    report_kind = models.CharField(max_length=16, choices=[("all_channels", "All channels"),
                                                         ("organic_search", "GA4 organic search sessions")],
                                   default="all_channels")
    result = models.JSONField()
    collected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "offset"], name="integrations_unique_ga4_job_page"),
            models.CheckConstraint(condition=Q(offset__in=[0, 100]), name="integrations_ga4_page_offset_valid"),
            models.CheckConstraint(condition=Q(report_kind__in=["all_channels", "organic_search"]),
                                   name="integrations_ga4_page_kind_valid"),
        ]

    def clean(self):
        if (self.connection_id and self.project_id and self.connection.project_id != self.project_id
            or self.grant_id and self.project_id and self.grant.project_id != self.project_id
            or self.job_id and self.project_id and self.job.project_id != self.project_id):
            raise ValidationError("GA4 evidence must stay within one project.")
        if self.job_id and (self.job.handler != "sync_ga4_landing"
                            or self.job.input_snapshot.get("report_kind") != self.report_kind):
            raise ValidationError("GA4 evidence requires its own scoped report job.")
        if self.connection_id and (self.connection.provider != "google_analytics_4"
                                   or self.property_id != self.connection.external_property_id):
            raise ValidationError("GA4 evidence must retain its exact source identity.")
        if (type(self.result) is not dict or self.result.get("property_id") != self.property_id
            or self.result.get("day") != self.day.isoformat() or self.result.get("offset") != self.offset
            or self.result.get("report_kind") != self.report_kind
            or self.result.get("timezone") != self.connection.timezone
            or self.result.get("currency") != self.connection.currency):
            raise ValidationError("GA4 evidence must preserve report grain and metric context.")
        try:
            encoded = json.dumps(self.result, allow_nan=False, separators=(",", ":")).encode()
        except (TypeError, ValueError):
            raise ValidationError("GA4 evidence must be valid JSON.") from None
        if len(encoded) > 256 * 1024:
            raise ValidationError("GA4 normalized page evidence exceeds 256 KiB.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("GA4 landing observations are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class GA4MeasurementReview(models.Model):
    class InstrumentationState(models.TextChoices):
        UNVERIFIED = "unverified", "Unverified"
        MANUAL_REVIEWED = "manual_reviewed", "Manually reviewed, not independently verified"

    class EventQualityState(models.TextChoices):
        NOT_CHECKED = "not_checked", "Not checked"
        SUSPECTED_MISSING = "suspected_missing", "Suspected missing events"
        SUSPECTED_DUPLICATE = "suspected_duplicate", "Suspected duplicate events"
        SUSPECTED_BOTH = "suspected_both", "Suspected missing and duplicate events"
        MANUAL_NO_CONCERN = "manual_review_no_concern", "Manual review noted no concern, not verified"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="ga4_measurement_reviews")
    connection = models.ForeignKey(IntegrationConnection, on_delete=models.PROTECT, related_name="ga4_measurement_reviews")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    revision = models.PositiveSmallIntegerField()
    property_id = models.CharField(max_length=20)
    currency = models.CharField(max_length=3)
    timezone = models.CharField(max_length=64)
    definitions = models.JSONField(default=list, blank=True)
    instrumentation_state = models.CharField(max_length=20, choices=InstrumentationState.choices,
                                               default=InstrumentationState.UNVERIFIED)
    event_quality_state = models.CharField(max_length=26, choices=EventQualityState.choices,
                                            default=EventQualityState.NOT_CHECKED)
    instrumentation_notes = models.TextField(max_length=1000, blank=True)
    attribution_notes = models.TextField(max_length=1000, blank=True)
    consent_notes = models.TextField(max_length=1000, blank=True)
    tracking_change_notes = models.TextField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["connection", "revision"], name="integrations_unique_ga4_quality_revision"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="integrations_ga4_quality_revision_positive"),
        ]

    def clean(self):
        if (self.connection_id and self.project_id and
            (self.connection.project_id != self.project_id or self.connection.provider != "google_analytics_4"
             or self.property_id != self.connection.external_property_id
             or self.currency != self.connection.currency or self.timezone != self.connection.timezone)):
            raise ValidationError("GA4 measurement review must preserve its source property and definitions.")
        if type(self.definitions) is not list or len(self.definitions) > 10:
            raise ValidationError("Choose up to ten reviewed GA4 goals and event names.")
        goals, events = set(), set()
        for definition in self.definitions:
            if type(definition) is not dict or set(definition) != {"goal", "event_name", "value_definition"}:
                raise ValidationError("GA4 goal mappings require exact fields.")
            goal, event, value = (definition[field] for field in ("goal", "event_name", "value_definition"))
            if (type(goal) is not str or not 1 <= len(goal.strip()) <= 80 or goal != goal.strip()
                or type(event) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", event)
                or type(value) is not str or len(value) > 120
                or goal.casefold() in goals or event in events):
                raise ValidationError("Choose unique bounded goal names and GA4 event identifiers.")
            goals.add(goal.casefold())
            events.add(event)
        if self.instrumentation_state == self.InstrumentationState.MANUAL_REVIEWED and not self.instrumentation_notes.strip():
            raise ValidationError("Manual instrumentation review requires a note; it is not provider verification.")
        if self.event_quality_state != self.EventQualityState.NOT_CHECKED and not self.instrumentation_notes.strip():
            raise ValidationError("Event-quality concerns require a manual observation note, not an API inference.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("GA4 measurement review history is append-only.")
        self.full_clean()
        return super().save(*args, **kwargs)


class SearchConsoleCoverageObservation(models.Model):
    class Source(models.TextChoices):
        INSPECTION = "inspection", "Google indexed-version URL inspection"
        SITEMAPS = "sitemaps", "Search Console submitted sitemaps"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="search_console_coverage")
    connection = models.ForeignKey(IntegrationConnection, on_delete=models.PROTECT,
                                   related_name="search_console_coverage")
    grant = models.ForeignKey(GoogleOAuthGrant, on_delete=models.PROTECT, related_name="search_console_coverage")
    job = models.ForeignKey("jobs.JobRun", on_delete=models.PROTECT, related_name="search_console_coverage")
    source = models.CharField(max_length=16, choices=Source.choices)
    external_property_id = models.CharField(max_length=512)
    requested_url = models.CharField(max_length=2048, blank=True)
    result = models.JSONField()
    collected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "source"], name="integrations_unique_coverage_job_source"),
            models.CheckConstraint(condition=Q(source__in=["inspection", "sitemaps"]),
                                   name="integrations_coverage_source_valid"),
            models.CheckConstraint(condition=(Q(source="inspection") & ~Q(requested_url=""))
                                   | Q(source="sitemaps", requested_url=""),
                                   name="integrations_coverage_requested_url_valid"),
        ]

    def clean(self):
        if type(self.result) is not dict:
            raise ValidationError("Search Console coverage requires a parsed bounded report.")
        if (self.project_id and self.connection_id and self.connection.project_id != self.project_id
            or self.project_id and self.grant_id and self.grant.project_id != self.project_id
            or self.project_id and self.job_id and self.job.project_id != self.project_id):
            raise ValidationError("Search Console coverage must stay inside one project.")
        if (self.job_id and self.job.handler != "collect_search_console_coverage"
            or self.connection_id and self.external_property_id != self.connection.external_property_id
            or self.source == self.Source.INSPECTION and self.result.get("inspection_url") != self.requested_url
            or self.source == self.Source.SITEMAPS and self.result.get("sitemaps") is None):
            raise ValidationError("Search Console coverage identity or report source changed.")
        try:
            encoded = json.dumps(self.result, allow_nan=False, separators=(",", ":")).encode()
        except (TypeError, ValueError, RecursionError):
            raise ValidationError("Search Console coverage must be valid JSON.") from None
        if len(encoded) > 64 * 1024:
            raise ValidationError("Search Console coverage exceeds its report limit.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Search Console coverage evidence is immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class QueryBrandReview(models.Model):
    class Label(models.TextChoices):
        BRANDED = "branded", "Branded"
        NON_BRANDED = "non_branded", "Non-branded"
        UNCLASSIFIED = "unclassified", "Unclassified"

    observation = models.ForeignKey(SearchMetricObservation, on_delete=models.PROTECT, related_name="brand_reviews")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="query_brand_reviews")
    revision = models.PositiveIntegerField()
    label = models.CharField(max_length=16, choices=Label.choices)
    reason = models.CharField(max_length=240)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["observation", "revision"], name="integrations_unique_brand_review_revision"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="integrations_brand_review_revision_valid"),
            models.CheckConstraint(condition=Q(label__in=["branded", "non_branded", "unclassified"]), name="integrations_brand_review_label_valid"),
        ]
        ordering = ["observation_id", "revision"]

    def clean(self):
        if self.observation_id and self.observation.dimension != SourceDimension.QUERY:
            raise ValidationError("Only query-grained observations may have brand reviews.")
        if not self.reason or not self.reason.strip():
            raise ValidationError("A review reason is required.")
        self.reason = self.reason.strip()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Query brand reviews are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class SyncCursor(models.Model):
    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        RUNNING = "running", "Running"
        WAITING_PROVIDER = "waiting_provider", "Waiting for provider"
        SUCCEEDED = "succeeded", "Succeeded"
        PARTIALLY_SUCCEEDED = "partially_succeeded", "Partially succeeded"
        FAILED = "failed", "Failed"
        UNAVAILABLE = "unavailable", "Unavailable"

    class QuotaState(models.TextChoices):
        AVAILABLE = "available", "Available"
        LIMITED = "limited", "Limited"
        EXHAUSTED = "exhausted", "Exhausted"
        UNAVAILABLE = "unavailable", "Unavailable"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="sync_cursors")
    connection = models.OneToOneField(IntegrationConnection, on_delete=models.PROTECT, related_name="sync_cursor")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.IDLE)
    position = models.JSONField(default=dict, blank=True)
    coverage_start = models.DateField(null=True, blank=True)
    coverage_end = models.DateField(null=True, blank=True)
    fresh_through = models.DateField(null=True, blank=True)
    quota_state = models.CharField(max_length=16, choices=QuotaState.choices, default=QuotaState.AVAILABLE)
    retry_after = models.DateTimeField(null=True, blank=True)
    error_category = models.CharField(max_length=64, blank=True)
    revision = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=[
                    "idle", "running", "waiting_provider", "succeeded", "partially_succeeded", "failed", "unavailable",
                ]),
                name="integrations_cursor_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(quota_state__in=["available", "limited", "exhausted", "unavailable"]),
                name="integrations_cursor_quota_valid",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(status__in=["idle", "running", "succeeded"])
                    | Q(error_category="", retry_after__isnull=True)
                ),
                name="integrations_cursor_terminal_fields_valid",
            ),
        ]

    def clean(self):
        if self.connection_id and self.project_id and self.connection.project_id != self.project_id:
            raise ValidationError("Sync cursor must stay within its connection's project.")
        if self.connection_id and IntegrationCapability.API_SYNC not in self.connection.capabilities:
            raise ValidationError("This connection does not support API synchronization.")
        self.position = _bounded_json_object(self.position, "position")
        if bool(self.coverage_start) != bool(self.coverage_end):
            raise ValidationError("Sync coverage requires both start and end dates.")
        if self.coverage_start and self.coverage_end:
            days = (self.coverage_end - self.coverage_start).days + 1
            if days < 1 or (self.connection_id and days > self.connection.backfill_limit_days):
                raise ValidationError("Sync coverage exceeds this connection's bounded window.")
        if self.status in {self.Status.PARTIALLY_SUCCEEDED, self.Status.FAILED, self.Status.UNAVAILABLE} and not self.error_category:
            raise ValidationError({"error_category": "Record a bounded failure category."})
        if self.status == self.Status.WAITING_PROVIDER and self.retry_after is None:
            raise ValidationError({"retry_after": "Record when this connection may retry."})
        if self.status in {self.Status.IDLE, self.Status.RUNNING, self.Status.SUCCEEDED} and (
            self.error_category or self.retry_after is not None
        ):
            raise ValidationError("Idle, running, and successful sync states cannot retain retry or failure details.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SearchConsoleBackfill(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        PAUSED = "paused", "Paused"
        SUCCEEDED = "succeeded", "Succeeded"

    organization = models.ForeignKey("tenancy.Organization", on_delete=models.PROTECT)
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    connection = models.ForeignKey(IntegrationConnection, on_delete=models.PROTECT)
    grant = models.ForeignKey(GoogleOAuthGrant, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    current_job = models.ForeignKey("jobs.JobRun", null=True, blank=True, on_delete=models.PROTECT)
    start_day = models.DateField()
    end_day = models.DateField()
    next_day = models.DateField()
    dimension = models.CharField(max_length=8, choices=[("date", "Date"), ("query", "Query"), ("page", "Page")])
    idempotency_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9._-]+$")])
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    error_category = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "idempotency_key"], name="integrations_unique_backfill_request"),
            models.UniqueConstraint(fields=["connection"], condition=Q(status="running"),
                                    name="integrations_one_active_backfill_per_source"),
            models.CheckConstraint(condition=Q(status__in=["running", "paused", "succeeded"]),
                                   name="integrations_backfill_status_valid"),
            models.CheckConstraint(condition=Q(start_day__lte=models.F("end_day"), next_day__gte=models.F("start_day")),
                                   name="integrations_backfill_day_order"),
        ]

    def clean(self):
        if self.project_id and self.organization_id and self.project.organization_id != self.organization_id:
            raise ValidationError("Backfill organization changed.")
        if self.project_id and self.connection_id and self.connection.project_id != self.project_id:
            raise ValidationError("Backfill connection changed.")
        if self.project_id and self.grant_id and (self.grant.project_id != self.project_id
                                                  or self.grant.organization_id != self.organization_id):
            raise ValidationError("Backfill grant changed.")
        if self.current_job_id and (self.current_job.project_id != self.project_id
                                    or self.current_job.handler != "sync_search_console"
                                    or self.current_job.input_snapshot.get("connection_id") != self.connection_id
                                    or self.current_job.input_snapshot.get("grant_id") != self.grant_id
                                    or self.current_job.input_snapshot.get("day") != self.next_day.isoformat()
                                    or self.current_job.input_snapshot.get("dimensions") != [self.dimension]):
            raise ValidationError("Backfill job changed.")
        if self.start_day and self.end_day and (self.end_day - self.start_day).days not in range(7):
            raise ValidationError("Choose one to seven backfill days.")
        if self.next_day and self.start_day and self.next_day < self.start_day:
            raise ValidationError("Backfill progress is unavailable.")
        if self.status == self.Status.SUCCEEDED and self.current_job_id is None:
            raise ValidationError("A completed backfill needs its final job.")

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.get(pk=self.pk)
            if any(getattr(self, field) != getattr(original, field) for field in (
                "organization_id", "project_id", "connection_id", "grant_id", "actor_id",
                "start_day", "end_day", "dimension", "idempotency_key",
            )):
                raise ValidationError("Backfill scope cannot change.")
        self.full_clean()
        return super().save(*args, **kwargs)


from .yandex_models import YandexOAuthApplication, YandexOAuthGrant, YandexOAuthIntent
from .serp_models import SerpConfiguration
from .repository_models import RepositoryApplication, RepositoryConsent, RepositoryGrant
