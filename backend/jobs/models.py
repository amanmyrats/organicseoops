import hashlib
import json
from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import RegexValidator, URLValidator
from django.db import models
from django.db.models import Q

from tenancy.artifacts import project_artifact_scope
from tenancy.models import Organization, Project
from providers.models import AIModel, AIProvider, AIProviderAccount


class JobStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    WAITING_PROVIDER = "waiting_provider", "Waiting for provider"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    PARTIALLY_SUCCEEDED = "partially_succeeded", "Partially succeeded"


LEGAL_TRANSITIONS = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RUNNING: {JobStatus.WAITING_PROVIDER, JobStatus.SUCCEEDED, JobStatus.FAILED,
                        JobStatus.CANCELLED, JobStatus.PARTIALLY_SUCCEEDED},
    JobStatus.WAITING_PROVIDER: {JobStatus.RUNNING, JobStatus.FAILED, JobStatus.CANCELLED},
}


class JobRun(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="jobs")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="jobs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="started_jobs")
    retry_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="retries")
    schedule = models.ForeignKey("JobSchedule", null=True, blank=True, on_delete=models.PROTECT, related_name="runs")
    scheduled_for = models.DateTimeField(null=True, blank=True)
    handler = models.CharField(max_length=64)
    idempotency_key = models.CharField(
        max_length=64, blank=True, validators=[RegexValidator(r"^[A-Za-z0-9._-]+$", "Invalid idempotency key.")],
    )
    status = models.CharField(max_length=24, choices=JobStatus.choices, default=JobStatus.QUEUED)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    dispatch_error = models.CharField(max_length=32, blank=True)
    input_snapshot = models.JSONField(default=dict)
    config_snapshot = models.JSONField(default=dict, blank=True)
    method_version = models.CharField(max_length=40)
    output = models.JSONField(default=dict, blank=True)
    error_category = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(status__in=JobStatus.values), name="jobs_run_status_valid"),
            models.UniqueConstraint(
                fields=["project", "handler", "idempotency_key"], condition=~Q(idempotency_key=""),
                name="jobs_unique_project_handler_request",
            ),
            models.UniqueConstraint(fields=["schedule", "scheduled_for"], condition=Q(schedule__isnull=False),
                                    name="jobs_unique_schedule_occurrence"),
            models.CheckConstraint(condition=Q(schedule__isnull=True, scheduled_for__isnull=True)
                                   | Q(schedule__isnull=False, scheduled_for__isnull=False),
                                   name="jobs_run_schedule_date_match"),
        ]
        ordering = ["-created_at", "-id"]

    def clean(self):
        if self.handler in {"classify_competitor_heading_topics", "synthesize_competitor_pair", "synthesize_competitor_headings_pair"}:
            from .competitor_synthesis_job import _contract
            _contract(self.handler).validate_job(self, current=self._state.adding)
        if self.handler in {"collect_competitor_root", "collect_competitor_schema_root", "collect_competitor_links_root", "collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats", "collect_competitor_lighthouse"}:
            from .competitor_collection import validate_job
            validate_job(self, current=self._state.adding)
        if self.handler in {"collect_passive_headers", "collect_passive_tls", "collect_passive_resources", "collect_passive_redirects", "collect_passive_http_redirects", "collect_passive_redirect_chain"}:
            from .passive_header_collection import validate_job
            validate_job(self, current=self._state.adding)
        if self.handler == "verify_authority_link_source":
            from .authority_link_collection import validate_job
            validate_job(self, current=self._state.adding)
        if self.handler == "business_profile_request":
            from integrations.business_profile_read import validate_business_job
            validate_business_job(self, current=self._state.adding)
        if self.handler == "analyze_repository":
            from .repository_analysis import validate_job
            validate_job(self, current=self._state.adding)
        if self.handler == "collect_serp":
            from .serp import validate_job
            validate_job(self, current=self._state.adding)
        if self.handler == "sync_yandex_webmaster":
            from integrations.yandex_sync import validate_job
            validate_job(self, current=self._state.adding)
        if self.handler == "import_yandex_webmaster_csv":
            from integrations.yandex_webmaster import validate_job
            validate_job(self, current=self._state.adding)
        if self.handler == "import_bot_logs":
            from .bot_log_import import validate_job
            validate_job(self, current=self._state.adding)
        if self.handler == "search_youtube" and self.output:
            raise ValidationError("YouTube API data must remain response-only.")
        if self.handler == "sample_ai_visibility":
            from .visibility_schedule import validate_scheduled_job
            validate_scheduled_job(self, current=self._state.adding)
        if self.organization_id and self.project_id and self.project.organization_id != self.organization_id:
            raise ValidationError("Job project must belong to its organization.")
        if self.retry_of_id and (self.retry_of_id == self.pk or self.retry_of.project_id != self.project_id):
            raise ValidationError("Retry must stay within its source project's scope.")
        if self.schedule_id and self.schedule.project_id != self.project_id:
            raise ValidationError("Scheduled runs must stay in their schedule's project.")
        if self._state.adding and self.project_id and self.actor_id:
            from tenancy.services import Action, require_project_action
            try:
                action = (Action.MANAGE_PROJECT if self.handler in {"classify_competitor_heading_topics", "synthesize_competitor_pair", "synthesize_competitor_headings_pair", "collect_competitor_root", "collect_competitor_schema_root", "collect_competitor_links_root", "collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats", "collect_competitor_lighthouse", "collect_passive_headers", "collect_passive_tls", "collect_passive_resources", "collect_passive_redirects", "collect_passive_http_redirects", "collect_passive_redirect_chain", "verify_authority_link_source", "business_profile_request", "import_bot_logs", "import_yandex_webmaster_csv", "sync_yandex_webmaster", "collect_serp", "analyze_repository", "verify_project_origin", "collect_search_console_coverage", "sync_ga4_landing"}
                          else Action.LAUNCH_JOB)
                require_project_action(project=self.project, user=self.actor, action=action)
            except PermissionDenied:
                raise ValidationError("The job actor cannot launch work for this project.") from None

    def save(self, *args, **kwargs):
        if self._state.adding:
            if self.status != JobStatus.QUEUED:
                raise ValidationError("Jobs must start queued.")
        else:
            previous = JobRun.objects.get(pk=self.pk)
            if (self.handler in {"classify_competitor_heading_topics", "synthesize_competitor_pair", "synthesize_competitor_headings_pair", "collect_competitor_root", "collect_competitor_schema_root", "collect_competitor_links_root", "collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats", "collect_competitor_lighthouse", "collect_passive_headers", "collect_passive_tls", "collect_passive_resources", "collect_passive_redirects", "collect_passive_http_redirects", "collect_passive_redirect_chain", "verify_authority_link_source", "sample_ai_visibility", "import_bot_logs", "import_yandex_webmaster_csv", "sync_yandex_webmaster", "collect_serp", "analyze_repository"} and previous.status not in LEGAL_TRANSITIONS
                and (self.output != previous.output or self.error_category != previous.error_category)):
                raise ValidationError("Final visibility answer evidence and collection status are immutable.")
            if any(getattr(self, field) != getattr(previous, field) for field in (
                "organization_id", "project_id", "actor_id", "handler", "idempotency_key", "retry_of_id",
                "schedule_id", "scheduled_for",
                "input_snapshot", "config_snapshot", "method_version",
            )):
                raise ValidationError("Job scope and snapshots cannot change after creation.")
            if self.status != previous.status and self.status not in LEGAL_TRANSITIONS.get(previous.status, set()):
                raise ValidationError("Invalid job status transition.")
        self.full_clean()
        return super().save(*args, **kwargs)


class JobStep(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    job = models.ForeignKey(JobRun, on_delete=models.PROTECT, related_name="steps")
    sequence = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=80)
    status = models.CharField(max_length=16, choices=Status.choices)
    progress_percent = models.PositiveSmallIntegerField(default=0)
    output = models.JSONField(default=dict, blank=True)
    error_category = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.job_id and self.job.handler in {"classify_competitor_heading_topics", "synthesize_competitor_pair", "synthesize_competitor_headings_pair"}:
            from .competitor_synthesis_job import _contract
            contract = _contract(self.job.handler)
            if (self.sequence != 1 or self.name != contract.STAGE or self.progress_percent not in {0, 100}
                or self.output not in [{"method": contract.METHOD, "state": state} for state in ("attempted", contract.STATE, "unavailable")]):
                raise ValidationError("Synthesis attempts retain categorical state only.")
            if self.pk and JobStep.objects.get(pk=self.pk).status != self.Status.RUNNING:
                raise ValidationError("Terminal synthesis attempt state is immutable.")
        if self.job_id and self.job.handler in {"collect_competitor_root", "collect_competitor_schema_root", "collect_competitor_links_root", "collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats", "collect_competitor_lighthouse"}:
            from .competitor_collection import _collection_contract
            method, stage, *_ = _collection_contract(self.job.handler)
            if (self.sequence != 1 or self.name != stage or self.progress_percent not in {0, 100}
                or self.output not in [{"method": method, "state": state} for state in ("attempted", "collected", "unavailable")]):
                raise ValidationError("Competitor attempts retain categorical state only.")
            if self.pk and JobStep.objects.get(pk=self.pk).status != self.Status.RUNNING:
                raise ValidationError("Terminal competitor attempt state is immutable.")
        if self.job_id and self.job.handler in {"collect_passive_headers", "collect_passive_tls", "collect_passive_resources", "collect_passive_redirects", "collect_passive_http_redirects", "collect_passive_redirect_chain"}:
            from .passive_header_collection import _collection_contract
            method, stage, *_ = _collection_contract(self.job.handler)
            if (self.sequence != 1 or self.name != stage or self.progress_percent not in {0, 100}
                or self.output not in [{"method": method, "state": state} for state in ("attempted", "collected", "unavailable")]):
                raise ValidationError("Header attempts retain categorical state only.")
            if self.pk and JobStep.objects.get(pk=self.pk).status != self.Status.RUNNING:
                raise ValidationError("Terminal header attempt state is immutable.")
        if self.job_id and self.job.handler == "verify_authority_link_source":
            from .authority_link_collection import STAGE, validate_job
            validate_job(self.job)
            if (self.sequence != 1 or self.name != STAGE or self.progress_percent not in {0, 100}
                or self.output not in [{"method": self.job.method_version, "state": state}
                                      for state in ("attempted", "collected", "unavailable")]):
                raise ValidationError("Static-link steps retain categorical attempt state only.")
            if self.pk and JobStep.objects.get(pk=self.pk).status != self.Status.RUNNING:
                raise ValidationError("Final static-link attempt state is immutable.")
        if self.job_id and self.job.handler == "business_profile_request":
            from integrations.business_profile_read import STAGES
            stages = STAGES[self.job.input_snapshot["operation"]]
            if (not 1 <= self.sequence <= len(stages) or self.name != stages[self.sequence - 1]
                or self.output or self.error_category or self.progress_percent or self.status != self.Status.RUNNING):
                raise ValidationError("Business Profile steps retain only categorical attempted requests.")
        if self.job_id and self.job.handler == "import_bot_logs":
            if (self.sequence != 1 or self.name != "Finalize minimized bot-log evidence"
                or self.output != {"method": "bot-log-jsonl-v1"} or self.error_category
                or self.status != self.Status.SUCCEEDED or self.progress_percent != 100):
                raise ValidationError("Bot-log steps contain categorical processing state only.")
        return super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "sequence"], name="jobs_unique_step_sequence"),
            models.CheckConstraint(condition=Q(progress_percent__lte=100), name="jobs_step_progress_valid"),
            models.CheckConstraint(condition=Q(status__in=["running", "succeeded", "failed"]), name="jobs_step_status_valid"),
        ]
        ordering = ["sequence", "id"]


