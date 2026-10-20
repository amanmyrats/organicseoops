"""Minimized exact-scoped staff investigation; no customer payload or recovery authority."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.staff_access import require_staff_permissions
from tenancy.models import AuditEvent, AuditEventType, Organization, Project, retained_content_window
from tenancy.support_requests import _safe_id
from .models import JobRun, JobStep
from .support_job_reference import _row as job_reference_row


METHOD = "scoped-staff-job-investigation-v1"
SCOPE = "recorded_job_step_status_not_root_cause_retry_correction_usage_or_customer_payload_authority"
REASONS = {"customer_request", "investigation"}
JOB_FIELDS = ("id", "organization_id", "project_id", "status", "created_at", "updated_at")
STEP_FIELDS = ("sequence", "status", "progress_percent", "created_at")


def require_job_staff(request):
    return require_staff_permissions(request, permissions=("jobs.view_jobrun", "jobs.view_jobstep"))


def _scope(organization_id, project_id):
    if not Project.objects.filter(pk=project_id, organization_id=organization_id,
        organization__is_suspended=False, organization__closed_at__isnull=True).filter(
            retained_content_window(organization_prefix="organization__")).exists():
        raise PermissionDenied


def _projection(organization_id, project_id, job_id):
    assessed = timezone.now()
    jobs = JobRun.objects.filter(pk=job_id, organization_id=organization_id, project_id=project_id,
        project__organization_id=organization_id).values(*JOB_FIELDS)
    original_job = jobs.first()
    if original_job is None: raise PermissionDenied
    job = job_reference_row(original_job, assessed)
    steps = JobStep.objects.filter(job_id=job_id).order_by("sequence", "id").values(*STEP_FIELDS)
    original_steps = list(steps[:101])
    if len(original_steps) > 100:
        raise ValidationError("Complete bounded job steps are unavailable.")
    result_steps, previous = [], 0
    for row in original_steps:
        if (type(row["sequence"]) is not int or not previous < row["sequence"] <= 65535
            or row["status"] not in JobStep.Status.values or type(row["progress_percent"]) is not int
            or not 0 <= row["progress_percent"] <= 100 or timezone.is_naive(row["created_at"])
            or not original_job["created_at"] <= row["created_at"] <= assessed):
            raise ValidationError("Recorded job steps need review.")
        result_steps.append({**row, "created_at": row["created_at"].isoformat()})
        previous = row["sequence"]
    result = {"method_version": METHOD, "project_id": project_id, "scope": SCOPE, "job": job, "steps": result_steps}
    if jobs.first() != original_job or list(steps[:101]) != original_steps:
        raise ValidationError("Recorded job status changed during inspection.")
    return result


def require_staff_job_delivery(*, request, organization_id, project_id, original):
    """Recheck the complete audited projection before returning rendered bytes."""
    require_job_staff(request)
    _scope(organization_id, project_id)
    if _projection(organization_id, project_id, original["job"]["id"]) != original:
        raise ValidationError("Recorded job status changed before delivery.")
    _scope(organization_id, project_id)
    require_job_staff(request)


def inspect_staff_job(*, request, organization_id, project_id, job_id, reason):
    for identity in (organization_id, project_id, job_id): _safe_id(identity)
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Choose a categorical job investigation reason.")
    actor = require_job_staff(request)
    _scope(organization_id, project_id)
    with transaction.atomic():
        # Use the existing org-first lifecycle lock order without selecting customer fields.
        Organization.objects.select_for_update().values_list("pk", flat=True).get(pk=organization_id)
        Project.objects.select_for_update().values_list("pk", flat=True).get(pk=project_id, organization_id=organization_id)
        _scope(organization_id, project_id)
        result = _projection(organization_id, project_id, job_id)
        AuditEvent.objects.create(organization_id=organization_id, project_id=project_id, actor=actor,
            event_type=AuditEventType.STAFF_JOB_INSPECTED,
            details={"job_id": job_id, "reason": reason, "status": result["job"]["status"], "step_count": len(result["steps"])})
        require_staff_job_delivery(request=request, organization_id=organization_id, project_id=project_id, original=result)
        return result
