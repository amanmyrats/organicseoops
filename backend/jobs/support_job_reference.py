"""Minimized retained job references for later scoped support, not source reuse or retry."""
from django.core.exceptions import ValidationError
from django.utils import timezone

from tenancy.services import Action, require_project_action
from .models import JobRun, JobStatus


METHOD = "retained-project-job-support-reference-v1"
SCOPE = "retained_operational_job_reference_not_completion_incident_seo_outcome_or_retry_authority"


def _row(row, assessed):
    if (type(row["id"]) is not int or not 1 <= row["id"] < 2**53 or row["status"] not in JobStatus.values
        or any(timezone.is_naive(row[key]) or row[key] > assessed for key in ("created_at", "updated_at"))
        or row["updated_at"] < row["created_at"]):
        raise ValidationError("Retained job reference needs review.")
    return {"id": row["id"], "status": row["status"], "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat()}


def retained_project_job_reference(*, project, actor, job_id):
    if type(job_id) is not int or not 1 <= job_id < 2**53:
        raise ValidationError("Choose one exact retained project job.")
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    assessed = timezone.now()
    queryset = JobRun.objects.filter(pk=job_id, project_id=project.pk, organization_id=project.organization_id).values(
        "id", "project_id", "organization_id", "status", "created_at", "updated_at")
    original = queryset.first()
    result = {"method_version": METHOD, "project_id": project.pk, "scope": SCOPE,
              "state": "retained_job_reference" if original else "unavailable_no_retained_project_job",
              "job": _row(original, assessed) if original else None}
    if queryset.first() != original:
        raise ValidationError("Retained job reference changed during inspection.")
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    return result