class JobCancellation(models.Model):
    job = models.OneToOneField(JobRun, on_delete=models.PROTECT, related_name="cancellation")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="job_cancellations")
    requested_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.job_id and self.requested_by_id and self._state.adding:
            from tenancy.services import Action, require_project_action
            try:
                action = (Action.MANAGE_PROJECT if self.job.handler in {"classify_competitor_heading_topics", "synthesize_competitor_pair", "synthesize_competitor_headings_pair", "collect_competitor_root", "collect_competitor_schema_root", "collect_competitor_links_root", "collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats", "collect_competitor_lighthouse", "collect_passive_headers", "collect_passive_tls", "collect_passive_resources", "collect_passive_redirects", "collect_passive_http_redirects", "collect_passive_redirect_chain", "verify_authority_link_source", "business_profile_request", "import_bot_logs", "import_yandex_webmaster_csv", "sync_yandex_webmaster", "collect_serp", "analyze_repository", "verify_project_origin", "collect_search_console_coverage", "sync_ga4_landing"}
                          else Action.LAUNCH_JOB)
                require_project_action(project=self.job.project, user=self.requested_by, action=action)
            except PermissionDenied:
                raise ValidationError("Actor cannot cancel this job.") from None

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class UsageReservation(models.Model):
    class State(models.TextChoices):
        RESERVED = "reserved", "Reserved"
        SETTLED = "settled", "Settled"
        RELEASED = "released", "Released"

    job = models.OneToOneField(JobRun, on_delete=models.PROTECT, related_name="usage")
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="job_usage")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="job_usage")
    provider = models.CharField(max_length=64, validators=[RegexValidator(r"^[a-z][a-z0-9_-]*$", "Invalid provider key.")])
    period_start = models.DateField()
    reserved_units = models.PositiveIntegerField()
    actual_units = models.PositiveIntegerField(default=0)
    state = models.CharField(max_length=16, choices=State.choices, default=State.RESERVED)
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(state__in=["reserved", "settled", "released"]), name="jobs_usage_state_valid"),
            models.CheckConstraint(condition=(
                Q(state="reserved", settled_at__isnull=True, actual_units=0)
                | Q(state="settled", settled_at__isnull=False, actual_units__gt=0)
                | Q(state="released", settled_at__isnull=False, actual_units=0)
            ), name="jobs_usage_settlement_valid"),
        ]

    def clean(self):
        if self.job_id and (self.job.organization_id != self.organization_id or self.job.project_id != self.project_id):
            raise ValidationError("Usage must stay within its job's organization and project.")
        if self.period_start and self.period_start.day != 1:
            raise ValidationError("Usage period must start on the first day of a month.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class AIUsageRecord(models.Model):
    class Status(models.TextChoices):
        ATTEMPTED = "attempted", "Request outcome pending"
        COMPLETED = "completed", "Provider completed"
        FAILED = "failed", "Provider returned an error"
        UNKNOWN = "unknown", "Provider outcome unknown"

    job = models.OneToOneField(JobRun, on_delete=models.PROTECT, related_name="ai_usage_record")
    step = models.OneToOneField(JobStep, on_delete=models.PROTECT, related_name="ai_usage_record")
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="ai_usage_records")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="ai_usage_records")
    provider = models.ForeignKey(AIProvider, on_delete=models.PROTECT, related_name="usage_records")
    model = models.ForeignKey(AIModel, on_delete=models.PROTECT, related_name="usage_records")
    account = models.ForeignKey(AIProviderAccount, on_delete=models.PROTECT, related_name="usage_records")
    operation_version = models.CharField(max_length=40)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ATTEMPTED)
    error_category = models.CharField(max_length=64, blank=True)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    provider_request_id = models.CharField(max_length=128, blank=True)
    provider_response_id = models.CharField(max_length=128, blank=True)
    estimated_cost_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    reported_cost_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    web_search_used = models.BooleanField(default=False)
    tool_call_count = models.PositiveSmallIntegerField(default=0)
    attempted_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(status__in=["attempted", "completed", "failed", "unknown"]),
                                   name="jobs_ai_usage_status_valid"),
            models.CheckConstraint(condition=Q(status="attempted", finished_at__isnull=True)
                                   | Q(status__in=["completed", "failed", "unknown"], finished_at__isnull=False),
                                   name="jobs_ai_usage_final_timestamp"),
            models.CheckConstraint(condition=Q(input_tokens__isnull=True) | Q(input_tokens__lte=100_000_000),
                                   name="jobs_ai_usage_input_tokens_bounded"),
            models.CheckConstraint(condition=Q(output_tokens__isnull=True) | Q(output_tokens__lte=100_000_000),
                                   name="jobs_ai_usage_output_tokens_bounded"),
            models.CheckConstraint(condition=Q(duration_ms__isnull=True) | Q(duration_ms__lte=120_000),
                                   name="jobs_ai_usage_duration_bounded"),
            models.CheckConstraint(condition=Q(estimated_cost_usd__isnull=True) | Q(estimated_cost_usd__gte=0),
                                   name="jobs_ai_usage_estimated_cost_valid"),
            models.CheckConstraint(condition=Q(reported_cost_usd__isnull=True) | Q(reported_cost_usd__gte=0),
                                   name="jobs_ai_usage_reported_cost_valid"),
        ]

    def clean(self):
        if self.job_id and self.step_id and (self.job.handler not in {"classify_competitor_heading_topics", "synthesize_competitor_pair", "synthesize_competitor_headings_pair", "ai_text", "research_topic", "generate_content", "sample_ai_visibility"} or self.step.job_id != self.job_id
                                             or self.step.sequence != 1):
            raise ValidationError("AI usage must refer to its attempted AI job step.")
        if self.job_id and (self.organization_id != self.job.organization_id or self.project_id != self.job.project_id
                            or self.operation_version != self.job.method_version):
            raise ValidationError("AI usage must remain inside the job's scope and operation version.")
        if self.model_id and self.provider_id and self.model.provider_id != self.provider_id:
            raise ValidationError("AI usage model must belong to the recorded provider.")
        if self.account_id and self.provider_id and (self.account.provider_id != self.provider_id
                                                      or self.account.organization_id not in (None, self.organization_id)):
            raise ValidationError("AI usage account must belong to the provider and owning organization.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = AIUsageRecord.objects.get(pk=self.pk)
            if any(getattr(self, field) != getattr(previous, field) for field in (
                "job_id", "step_id", "organization_id", "project_id", "provider_id", "model_id", "account_id",
                "operation_version", "web_search_used", "tool_call_count",
            )) or previous.status != self.Status.ATTEMPTED:
                raise ValidationError("AI usage ownership and settled observations cannot change.")
        self.full_clean()
        return super().save(*args, **kwargs)


class Artifact(models.Model):
    job = models.ForeignKey(JobRun, on_delete=models.PROTECT, related_name="artifacts")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="job_artifacts")
    key = models.CharField(max_length=512, unique=True)
    content_type = models.CharField(max_length=64)
    size_bytes = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.job_id and self.job.handler in {"classify_competitor_heading_topics", "synthesize_competitor_pair", "synthesize_competitor_headings_pair"}:
            from .competitor_synthesis_job import MAX_RESULT_BYTES
            if self.content_type != "application/json" or not 1 <= self.size_bytes <= MAX_RESULT_BYTES:
                raise ValidationError("Synthesis retains bounded private original facts and unverified notes only.")
        if self.job_id and self.job.handler in {"collect_competitor_root", "collect_competitor_schema_root", "collect_competitor_links_root", "collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats", "collect_competitor_lighthouse"}:
            from .competitor_collection import MAX_RESULT_BYTES
            if self.content_type != "application/json" or not 1 <= self.size_bytes <= MAX_RESULT_BYTES:
                raise ValidationError("Competitor evidence retains bounded minimized private JSON only.")
        if self.job_id and self.job.handler in {"collect_passive_headers", "collect_passive_tls", "collect_passive_resources", "collect_passive_redirects", "collect_passive_http_redirects", "collect_passive_redirect_chain"}:
            from .passive_header_collection import result_byte_limit
            if self.content_type != "application/json" or not 1 <= self.size_bytes <= result_byte_limit(self.job.handler):
                raise ValidationError("Header evidence retains only bounded minimized private JSON.")
        if self.job_id and self.job.handler == "verify_authority_link_source":
            from .authority_link_sources import MAX_RESULT_BYTES
            if self.content_type != "application/json" or not 1 <= self.size_bytes <= MAX_RESULT_BYTES:
                raise ValidationError("Static-link sources retain only bounded minimized private JSON.")
        if self.job_id and self.job.handler == "business_profile_request":
            raise ValidationError("Business Profile requests cannot store response artifacts.")
        if self.job_id and self.project_id:
            if self.job.project_id != self.project_id or self.job.organization_id != self.project.organization_id:
                raise ValidationError("Artifact must stay within its job's project.")
            if not self.key.startswith(project_artifact_scope(self.project) + "/"):
                raise ValidationError("Artifact key must stay within its project namespace.")
        if self.key:
            from config.artifacts import ArtifactValidationError, _validate_key
            try:
                _validate_key(self.key)
            except ArtifactValidationError:
                raise ValidationError("Invalid artifact key.") from None
        if self.content_type and self.content_type not in settings.ARTIFACT_ALLOWED_CONTENT_TYPES:
            raise ValidationError("Artifact type is not supported.")
        if self.key and self.content_type and self.key.rsplit(".", 1)[-1] != {
            "application/json": "json", "text/csv": "csv", "text/html": "html", "text/plain": "txt",
        }.get(self.content_type):
            raise ValidationError("Artifact type does not match its key.")
        if self.size_bytes is not None and not 0 < self.size_bytes <= settings.ARTIFACT_MAX_BYTES:
            raise ValidationError("Artifact exceeds the configured size limit.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = Artifact.objects.get(pk=self.pk)
            if any(getattr(self, field) != getattr(previous, field) for field in (
                "job_id", "project_id", "key", "content_type", "size_bytes",
            )):
                raise ValidationError("Artifact scope and storage metadata are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class SourceCitation(models.Model):
    job = models.ForeignKey(JobRun, on_delete=models.PROTECT, related_name="citations")
    step = models.ForeignKey(JobStep, on_delete=models.PROTECT, related_name="citations")
    source_title = models.CharField(max_length=240)
    source_url = models.URLField(max_length=1024, blank=True)
    observed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.job_id and self.job.handler == "business_profile_request":
            raise ValidationError("Business Profile requests cannot store returned citations.")
        if self.job_id and self.step_id and self.step.job_id != self.job_id:
            raise ValidationError("Citation step must belong to the same job.")
        if self.source_url:
            URLValidator(schemes=["http", "https"])(self.source_url)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ContentBriefSnapshot(models.Model):
    """Immutable private draft linked to exact research and human-action revisions."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="content_briefs")
    research_job = models.ForeignKey(JobRun, on_delete=models.PROTECT, related_name="content_briefs")
    action_review = models.ForeignKey("ActionReview", on_delete=models.PROTECT, related_name="content_briefs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=64)
    artifact_key = models.CharField(max_length=512, editable=False)
    content_sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "request_key"], name="jobs_unique_content_brief_request"),
                       models.CheckConstraint(condition=Q(content_sha256__regex=r"^[0-9a-f]{64}$", size_bytes__gt=0),
                                              name="jobs_content_brief_integrity_valid")]

    def clean(self):
        if (self.project_id and self.research_job_id and self.action_review_id and
            (self.research_job.project_id != self.project_id or self.action_review.project_id != self.project_id
             or self.research_job.handler != "research_topic")):
            raise ValidationError("Brief sources must belong to one project and research handler.")
        if self.artifact_key and not self.artifact_key.startswith(project_artifact_scope(self.project) + "/"):
            raise ValidationError("Brief storage must stay in its project namespace.")
        if not self.content_sha256 or self.size_bytes > settings.ARTIFACT_MAX_BYTES:
            raise ValidationError("Brief integrity is unavailable.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Content brief snapshots are immutable; create a new reviewed revision.")
        self.full_clean()
        return super().save(*args, **kwargs)


class ContentItem(models.Model):
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="content_items")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "request_key"], name="jobs_unique_content_item_request")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Content identity is immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class ContentRevision(models.Model):
    """Append-only text and lifecycle history; publication is a human report only."""

    class State(models.TextChoices):
        IDEA = "idea", "Idea"
        RESEARCH = "research", "Research"
        BRIEF = "brief", "Brief"
        DRAFT = "draft", "Unapproved draft"
        REVIEW = "review", "Human review required"
        APPROVED = "approved", "Human approved"
        PUBLISHED = "published", "Publication reported manually, not verified"
        ARCHIVED = "archived", "Archived record, no live page removed"

    class Kind(models.TextChoices):
        BLOG = "blog", "Blog article"
        REFRESH = "refresh", "Existing article refresh"
        LANDING = "landing", "Landing page"
        SERVICE = "service", "Service page"
        SOCIAL = "social", "Social post"
        SOCIAL_SERIES = "social_series", "Social post series"
        NEWSLETTER = "newsletter", "Newsletter"
        DESCRIPTION = "description", "Product or service description"
        CUSTOM = "custom", "Custom content"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="content_revisions")
    item = models.ForeignKey(ContentItem, on_delete=models.PROTECT, related_name="revisions")
    brief = models.ForeignKey(ContentBriefSnapshot, on_delete=models.PROTECT, related_name="content_revisions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="content_revisions")
    generating_job = models.ForeignKey(JobRun, null=True, blank=True, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    revision = models.PositiveIntegerField()
    state = models.CharField(max_length=16, choices=State.choices)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    title = models.CharField(max_length=240)
    body = models.TextField(max_length=30000, blank=True)
    meta_description = models.CharField(max_length=320, blank=True)
    reason = models.CharField(max_length=500)
    reviewed_revision = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="approvals")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.PROTECT, related_name="content_approvals")
    approved_at = models.DateTimeField(null=True, blank=True)
    publication_url = models.URLField(max_length=512, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["item", "revision"], name="jobs_unique_content_revision"),
            models.UniqueConstraint(fields=["project", "request_key"], name="jobs_unique_content_revision_request"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_content_revision_positive"),
            models.CheckConstraint(condition=Q(state__in=["idea", "research", "brief", "draft", "review", "approved", "published", "archived"]), name="jobs_content_state_valid"),
            models.CheckConstraint(condition=Q(kind__in=["blog", "refresh", "landing", "service", "social", "social_series", "newsletter", "description", "custom"]), name="jobs_content_kind_valid"),
            models.CheckConstraint(condition=Q(reviewed_revision__isnull=True, approved_by__isnull=True, approved_at__isnull=True)
                                   | Q(reviewed_revision__isnull=False, approved_by__isnull=False, approved_at__isnull=False), name="jobs_content_approval_complete"),
            models.CheckConstraint(condition=~Q(state__in=["approved", "published"]) | Q(reviewed_revision__isnull=False), name="jobs_content_approved_reference"),
            models.CheckConstraint(condition=Q(publication_url="", published_at__isnull=True)
                                   | (~Q(publication_url="") & Q(published_at__isnull=False)), name="jobs_content_publication_complete"),
        ]

    def clean(self):
        if (self.item.project_id != self.project_id or self.brief.project_id != self.project_id
            or self.generating_job_id and self.generating_job.project_id != self.project_id):
            raise ValidationError("Content and every source must stay within one project.")
        if not self.title.strip() or not self.reason.strip() or len(self.body.encode()) > 120000:
            raise ValidationError("Choose bounded native text and a human rationale.")
        if self.state in {"review", "approved", "published"} and not self.body.strip():
            raise ValidationError("Review requires an actual draft.")
        if self.reviewed_revision_id:
            reviewed = self.reviewed_revision
            if (reviewed.item_id != self.item_id or reviewed.project_id != self.project_id
                or reviewed.state != "review" or reviewed.revision >= self.revision
                or any(getattr(reviewed, name) != getattr(self, name)
                       for name in ("brief_id", "kind", "title", "body", "meta_description", "generating_job_id"))):
                raise ValidationError("Approval must bind the exact reviewed text and provenance.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Content changes require a new immutable revision.")
        self.full_clean()
        return super().save(*args, **kwargs)


class ContentLifecycleReview(models.Model):
    """Immutable human quality/proposal history; approval never changes a live page."""
    class State(models.TextChoices):
        DRAFT = "draft", "Unapproved human judgment"
        REVIEW = "review", "Human review required"
        APPROVED = "approved", "Exact judgment and proposal approved, not site work"
        REPORTED = "reported", "Manual review handoff reported, not site implementation"
        DISMISSED = "dismissed", "Human proposal dismissed"

    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    content_revision = models.ForeignKey(ContentRevision, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="content_lifecycle_reviews")
    source_actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="content_lifecycle_sources")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="content_lifecycle_assignments")
    review_id = models.UUIDField(default=uuid4)
    revision = models.PositiveIntegerField()
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    state = models.CharField(max_length=9, choices=State.choices)
    source_evidence = models.JSONField()
    intake = models.JSONField()
    reason = models.CharField(max_length=500)
    reviewed_revision = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="approvals")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="content_lifecycle_approvals")
    approved_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    execution_note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "review_id", "revision"], name="jobs_quality_revision_unique"),
            models.UniqueConstraint(fields=["project", "request_key"], name="jobs_quality_request_unique"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_quality_revision_positive"),
            models.CheckConstraint(condition=Q(state__in=["draft", "review", "approved", "reported", "dismissed"]), name="jobs_quality_state_valid"),
            models.CheckConstraint(condition=Q(state__in=["draft", "review", "dismissed"], reviewed_revision__isnull=True,
                approved_by__isnull=True, approved_at__isnull=True) | Q(state__in=["approved", "reported"],
                reviewed_revision__isnull=False, approved_by__isnull=False, approved_at__isnull=False), name="jobs_quality_exact_approval"),
            models.CheckConstraint(condition=(Q(state="reported", executed_at__isnull=False) & ~Q(execution_note=""))
                | (~Q(state="reported") & Q(executed_at__isnull=True, execution_note="")), name="jobs_quality_manual_handoff"),
        ]

    def clean(self):
        from django.utils import timezone
        from .content_lifecycle import TRANSITIONS, require_current_lifecycle_review, validate_content_lifecycle_intake
        from .local_feedback import _text
        validate_content_lifecycle_intake(self.intake, project=self.project, revision=self.content_revision, evidence=self.source_evidence)
        _text(self.reason, 500, required=True)
        _text(self.execution_note, 500, required=self.state == "reported")
        if self.state in {"review", "approved", "reported"} and self.intake["proposed_action"] == "unselected":
            raise ValidationError("Review an actual substantive human lifecycle proposal before approval/handoff.")
        if self.reviewed_revision_id:
            reviewed = self.reviewed_revision
            if (reviewed.project_id != self.project_id or reviewed.review_id != self.review_id or reviewed.state != "review"
                or reviewed.revision >= self.revision or any(getattr(reviewed, key) != getattr(self, key) for key in
                    ("content_revision_id", "intake", "source_evidence", "assignee_id", "source_actor_id"))):
                raise ValidationError("Approval binds the exact reviewed content, source, judgment and assignee.")
        if (self.approved_at and (timezone.is_naive(self.approved_at) or self.approved_at > timezone.now())
            or self.executed_at and (timezone.is_naive(self.executed_at) or self.executed_at > timezone.now()
                or not self.approved_at or self.executed_at < self.approved_at)):
            raise ValidationError("Keep actual approval and separate nonfuture manual handoff time.")
        if len(json.dumps({"source": self.source_evidence, "intake": self.intake}, allow_nan=False).encode()) > 32 * 1024:
            raise ValidationError("Content review exceeds its private evidence ceiling.")
        if self._state.adding:
            previous = ContentLifecycleReview.objects.filter(project=self.project, review_id=self.review_id).order_by("-revision").first()
            if (not previous and (self.revision != 1 or self.state != "draft")
                or previous and (self.revision != previous.revision + 1 or self.state not in TRANSITIONS[previous.state]
                    or previous.content_revision.item_id != self.content_revision.item_id
                    or self.state != "draft" and any(getattr(previous, key) != getattr(self, key) for key in
                        ("content_revision_id", "intake", "source_evidence", "assignee_id", "source_actor_id")))
                or self.state == "approved" and self.reviewed_revision_id != previous.pk
                or self.state == "reported" and self.reviewed_revision_id != previous.reviewed_revision_id):
                raise ValidationError("Keep exact current immutable review transitions; source/decision corrections reset approval.")
            require_current_lifecycle_review(self)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Content-quality changes require a new immutable human revision.")
        self.full_clean()
        return super().save(*args, **kwargs)


class CrawlRun(models.Model):
    job = models.OneToOneField(JobRun, on_delete=models.PROTECT, related_name="crawl_run")
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="crawl_runs")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="crawl_runs")
    page_limit = models.PositiveSmallIntegerField()
    pages_attempted = models.PositiveSmallIntegerField(default=0)
    pages_observed = models.PositiveSmallIntegerField(default=0)
    robots_status = models.CharField(max_length=16, blank=True)
    discovery = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(page_limit__gte=1, page_limit__lte=25), name="jobs_crawl_page_limit"),
            models.CheckConstraint(condition=Q(pages_attempted__lte=models.F("page_limit")), name="jobs_crawl_attempted_limit"),
            models.CheckConstraint(condition=Q(pages_observed__lte=models.F("pages_attempted")), name="jobs_crawl_observed_limit"),
        ]

    def clean(self):
        if self.job_id and (
            self.job.organization_id != self.organization_id
            or self.job.project_id != self.project_id
            or self.job.handler != "crawl_site"
        ):
            raise ValidationError("Crawl run must stay within its crawl job scope.")
        if not 1 <= self.page_limit <= 25:
            raise ValidationError("Crawl page limit must be between 1 and 25.")
        if not 0 <= self.pages_observed <= self.pages_attempted <= self.page_limit:
            raise ValidationError("Crawl progress exceeds its page limit.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class FirstBoundedAuditCompletion(models.Model):
    """Customer completion provenance, not restricted billing or accepted first-value evidence."""
    organization = models.OneToOneField(Organization, on_delete=models.PROTECT, related_name="first_bounded_audit")
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    job = models.OneToOneField(JobRun, on_delete=models.PROTECT)
    observed_at = models.DateTimeField(editable=False)
    source = models.JSONField(editable=False)
    source_digest = models.CharField(max_length=64, editable=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(source_digest__regex=r"^[a-f0-9]{64}$"),
                                              name="jobs_first_audit_digest_valid")]

    def clean(self):
        from .first_audit_evidence import bounded_completion_capture_source, completion_source_digest
        if self.pk is not None or not self._state.adding:
            raise ValidationError("Bounded first-audit completion history is immutable.")
        if (self.project.organization_id != self.organization_id or self.job.organization_id != self.organization_id
            or self.job.project_id != self.project_id or self.observed_at != self.job.crawl_run.completed_at
            or self.source != bounded_completion_capture_source(job=self.job)
            or self.source_digest != completion_source_digest(self.source)):
            raise ValidationError("Bounded completion must retain its exact original current source.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class FirstAuditValueAcknowledgment(models.Model):
    """One prospective subjective customer declaration; original audit/action dates are separate."""
    organization = models.OneToOneField(Organization, on_delete=models.PROTECT, related_name="first_audit_value")
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    job = models.ForeignKey(JobRun, on_delete=models.PROTECT)
    action_review = models.ForeignKey("ActionReview", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    acknowledged_at = models.DateTimeField(editable=False)
    source = models.JSONField(editable=False)
    source_digest = models.CharField(max_length=64, editable=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(source_digest__regex=r"^[a-f0-9]{64}$"),
                                              name="jobs_first_value_digest_valid")]

    def clean(self):
        from .first_audit_value import validate_first_value_capture
        if self.pk is not None or not self._state.adding:
            raise ValidationError("First usefulness acknowledgment history is immutable.")
        validate_first_value_capture(self)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CrawlPageSnapshot(models.Model):
    crawl_run = models.ForeignKey(CrawlRun, on_delete=models.PROTECT, related_name="pages")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="crawl_page_snapshots")
    requested_url = models.URLField(max_length=2048)
    final_url = models.URLField(max_length=2048, blank=True)
    redirect_chain = models.JSONField(default=list, blank=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    title = models.CharField(max_length=500, blank=True)
    meta_description = models.TextField(max_length=1000, blank=True)
    headings = models.JSONField(default=list, blank=True)
    canonical_url = models.URLField(max_length=2048, blank=True)
    robots_directives = models.JSONField(default=list, blank=True)
    hreflang = models.JSONField(default=list, blank=True)
    links = models.JSONField(default=list, blank=True)
    structured_data = models.JSONField(default=list, blank=True)
    structured_data_errors = models.JSONField(default=list, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    etag = models.CharField(max_length=500, blank=True)
    last_modified = models.CharField(max_length=200, blank=True)
    raw_artifact = models.ForeignKey(Artifact, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="crawl_page_snapshots")
    reused_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="reuses")
    error_category = models.CharField(max_length=64, blank=True)
    observed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["crawl_run", "requested_url"], name="jobs_unique_crawl_requested_url"),
            models.CheckConstraint(condition=Q(status_code__isnull=True) | Q(status_code__gte=100, status_code__lte=599),
                                   name="jobs_crawl_status_code_valid"),
        ]
        ordering = ["observed_at", "id"]

    def clean(self):
        if self.crawl_run_id and self.project_id and self.crawl_run.project_id != self.project_id:
            raise ValidationError("Crawl page must stay within its run's project.")
        if self.raw_artifact_id and self.raw_artifact.project_id != self.project_id:
            raise ValidationError("Crawl page artifact must stay within its project.")
        if self.reused_from_id and (
            self.reused_from_id == self.pk or self.reused_from.project_id != self.project_id
        ):
            raise ValidationError("Reused crawl content must stay within its project.")
        if self.reused_from_id and self.raw_artifact_id != self.reused_from.raw_artifact_id:
            raise ValidationError("Reused crawl content must retain its source artifact.")
        if self.raw_artifact_id and not self.reused_from_id and self.raw_artifact.job_id != self.crawl_run.job_id:
            raise ValidationError("New crawl content must use an artifact from its crawl job.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Crawl page snapshots are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class RenderAttempt(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        PARTIALLY_SUCCEEDED = "partially_succeeded", "Partially succeeded"
        FAILED = "failed", "Failed"

    request_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    crawl_page = models.ForeignKey(CrawlPageSnapshot, on_delete=models.PROTECT, related_name="render_attempts")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="render_attempts")
    token_hash = models.CharField(max_length=64, unique=True, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    request_hash = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    source_hash = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    method_version = models.CharField(max_length=64)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.QUEUED)
    error_category = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=["queued", "running", "succeeded", "partially_succeeded", "failed"]),
                name="jobs_render_status_valid",
            ),
        ]
        ordering = ["created_at", "id"]

    def clean(self):
        if self.crawl_page_id and self.project_id and self.crawl_page.project_id != self.project_id:
            raise ValidationError("Render attempt must stay within its crawl page's project.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = RenderAttempt.objects.get(pk=self.pk)
            if any(getattr(self, field) != getattr(previous, field) for field in (
                "request_id", "crawl_page_id", "project_id", "token_hash", "request_hash",
                "source_hash", "method_version",
            )):
                raise ValidationError("Render request identity cannot change.")
        self.full_clean()
        return super().save(*args, **kwargs)


class RenderedPageSnapshot(models.Model):
    attempt = models.OneToOneField(RenderAttempt, on_delete=models.PROTECT, related_name="observation")
    crawl_page = models.ForeignKey(CrawlPageSnapshot, on_delete=models.PROTECT, related_name="rendered_observations")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="rendered_page_snapshots")
    rendered_artifact = models.ForeignKey(Artifact, on_delete=models.PROTECT, related_name="rendered_page_snapshots")
    content_hash = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    text_hash = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    text_excerpt = models.TextField(max_length=16000, blank=True)
    title = models.CharField(max_length=500, blank=True)
    meta_description = models.TextField(max_length=1000, blank=True)
    headings = models.JSONField(default=list, blank=True)
    canonical_url = models.URLField(max_length=2048, blank=True)
    robots_directives = models.JSONField(default=list, blank=True)
    hreflang = models.JSONField(default=list, blank=True)
    links = models.JSONField(default=list, blank=True)
    comparison = models.JSONField(default=dict)
    blocked_requests = models.JSONField(default=list, blank=True)
    duration_ms = models.PositiveIntegerField()
    method_version = models.CharField(max_length=64)
    observed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["observed_at", "id"]

    def clean(self):
        if self.attempt_id and self.crawl_page_id and self.attempt.crawl_page_id != self.crawl_page_id:
            raise ValidationError("Rendered observation must use its attempt's crawl page.")
        if self.crawl_page_id and self.project_id and self.crawl_page.project_id != self.project_id:
            raise ValidationError("Rendered observation must stay within its crawl page's project.")
        if self.rendered_artifact_id and (
            self.rendered_artifact.project_id != self.project_id
            or self.rendered_artifact.job_id != self.crawl_page.crawl_run.job_id
        ):
            raise ValidationError("Rendered artifact must stay within its crawl job scope.")
        if self.attempt_id and self.method_version != self.attempt.method_version:
            raise ValidationError("Rendered observation must retain its attempt method version.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Rendered page snapshots are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class TechnicalDiagnosticsSnapshot(models.Model):
    crawl_run = models.OneToOneField(CrawlRun, on_delete=models.PROTECT, related_name="technical_diagnostics")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="technical_diagnostics")
    input_hash = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    method_version = models.CharField(max_length=64)
    ruleset_version = models.CharField(max_length=64)
    output = models.JSONField(default=dict)
    observed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["observed_at", "id"]

    def clean(self):
        if self.crawl_run_id and self.project_id and self.crawl_run.project_id != self.project_id:
            raise ValidationError("Technical diagnostics must stay within their crawl run's project.")
        try:
            encoded = json.dumps(self.output, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
        except (TypeError, ValueError):
            raise ValidationError("Technical diagnostics must be valid JSON.") from None
        if not isinstance(self.output, dict) or len(encoded) > 262144:
            raise ValidationError("Technical diagnostics must be a bounded JSON object.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Technical diagnostics snapshots are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class IndexationEvidenceSnapshot(models.Model):
    crawl_run = models.OneToOneField(CrawlRun, on_delete=models.PROTECT, related_name="indexation_evidence")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="indexation_evidence")
    diagnostics = models.OneToOneField(TechnicalDiagnosticsSnapshot, on_delete=models.PROTECT, related_name="indexation_evidence")
    input_hash = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    method_version = models.CharField(max_length=64)
    output = models.JSONField(default=dict)
    observed_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.crawl_run_id and self.project_id and self.crawl_run.project_id != self.project_id:
            raise ValidationError("Indexation evidence must stay within its crawl project's scope.")
        if self.diagnostics_id and self.crawl_run_id and (
            self.diagnostics.crawl_run_id != self.crawl_run_id or self.diagnostics.project_id != self.project_id
        ):
            raise ValidationError("Indexation evidence must use diagnostics from the same crawl and project.")
        try:
            encoded = json.dumps(self.output, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
        except (TypeError, ValueError):
            raise ValidationError("Indexation evidence must be valid JSON.") from None
        if not isinstance(self.output, dict) or len(encoded) > 262144:
            raise ValidationError("Indexation evidence must be a bounded JSON object.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Indexation evidence snapshots are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class TopicCandidateSnapshot(models.Model):
    job = models.OneToOneField(JobRun, on_delete=models.PROTECT, related_name="topic_candidates")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="topic_candidate_snapshots")
    method_version = models.CharField(max_length=40)
    output = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.job_id and self.project_id and (
            self.job.project_id != self.project_id or self.job.handler != "discover_topics"
            or self.job.status not in {JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED}
            or self.method_version != self.job.method_version
        ):
            raise ValidationError("Topic candidates require a completed same-project discovery job and method.")
        try:
            encoded = json.dumps(self.output, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
        except (TypeError, ValueError):
            raise ValidationError("Topic candidates must be valid JSON.") from None
        if not isinstance(self.output, dict) or len(encoded) > 131072:
            raise ValidationError("Topic candidate evidence must be a bounded JSON object.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Topic candidate snapshots are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class TopicReview(models.Model):
    """Immutable human topic judgment over an exact bounded source candidate."""
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="topic_reviews")
    snapshot = models.ForeignKey(TopicCandidateSnapshot, on_delete=models.PROTECT, related_name="reviews")
    intent_cluster = models.ForeignKey("IntentClusterReview", null=True, blank=True, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    candidate_index = models.PositiveSmallIntegerField()
    revision = models.PositiveIntegerField()
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    label = models.CharField(max_length=240)
    classification = models.CharField(max_length=16, choices=[("unknown", "Unknown"), ("trending", "Human trending judgment"), ("evergreen", "Human evergreen judgment")])
    language = models.CharField(max_length=35)
    market = models.CharField(max_length=120)
    judgments = models.JSONField()
    reason = models.CharField(max_length=500)
    report = models.JSONField()
    method_version = models.CharField(max_length=40, default="topic-review-v1")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["snapshot", "candidate_index", "revision"], name="jobs_unique_topic_review_revision"),
            models.UniqueConstraint(fields=["project", "request_key"], name="jobs_unique_topic_review_request"),
            models.CheckConstraint(condition=Q(candidate_index__lte=39, revision__gte=1), name="jobs_topic_review_index_revision"),
            models.CheckConstraint(condition=Q(classification__in=["unknown", "trending", "evergreen"]), name="jobs_topic_classification_valid"),
        ]

    def clean(self):
        if (self.snapshot.project_id != self.project_id
            or self.intent_cluster_id and self.intent_cluster.project_id != self.project_id
            or not 0 <= self.candidate_index < len(self.snapshot.output.get("candidates", []))
            or self.method_version != "topic-review-v1" or not self.label.strip() or not self.reason.strip()):
            raise ValidationError("Topic reviews require one same-project source and an explicit human rationale.")
        from .topic_review import validate_judgments
        validate_judgments(self.judgments)
        try:
            size = len(json.dumps(self.report, allow_nan=False).encode())
        except (ValueError, TypeError, RecursionError):
            raise ValidationError("Topic score evidence must be valid JSON.") from None
        if (type(self.report) is not dict or size > 16384 or self.report.get("method") != self.method_version
            or self.report.get("snapshot_id") != self.snapshot_id or self.report.get("candidate_index") != self.candidate_index):
            raise ValidationError("Topic score must retain bounded source and method provenance.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Topic corrections require a new immutable review revision.")
        self.full_clean()
        return super().save(*args, **kwargs)


class PerformanceObservationSnapshot(models.Model):
    class Source(models.TextChoices):
        PSI_LAB = "psi_lab", "PageSpeed Lighthouse lab"
        CRUX_CURRENT = "crux_current", "CrUX current field"
        CRUX_HISTORY = "crux_history", "CrUX history field"

    job = models.ForeignKey(JobRun, on_delete=models.PROTECT, related_name="performance_observations")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="performance_observations")
    raw_artifact = models.ForeignKey(Artifact, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="performance_observations")
    source = models.CharField(max_length=16, choices=Source.choices)
    target = models.URLField(max_length=2048)
    strategy = models.CharField(max_length=8)
    grain = models.CharField(max_length=8)
    output = models.JSONField()
    raw_sha256 = models.CharField(max_length=64, null=True, blank=True, editable=False,
                                  validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    collected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "source"], name="jobs_unique_performance_job_source"),
            models.CheckConstraint(condition=Q(source__in=["psi_lab", "crux_current", "crux_history"]),
                                   name="jobs_performance_source_valid"),
            models.CheckConstraint(condition=Q(grain__in=["page", "origin"]), name="jobs_performance_grain_valid"),
            models.CheckConstraint(condition=Q(strategy__in=["mobile", "desktop", "tablet"]),
                                   name="jobs_performance_strategy_valid"),
            models.CheckConstraint(condition=Q(raw_sha256__isnull=True) | Q(raw_sha256__regex=r"^[0-9a-f]{64}$"),
                                   name="jobs_performance_raw_sha_valid"),
        ]

    @staticmethod
    def artifact_stem(job_id, source):
        return hashlib.sha256(f"performance-v1:{job_id}:{source}".encode()).hexdigest()[:32]

    def clean(self):
        if self.job_id and (self.job.project_id != self.project_id or self.job.handler != "audit_performance"
                            or self.source not in self.job.input_snapshot.get("sources", [])
                            or self.target != self.job.input_snapshot.get("target")
                            or self.strategy != self.job.input_snapshot.get("strategy")
                            or self.grain != self.job.input_snapshot.get("grain")):
            raise ValidationError("Performance observation must match its project job and selected source.")
        if self.project_id:
            from .performance import _scoped_url
            if _scoped_url(self.project, self.target, origin=self.grain == "origin") != self.target:
                raise ValidationError("Performance evidence target must retain exact project scope.")
        if self.source == self.Source.PSI_LAB and (self.grain != "page" or self.strategy == "tablet"):
            raise ValidationError("PageSpeed lab evidence needs a page and supported device.")
        if self.raw_artifact_id is None or (
            self.raw_artifact.job_id != self.job_id or self.raw_artifact.project_id != self.project_id
            or self.raw_artifact.content_type != "application/json"
            or self.raw_artifact.size_bytes > (2 * 1024 * 1024 if self.source == self.Source.PSI_LAB else 256 * 1024)
        ):
            raise ValidationError("Performance evidence requires a bounded private same-job provider artifact.")
        stem = self.artifact_stem(self.job_id, self.source)
        if self.raw_artifact.key != f"{project_artifact_scope(self.project)}/jobs/{self.job_id}/{stem}.json":
            raise ValidationError("Performance raw evidence must match its exact job and source.")
        expected = {"psi_lab": "pagespeed_insights", "crux_current": "crux_api", "crux_history": "crux_history_api"}
        if (type(self.output) is not dict or self.output.get("source") != expected.get(self.source)
            or self.output.get("requested_url") != self.target):
            raise ValidationError("Performance observation must retain its parsed source and target.")
        try:
            encoded = json.dumps(self.output, allow_nan=False, separators=(",", ":")).encode()
        except (TypeError, ValueError):
            raise ValidationError("Performance evidence must be valid JSON.") from None
        if len(encoded) > 256 * 1024:
            raise ValidationError("Performance evidence exceeds its bounded snapshot size.")

    def save(self, *args, **kwargs):
        if not self._state.adding or (self.pk is not None and type(self).objects.filter(pk=self.pk).exists()):
            raise ValidationError("Performance observation snapshots are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class JobSchedule(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="job_schedules")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="job_schedules")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="job_schedules")
    handler = models.CharField(max_length=64)
    idempotency_key = models.CharField(
        max_length=64, blank=True, validators=[RegexValidator(r"^[A-Za-z0-9._-]+$", "Invalid schedule key.")],
    )
    input_snapshot = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=False)
    interval_minutes = models.PositiveSmallIntegerField(default=1440)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    skipped_occurrences = models.PositiveIntegerField(default=0)
    last_error_category = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "handler", "idempotency_key"],
                                    condition=~Q(idempotency_key=""), name="jobs_unique_project_schedule_request"),
            models.CheckConstraint(condition=Q(enabled=False) | Q(next_run_at__isnull=False),
                                   name="jobs_enabled_schedule_has_due"),
            models.CheckConstraint(condition=Q(interval_minutes__gte=60, interval_minutes__lte=10080),
                                   name="jobs_schedule_interval_bounds"),
        ]

    def clean(self):
        if self.handler == "collect_serp":
            from .serp_schedule import validate_schedule
            validate_schedule(self)
        if self.handler == "sample_ai_visibility":
            from .visibility_schedule import validate_schedule_snapshot
            issued, expires = validate_schedule_snapshot(self)
            if self._state.adding:
                from django.utils import timezone
                from tenancy.services import Action, require_project_action
                from .visibility_collection import selection_snapshot
                from .usage import require_billable_access
                require_project_action(project=self.project, user=self.actor, action=Action.MANAGE_PROJECT)
                require_billable_access(organization=self.project.organization)
                config = selection_snapshot(self.project, self.actor, self.input_snapshot["sample"])[2]
                if (config != self.input_snapshot["selection"] or not issued <= timezone.now() < expires
                    or timezone.now() - issued > timedelta(minutes=5)):
                    raise ValidationError("Create a fresh current repeat authorization.")
        if self.organization_id and self.project_id and self.project.organization_id != self.organization_id:
            raise ValidationError("Schedule project must belong to its organization.")
        if self._state.adding and self.project_id and self.actor_id:
            from tenancy.services import Action, require_project_action
            try:
                require_project_action(project=self.project, user=self.actor, action=Action.LAUNCH_JOB)
            except PermissionDenied:
                raise ValidationError("The schedule actor cannot launch work for this project.") from None
        if not 60 <= self.interval_minutes <= 10080:
            raise ValidationError("Diagnostic schedules must be between one hour and one week apart.")
        if self.enabled and self.next_run_at is None:
            raise ValidationError("Enabled schedules require a next run time.")

    def save(self, *args, **kwargs):
        previous = JobSchedule.objects.get(pk=self.pk) if not self._state.adding else None
        if self.handler in {"sample_ai_visibility", "collect_serp"}:
            if self._state.adding and self.enabled:
                raise ValidationError("Repeat schedules must start paused.")
        if previous and {"sample_ai_visibility", "collect_serp"} & {self.handler, previous.handler}:
            if any(getattr(self, field) != getattr(previous, field) for field in (
                "organization_id", "project_id", "actor_id", "handler", "idempotency_key", "input_snapshot", "interval_minutes",
            )):
                raise ValidationError("Repeat authorization and its lifetime cannot change.")
        self.full_clean()
        return super().save(*args, **kwargs)


class Finding(models.Model):
    """Immutable source observation or qualified detector candidate, not an approved action."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="findings")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="detected_findings")
    source_metric = models.ForeignKey("integrations.SearchMetricObservation", null=True, blank=True,
                                      on_delete=models.PROTECT)
    source_api_page = models.ForeignKey("integrations.SearchAnalyticsPageSnapshot", null=True, blank=True,
                                        on_delete=models.PROTECT)
    source_diagnostics = models.ForeignKey(TechnicalDiagnosticsSnapshot, null=True, blank=True,
                                           on_delete=models.PROTECT)
    source_indexation = models.ForeignKey(IndexationEvidenceSnapshot, null=True, blank=True,
                                          on_delete=models.PROTECT)
    source_performance = models.ForeignKey(PerformanceObservationSnapshot, null=True, blank=True,
                                           on_delete=models.PROTECT)
    source_passive_header = models.ForeignKey(JobRun, null=True, blank=True, on_delete=models.PROTECT,
                                              related_name="passive_header_findings")
    source_passive_resource = models.ForeignKey(JobRun, null=True, blank=True, on_delete=models.PROTECT,
                                                related_name="passive_resource_findings")
    source_passive_tls = models.ForeignKey(JobRun, null=True, blank=True, on_delete=models.PROTECT,
                                           related_name="passive_tls_findings")
    source_passive_redirect = models.ForeignKey(JobRun, null=True, blank=True, on_delete=models.PROTECT,
                                                related_name="passive_redirect_findings")
    source_passive_redirect_chain = models.ForeignKey(JobRun, null=True, blank=True, on_delete=models.PROTECT,
                                                      related_name="passive_redirect_chain_findings")
    detector = models.CharField(max_length=80)
    method_version = models.CharField(max_length=64)
    subject = models.CharField(max_length=2048)
    fingerprint = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    evidence = models.JSONField()
    confidence = models.CharField(max_length=40, default="candidate_not_proven_business_value")
    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "fingerprint"], name="jobs_unique_project_finding_evidence"),
            models.CheckConstraint(condition=(Q(source_passive_redirect_chain__isnull=True) & ((Q(source_passive_redirect__isnull=True) & ((Q(source_passive_tls__isnull=True) & ((Q(source_passive_resource__isnull=True) & ((Q(source_passive_header__isnull=True) & (
                Q(source_metric__isnull=False, source_api_page__isnull=True, source_diagnostics__isnull=True,
                  source_indexation__isnull=True, source_performance__isnull=True)
                | Q(source_metric__isnull=True, source_api_page__isnull=False, source_diagnostics__isnull=True,
                    source_indexation__isnull=True, source_performance__isnull=True)
                | Q(source_metric__isnull=True, source_api_page__isnull=True, source_diagnostics__isnull=False,
                    source_indexation__isnull=True, source_performance__isnull=True)
                | Q(source_metric__isnull=True, source_api_page__isnull=True, source_diagnostics__isnull=True,
                    source_indexation__isnull=False, source_performance__isnull=True)
                | Q(source_metric__isnull=True, source_api_page__isnull=True, source_diagnostics__isnull=True,
                    source_indexation__isnull=True, source_performance__isnull=False)
            )) | Q(source_metric__isnull=True, source_api_page__isnull=True, source_diagnostics__isnull=True,
                   source_indexation__isnull=True, source_performance__isnull=True, source_passive_header__isnull=False)))
                | Q(source_metric__isnull=True, source_api_page__isnull=True, source_diagnostics__isnull=True,
                    source_indexation__isnull=True, source_performance__isnull=True, source_passive_header__isnull=True,
                    source_passive_resource__isnull=False)))
                | Q(source_metric__isnull=True, source_api_page__isnull=True, source_diagnostics__isnull=True,
                    source_indexation__isnull=True, source_performance__isnull=True, source_passive_header__isnull=True,
                    source_passive_resource__isnull=True, source_passive_tls__isnull=False)))
                | Q(source_metric__isnull=True, source_api_page__isnull=True, source_diagnostics__isnull=True,
                    source_indexation__isnull=True, source_performance__isnull=True, source_passive_header__isnull=True,
                    source_passive_resource__isnull=True, source_passive_tls__isnull=True, source_passive_redirect__isnull=False)))
                | Q(source_metric__isnull=True, source_api_page__isnull=True, source_diagnostics__isnull=True,
                    source_indexation__isnull=True, source_performance__isnull=True, source_passive_header__isnull=True,
                    source_passive_resource__isnull=True, source_passive_tls__isnull=True, source_passive_redirect__isnull=True,
                    source_passive_redirect_chain__isnull=False),
                name="jobs_finding_one_source"),
        ]

    def clean(self):
        sources = (self.source_metric, self.source_api_page, self.source_diagnostics,
                   self.source_indexation, self.source_performance, self.source_passive_header, self.source_passive_resource,
                   self.source_passive_tls, self.source_passive_redirect, self.source_passive_redirect_chain)
        if sum(item is not None for item in sources) != 1:
            raise ValidationError("A finding needs one project-owned observation source.")
        source = next(item for item in sources if item is not None)
        source_project_id = (source.import_run.project_id if self.source_metric_id else source.project_id)
        if source_project_id != self.project_id:
            raise ValidationError("Finding evidence belongs to another project.")
        if self.source_passive_header_id:
            from .passive_header_findings import validate_header_finding
            validate_header_finding(self)
        if self.source_passive_resource_id:
            from .passive_resource_findings import validate_resource_finding
            validate_resource_finding(self)
        if self.source_passive_tls_id:
            from .passive_tls_findings import validate_tls_finding
            validate_tls_finding(self)
        if self.source_passive_redirect_id:
            from .passive_redirect_findings import validate_redirect_finding
            validate_redirect_finding(self)
        if self.source_passive_redirect_chain_id:
            from .passive_redirect_chain_findings import validate_redirect_chain_finding
            validate_redirect_chain_finding(self)
        if type(self.evidence) is not dict or not self.subject or not self.detector or not self.method_version:
            raise ValidationError("A finding needs bounded source evidence and a detector version.")
        try:
            data = json.dumps(self.evidence, allow_nan=False, separators=(",", ":")).encode()
        except (TypeError, ValueError, RecursionError):
            raise ValidationError("Finding evidence must be valid JSON.") from None
        if len(data) > 4096:
            raise ValidationError("Finding evidence exceeds 4 KiB.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Finding source evidence is immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class Opportunity(models.Model):
    """Explicit review/prioritization of a finding; no action is approved here."""

    class Priority(models.TextChoices):
        UNPRIORITIZED = "unprioritized", "Not prioritized"
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="opportunities")
    finding = models.ForeignKey(Finding, on_delete=models.PROTECT, related_name="opportunity_reviews")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reviewed_opportunities")
    revision = models.PositiveSmallIntegerField(default=1)
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.UNPRIORITIZED)
    estimated_effort = models.CharField(max_length=16, choices=[(item, item) for item in ("unknown", "small", "medium", "large")], default="unknown")
    business_relevance = models.CharField(max_length=16, choices=[(item, item) for item in ("unknown", "low", "medium", "high")], default="unknown")
    review_reason = models.CharField(max_length=240)
    passive_source_sha256 = models.CharField(max_length=64, blank=True, default="",
        validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["finding", "revision"], name="jobs_unique_opportunity_review_revision"),
                       models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_opportunity_revision_positive"),
                       models.CheckConstraint(condition=Q(passive_source_sha256="") | Q(passive_source_sha256__regex=r"^[0-9a-f]{64}$"),
                           name="jobs_opportunity_passive_digest_shape")]

    def clean(self):
        if self.finding_id and self.finding.project_id != self.project_id:
            raise ValidationError("An opportunity must use a finding in the same project.")
        if self.finding_id and (self.finding.source_passive_header_id or self.finding.source_passive_resource_id
            or self.finding.source_passive_tls_id or self.finding.source_passive_redirect_id
            or self.finding.source_passive_redirect_chain_id):
            from .passive_finding_reviews import validate_passive_opportunity
            validate_passive_opportunity(self)
        elif self.passive_source_sha256:
            raise ValidationError("An ordinary opportunity cannot claim a passive source digest.")
        if not self.review_reason or not self.review_reason.strip():
            raise ValidationError("Record why this candidate merits review.")
        self.review_reason = self.review_reason.strip()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Opportunity decisions need a new review revision.")
        self.full_clean()
        return super().save(*args, **kwargs)


