from django.contrib import admin
from . import staff_job_admin

from tenancy.admin import InspectOnlyAdmin
from .models import AIVisibilityPromptSet, AIVisibilityAnswerReview
from .models import LocalFeedbackReview, LocalVisibilityObservation
from .models import AIVisibilityManualObservation
from .models import AuthorityLinkReview, AuthorityProspectReview, ContentLifecycleReview
from .models import FirstAuditValueAcknowledgment, FirstBoundedAuditCompletion


@admin.register(FirstBoundedAuditCompletion)
class FirstBoundedAuditCompletionAdmin(InspectOnlyAdmin):
    fields = ("organization", "project", "job", "observed_at", "source_digest")
    list_display = ("id", "organization_id", "project_id", "job_id", "observed_at")
    search_fields = ("=organization__id", "=project__id", "=job__id")


@admin.register(FirstAuditValueAcknowledgment)
class FirstAuditValueAcknowledgmentAdmin(InspectOnlyAdmin):
    fields = ("organization", "project", "job", "action_review", "actor", "acknowledged_at", "source_digest")
    list_display = ("id", "organization_id", "project_id", "job_id", "acknowledged_at")
    search_fields = ("=organization__id", "=project__id", "=job__id")


@admin.register(ContentLifecycleReview)
class ContentLifecycleReviewAdmin(InspectOnlyAdmin):
    fields = ("project", "content_revision", "actor", "source_actor", "assignee", "review_id", "revision", "state",
              "reviewed_revision", "approved_by", "approved_at", "executed_at", "created_at")
    list_display = ("id", "project_id", "content_revision_id", "review_id", "revision", "state", "created_at")
    search_fields = ("=project__id", "=review_id")
    list_filter = ("state",)


@admin.register(AuthorityLinkReview)
class AuthorityLinkReviewAdmin(InspectOnlyAdmin):
    fields = ("project", "actor", "source_actor", "assignee", "verification", "verified_at", "crawl_page",
        "recovery_action_review", "link_id", "revision", "state", "reviewed_revision", "approved_by", "approved_at", "executed_at", "created_at")
    list_display = ("id", "project_id", "link_id", "revision", "state", "created_at")
    search_fields = ("=project__id", "=link_id")
    list_filter = ("state",)


@admin.register(AuthorityProspectReview)
class AuthorityProspectReviewAdmin(InspectOnlyAdmin):
    fields = ("project", "actor", "source_actor", "assignee", "research_job", "source_index", "prospect_id", "revision",
              "state", "reviewed_revision", "approved_by", "approved_at", "executed_at", "created_at")
    list_display = ("id", "project_id", "prospect_id", "revision", "state", "created_at")
    search_fields = ("=project__id", "=prospect_id")
    list_filter = ("state",)


@admin.register(AIVisibilityManualObservation)
class AIVisibilityManualObservationAdmin(InspectOnlyAdmin):
    fields = ("project", "actor", "intent_review", "verification", "verified_at", "observation_id", "revision", "evaluated", "created_at")
    list_display = ("id", "project_id", "observation_id", "revision", "evaluated", "created_at")
    search_fields = ("=project__id", "=observation_id")


@admin.register(LocalVisibilityObservation)
class LocalVisibilityObservationAdmin(InspectOnlyAdmin):
    fields = ("project", "actor", "assessment", "verification", "verified_at", "observation_id", "revision", "created_at")
    list_display = ("id", "project_id", "observation_id", "revision", "created_at")
    search_fields = ("=project__id", "=observation_id")


@admin.register(LocalFeedbackReview)
class LocalFeedbackReviewAdmin(InspectOnlyAdmin):
    fields = ("project", "actor", "source_actor", "assessment", "verification", "feedback_id", "revision",
              "state", "reviewed_revision", "approved_by", "approved_at", "executed_at", "created_at")
    list_display = ("id", "project_id", "feedback_id", "revision", "state", "created_at")
    search_fields = ("=project__id", "=feedback_id")
    list_filter = ("state",)


@admin.register(AIVisibilityAnswerReview)
class AIVisibilityAnswerReviewAdmin(InspectOnlyAdmin):
    fields = ("project", "job", "actor", "revision", "method_version", "answer_sha256", "evaluated", "created_at")
    list_display = ("id", "project_id", "job_id", "revision", "evaluated", "created_at")
    search_fields = ("=project__id", "=job__id")


@admin.register(AIVisibilityPromptSet)
class AIVisibilityPromptSetAdmin(InspectOnlyAdmin):
    fields = ("project", "actor", "set_id", "revision", "label", "market", "language", "created_at")
    list_display = ("id", "project_id", "set_id", "revision", "label", "language", "created_at")
    search_fields = ("=project__id", "=set_id")

