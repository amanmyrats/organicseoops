"""Explicit ownership map for organization export and resumable deletion."""
from django.apps import apps
from django.db import transaction
from django.db.models import Count, Max

from .artifacts import iter_project_artifact_keys
from .models import Organization, Project
from .services import Action, require_organization_action


# Each entry points only to the owning organization's primary key. Adding a model
# requires assigning it to one of these buckets before closure/export can ship.
CUSTOMER = {
    "tenancy.Organization": "pk", "tenancy.OrganizationMembership": "organization_id",
    "tenancy.Project": "organization_id", "tenancy.ProjectConfiguration": "project__organization_id",
    "tenancy.ProjectMembership": "project__organization_id", "tenancy.DomainAlias": "organization_id",
    "tenancy.ProjectOriginVerification": "organization_id",
    "tenancy.OrganizationInvitation": "organization_id",
    "tenancy.InvitationProject": "invitation__organization_id",
    "tenancy.OwnershipTransfer": "organization_id",
    "tenancy.SupportRequest": "project__organization_id",
    "tenancy.SupportRequestUpdate": "request__project__organization_id",
    "jobs.JobRun": "organization_id", "jobs.JobStep": "job__organization_id",
    "jobs.JobCancellation": "job__organization_id", "jobs.Artifact": "project__organization_id",
    "jobs.SourceCitation": "job__organization_id", "jobs.CrawlRun": "organization_id",
    "jobs.FirstBoundedAuditCompletion": "organization_id",
    "jobs.FirstAuditValueAcknowledgment": "organization_id",
    "jobs.ContentBriefSnapshot": "project__organization_id",
    "jobs.ContentItem": "project__organization_id", "jobs.ContentRevision": "project__organization_id",
    "jobs.ContentLifecycleReview": "project__organization_id",
    "jobs.CrawlPageSnapshot": "project__organization_id", "jobs.RenderAttempt": "project__organization_id",
    "jobs.RenderedPageSnapshot": "project__organization_id",
    "jobs.TechnicalDiagnosticsSnapshot": "project__organization_id",
    "jobs.IndexationEvidenceSnapshot": "project__organization_id",
    "jobs.TopicCandidateSnapshot": "project__organization_id",
    "jobs.TopicReview": "project__organization_id",
    "jobs.AIVisibilityPromptSet": "project__organization_id",
    "jobs.AIVisibilityAnswerReview": "project__organization_id",
    "jobs.AIVisibilityManualObservation": "project__organization_id",
    "jobs.PerformanceObservationSnapshot": "project__organization_id",
    "jobs.JobSchedule": "organization_id", "jobs.Finding": "project__organization_id",
    "jobs.Opportunity": "project__organization_id", "jobs.Recommendation": "project__organization_id",
    "jobs.IntentClusterReview": "project__organization_id", "jobs.ActionReview": "project__organization_id",
    "jobs.ActionOutcomeSnapshot": "project__organization_id",
    "jobs.ActionTechnicalOutcomeSnapshot": "project__organization_id",
    "jobs.LocalBusinessAssessment": "project__organization_id",
    "jobs.LocalFeedbackReview": "project__organization_id",
    "jobs.AuthorityProspectReview": "project__organization_id",
    "jobs.AuthorityLinkReview": "project__organization_id",
    "jobs.LocalVisibilityObservation": "project__organization_id",
    "jobs.ProjectReportSnapshot": "project__organization_id",
    "jobs.ProjectSummaryPreference": "project__organization_id",
    "jobs.ProjectAlertPreference": "project__organization_id",
    "jobs.ProjectCruxAlertPreference": "project__organization_id",
    "jobs.ProjectCruxAlertDelivery": "project__organization_id",
    "jobs.ProjectCruxEpisodeClaim": "project__organization_id",
    "jobs.ProjectSummaryDelivery": "project__organization_id",
    "jobs.ProjectAlertDelivery": "project__organization_id",
    "jobs.ProjectAlertEpisodeClaim": "project__organization_id",
    "jobs.ProjectReportShare": "project__organization_id",
    "integrations.IntegrationConnection": "project__organization_id",
    "integrations.ImportRun": "project__organization_id",
    "integrations.ImportRowError": "import_run__project__organization_id",
    "integrations.PendingArtifactCleanup": "project__organization_id",
    "integrations.ImportExecutionState": "job__organization_id",
    "integrations.SearchMetricObservation": "import_run__project__organization_id",
    "integrations.SearchAnalyticsPageSnapshot": "project__organization_id",
    "integrations.SearchAnalyticsQueryPageSnapshot": "project__organization_id",
    "integrations.GA4LandingPageSnapshot": "project__organization_id",
    "integrations.GA4MeasurementReview": "project__organization_id",
    "integrations.SearchConsoleCoverageObservation": "project__organization_id",
    "integrations.QueryBrandReview": "observation__import_run__project__organization_id",
    "integrations.SyncCursor": "project__organization_id",
    "integrations.SearchConsoleBackfill": "organization_id",
    "providers.AIRoutingPolicy": "project__organization_id",
    "providers.AIProviderAccount": "organization_id",
}