class AIVisibilityAnswerReview(models.Model):
    """Append-only human entity evaluation of one private immutable answer."""
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="visibility_answer_reviews")
    job = models.ForeignKey(JobRun, on_delete=models.PROTECT, related_name="visibility_reviews")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    revision = models.PositiveSmallIntegerField()
    answer_sha256 = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    method_version = models.CharField(max_length=40)
    context = models.JSONField()
    matches = models.JSONField(default=list, blank=True)
    evaluated = models.BooleanField(default=False)
    review_note = models.CharField(max_length=500)
    factual_notes = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "revision"], name="jobs_visibility_review_revision"),
            models.UniqueConstraint(fields=["project", "request_key"], name="jobs_visibility_review_request"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_visibility_review_positive"),
        ]

    def clean(self):
        from .visibility_entities import validate_review_snapshot
        validate_review_snapshot(self)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Visibility corrections require a new immutable review revision.")
        self.full_clean()
        return super().save(*args, **kwargs)


class Recommendation(models.Model):
    """Human-authored draft only; implementation and approval are separate later workflow states."""

    opportunity = models.ForeignKey(Opportunity, on_delete=models.PROTECT, related_name="recommendations")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="recommendations")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    revision = models.PositiveSmallIntegerField()
    draft = models.CharField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["opportunity", "revision"], name="jobs_unique_recommendation_revision"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_recommendation_revision_positive"),
        ]

    def clean(self):
        if self.opportunity_id and self.opportunity.project_id != self.project_id:
            raise ValidationError("A recommendation draft belongs to its opportunity project.")
        if self.opportunity_id and (self.opportunity.finding.source_passive_header_id or self.opportunity.finding.source_passive_resource_id
            or self.opportunity.finding.source_passive_tls_id or self.opportunity.finding.source_passive_redirect_id
            or self.opportunity.finding.source_passive_redirect_chain_id):
            raise ValidationError("Passive findings do not yet support recommendation drafts.")
        if not self.draft or not self.draft.strip():
            raise ValidationError("Recommendation drafts need content.")
        self.draft = self.draft.strip()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Recommendation drafts are immutable revisions.")
        self.full_clean()
        return super().save(*args, **kwargs)


