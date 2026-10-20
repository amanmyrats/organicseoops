from django.contrib import admin
from . import support_admin
from . import public_contact_admin
from . import staff_notice_admin
from . import staff_feedback_admin
from . import staff_receipt_admin
from . import trial_correction_admin
from . import staff_subscription_admin
from . import staff_subscription_history_admin
from . import staff_cancellation_admin
from . import staff_checkout_admin
from . import staff_checkout_link_admin
from . import staff_first_active_admin

from .models import (
    AutomaticTrialEligibility,
    AuditEvent,
    DomainAlias,
    EmailFeedbackReceipt,
    EmailSuppression,
    Organization,
    OrganizationBillingCancellation,
    OrganizationCustomerExport,
    OrganizationInvitation,
    OrganizationMembership,
    OrganizationNotice,
    OrganizationTrial,
    PaddleSubscription,
    PaddleSubscriptionHistory,
    PaddleSellerConfiguration,
    PaddleCheckoutAttempt,
    PaddleCheckoutLinkReceipt,
    PaddleFirstActiveObservation,
    PaddleWebhookReceipt,
    OwnershipTransfer,
    Project,
    ProjectConfiguration,
    ProjectMembership,
    ProjectOriginVerification,
    PublicAnalyticsConsentEpoch,
    PublicAnalyticsObservation,
)


class InspectOnlyAdmin(admin.ModelAdmin):
    """Operational inspection; tenant mutations use audited, locked services."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Organization)
class OrganizationAdmin(InspectOnlyAdmin):
    list_display = ("id", "name", "is_suspended", "closed_at", "created_at")
    search_fields = ("=id", "name")
    list_filter = ("is_suspended",)


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(InspectOnlyAdmin):
    list_display = ("id", "organization_id", "user_id", "role", "created_at")
    search_fields = ("=organization__id", "user__email")
    list_filter = ("role",)


@admin.register(AutomaticTrialEligibility)
class AutomaticTrialEligibilityAdmin(InspectOnlyAdmin):
    def get_queryset(self, request): return super().get_queryset(request).none()
    def has_module_permission(self, request): return False
    def has_view_permission(self, request, obj=None): return False


@admin.register(OrganizationCustomerExport)
class OrganizationCustomerExportAdmin(InspectOnlyAdmin):
    fields = ("organization", "actor", "format", "state", "size_bytes", "created_at", "last_progress_at", "completed_at")
    list_display = ("id", "organization_id", "actor_id", "state", "size_bytes", "last_progress_at")
    search_fields = ("=organization__id", "=id")
    list_filter = ("state",)


@admin.register(PaddleSellerConfiguration)
class PaddleSellerConfigurationAdmin(InspectOnlyAdmin):
    fields = ("environment", "state", "product_id", "price_id", "rotated_at")
    list_display = ("environment", "state", "rotated_at")


@admin.register(Project)
class ProjectAdmin(InspectOnlyAdmin):
    list_display = ("id", "organization_id", "name", "canonical_origin", "access_restricted")
    search_fields = ("=organization__id", "name", "canonical_origin")
    list_filter = ("access_restricted",)


@admin.register(ProjectConfiguration)
class ProjectConfigurationAdmin(InspectOnlyAdmin):
    list_display = ("id", "project_id", "current_step", "source_choice", "revision", "updated_at")
    search_fields = ("=project__id", "project__name", "target_country", "business_goal")
    list_filter = ("current_step", "source_choice")


@admin.register(ProjectMembership)
class ProjectMembershipAdmin(InspectOnlyAdmin):
    list_display = ("id", "project_id", "organization_membership_id")
    search_fields = ("=project__id", "=organization_membership__user__email")


@admin.register(DomainAlias)
class DomainAliasAdmin(InspectOnlyAdmin):
    list_display = ("id", "organization_id", "project_id", "origin")
    search_fields = ("=organization__id", "origin")


@admin.register(ProjectOriginVerification)
class ProjectOriginVerificationAdmin(InspectOnlyAdmin):
    fields = ("organization", "project", "origin", "method", "state", "verified_at", "revoked_at", "created_at", "updated_at")
    list_display = ("id", "organization_id", "project_id", "origin", "method", "state", "verified_at", "revoked_at")
    search_fields = ("=organization__id", "=project__id", "origin")
    list_filter = ("method", "state")


@admin.register(OrganizationInvitation)
class OrganizationInvitationAdmin(InspectOnlyAdmin):
    fields = ("organization", "email", "role", "inviter", "state", "expires_at", "accepted_at", "revoked_at", "expired_at", "created_at")
    list_display = ("id", "organization_id", "email", "role", "state", "expires_at")
    search_fields = ("=organization__id", "email")
    list_filter = ("state", "role")


@admin.register(OwnershipTransfer)
class OwnershipTransferAdmin(InspectOnlyAdmin):
    list_display = ("id", "organization_id", "from_user_id", "to_user_id", "state", "created_at")
    search_fields = ("=organization__id", "from_user__email", "to_user__email")
    list_filter = ("state",)


@admin.register(AuditEvent)
class AuditEventAdmin(InspectOnlyAdmin):
    list_display = ("id", "organization_id", "event_type", "actor_id", "subject_user_id", "created_at")
    search_fields = ("=organization__id", "=project__id", "=request_id", "actor__email")
    list_filter = ("event_type",)


@admin.register(PublicAnalyticsConsentEpoch)
class PublicAnalyticsConsentEpochAdmin(InspectOnlyAdmin):
    fields = ("created_at", "expires_at", "revoked_at")
    list_display = ("created_at", "expires_at", "revoked_at")


@admin.register(PublicAnalyticsObservation)
class PublicAnalyticsObservationAdmin(InspectOnlyAdmin):
    fields = ("event_id", "route_id", "locale", "cta_id", "occurred_at")
    list_display = ("event_id", "route_id", "locale", "cta_id", "occurred_at")
