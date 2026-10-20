import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, URLValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


_provider_key = RegexValidator(r"^[a-z][a-z0-9_-]{1,31}$", "Enter a valid provider key.")
_model_identifier = RegexValidator(
    r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$",
    "Enter a valid provider model identifier.",
)
_secret_reference = RegexValidator(
    r"^env:[A-Z][A-Z0-9_]{2,63}$",
    "Use an allowlisted environment secret reference.",
)
_dns_label = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_compatible_endpoint(value):
    if not isinstance(value, str) or not value or len(value) > 1024 or "\\" in value:
        raise ValidationError("Enter a bounded public HTTPS endpoint.")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname.encode("idna").decode().lower().rstrip(".") if parsed.hostname else ""
        port = parsed.port
    except (UnicodeError, ValueError):
        raise ValidationError("Enter a bounded public HTTPS endpoint.") from None
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
        or any(ord(character) < 32 for character in value)
    ):
        raise ValidationError("Enter a bounded public HTTPS endpoint.")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal", ".home.arpa")):
        raise ValidationError("Provider endpoints must use a public host.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        labels = hostname.split(".")
        if len(hostname) > 253 or len(labels) < 2 or any(not _dns_label.fullmatch(label) for label in labels):
            raise ValidationError("Provider endpoints must use a valid public host.") from None
        host = hostname
    else:
        if not address.is_global:
            raise ValidationError("Provider endpoints must use a public host.")
        host = f"[{hostname}]" if address.version == 6 else hostname
    path = parsed.path.rstrip("/")
    URLValidator(schemes=["https"])(urlunsplit(("https", host, path, "", "")))
    return urlunsplit(("https", host, path, "", ""))


class AIProvider(models.Model):
    class Kind(models.TextChoices):
        OPENAI = "openai", "OpenAI"
        OPENAI_COMPATIBLE = "openai_compatible", "OpenAI-compatible"

    class EgressPolicy(models.TextChoices):
        OFFICIAL_OPENAI = "official_openai", "Official OpenAI endpoint"
        PUBLIC_HTTPS = "public_https", "Public HTTPS endpoint"

    key = models.CharField(max_length=32, unique=True, validators=[_provider_key])
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    base_url = models.CharField(max_length=1024, blank=True)
    egress_policy = models.CharField(max_length=24, choices=EgressPolicy.choices)
    enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind="openai", base_url="", egress_policy="official_openai")
                    | Q(kind="openai_compatible", egress_policy="public_https") & ~Q(base_url="")
                ),
                name="providers_provider_kind_endpoint_valid",
            ),
        ]
        ordering = ["key"]

    def clean_fields(self, exclude=None):
        if isinstance(self.key, str):
            self.key = self.key.strip().lower()
        if isinstance(self.name, str):
            self.name = self.name.strip()
        if self.kind == self.Kind.OPENAI:
            if self.base_url:
                raise ValidationError({"base_url": "The native OpenAI endpoint is not configurable."})
            self.egress_policy = self.EgressPolicy.OFFICIAL_OPENAI
        elif self.kind == self.Kind.OPENAI_COMPATIBLE:
            try:
                self.base_url = normalize_compatible_endpoint(self.base_url)
            except ValidationError as error:
                raise ValidationError({"base_url": error.messages}) from None
            self.egress_policy = self.EgressPolicy.PUBLIC_HTTPS
        super().clean_fields(exclude=exclude)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class AIProviderAccount(models.Model):
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    provider = models.ForeignKey(AIProvider, on_delete=models.PROTECT, related_name="accounts")
    organization = models.ForeignKey("tenancy.Organization", on_delete=models.PROTECT, null=True, blank=True,
                                     related_name="ai_provider_accounts")
    label = models.CharField(max_length=80)
    secret_reference = models.CharField(max_length=68, validators=[_secret_reference], blank=True, default="", editable=False)
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    rotated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "label"], condition=Q(organization__isnull=True),
                                    name="providers_unique_platform_account_label"),
            models.UniqueConstraint(fields=["provider", "organization", "label"],
                                    condition=Q(organization__isnull=False), name="providers_unique_org_account_label"),
            models.CheckConstraint(condition=Q(organization__isnull=True) | Q(secret_reference=""),
                                   name="providers_org_account_no_env_reference"),
            models.CheckConstraint(
                condition=Q(state="active", revoked_at__isnull=True) | Q(state="revoked", revoked_at__isnull=False),
                name="providers_account_state_valid",
            ),
        ]
        ordering = ["provider__key", "label", "id"]

    def clean_fields(self, exclude=None):
        if isinstance(self.label, str):
            self.label = self.label.strip()
        super().clean_fields(exclude=exclude)

    def clean(self):
        if self.secret_reference and self.secret_reference not in settings.AI_PROVIDER_SECRET_REFERENCES:
            raise ValidationError({"secret_reference": "Secret reference is not allowlisted."})
        if self.organization_id and self.secret_reference:
            raise ValidationError("Organization keys cannot use platform environment references.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.provider.key}: {self.label}"


class AIProviderSecret(models.Model):
    account = models.OneToOneField(AIProviderAccount, on_delete=models.PROTECT, related_name="encrypted_secret")
    ciphertext = models.TextField(editable=False)
    rotated_at = models.DateTimeField()

    def clean(self):
        if not self.ciphertext.startswith("v1:") or len(self.ciphertext) > 8192:
            raise ValidationError("Invalid encrypted provider credential.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class GoogleOAuthApplication(models.Model):
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    key = models.CharField(max_length=16, unique=True, default="primary", editable=False)
    client_id = models.CharField(max_length=512, blank=True)
    redirect_uri = models.URLField(max_length=512, blank=True)
    encrypted_secret = models.TextField(blank=True, editable=False)
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    rotated_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(key__in=["primary", "analytics", "business_profile"]), name="providers_google_app_allowed_keys"),
            models.CheckConstraint(condition=(Q(state="active") & ~Q(client_id="") & ~Q(redirect_uri="")
                                              & Q(encrypted_secret__startswith="v1:"))
                                   | Q(state="revoked", encrypted_secret=""), name="providers_google_app_state_valid"),
        ]

    def clean(self):
        if self.key not in {"primary", "analytics", "business_profile"} or self.state not in self.State.values or len(self.encrypted_secret) > 8192:
            raise ValidationError("Invalid Google application configuration.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PerformanceAPIKey(models.Model):
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    key = models.CharField(max_length=8, unique=True, default="primary", editable=False)
    encrypted_secret = models.TextField(blank=True, editable=False)
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    rotated_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(key="primary"), name="providers_performance_key_primary_only"),
            models.CheckConstraint(condition=Q(state="active", encrypted_secret__startswith="v1:")
                                   | Q(state="revoked", encrypted_secret=""),
                                   name="providers_performance_key_state_valid"),
        ]

    def clean(self):
        if self.key != "primary" or self.state not in self.State.values or len(self.encrypted_secret) > 8192:
            raise ValidationError("Invalid performance credential configuration.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class YouTubeAPIKey(models.Model):
    """One API Client/project. Operational counters contain no returned API data."""
    key = models.CharField(max_length=8, unique=True, default="primary", editable=False)
    api_project = models.CharField(max_length=30, validators=[RegexValidator(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")])
    encrypted_secret = models.TextField(blank=True, editable=False)
    state = models.CharField(max_length=16, choices=PerformanceAPIKey.State.choices)
    rotated_at = models.DateTimeField()
    daily_limit = models.PositiveSmallIntegerField()
    quota_day = models.DateField(null=True, blank=True)
    attempted_requests = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(key="primary"), name="providers_youtube_single_client"),
            models.CheckConstraint(condition=Q(daily_limit__gte=1, daily_limit__lte=100), name="providers_youtube_daily_bound"),
            models.CheckConstraint(condition=Q(attempted_requests__lte=100), name="providers_youtube_attempt_bound"),
            models.CheckConstraint(condition=Q(state="active", encrypted_secret__startswith="v1:")
                | Q(state="revoked", encrypted_secret=""), name="providers_youtube_key_state"),
        ]

    def clean(self):
        if len(self.encrypted_secret) > 8192:
            raise ValidationError("Invalid encrypted YouTube credential.")

    def save(self, *args, **kwargs):
        if self.pk and self.api_project != type(self).objects.get(pk=self.pk).api_project:
            raise ValidationError("The YouTube API Client must keep its single API project.")
        self.full_clean()
        return super().save(*args, **kwargs)


class OrganizationPerformanceKey(models.Model):
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    organization = models.OneToOneField("tenancy.Organization", on_delete=models.PROTECT,
                                        related_name="performance_credential")
    encrypted_secret = models.TextField(blank=True, editable=False)
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    rotated_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(state="active", encrypted_secret__startswith="v1:")
                                   | Q(state="revoked", encrypted_secret=""),
                                   name="providers_org_performance_state_valid"),
        ]

    def clean(self):
        if self.state not in self.State.values or len(self.encrypted_secret) > 8192:
            raise ValidationError("Invalid organization performance credential.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class AIModelCapability(models.TextChoices):
    TEXT_GENERATION = "text_generation", "Text generation"
    STRUCTURED_OUTPUT = "structured_output", "Structured output"
    REASONING = "reasoning", "Reasoning"
    TOOL_CALLING = "tool_calling", "Tool calling"
    WEB_SEARCH = "web_search", "Web search"
    IMAGE_UNDERSTANDING = "image_understanding", "Image understanding"
    EMBEDDINGS = "embeddings", "Embeddings"
    BATCH = "batch", "Batch"
    BACKGROUND = "background", "Background"


class AIModel(models.Model):
    class AccessTier(models.TextChoices):
        UNKNOWN = "unknown", "Not verified"
        STANDARD = "standard", "Standard paid access"
        FREE = "free", "Free/contributor tier"

    provider = models.ForeignKey(AIProvider, on_delete=models.PROTECT, related_name="models")
    identifier = models.CharField(max_length=128, validators=[_model_identifier])
    name = models.CharField(max_length=120)
    capabilities = models.JSONField(default=list)
    context_window = models.PositiveIntegerField(null=True, blank=True)
    max_output_tokens = models.PositiveIntegerField(null=True, blank=True)
    capability_source = models.URLField(max_length=1024, blank=True)
    capabilities_verified_at = models.DateTimeField(null=True, blank=True)
    input_price_usd_per_million = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    output_price_usd_per_million = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    pricing_source = models.URLField(max_length=1024, blank=True)
    pricing_verified_at = models.DateTimeField(null=True, blank=True)
    access_tier = models.CharField(max_length=16, choices=AccessTier.choices, default=AccessTier.UNKNOWN)
    privacy_policy_url = models.URLField(max_length=1024, blank=True)
    enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "identifier"], name="providers_unique_provider_model"),
            models.CheckConstraint(
                condition=Q(context_window__isnull=True) | Q(context_window__gte=1, context_window__lte=10_000_000),
                name="providers_model_context_window_valid",
            ),
            models.CheckConstraint(
                condition=Q(max_output_tokens__isnull=True) | Q(max_output_tokens__gte=1, max_output_tokens__lte=10_000_000),
                name="providers_model_output_limit_valid",
            ),
            models.CheckConstraint(
                condition=(Q(input_price_usd_per_million__isnull=True, output_price_usd_per_million__isnull=True)
                           | Q(input_price_usd_per_million__gte=0, input_price_usd_per_million__lte=10_000,
                               output_price_usd_per_million__gte=0, output_price_usd_per_million__lte=10_000)),
                name="providers_model_prices_both_or_neither_valid",
            ),
            models.CheckConstraint(condition=Q(access_tier__in=["unknown", "standard", "free"]),
                                   name="providers_model_access_tier_valid"),
        ]
        ordering = ["provider__key", "identifier"]

    def clean_fields(self, exclude=None):
        if isinstance(self.identifier, str):
            self.identifier = self.identifier.strip()
        if isinstance(self.name, str):
            self.name = self.name.strip()
        super().clean_fields(exclude=exclude)

    def clean(self):
        if (
            type(self.capabilities) is not list
            or len(self.capabilities) > len(AIModelCapability.values)
            or any(not isinstance(item, str) or item not in AIModelCapability.values for item in self.capabilities)
            or len(self.capabilities) != len(set(self.capabilities))
        ):
            raise ValidationError({"capabilities": "Choose unique supported capabilities."})
        self.capabilities = sorted(self.capabilities)
        if self.max_output_tokens and self.context_window and self.max_output_tokens > self.context_window:
            raise ValidationError({"max_output_tokens": "Output limit cannot exceed the context window."})
        if self.enabled and (not self.capability_source or self.capabilities_verified_at is None):
            raise ValidationError("Enabled models require dated capability evidence.")
        if self.capability_source:
            try:
                self.capability_source = normalize_compatible_endpoint(self.capability_source)
            except ValidationError:
                raise ValidationError({
                    "capability_source": "Enter a public HTTPS evidence URL without credentials, query, or fragment."
                }) from None
        if self.capabilities_verified_at and (
            timezone.is_naive(self.capabilities_verified_at)
            or self.capabilities_verified_at > timezone.now()
        ):
            raise ValidationError({"capabilities_verified_at": "Capability evidence cannot be dated in the future."})
        if (self.input_price_usd_per_million is None) != (self.output_price_usd_per_million is None):
            raise ValidationError("Input and output price evidence must be supplied together.")
        if self.input_price_usd_per_million is not None:
            if not self.pricing_source or self.pricing_verified_at is None:
                raise ValidationError("Prices require dated public evidence.")
        elif self.pricing_source or self.pricing_verified_at is not None:
            raise ValidationError("Price evidence requires both prices; absent prices remain unknown.")
        for field in ("pricing_source", "privacy_policy_url"):
            value = getattr(self, field)
            if value:
                try:
                    setattr(self, field, normalize_compatible_endpoint(value))
                except ValidationError:
                    raise ValidationError({field: "Use public HTTPS evidence without credentials, query, or fragment."}) from None
        if self.access_tier == self.AccessTier.FREE and not self.privacy_policy_url:
            raise ValidationError({"privacy_policy_url": "Free access requires a public data-use policy."})
        if self.pricing_verified_at and (timezone.is_naive(self.pricing_verified_at)
                                         or self.pricing_verified_at > timezone.now()):
            raise ValidationError({"pricing_verified_at": "Price evidence cannot be dated in the future."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.provider.key}: {self.identifier}"


class AIRoutingPolicy(models.Model):
    project = models.OneToOneField("tenancy.Project", null=True, blank=True, on_delete=models.CASCADE,
                                   related_name="ai_routing_policy")
    task_key = models.CharField(max_length=24, default="ai_text")
    model = models.ForeignKey(AIModel, on_delete=models.PROTECT, related_name="routing_primaries")
    account = models.ForeignKey(AIProviderAccount, on_delete=models.PROTECT, related_name="routing_policies")
    fallback_model_ids = models.JSONField(default=list, blank=True)
    max_output_tokens = models.PositiveSmallIntegerField()
    max_cost_usd = models.DecimalField(max_digits=9, decimal_places=6)
    timeout_seconds = models.PositiveSmallIntegerField()
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["task_key"], condition=Q(project__isnull=True),
                                    name="providers_unique_system_ai_route_task"),
            models.CheckConstraint(condition=Q(task_key="ai_text"), name="providers_ai_route_task_valid"),
            models.CheckConstraint(condition=Q(max_output_tokens__gte=1, max_output_tokens__lte=256),
                                   name="providers_ai_route_output_limit"),
            models.CheckConstraint(condition=Q(max_cost_usd__gt=0, max_cost_usd__lte=100),
                                   name="providers_ai_route_cost_limit"),
            models.CheckConstraint(condition=Q(timeout_seconds__gte=1, timeout_seconds__lte=30),
                                   name="providers_ai_route_timeout_limit"),
        ]

    def clean(self):
        if self.task_key != "ai_text":
            raise ValidationError("Only configured AI text routing is supported.")
        if (type(self.fallback_model_ids) is not list or len(self.fallback_model_ids) > 2
            or any(type(item) is not int or item < 1 for item in self.fallback_model_ids)
            or len(set(self.fallback_model_ids)) != len(self.fallback_model_ids)
            or self.model_id in self.fallback_model_ids):
            raise ValidationError("Choose at most two distinct fallback models.")
        if self.model_id and self.account_id:
            if self.model.provider_id != self.account.provider_id:
                raise ValidationError("Routing models and account must share a provider.")
            if self.account.organization_id != (self.project.organization_id if self.project_id else None) \
                    and self.account.organization_id is not None:
                raise ValidationError("Routing account belongs to another organization.")
            candidates = AIModel.objects.filter(pk__in=self.fallback_model_ids, provider_id=self.model.provider_id)
            if candidates.count() != len(self.fallback_model_ids):
                raise ValidationError("Fallback models must use the selected account's provider.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