class IntentClusterReview(models.Model):
    """Human mapping of evidenced queries to a page; never a proven query-page join."""

    class Intent(models.TextChoices):
        UNKNOWN = "unknown", "Unclassified"
        INFORMATIONAL = "informational", "Informational"
        COMMERCIAL = "commercial", "Commercial"
        NAVIGATIONAL = "navigational", "Navigational"
        TRANSACTIONAL = "transactional", "Transactional"
        LOCAL = "local", "Local"
        MIXED = "mixed", "Mixed/uncertain"

    class PageKind(models.TextChoices):
        UNMAPPED = "unmapped", "No selected page"
        EXISTING_UNVERIFIED = "existing_unverified", "Human-selected existing page; not source-attributed"
        PROPOSED = "proposed", "Proposed page; not published"

    class ProposedAction(models.TextChoices):
        UNSELECTED = "unselected", "No action proposed"
        KEEP = "keep", "Keep existing page"
        REFRESH = "refresh", "Refresh existing page"
        MERGE = "merge", "Propose merging an affected page into this page"
        REDIRECT = "redirect", "Propose redirecting an affected page to this page"
        RETIRE = "retire", "Propose retiring the selected page after review"
        CREATE = "create", "Propose creating the selected page"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="intent_cluster_reviews")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    cluster_id = models.UUIDField(default=uuid4, editable=False)
    revision = models.PositiveSmallIntegerField(default=1)
    label = models.CharField(max_length=120)
    source_finding_ids = models.JSONField(default=list, blank=True)
    manual_topics = models.JSONField(default=list, blank=True)
    market = models.CharField(max_length=80)
    language = models.CharField(max_length=35)
    intent = models.CharField(max_length=20, choices=Intent.choices, default=Intent.UNKNOWN)
    page_kind = models.CharField(max_length=24, choices=PageKind.choices, default=PageKind.UNMAPPED)
    preferred_page = models.CharField(max_length=512, blank=True)
    reason = models.CharField(max_length=500)
    proposed_action = models.CharField(max_length=16, choices=ProposedAction.choices,
                                       default=ProposedAction.UNSELECTED)
    action_reason = models.CharField(max_length=500, blank=True)
    affected_page = models.CharField(max_length=512, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "cluster_id", "revision"],
                                    name="jobs_unique_project_intent_revision"),
            models.UniqueConstraint(fields=["project", "request_key"], name="jobs_unique_project_intent_request"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_intent_revision_positive"),
            models.CheckConstraint(condition=Q(intent__in=["unknown", "informational", "commercial",
                                                    "navigational", "transactional", "local", "mixed"]),
                                   name="jobs_intent_kind_valid"),
            models.CheckConstraint(condition=Q(page_kind="unmapped", preferred_page="")
                                   | Q(page_kind__in=["existing_unverified", "proposed"]) & ~Q(preferred_page=""),
                                   name="jobs_intent_page_state_valid"),
            models.CheckConstraint(condition=Q(proposed_action="unselected", action_reason="", affected_page="")
                                   | Q(proposed_action__in=["keep", "refresh", "retire"], page_kind="existing_unverified",
                                       affected_page="", action_reason__regex=r"\S")
                                   | Q(proposed_action="create", page_kind="proposed", affected_page="",
                                       action_reason__regex=r"\S")
                                   | Q(proposed_action__in=["merge", "redirect"], page_kind="existing_unverified",
                                       affected_page__regex=r"\S", action_reason__regex=r"\S"),
                                   name="jobs_intent_action_proposal_valid"),
        ]

    def clean(self):
        if (type(self.source_finding_ids) is not list or len(self.source_finding_ids) > 10
            or any(type(item) is not int or item < 1 for item in self.source_finding_ids)
            or len(set(self.source_finding_ids)) != len(self.source_finding_ids)
            or type(self.manual_topics) is not list or len(self.manual_topics) > 10
            or any(type(item) is not str or not 1 <= len(item) <= 120 or item != item.strip()
                   for item in self.manual_topics)
            or len(set(self.manual_topics)) != len(self.manual_topics)
            or bool(self.source_finding_ids) == bool(self.manual_topics)):
            raise ValidationError("Choose distinct query findings or unmeasured project seed topics, not both.")
        if any(not isinstance(value, str) or not value.strip() for value in
               (self.label, self.reason, self.market, self.language)):
            raise ValidationError("Record the market, language and human mapping rationale.")
        if self.proposed_action not in self.ProposedAction.values or not isinstance(self.action_reason, str):
            raise ValidationError("Choose a supported human action proposal.")
        if self.project_id and self.actor_id:
            from tenancy.services import Action, require_project_action
            try:
                require_project_action(project=self.project, user=self.actor, action=Action.MANAGE_PROJECT)
            except PermissionDenied:
                raise ValidationError("The reviewer cannot manage this project.") from None
        if self.project_id and self.source_finding_ids and Finding.objects.filter(
                                                      pk__in=self.source_finding_ids, project_id=self.project_id,
                                                      source_metric__query__gt="").count() != len(self.source_finding_ids):
            raise ValidationError("Cluster queries must use same-project query observations.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Intent mappings require a new immutable review revision.")
        self.full_clean()
        return super().save(*args, **kwargs)