from .models import (
    AIUsageRecord, Artifact, ContentBriefSnapshot, ContentItem, ContentRevision, CrawlPageSnapshot, CrawlRun, Finding, IndexationEvidenceSnapshot, JobCancellation, JobRun, JobSchedule,
    JobStep, Opportunity, PerformanceObservationSnapshot, Recommendation, RenderAttempt, RenderedPageSnapshot, SourceCitation, TechnicalDiagnosticsSnapshot, TopicCandidateSnapshot,
    UsageReservation, TopicReview,
)


@admin.register(JobSchedule)
class JobScheduleAdmin(InspectOnlyAdmin):
    fields = ("organization", "project", "actor", "handler", "enabled", "interval_minutes", "next_run_at",
              "last_run_at", "skipped_occurrences", "last_error_category", "created_at")
    list_display = ("id", "organization_id", "project_id", "enabled", "next_run_at", "last_error_category")
    list_filter = ("enabled", "last_error_category")
    search_fields = ("=id", "=organization__id", "=project__id")


@admin.register(JobStep)
class JobStepAdmin(InspectOnlyAdmin):
    # Step permission authorizes only the combined audited exact-job form.
    def get_queryset(self, request):
        return super().get_queryset(request).none()

    def has_view_permission(self, request, obj=None):
        return False

    def has_module_permission(self, request):
        return False


@admin.register(Artifact)
class ArtifactAdmin(InspectOnlyAdmin):
    list_display = ("id", "job_id", "project_id", "content_type", "size_bytes", "created_at")
    search_fields = ("=job__id", "=project__id")
    fields = ("job", "project", "content_type", "size_bytes", "created_at")


@admin.register(SourceCitation)
class SourceCitationAdmin(InspectOnlyAdmin):
    list_display = ("id", "job_id", "step_id", "source_title", "observed_at")
    search_fields = ("=job__id", "=step__id", "source_title")
    fields = ("job", "step", "source_title", "observed_at", "created_at")


@admin.register(ContentBriefSnapshot)
class ContentBriefSnapshotAdmin(InspectOnlyAdmin):
    list_display = ("id", "project_id", "research_job_id", "action_review_id", "size_bytes", "created_at")
    search_fields = ("=id", "=project__id", "=research_job__id")
    fields = ("project", "research_job", "action_review", "actor", "size_bytes", "created_at")


@admin.register(ContentItem)
class ContentItemAdmin(InspectOnlyAdmin):
    fields = ("project", "actor", "created_at")
    list_display = ("id", "project_id", "actor_id", "created_at")
    search_fields = ("=id", "=project__id")


@admin.register(TopicReview)
class TopicReviewAdmin(InspectOnlyAdmin):
    fields = ("project", "snapshot", "candidate_index", "intent_cluster", "actor", "revision", "classification", "language", "market", "method_version", "created_at")
    list_display = ("id", "project_id", "snapshot_id", "candidate_index", "revision", "classification", "created_at")
    list_filter = ("classification", "language")
    search_fields = ("=project__id", "=snapshot__id")


@admin.register(ContentRevision)
class ContentRevisionAdmin(InspectOnlyAdmin):
    fields = ("project", "item", "brief", "actor", "generating_job", "revision", "state", "kind",
              "reviewed_revision", "approved_by", "approved_at", "publication_url", "published_at", "created_at")
    list_display = ("id", "project_id", "item_id", "revision", "state", "kind", "created_at")
    list_filter = ("state", "kind")
    search_fields = ("=item__id", "=project__id")


@admin.register(CrawlRun)
class CrawlRunAdmin(InspectOnlyAdmin):
    list_display = ("id", "organization_id", "project_id", "job_id", "pages_attempted", "pages_observed", "completed_at")
    search_fields = ("=organization__id", "=project__id", "=job__id")
    fields = ("job", "organization", "project", "page_limit", "pages_attempted", "pages_observed",
              "robots_status", "started_at", "completed_at")


@admin.register(CrawlPageSnapshot)
class CrawlPageSnapshotAdmin(InspectOnlyAdmin):
    list_display = ("id", "project_id", "crawl_run_id", "status_code", "error_category", "observed_at")
    search_fields = ("=project__id", "=crawl_run__id", "requested_url", "final_url")
    fields = ("crawl_run", "project", "requested_url", "final_url", "status_code", "content_hash",
              "raw_artifact", "reused_from", "error_category", "observed_at")


@admin.register(RenderAttempt)
class RenderAttemptAdmin(InspectOnlyAdmin):
    list_display = ("id", "project_id", "crawl_page_id", "status", "error_category", "created_at")
    list_filter = ("status", "error_category")
    search_fields = ("=id", "=project__id", "=crawl_page__id", "=request_id")
    fields = ("project", "crawl_page", "request_id", "source_hash", "method_version", "status",
              "error_category", "created_at", "completed_at")


