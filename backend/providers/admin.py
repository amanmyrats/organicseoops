from django.contrib import admin

from tenancy.admin import InspectOnlyAdmin
from .models import YouTubeAPIKey

from .models import AIModel, AIProvider, AIProviderAccount, AIProviderSecret, AIRoutingPolicy, GoogleOAuthApplication, PerformanceAPIKey


@admin.register(YouTubeAPIKey)
class YouTubeAPIKeyAdmin(InspectOnlyAdmin):
    fields = ("key", "api_project", "state", "rotated_at", "daily_limit", "quota_day", "attempted_requests")
    list_display = ("key", "api_project", "state", "daily_limit", "quota_day", "attempted_requests")


@admin.register(AIProvider)
class AIProviderAdmin(InspectOnlyAdmin):
    fields = ("key", "name", "kind", "base_url", "egress_policy", "enabled", "created_at", "updated_at")
    list_display = ("id", "key", "name", "kind", "egress_policy", "enabled", "updated_at")
    list_filter = ("kind", "egress_policy", "enabled")
    search_fields = ("=id", "key", "name", "base_url")


@admin.register(AIProviderAccount)
class AIProviderAccountAdmin(InspectOnlyAdmin):
    fields = ("provider", "label", "credential_status", "state", "rotated_at", "revoked_at", "created_at", "updated_at")
    readonly_fields = ("credential_status",)
    list_display = ("id", "provider_id", "label", "credential_status", "state", "rotated_at", "revoked_at")
    list_filter = ("state", "provider")
    search_fields = ("=id", "=provider__key", "label")

    @admin.display(description="Credential reference")
    def credential_status(self, obj):
        return "configured" if obj and (obj.secret_reference or AIProviderSecret.objects.filter(account=obj).exists()) else "missing"


@admin.register(AIModel)
class AIModelAdmin(InspectOnlyAdmin):
    fields = (
        "provider", "identifier", "name", "capabilities", "context_window", "max_output_tokens",
        "capability_source", "capabilities_verified_at", "enabled", "created_at", "updated_at",
    )
    list_display = ("id", "provider_id", "identifier", "name", "enabled", "capabilities_verified_at")
    list_filter = ("provider", "enabled")
    search_fields = ("=id", "=provider__key", "identifier", "name")


@admin.register(AIRoutingPolicy)
class AIRoutingPolicyAdmin(InspectOnlyAdmin):
    fields = ("project", "task_key", "model", "account", "fallback_model_ids", "max_output_tokens",
              "max_cost_usd", "timeout_seconds", "revision", "updated_at")
    list_display = ("id", "project_id", "task_key", "model_id", "account_id", "revision", "updated_at")
    search_fields = ("=id", "=project__id", "=model__identifier")


@admin.register(GoogleOAuthApplication)
class GoogleOAuthApplicationAdmin(InspectOnlyAdmin):
    fields = ("key", "client_id", "redirect_uri", "state", "rotated_at", "credential_status")
    readonly_fields = ("credential_status",)
    list_display = ("key", "state", "rotated_at", "credential_status")
    list_filter = ("state",)

    @admin.display(description="Credential status")
    def credential_status(self, obj):
        return "configured" if obj and obj.state == obj.State.ACTIVE and obj.encrypted_secret else "unavailable"


@admin.register(PerformanceAPIKey)
class PerformanceAPIKeyAdmin(InspectOnlyAdmin):
    fields = ("key", "state", "rotated_at", "credential_status")
    readonly_fields = ("credential_status",)
    list_display = ("key", "state", "rotated_at", "credential_status")
    list_filter = ("state",)

    @admin.display(description="Credential status")
    def credential_status(self, obj):
        return "configured" if obj and obj.state == obj.State.ACTIVE and obj.encrypted_secret else "unavailable"