class AIVisibilityPromptSet(models.Model):
    """Append-only human methodology; saving never runs an AI request."""
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="visibility_prompt_sets")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    set_id = models.UUIDField(default=uuid4, editable=False)
    revision = models.PositiveSmallIntegerField(default=1)
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    label = models.CharField(max_length=120)
    language = models.CharField(max_length=35)
    market = models.CharField(max_length=80)
    prompts = models.JSONField()
    context = models.JSONField()
    policy = models.JSONField()
    review_note = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "set_id", "revision"], name="jobs_visibility_set_revision"),
            models.UniqueConstraint(fields=["project", "request_key"], name="jobs_visibility_set_request"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_visibility_revision_positive"),
        ]

    def clean(self):
        from .visibility_prompts import validate_prompt_set_snapshot, _context
        validate_prompt_set_snapshot(self)
        if self._state.adding:
            from tenancy.services import Action, require_project_action
            require_project_action(project=self.project, user=self.actor, action=Action.MANAGE_PROJECT)
            if self.context != _context(self.project, self.language, self.prompts):
                raise ValidationError("Prompt-set context and intent sources must belong to this current project.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("AI visibility methodology needs a new immutable revision.")
        self.full_clean()
        return super().save(*args, **kwargs)


class ActionReview(models.Model):
    """Append-only human action state; never applies a website change."""

    class State(models.TextChoices):
        PROPOSED = "proposed", "Proposal awaiting approval"
        ACCEPTED = "accepted", "Approved for manual work"
        IN_PROGRESS = "in_progress", "Assigned work in progress"
        IMPLEMENTED = "implemented", "Implementation claimed, not verified"
        VERIFIED = "verified", "Technical verification reviewed"
        OUTCOME_REVIEWED = "outcome_reviewed", "Outcome reviewed, not necessarily improved"
        DISMISSED = "dismissed", "Dismissed by reviewer"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="action_reviews")
    intent_cluster = models.ForeignKey(IntentClusterReview, null=True, blank=True,
                                       on_delete=models.PROTECT, related_name="action_reviews")
    opportunity = models.ForeignKey(Opportunity, null=True, blank=True,
                                    on_delete=models.PROTECT, related_name="action_reviews")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="seo_action_reviews")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.PROTECT, related_name="assigned_seo_action_reviews")
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    action_id = models.UUIDField(default=uuid4, editable=False)
    revision = models.PositiveSmallIntegerField(default=1)
    state = models.CharField(max_length=20, choices=State.choices, default=State.PROPOSED)
    action_kind = models.CharField(max_length=16, choices=IntentClusterReview.ProposedAction.choices)
    affected_urls = models.JSONField(default=list)
    acceptance_criteria = models.CharField(max_length=500)
    reason = models.CharField(max_length=500)
    change_summary = models.CharField(max_length=500, blank=True)
    verification_note = models.CharField(max_length=500, blank=True)
    outcome_note = models.CharField(max_length=500, blank=True)
    implemented_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    outcome_reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "action_id", "revision"],
                                    name="jobs_unique_project_action_revision"),
            models.UniqueConstraint(fields=["project", "request_key"], name="jobs_unique_project_action_request"),
            models.CheckConstraint(condition=Q(intent_cluster__isnull=False, opportunity__isnull=True)
                                   | Q(intent_cluster__isnull=True, opportunity__isnull=False),
                                   name="jobs_action_exactly_one_source"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_action_revision_positive"),
            models.CheckConstraint(condition=Q(state__in=["proposed", "accepted", "in_progress", "implemented",
                                                  "verified", "outcome_reviewed", "dismissed"]),
                                   name="jobs_action_state_valid"),
            models.CheckConstraint(condition=Q(action_kind__in=["keep", "refresh", "merge", "redirect",
                                                        "retire", "create"]), name="jobs_action_kind_valid"),
            models.CheckConstraint(condition=(
                Q(state__in=["proposed", "accepted", "in_progress", "dismissed"], implemented_at__isnull=True,
                  verified_at__isnull=True, outcome_reviewed_at__isnull=True)
                | Q(state="implemented", implemented_at__isnull=False, verified_at__isnull=True,
                    outcome_reviewed_at__isnull=True)
                | Q(state="verified", implemented_at__isnull=False, verified_at__isnull=False,
                    outcome_reviewed_at__isnull=True)
                | Q(state="outcome_reviewed", implemented_at__isnull=False, verified_at__isnull=False,
                    outcome_reviewed_at__isnull=False)), name="jobs_action_state_dates_valid"),
            models.CheckConstraint(condition=(
                Q(state__in=["proposed", "accepted", "in_progress", "dismissed"],
                  change_summary="", verification_note="", outcome_note="")
                | Q(state="implemented", change_summary__regex=r"\S", verification_note="", outcome_note="")
                | Q(state="verified", change_summary__regex=r"\S", verification_note__regex=r"\S", outcome_note="")
                | Q(state="outcome_reviewed", change_summary__regex=r"\S", verification_note__regex=r"\S",
                    outcome_note__regex=r"\S")), name="jobs_action_evidence_by_stage"),
        ]

    def clean(self):
        source = self.intent_cluster or self.opportunity
        if (source is None or source.project_id != self.project_id
            or type(self.affected_urls) is not list or not 1 <= len(self.affected_urls) <= 10
            or any(type(url) is not str or not 1 <= len(url) <= 512 for url in self.affected_urls)
            or len(set(self.affected_urls)) != len(self.affected_urls)
            or self.action_kind not in IntentClusterReview.ProposedAction.values
            or self.action_kind == IntentClusterReview.ProposedAction.UNSELECTED
            or not self.acceptance_criteria.strip() or not self.reason.strip()):
            raise ValidationError("Choose one current project source and bounded manual action criteria.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Action changes require a new immutable history revision.")
        self.full_clean()
        return super().save(*args, **kwargs)