@admin.register(RenderedPageSnapshot)
class RenderedPageSnapshotAdmin(InspectOnlyAdmin):
    list_display = ("id", "project_id", "crawl_page_id", "duration_ms", "method_version", "observed_at")
    search_fields = ("=id", "=project__id", "=crawl_page__id", "=attempt__id")
    fields = ("attempt", "project", "crawl_page", "rendered_artifact", "content_hash", "text_hash",
              "duration_ms", "method_version", "observed_at")


@admin.register(TechnicalDiagnosticsSnapshot)
class TechnicalDiagnosticsSnapshotAdmin(InspectOnlyAdmin):
    list_display = ("id", "project_id", "crawl_run_id", "method_version", "ruleset_version", "observed_at")
    search_fields = ("=id", "=project__id", "=crawl_run__id")
    fields = ("crawl_run", "project", "input_hash", "method_version", "ruleset_version", "observed_at")


@admin.register(IndexationEvidenceSnapshot)
class IndexationEvidenceSnapshotAdmin(InspectOnlyAdmin):
    list_display = ("id", "project_id", "crawl_run_id", "method_version", "observed_at")
    search_fields = ("=id", "=project__id", "=crawl_run__id")
    fields = ("crawl_run", "project", "diagnostics", "input_hash", "method_version", "observed_at")


@admin.register(TopicCandidateSnapshot)
class TopicCandidateSnapshotAdmin(InspectOnlyAdmin):
    list_display = ("id", "project_id", "job_id", "method_version", "created_at")
    search_fields = ("=id", "=project__id", "=job__id")
    fields = ("project", "job", "method_version", "created_at")


@admin.register(PerformanceObservationSnapshot)
class PerformanceObservationSnapshotAdmin(InspectOnlyAdmin):
    list_display = ("id", "project_id", "job_id", "source", "strategy", "grain", "collected_at")
    list_filter = ("source", "strategy", "grain")
    search_fields = ("=id", "=project__id", "=job__id")
    fields = ("project", "job", "source", "strategy", "grain", "collected_at")


@admin.register(UsageReservation)
class UsageReservationAdmin(InspectOnlyAdmin):
    # Reservation permission authorizes only the separate exact-job history action.
    def get_queryset(self, request):
        return super().get_queryset(request).none()

    def has_view_permission(self, request, obj=None):
        return False

    def has_module_permission(self, request):
        return False


@admin.register(AIUsageRecord)
class AIUsageRecordAdmin(InspectOnlyAdmin):
    # AI observation permission authorizes only the separate audited exact-job action.
    def get_queryset(self, request):
        return super().get_queryset(request).none()

    def has_view_permission(self, request, obj=None):
        return False

    def has_module_permission(self, request):
        return False


@admin.register(JobCancellation)
class JobCancellationAdmin(InspectOnlyAdmin):
    list_display = ("id", "job_id", "requested_by_id", "requested_at")
    search_fields = ("=job__id", "=job__project__id")


@admin.register(Finding)
class FindingAdmin(InspectOnlyAdmin):
    list_display = ("id", "project_id", "detector", "method_version", "detected_at")
    search_fields = ("=id", "=project__id", "=source_metric__id")
    fields = ("project", "actor", "source_metric", "source_api_page", "source_diagnostics",
              "source_indexation", "source_performance", "detector", "method_version", "confidence", "detected_at")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(source_passive_header__isnull=True, source_passive_resource__isnull=True,
            source_passive_tls__isnull=True, source_passive_redirect__isnull=True, source_passive_redirect_chain__isnull=True)


@admin.register(Opportunity)
class OpportunityAdmin(InspectOnlyAdmin):
    list_display = ("id", "project_id", "finding_id", "revision", "priority", "created_at")
    search_fields = ("=id", "=project__id", "=finding__id")
    fields = ("project", "finding", "actor", "revision", "priority", "estimated_effort",
              "business_relevance", "review_reason", "created_at")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(finding__source_passive_header__isnull=True, finding__source_passive_resource__isnull=True,
            finding__source_passive_tls__isnull=True, finding__source_passive_redirect__isnull=True,
            finding__source_passive_redirect_chain__isnull=True)


@admin.register(Recommendation)
class RecommendationAdmin(InspectOnlyAdmin):
    list_display = ("id", "project_id", "opportunity_id", "revision", "created_at")
    search_fields = ("=id", "=project__id", "=opportunity__id")
    fields = ("project", "opportunity", "actor", "revision", "created_at")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(opportunity__finding__source_passive_header__isnull=True,
            opportunity__finding__source_passive_resource__isnull=True, opportunity__finding__source_passive_tls__isnull=True,
            opportunity__finding__source_passive_redirect__isnull=True, opportunity__finding__source_passive_redirect_chain__isnull=True)