RESTRICTED = {
    "tenancy.ProjectArtifactMutationAttempt": "organization_id",
    "tenancy.ProjectArtifactMutation": "attempt__organization_id",
    "tenancy.AutomaticTrialEligibility": "organization_id",
    "tenancy.OrganizationTrial": "organization_id", "tenancy.OrganizationNotice": "organization_id",
    "tenancy.PaddleSubscription": "organization_id", "tenancy.PaddleSubscriptionHistory": "organization_id",
    "tenancy.PaddleCheckoutAttempt": "organization_id",
    "tenancy.PaddleCheckoutLinkReceipt": "attempt__organization_id",
    "tenancy.PaddleFirstActiveObservation": "organization_id",
    "tenancy.OrganizationBillingCancellation": "organization_id",
    "tenancy.OrganizationDeletionRun": "organization_id",
    "tenancy.OrganizationCustomerExport": "organization_id",
    "tenancy.OrganizationCustomerExportPart": "export__organization_id",
    "tenancy.AuditEvent": "organization_id", "jobs.UsageReservation": "organization_id",
    "jobs.AIUsageRecord": "organization_id",
}

SECRETS = {
    "integrations.RepositoryConsent": "organization_id", "integrations.RepositoryGrant": "organization_id",
    "integrations.YandexOAuthIntent": "organization_id", "integrations.YandexOAuthGrant": "organization_id",
    "integrations.GoogleOAuthIntent": "organization_id", "integrations.GoogleOAuthGrant": "organization_id",
    "integrations.GA4OAuthIntent": "organization_id", "integrations.GA4OAuthGrant": "organization_id",
    "integrations.BusinessProfileOAuthIntent": "organization_id", "integrations.BusinessProfileOAuthGrant": "organization_id",
    "providers.AIProviderSecret": "account__organization_id",
    "providers.OrganizationPerformanceKey": "organization_id",
}

# These resources have no one-organization ownership: never infer tenancy from a
# matching email, provider identifier or globally configured platform account.
GLOBAL = {
    "integrations.RepositoryApplication",
    "integrations.SerpConfiguration",
    "integrations.YandexOAuthApplication",
    "tenancy.PublicContactRequest",
    "tenancy.PublicAnalyticsConsentEpoch", "tenancy.PublicAnalyticsObservation",
    "accounts.User", "accounts.AccountEmailDelivery", "accounts.RetainedTrialIdentity", "tenancy.EmailFeedbackReceipt",
    "tenancy.EmailSuppression", "tenancy.PaddleSellerConfiguration", "tenancy.PaddleWebhookReceipt",
    "providers.AIProvider", "providers.GoogleOAuthApplication", "providers.PerformanceAPIKey",
    "providers.AIModel",
    "providers.YouTubeAPIKey",
}


def require_complete_ownership_map():
    available = {model._meta.label for model in apps.get_models()
                 if model._meta.app_label in {"accounts", "tenancy", "jobs", "integrations", "providers"}}
    registered = set(CUSTOMER) | set(RESTRICTED) | set(SECRETS) | GLOBAL
    if available != registered or sum(len(group) for group in (CUSTOMER, RESTRICTED, SECRETS, GLOBAL)) != len(available):
        raise RuntimeError("Customer data inventory needs a reviewed ownership assignment.")


def inventory_customer_data(*, organization, actor):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_EXPORT)
        require_complete_ownership_map()
        result = {"version": "customer-data-inventory-v1", "organization_id": organization.pk,
                  "scope": "record_counts_only_not_a_complete_export_or_deletion_receipt"}
        for bucket, models in (("customer", CUSTOMER), ("restricted", RESTRICTED), ("secret_bearing", SECRETS)):
            result[bucket] = []
            for label, lookup in sorted(models.items()):
                queryset = apps.get_model(label).objects.filter(**{lookup: organization.pk})
                if bucket == "customer":
                    stats = queryset.aggregate(count=Count("pk"), latest_id=Max("pk"))
                    result[bucket].append({"model": label, **stats})
                else:
                    result[bucket].append({"model": label, "count": queryset.count()})
        project_storage = [{"project_id": project.pk,
                            "visible_count": sum(1 for _ in iter_project_artifact_keys(project=project))}
                           for project in Project.objects.filter(organization=organization).order_by("pk")]
        result["artifact_counts"] = {
            "job_artifacts": next(row["count"] for row in result["customer"] if row["model"] == "jobs.Artifact"),
            "report_artifacts": next(row["count"] for row in result["customer"]
                                     if row["model"] == "jobs.ProjectReportSnapshot"),
            "pending_cleanup": next(row["count"] for row in result["customer"]
                                    if row["model"] == "integrations.PendingArtifactCleanup"),
            "visible_storage_objects": sum(row["visible_count"] for row in project_storage),
            "projects": project_storage,
        }
        return result