class ActionOutcomeSnapshot(models.Model):
    """One immutable, source-qualified before/after comparison per action revision."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="action_outcomes")
    action_review = models.OneToOneField(ActionReview, on_delete=models.PROTECT, related_name="outcome_snapshot")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    connection = models.ForeignKey("integrations.IntegrationConnection", on_delete=models.PROTECT)
    previous_import = models.ForeignKey("integrations.ImportRun", on_delete=models.PROTECT,
                                        related_name="previous_action_outcomes")
    current_import = models.ForeignKey("integrations.ImportRun", on_delete=models.PROTECT,
                                       related_name="current_action_outcomes")
    method_version = models.CharField(max_length=40, default="gsc-csv-page-outcome-v1")
    page = models.CharField(max_length=512)
    report = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if not all((self.project_id, self.action_review_id, self.actor_id, self.connection_id,
                    self.previous_import_id, self.current_import_id)):
            raise ValidationError("Outcome requires complete project-owned source identifiers.")
        if (self.project_id and (self.action_review.project_id != self.project_id
            or self.connection.project_id != self.project_id
            or self.previous_import.project_id != self.project_id
            or self.current_import.project_id != self.project_id
            or self.previous_import.connection_id != self.connection_id
            or self.current_import.connection_id != self.connection_id
            or self.previous_import_id == self.current_import_id
            or self.page != self.action_review.affected_urls[-1])):
            raise ValidationError("Outcome sources must stay within the selected action and property.")
        before = self.report.get("before") if type(self.report) is dict else None
        after = self.report.get("after") if type(self.report) is dict else None
        if (type(before) is not dict or type(after) is not dict
            or self.report.get("method_version") != self.method_version
            or self.report.get("project_id") != self.project_id
            or self.report.get("action_id") != str(self.action_review.action_id)
            or self.report.get("action_revision") != self.action_review.revision
            or self.report.get("connection_id") != self.connection_id
            or self.report.get("page") != self.page
            or before.get("import_id") != self.previous_import_id
            or after.get("import_id") != self.current_import_id):
            raise ValidationError("Outcome must preserve its deterministic source metadata.")
        try:
            encoded = json.dumps(self.report, allow_nan=False, separators=(",", ":")).encode()
        except (TypeError, ValueError, RecursionError):
            raise ValidationError("Outcome must contain bounded safe JSON.") from None
        if len(encoded) > 32768:
            raise ValidationError("Outcome evidence exceeds the private snapshot limit.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Outcome snapshots are immutable; a new reviewed action revision is required.")
        self.full_clean()
        return super().save(*args, **kwargs)


class ActionTechnicalOutcomeSnapshot(models.Model):
    """Bounded immutable crawl observations; not a verified website fix."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="technical_action_outcomes")
    action_review = models.OneToOneField(ActionReview, on_delete=models.PROTECT,
                                         related_name="technical_outcome_snapshot")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    previous_crawl = models.ForeignKey(CrawlRun, on_delete=models.PROTECT,
                                       related_name="previous_action_checks")
    current_crawl = models.ForeignKey(CrawlRun, on_delete=models.PROTECT,
                                      related_name="current_action_checks")
    method_version = models.CharField(max_length=40, default="action-crawl-observation-v1")
    report = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if not all((self.project_id, self.action_review_id, self.actor_id,
                    self.previous_crawl_id, self.current_crawl_id)):
            raise ValidationError("Technical outcome needs complete project-owned sources.")
        if (self.action_review.project_id != self.project_id
            or self.previous_crawl.project_id != self.project_id
            or self.current_crawl.project_id != self.project_id
            or self.previous_crawl_id == self.current_crawl_id):
            raise ValidationError("Technical outcome crawls must stay inside the action's project.")
        before = self.report.get("previous") if type(self.report) is dict else None
        after = self.report.get("current") if type(self.report) is dict else None
        if (type(before) is not dict or type(after) is not dict
            or self.report.get("method_version") != self.method_version
            or self.report.get("project_id") != self.project_id
            or self.report.get("action_id") != str(self.action_review.action_id)
            or self.report.get("action_revision") != self.action_review.revision
            or before.get("crawl_run_id") != self.previous_crawl_id
            or after.get("crawl_run_id") != self.current_crawl_id):
            raise ValidationError("Technical observation must retain its crawl and action provenance.")
        try:
            encoded = json.dumps(self.report, allow_nan=False, separators=(",", ":")).encode()
        except (TypeError, ValueError, RecursionError):
            raise ValidationError("Technical observations need bounded safe JSON.") from None
        if len(encoded) > 32768:
            raise ValidationError("Technical observation exceeds the private snapshot limit.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Technical outcome snapshots are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class LocalBusinessAssessment(models.Model):
    """Manual user-supplied business facts; no profile/API verification or local ranking."""

    class Eligibility(models.TextChoices):
        UNKNOWN = "unknown", "Eligibility unknown"
        REVIEW_NEEDED = "review_needed", "Manual eligibility review needed"
        USER_ATTESTED = "user_attested", "Business claims eligibility; not provider verified"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="local_assessments")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="local_assessments")
    location_digest = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    revision = models.PositiveSmallIntegerField(default=1)
    configuration_revision = models.PositiveIntegerField()
    location_label = models.CharField(max_length=240, blank=True)
    business_name = models.CharField(max_length=160)
    address_display = models.CharField(max_length=512, blank=True)
    phone = models.CharField(max_length=64, blank=True)
    hours = models.CharField(max_length=500, blank=True)
    services = models.JSONField(default=list)
    service_areas = models.JSONField(default=list)
    profile_url = models.CharField(max_length=512, blank=True)
    eligibility = models.CharField(max_length=16, choices=Eligibility.choices, default=Eligibility.UNKNOWN)
    review_theme = models.CharField(max_length=240, blank=True)
    evidence_note = models.CharField(max_length=500)
    suggested_action = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "location_digest", "revision"],
                                    name="jobs_unique_local_assessment_revision"),
            models.UniqueConstraint(fields=["project", "request_key"], name="jobs_unique_local_assessment_request"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_local_assessment_revision_positive"),
            models.CheckConstraint(condition=Q(eligibility__in=["unknown", "review_needed", "user_attested"]),
                                   name="jobs_local_assessment_eligibility_valid"),
        ]

    def clean(self):
        if (type(self.services) is not list or not 1 <= len(self.services) <= 20
            or any(type(value) is not str or not 1 <= len(value.strip()) <= 120 for value in self.services)
            or type(self.service_areas) is not list or len(self.service_areas) > 20
            or any(type(value) is not str or not 1 <= len(value.strip()) <= 240 for value in self.service_areas)
            or not self.business_name.strip() or not self.evidence_note.strip()):
            raise ValidationError("A local assessment requires bounded user-entered facts and review context.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Local reviews require a new immutable assessment revision.")
        self.full_clean()
        return super().save(*args, **kwargs)


