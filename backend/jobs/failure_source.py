"""Retained operational candidates, not incident, regression or delivery authority."""
from django.core.exceptions import ValidationError
from django.utils import timezone

from tenancy.services import Action, require_project_action
from .models import JobRun, JobStatus


METHOD = "retained-crawl-failures-v1"
SCOPE = "retained_failed_crawl_jobs_not_current_incident_regression_or_retry_authority"
_CATEGORIES = {"handler_failed", "crawl_deadline", "robots_unavailable", "crawl_incomplete"}


def _row(row, assessed):
    if (not 1 <= row["id"] < 2**53 or timezone.is_naive(row["created_at"])
        or timezone.is_naive(row["updated_at"]) or not row["created_at"] <= row["updated_at"] <= assessed):
        raise ValidationError("Retained crawl failure source needs review.")
    return {"job_id": row["id"], "source_method": row["method_version"],
            "created_at": row["created_at"].isoformat(), "status_updated_at": row["updated_at"].isoformat(),
            "failure_category": row["error_category"] if row["error_category"] in _CATEGORIES else "unclassified_failure"}


def retained_crawl_failures(*, project, actor):
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    assessed = timezone.now()
    queryset = JobRun.objects.filter(project_id=project.pk, organization_id=project.organization_id,
        handler="crawl_site", method_version__in=["crawl-http-v1", "crawl-http-v2"],
        status=JobStatus.FAILED, updated_at__lte=assessed).order_by("-updated_at", "-pk").values(
            "id", "method_version", "created_at", "updated_at", "error_category")
    rows = list(queryset[:21])
    result = {"method_version": METHOD, "project_id": project.pk, "scope": SCOPE,
              "assessed_at": assessed.isoformat(), "rows": [_row(row, assessed) for row in rows[:20]],
              "has_more": len(rows) > 20}
    if list(queryset[:21]) != rows:
        raise ValidationError("Retained crawl failure source changed during inspection.")
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    return result
