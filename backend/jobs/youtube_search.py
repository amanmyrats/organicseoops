"""A bounded response-only search. Stored records never contain returned API data."""
from datetime import timedelta
import re
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from providers.models import YouTubeAPIKey
from providers.youtube_key import youtube_key
from tenancy.models import Organization, ProjectConfiguration
from .models import JobCancellation, JobRun, JobStatus
from .usage import UsageLimitError, reserve_usage, settle_usage, usage_denial
from .youtube import current_youtube_selection, parse_youtube_search, youtube_search_request, YouTubeSourceError

POLICY_VERSION = "youtube-response-only-v1"
MEMORY_SECONDS = 900
HANDLER = "search_youtube"


def youtube_quota_day(now):
    return now.astimezone(ZoneInfo("America/Los_Angeles")).date()


def _checkpoint(job):
    current = JobRun.objects.get(pk=job.pk)
    if current.status != JobStatus.RUNNING or JobCancellation.objects.filter(job=job).exists():
        raise YouTubeSourceError("cancelled")
    config = current_youtube_selection(job.project, job.actor, job.input_snapshot["selection"])
    if config.revision != job.config_snapshot["project_revision"]:
        raise YouTubeSourceError("project_configuration_changed")
    denied = usage_denial(job=job)
    if denied:
        raise UsageLimitError("Search allowance unavailable.", category=denied)
    youtube_key(job.config_snapshot["credential_revision"])
    if timezone.now() >= job.created_at + timedelta(seconds=60):
        raise YouTubeSourceError("request_expired")


def finish_youtube_attempt(job, *, error=""):
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=job.organization_id)
        current = JobRun.objects.select_for_update(no_key=True).get(pk=job.pk)
        if current.status != JobStatus.RUNNING:
            return False
        if not error:
            _checkpoint(current)
        current.status = JobStatus.FAILED if error else JobStatus.SUCCEEDED
        current.error_category = error
        current.save(update_fields=["status", "error_category", "updated_at"])
        settle_usage(job=current, actual_units=1)
        return True


@sensitive_variables()
def search_youtube(*, project, actor, selection, policy_version, accepted, request_key, transport=None):
    if (policy_version != POLICY_VERSION or accepted is not True or type(request_key) is not str
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", request_key)):
        raise ValidationError("Accept the current feature Terms/privacy and use a bounded request key.")
    current_youtube_selection(project, actor, selection)
    # Commit an operational attempt before network work. Never replay an uncertain request.
    with transaction.atomic():
        credential = YouTubeAPIKey.objects.select_for_update().filter(key="primary", state="active").first()
        if credential is None:
            raise YouTubeSourceError("credential_unavailable")
        key = youtube_key(credential.rotated_at.isoformat())
        Organization.objects.select_for_update().get(pk=project.organization_id)
        config = current_youtube_selection(project, actor, selection)
        if JobRun.objects.filter(project=project, handler=HANDLER, idempotency_key=request_key).exists():
            raise YouTubeSourceError("request_already_attempted")
        if JobRun.objects.filter(handler=HANDLER, status=JobStatus.RUNNING).exists():
            raise YouTubeSourceError("client_busy")
        day = youtube_quota_day(timezone.now())
        if credential.quota_day != day:
            credential.quota_day, credential.attempted_requests = day, 0
        if credential.attempted_requests >= credential.daily_limit:
            raise YouTubeSourceError("client_daily_quota")
        job = JobRun.objects.create(organization=project.organization, project=project, actor=actor,
            handler=HANDLER, method_version=POLICY_VERSION, idempotency_key=request_key,
            input_snapshot={"selection": selection, "policy_version": policy_version, "accepted": True},
            config_snapshot={"project_revision": config.revision, "credential_revision": credential.rotated_at.isoformat()})
        reserve_usage(job=job, provider="youtube_search", units=1)
        job.status = JobStatus.RUNNING
        job.save(update_fields=["status", "updated_at"])
        credential.attempted_requests += 1
        credential.save(update_fields=["quota_day", "attempted_requests"])
    try:
        _checkpoint(job)
        payload = (transport or youtube_search_request)(project=project, actor=actor, selection=selection,
            as_of=job.created_at, api_key=key, checkpoint=lambda: _checkpoint(job))
        parse_youtube_search(payload)
        if not finish_youtube_attempt(job):
            raise YouTubeSourceError("request_outcome_unknown")
        return {"project_id": project.pk, "job_id": job.pk, "source": "youtube",
            "requested": selection, "collected_at": timezone.now().isoformat(),
            "expires_at": (job.created_at + timedelta(seconds=MEMORY_SECONDS)).isoformat(),
            "page": payload, "estimated_units": 1, "actual_units": 1}
    except (YouTubeSourceError, PermissionDenied, ValidationError) as error:
        category = (error.category if isinstance(error, (YouTubeSourceError, UsageLimitError)) else
            "actor_or_source_revoked" if isinstance(error, PermissionDenied) else "credential_or_scope_unavailable")
        finish_youtube_attempt(job, error=category)
        raise
    except Exception:
        # Never log provider payloads, secret-bearing exception text or local variables.
        finish_youtube_attempt(job, error="request_outcome_unknown")
        raise YouTubeSourceError("request_outcome_unknown") from None