class AuthorityLinkReview(models.Model):
    """Independent human source/link activity history, not site remediation approval or link proof."""
    class State(models.TextChoices):
        DRAFT = "draft", "Unapproved human draft"
        REVIEW = "review", "Exact human review required"
        APPROVED = "approved", "Exact human activity approved"
        REPORTED = "reported", "Manual activity reported, not verified"
        DISMISSED = "dismissed", "Human link candidate dismissed"

    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authority_link_reviews")
    source_actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authority_link_sources")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authority_link_assignments")
    verification = models.ForeignKey("tenancy.ProjectOriginVerification", on_delete=models.PROTECT)
    verified_at = models.DateTimeField()
    crawl_page = models.ForeignKey(CrawlPageSnapshot, on_delete=models.PROTECT)
    intake = models.JSONField()
    target_evidence = models.JSONField()
    proposal = models.JSONField()
    recovery_action_review = models.ForeignKey(ActionReview, null=True, blank=True, on_delete=models.PROTECT)
    recovery_evidence = models.JSONField(default=dict, blank=True)
    link_id = models.UUIDField(default=uuid4)
    revision = models.PositiveIntegerField()
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    state = models.CharField(max_length=9, choices=State.choices)
    reason = models.CharField(max_length=500)
    reviewed_revision = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="approvals")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="authority_link_approvals")
    approved_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    execution_note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "link_id", "revision"], name="jobs_link_review_revision_unique"),
            models.UniqueConstraint(fields=["project", "request_key"], name="jobs_link_review_request_unique"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_link_review_revision_positive"),
            models.CheckConstraint(condition=Q(state__in=["draft", "review", "approved", "reported", "dismissed"]), name="jobs_link_review_state_valid"),
            models.CheckConstraint(condition=Q(state__in=["draft", "review", "dismissed"], reviewed_revision__isnull=True,
                approved_by__isnull=True, approved_at__isnull=True) | Q(state__in=["approved", "reported"],
                reviewed_revision__isnull=False, approved_by__isnull=False, approved_at__isnull=False), name="jobs_link_review_exact_approval"),
            models.CheckConstraint(condition=(Q(state="reported", executed_at__isnull=False) & ~Q(execution_note=""))
                | (~Q(state="reported") & Q(executed_at__isnull=True, execution_note="")), name="jobs_link_review_manual_report"),
        ]

    def clean(self):
        from .authority_links import require_current_link_review, validate_link_intake, validate_link_proposal
        from .local_feedback import _text
        from django.utils import timezone
        data = validate_link_intake(self.intake)
        proposal = validate_link_proposal(self.proposal)
        _text(self.reason, 500, required=True)
        _text(self.execution_note, 500, required=self.state == "reported")
        if (self.crawl_page.project_id != self.project_id or self.crawl_page_id != data["crawl_page_id"]
            or self.verification.project_id != self.project_id or self.verification.origin != data["origin"]
            or timezone.is_naive(self.verified_at) or self.verified_at > timezone.now()
            or (proposal["action"] == "review_target_recovery") != bool(self.recovery_action_review_id)
            or not self.recovery_action_review_id and self.recovery_evidence):
            raise ValidationError("Bind actual same-project target/source authority and genuine recovery handoff only.")
        if self.state in {"review", "approved", "reported"} and (not proposal["draft_text"].strip()
            or proposal["action"] == "request_source_correction" and
                (data["status"] != "observed" or proposal["outreach_permission"] is not True)):
            raise ValidationError("Review actual human text; source-correction outreach needs observed href and separate permission.")
        if self.reviewed_revision_id:
            reviewed = self.reviewed_revision
            if (reviewed.project_id != self.project_id or reviewed.link_id != self.link_id or reviewed.state != "review"
                or reviewed.revision >= self.revision or any(getattr(reviewed, field) != getattr(self, field) for field in
                    ("intake", "target_evidence", "proposal", "assignee_id", "source_actor_id", "verification_id", "verified_at",
                     "crawl_page_id", "recovery_action_review_id", "recovery_evidence"))):
                raise ValidationError("Approval must bind the exact reviewed source, target, assignee and human proposal.")
        if (self.approved_at and (timezone.is_naive(self.approved_at) or self.approved_at > timezone.now())
            or self.executed_at and (timezone.is_naive(self.executed_at) or self.executed_at > timezone.now()
                or not self.approved_at or self.executed_at < self.approved_at)):
            raise ValidationError("Keep actual nonfuture approval and separate manual activity time.")
        if self._state.adding:
            require_current_link_review(self)
        if len(json.dumps({"intake": self.intake, "target": self.target_evidence, "proposal": self.proposal,
            "recovery": self.recovery_evidence}, allow_nan=False).encode()) > 32 * 1024:
            raise ValidationError("Human link review exceeds its private 32 KiB evidence ceiling.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Link-review changes require a new immutable human revision.")
        self.full_clean()
        return super().save(*args, **kwargs)


class AuthorityProspectReview(models.Model):
    """Immutable research-quote human prospect/reply decisions, never link proof or automatic outreach."""
    class State(models.TextChoices):
        DRAFT = "draft", "Unapproved human draft"
        REVIEW = "review", "Human review required"
        APPROVED = "approved", "Exact reviewed draft approved"
        REPORTED = "reported", "Manual execution reported, not verified"
        DISMISSED = "dismissed", "Human prospect dismissed"

    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authority_reviews")
    source_actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authority_sources")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authority_assignments")
    research_job = models.ForeignKey(JobRun, on_delete=models.PROTECT)
    source_index = models.PositiveSmallIntegerField()
    source_evidence = models.JSONField()
    prospect_id = models.UUIDField(default=uuid4)
    revision = models.PositiveIntegerField()
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    state = models.CharField(max_length=9, choices=State.choices)
    intake = models.JSONField()
    reason = models.CharField(max_length=500)
    reviewed_revision = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="approvals")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="authority_approvals")
    approved_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    execution_note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "prospect_id", "revision"], name="jobs_authority_revision_unique"),
            models.UniqueConstraint(fields=["project", "request_key"], name="jobs_authority_request_unique"),
            models.CheckConstraint(condition=Q(revision__gte=1, source_index__lt=5), name="jobs_authority_revision_source"),
            models.CheckConstraint(condition=Q(state__in=["draft", "review", "approved", "reported", "dismissed"]), name="jobs_authority_state_valid"),
            models.CheckConstraint(condition=Q(state__in=["draft", "review", "dismissed"], reviewed_revision__isnull=True,
                approved_by__isnull=True, approved_at__isnull=True) | Q(state__in=["approved", "reported"],
                reviewed_revision__isnull=False, approved_by__isnull=False, approved_at__isnull=False), name="jobs_authority_exact_approval"),
            models.CheckConstraint(condition=(Q(state="reported", executed_at__isnull=False) & ~Q(execution_note=""))
                | (~Q(state="reported") & Q(executed_at__isnull=True, execution_note="")), name="jobs_authority_manual_report"),
        ]

    def clean(self):
        from .authority import validate_prospect_intake
        from .local_feedback import _text
        from django.utils import timezone
        validate_prospect_intake(self.intake, evidence=self.source_evidence)
        _text(self.reason, 500, required=True)
        _text(self.execution_note, 500, required=self.state == "reported")
        if (self.research_job.project_id != self.project_id or self.research_job.handler != "research_topic"
            or self.source_evidence.get("project_id") != self.project_id
            or (self.research_job_id, self.source_index) != (self.intake["research_job_id"], self.intake["source_index"])):
            raise ValidationError("Prospect must bind actual same-project research evidence.")
        if self.state in {"review", "approved", "reported"} and (not self.intake["draft_text"].strip()
                                                                or self.intake["outreach_permission"] is not True):
            raise ValidationError("Review requires exact human text and independently declared outreach permission.")
        if self.reviewed_revision_id:
            reviewed = self.reviewed_revision
            if (reviewed.project_id != self.project_id or reviewed.prospect_id != self.prospect_id
                or reviewed.state != "review" or reviewed.revision >= self.revision
                or any(getattr(reviewed, key) != getattr(self, key) for key in
                    ("intake", "source_evidence", "research_job_id", "source_index", "assignee_id", "source_actor_id"))):
                raise ValidationError("Approval must bind exact reviewed source, target, assignee and text.")
        if (self.approved_at and self.approved_at > timezone.now()
            or self.executed_at and (self.executed_at > timezone.now() or not self.approved_at
                                     or self.executed_at < self.approved_at)):
            raise ValidationError("Record actual nonfuture approval and separate manual execution times.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Prospect changes require a new immutable human revision.")
        self.full_clean()
        return super().save(*args, **kwargs)


class LocalFeedbackReview(models.Model):
    """Independent customer-owned feedback; immutable human reply history, no provider write."""

    class State(models.TextChoices):
        DRAFT = "draft", "Unapproved human draft"
        REVIEW = "review", "Human review required"
        APPROVED = "approved", "Exact reviewed reply approved"
        REPORTED = "reported", "Manual execution reported, not verified"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="local_feedback_reviews")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="local_feedback_reviews")
    source_actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="local_feedback_sources")
    assessment = models.ForeignKey(LocalBusinessAssessment, on_delete=models.PROTECT)
    verification = models.ForeignKey("tenancy.ProjectOriginVerification", on_delete=models.PROTECT)
    verified_at = models.DateTimeField()
    origin = models.CharField(max_length=512)
    feedback_id = models.UUIDField(default=uuid4)
    revision = models.PositiveIntegerField()
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    state = models.CharField(max_length=8, choices=State.choices)
    intake = models.JSONField()
    reason = models.CharField(max_length=500)
    reviewed_revision = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="approvals")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="local_feedback_approvals")
    approved_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    execution_note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "feedback_id", "revision"], name="jobs_unique_feedback_revision"),
            models.UniqueConstraint(fields=["project", "request_key"], name="jobs_unique_feedback_request"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_feedback_revision_positive"),
            models.CheckConstraint(condition=Q(state__in=["draft", "review", "approved", "reported"]), name="jobs_feedback_state_valid"),
            models.CheckConstraint(condition=(Q(state__in=["draft", "review"], reviewed_revision__isnull=True,
                approved_by__isnull=True, approved_at__isnull=True) | Q(state__in=["approved", "reported"],
                reviewed_revision__isnull=False, approved_by__isnull=False, approved_at__isnull=False)),
                name="jobs_feedback_exact_approval"),
            models.CheckConstraint(condition=(Q(state="reported", executed_at__isnull=False) & ~Q(execution_note=""))
                | (~Q(state="reported") & Q(executed_at__isnull=True, execution_note="")), name="jobs_feedback_manual_report"),
        ]

    def clean(self):
        from .local_feedback import _text, validate_local_feedback
        from django.utils import timezone
        validate_local_feedback(self.intake, approved_origin=self.origin)
        _text(self.reason, 500, required=True)
        _text(self.execution_note, 500, required=self.state == "reported")
        if (self.assessment.project_id != self.project_id or self.verification.project_id != self.project_id
            or self.verification.origin != self.origin or self.intake["assessment_id"] != self.assessment_id
            or self.intake["configuration_revision"] != self.assessment.configuration_revision):
            raise ValidationError("Feedback and its actual business/source evidence must share one project.")
        if self.state != "draft" and not self.intake["reply_draft"].strip():
            raise ValidationError("Review requires an actual human reply draft.")
        if self.reviewed_revision_id:
            reviewed = self.reviewed_revision
            if (reviewed.project_id != self.project_id or reviewed.feedback_id != self.feedback_id
                or reviewed.state != "review" or reviewed.revision >= self.revision
                or any(getattr(reviewed, key) != getattr(self, key) for key in
                       ("intake", "assessment_id", "verification_id", "verified_at", "origin", "source_actor_id"))):
                raise ValidationError("Approval must bind the exact reviewed source, target and text.")
        if (self.verified_at > timezone.now() or self.approved_at and self.approved_at > timezone.now()
            or self.executed_at and (self.executed_at > timezone.now() or not self.approved_at
                                     or self.executed_at < self.approved_at)):
            raise ValidationError("Record actual nonfuture source, approval and separate execution times.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Feedback changes require a new immutable review revision.")
        self.full_clean()
        return super().save(*args, **kwargs)


class LocalVisibilityObservation(models.Model):
    """Immutable customer-reported ordinal among inspected organic links, never universal rank."""
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="local_visibility_observations")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    assessment = models.ForeignKey(LocalBusinessAssessment, on_delete=models.PROTECT)
    verification = models.ForeignKey("tenancy.ProjectOriginVerification", on_delete=models.PROTECT)
    verified_at = models.DateTimeField()
    observation_id = models.UUIDField(default=uuid4)
    revision = models.PositiveIntegerField()
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    intake = models.JSONField()
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "observation_id", "revision"], name="jobs_unique_local_visibility_revision"),
            models.UniqueConstraint(fields=["project", "request_key"], name="jobs_unique_local_visibility_request"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_local_visibility_revision_positive"),
        ]

    def clean(self):
        from .local_feedback import _text
        from .local_visibility import validate_local_visibility
        validate_local_visibility(self.intake, approved_origin=self.verification.origin)
        _text(self.reason, 500, required=True)
        if (self.assessment.project_id != self.project_id or self.verification.project_id != self.project_id
            or self.intake["assessment_id"] != self.assessment_id
            or self.intake["configuration_revision"] != self.assessment.configuration_revision):
            raise ValidationError("Local observations and actual business/site evidence must share one project.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Local observations require a new immutable correction revision.")
        self.full_clean()
        return super().save(*args, **kwargs)


class AIVisibilityManualObservation(models.Model):
    """Append-only independently permitted human answer/evaluation; never provider-verified output."""
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="manual_visibility_observations")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    intent_review = models.ForeignKey(IntentClusterReview, on_delete=models.PROTECT)
    verification = models.ForeignKey("tenancy.ProjectOriginVerification", on_delete=models.PROTECT)
    verified_at = models.DateTimeField()
    observation_id = models.UUIDField(default=uuid4)
    revision = models.PositiveIntegerField()
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    intake = models.JSONField()
    context = models.JSONField()
    evaluated = models.BooleanField(default=False)
    matches = models.JSONField(default=list, blank=True)
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "observation_id", "revision"], name="jobs_manual_answer_revision"),
            models.UniqueConstraint(fields=["project", "request_key"], name="jobs_manual_answer_request"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_manual_answer_revision_positive"),
        ]

    def clean(self):
        from .visibility_manual import validate_manual_snapshot
        validate_manual_snapshot(self)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Manual answer corrections/evaluations require a new immutable revision.")
        self.full_clean()
        return super().save(*args, **kwargs)


class ProjectAlertPreference(models.Model):
    """Independent self-owned optional alert intent, not a sender or source policy."""
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    frequency = models.CharField(max_length=5, choices=[("off", "Off"), ("daily", "Daily")], default="off")
    crawl_failure = models.BooleanField(default=False)
    integration_health = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="jobs_alert_pref_project_user_unique"),
            models.CheckConstraint(condition=Q(frequency__in=["off", "daily"]), name="jobs_alert_pref_frequency_valid"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_alert_pref_revision_positive"),
            models.CheckConstraint(condition=Q(frequency="off") | Q(crawl_failure=True) | Q(integration_health=True),
                                   name="jobs_alert_pref_daily_source"),
        ]


class ProjectCruxAlertPreference(models.Model):
    """Separate own material-CrUX intent; no operational digest or sender authority."""
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    frequency = models.CharField(max_length=5, choices=[("off", "Off"), ("daily", "Daily")], default="off")
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="jobs_crux_pref_project_user_unique"),
            models.CheckConstraint(condition=Q(frequency__in=["off", "daily"]), name="jobs_crux_pref_frequency_valid"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_crux_pref_revision_positive"),
        ]


class ProjectSummaryPreference(models.Model):
    """Self-owned optional email intent; never enables account/billing mail or a sender."""
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    frequency = models.CharField(max_length=6, choices=[("off", "Off"), ("weekly", "Weekly")], default="off")
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="jobs_summary_pref_project_user_unique"),
            models.CheckConstraint(condition=Q(frequency__in=["off", "weekly"]), name="jobs_summary_pref_frequency_valid"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="jobs_summary_pref_revision_positive"),
        ]


class ProjectReportSnapshot(models.Model):
    """Private, bounded project report; artifacts are never public storage objects."""

    class Format(models.TextChoices):
        JSON = "json", "JSON"
        CSV = "csv", "CSV"

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="report_snapshots")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    content_format = models.CharField(max_length=4, choices=Format.choices)
    artifact_key = models.CharField(max_length=512, unique=True)
    content_sha256 = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    size_bytes = models.PositiveIntegerField()
    finding_ids = models.JSONField(default=list, blank=True)
    action_review_ids = models.JSONField(default=list, blank=True)
    outcome_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "request_key"], name="jobs_unique_project_report_request"),
            models.CheckConstraint(condition=Q(content_format__in=["json", "csv"]), name="jobs_report_format_valid"),
            models.CheckConstraint(condition=Q(size_bytes__gte=1, size_bytes__lte=131072),
                                   name="jobs_report_size_valid"),
        ]

    def clean(self):
        from tenancy.artifacts import project_artifact_scope
        if (self.project_id is None or self.created_by_id is None
            or not self.artifact_key.startswith(project_artifact_scope(self.project) + "/")
            or not self.artifact_key.endswith("." + self.content_format)
            or any(type(ids) is not list or len(ids) > 20
                   or any(type(item) is not int or item < 1 for item in ids) or len(set(ids)) != len(ids)
                   for ids in (self.finding_ids, self.action_review_ids, self.outcome_ids))
            or not any((self.finding_ids, self.action_review_ids, self.outcome_ids))):
            raise ValidationError("Report must use scoped, bounded project source references.")
        for ids, model in ((self.finding_ids, Finding), (self.action_review_ids, ActionReview),
                           (self.outcome_ids, ActionOutcomeSnapshot)):
            if model.objects.filter(pk__in=ids, project_id=self.project_id).count() != len(ids):
                raise ValidationError("Report source belongs to another project.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Report content and provenance are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class ProjectSummaryDelivery(models.Model):
    """One optional delivery identity per recipient/project/completed report week."""
    class State(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending (outcome pending)"
        SENT = "sent", "Transport accepted"
        SKIPPED = "skipped", "Skipped"
        UNKNOWN = "unknown", "Outcome unknown (never replayed)"

    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    preference = models.ForeignKey(ProjectSummaryPreference, on_delete=models.PROTECT)
    preference_revision = models.PositiveIntegerField()
    primary_address_id = models.PositiveBigIntegerField()
    report = models.ForeignKey(ProjectReportSnapshot, on_delete=models.PROTECT)
    week_start = models.DateField()
    source_metadata = models.JSONField()
    source_fingerprint = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    state = models.CharField(max_length=7, choices=State.choices, default=State.QUEUED)
    error_category = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    attempted_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "recipient", "week_start"], name="jobs_summary_delivery_week_unique"),
            models.CheckConstraint(condition=Q(preference_revision__gte=1, primary_address_id__gte=1),
                                   name="jobs_summary_delivery_binding_positive"),
            models.CheckConstraint(condition=Q(state__in=["queued", "sending", "sent", "skipped", "unknown"]),
                                   name="jobs_summary_delivery_state_valid"),
            models.CheckConstraint(condition=(Q(state="queued", attempted_at__isnull=True, sent_at__isnull=True)
                | Q(state__in=["sending", "skipped", "unknown"], attempted_at__isnull=False, sent_at__isnull=True)
                | Q(state="sent", attempted_at__isnull=False, sent_at__isnull=False)),
                name="jobs_summary_delivery_timestamps"),
        ]

    def clean(self):
        if (self.preference.project_id != self.project_id or self.preference.user_id != self.recipient_id
            or self.report.project_id != self.project_id or self.week_start.weekday() != 0):
            raise ValidationError("Weekly delivery needs original same-project recipient and source.")


class ProjectAlertDelivery(models.Model):
    """One optional operational digest per recipient/project/completed UTC day."""
    State = ProjectSummaryDelivery.State

    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    preference = models.ForeignKey(ProjectAlertPreference, on_delete=models.PROTECT)
    preference_revision = models.PositiveIntegerField()
    primary_address_id = models.PositiveBigIntegerField()
    day_start = models.DateField()
    source_metadata = models.JSONField()
    source_fingerprint = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    state = models.CharField(max_length=7, choices=State.choices, default=State.QUEUED)
    error_category = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    attempted_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "recipient", "day_start"], name="jobs_alert_delivery_day_unique"),
            models.CheckConstraint(condition=Q(preference_revision__gte=1, primary_address_id__gte=1),
                                   name="jobs_alert_delivery_binding_positive"),
            models.CheckConstraint(condition=Q(state__in=["queued", "sending", "sent", "skipped", "unknown"]),
                                   name="jobs_alert_delivery_state_valid"),
            models.CheckConstraint(condition=(Q(state="queued", attempted_at__isnull=True, sent_at__isnull=True)
                | Q(state__in=["sending", "skipped", "unknown"], attempted_at__isnull=False, sent_at__isnull=True)
                | Q(state="sent", attempted_at__isnull=False, sent_at__isnull=False)),
                name="jobs_alert_delivery_timestamps"),
        ]

    def clean(self):
        from .alert_digest_source import _fingerprint
        if (self.preference.project_id != self.project_id or self.preference.user_id != self.recipient_id
            or type(self.source_metadata) is not dict or set(self.source_metadata) != {"source", "claimed_episodes"}
            or type(self.source_metadata["source"]) is not dict):
            raise ValidationError("Daily delivery needs original same-project recipient and source.")
        keys = self.source_metadata["claimed_episodes"]
        if (type(keys) is not list or not 1 <= len(keys) <= 40 or any(type(key) is not str for key in keys)
            or len(set(keys)) != len(keys)):
            raise ValidationError("Daily delivery needs bounded unique original episode claims.")
        for key in keys:
            RegexValidator(r"^(crawl:[1-9][0-9]*|reconnect:[1-9][0-9]*:[1-9][0-9]*)$")(key)
        _fingerprint(self.source_metadata)


class ProjectAlertEpisodeClaim(models.Model):
    """Consumed related episode; all parent states retain it until customer erasure."""
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    delivery = models.ForeignKey(ProjectAlertDelivery, on_delete=models.PROTECT)
    episode_key = models.CharField(max_length=64, validators=[
        RegexValidator(r"^(crawl:[1-9][0-9]*|reconnect:[1-9][0-9]*:[1-9][0-9]*)$")])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "recipient", "episode_key"], name="jobs_alert_episode_unique"),
            models.CheckConstraint(condition=Q(episode_key__regex=r"^(crawl:[1-9][0-9]*|reconnect:[1-9][0-9]*:[1-9][0-9]*)$"),
                                   name="jobs_alert_episode_key_valid"),
        ]

    def clean(self):
        if self.delivery.project_id != self.project_id or self.delivery.recipient_id != self.recipient_id:
            raise ValidationError("Episode claims must stay in their original delivery scope.")


class ProjectCruxAlertDelivery(models.Model):
    """Independent material CrUX digest identity, never operational alert consent."""
    State = ProjectSummaryDelivery.State

    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    preference = models.ForeignKey(ProjectCruxAlertPreference, on_delete=models.PROTECT)
    preference_revision = models.PositiveIntegerField()
    primary_address_id = models.PositiveBigIntegerField()
    day_start = models.DateField()
    source_metadata = models.JSONField()
    source_fingerprint = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    state = models.CharField(max_length=7, choices=State.choices, default=State.QUEUED)
    error_category = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    attempted_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "recipient", "day_start"], name="jobs_crux_delivery_day_unique"),
            models.CheckConstraint(condition=Q(preference_revision__gte=1, primary_address_id__gte=1),
                                   name="jobs_crux_delivery_binding_positive"),
            models.CheckConstraint(condition=Q(state__in=["queued", "sending", "sent", "skipped", "unknown"]),
                                   name="jobs_crux_delivery_state_valid"),
            models.CheckConstraint(condition=(Q(state="queued", attempted_at__isnull=True, sent_at__isnull=True)
                | Q(state__in=["sending", "skipped", "unknown"], attempted_at__isnull=False, sent_at__isnull=True)
                | Q(state="sent", attempted_at__isnull=False, sent_at__isnull=False)), name="jobs_crux_delivery_timestamps"),
        ]

    def clean(self):
        from .crux_history_source import _encoded
        if (self.preference.project_id != self.project_id or self.preference.user_id != self.recipient_id
            or type(self.source_metadata) is not dict or set(self.source_metadata) != {"source", "claimed_episodes"}
            or type(self.source_metadata["source"]) is not dict):
            raise ValidationError("CrUX delivery needs original same-project recipient and source.")
        keys = self.source_metadata["claimed_episodes"]
        if (type(keys) is not list or not 1 <= len(keys) <= 300 or any(type(key) is not str for key in keys)
            or len(set(keys)) != len(keys)):
            raise ValidationError("CrUX delivery needs bounded unique original period claims.")
        for key in keys:
            RegexValidator(r"^crux:[0-9a-f]{64}$")(key)
        _encoded(self.source_metadata)


class ProjectCruxEpisodeClaim(models.Model):
    """Consumed genuine observed metric/period pair, including skipped/unknown mail."""
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    delivery = models.ForeignKey(ProjectCruxAlertDelivery, on_delete=models.PROTECT)
    episode_key = models.CharField(max_length=69, validators=[RegexValidator(r"^crux:[0-9a-f]{64}$")])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "recipient", "episode_key"], name="jobs_crux_episode_unique"),
            models.CheckConstraint(condition=Q(episode_key__regex=r"^crux:[0-9a-f]{64}$"), name="jobs_crux_episode_key_valid"),
        ]

    def clean(self):
        if self.delivery.project_id != self.project_id or self.delivery.recipient_id != self.recipient_id:
            raise ValidationError("CrUX claims must stay in their original delivery scope.")


class ProjectReportShare(models.Model):
    """Digest-only bounded bearer link to one private project report."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="report_shares")
    report = models.ForeignKey(ProjectReportSnapshot, on_delete=models.PROTECT, related_name="shares")
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=64, validators=[RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")])
    token_digest = models.CharField(max_length=64, unique=True, validators=[RegexValidator(r"^[0-9a-f]{64}$")], editable=False)
    intended_recipient = models.EmailField()
    expires_at = models.DateTimeField()
    disclosure_confirmed_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "request_key"], name="jobs_unique_project_share_request"),
            models.CheckConstraint(condition=Q(expires_at__gt=models.F("created_at")),
                                   name="jobs_share_expires_after_issue"),
        ]

    def clean(self):
        if not self.project_id or not self.report_id or self.report.project_id != self.project_id:
            raise ValidationError("Shares are limited to an owned private project report.")
        if self.expires_at and self.disclosure_confirmed_at and self.expires_at <= self.disclosure_confirmed_at:
            raise ValidationError("A share must expire after link disclosure.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = ProjectReportShare.objects.get(pk=self.pk)
            if any(getattr(self, field) != getattr(previous, field) for field in (
                "project_id", "report_id", "creator_id", "request_key", "token_digest", "intended_recipient",
                "expires_at", "disclosure_confirmed_at", "created_at",
            )) or previous.revoked_at is not None or self.revoked_at is None:
                raise ValidationError("Only one irreversible share revocation is allowed.")
        self.full_clean()
        return super().save(*args, **kwargs)
