"""Original nullable AI observations; no provider request, pricing or billing authority."""
import hashlib
import json
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.staff_access import require_staff_permissions
from tenancy.models import AuditEvent, AuditEventType, Organization, Project
from tenancy.support_requests import _safe_id
from .models import AIUsageRecord, JobRun
from .staff_job_investigation import JOB_FIELDS, REASONS, _scope
from .support_job_reference import _row as job_reference_row


METHOD = "scoped-staff-ai-observation-v1"
SCOPE = "original_ai_observations_not_current_pricing_invoices_customer_charges_or_correction_authority"
AI_JOB_FIELDS = (*JOB_FIELDS, "handler", "method_version")
OPERATIONS = {("ai_text", "ai-text-v2"), ("research_topic", "research-v1"),
              ("classify_competitor_heading_topics", "competitor-heading-topics-v1"),
              ("synthesize_competitor_pair", "competitor-static-synthesis-v1"), ("synthesize_competitor_headings_pair", "competitor-heading-synthesis-v1"),
              ("generate_content", "content-generation-v1"), ("sample_ai_visibility", "visibility-text-collection-v1")}
FIELDS = ("id", "job_id", "organization_id", "project_id", "step_id", "step__job_id", "step__sequence",
          "step__created_at", "operation_version", "provider_id", "model_id", "model__provider_id",
          "account_id", "account__provider_id", "account__organization_id", "status", "input_tokens",
          "output_tokens", "duration_ms", "estimated_cost_usd", "reported_cost_usd", "attempted_at", "finished_at")


def require_ai_usage_staff(request):
    return require_staff_permissions(request, permissions=("jobs.view_jobrun", "jobs.view_aiusagerecord"))


def _cost(value):
    if value is None: return None
    if (type(value) is not Decimal or not value.is_finite() or not 0 <= value < 1_000_000
        or value.as_tuple().exponent < -6):
        raise ValidationError("Recorded AI currency observation needs review.")
    return format(value, ".6f")


def _observation(row, job, assessed):
    if row is None: return None
    for key in ("id", "step_id", "provider_id", "model_id", "account_id"): _safe_id(row[key])
    if ((job["handler"], job["method_version"]) not in OPERATIONS
        or row["operation_version"] != job["method_version"]
        or row["job_id"] != job["id"] or row["step__job_id"] != job["id"] or row["step__sequence"] != 1
        or any(row[key] != job[key] for key in ("organization_id", "project_id"))
        or row["model__provider_id"] != row["provider_id"] or row["account__provider_id"] != row["provider_id"]
        or row["account__organization_id"] not in (None, job["organization_id"])
        or row["status"] not in AIUsageRecord.Status.values
        or any(row[key] is not None and (type(row[key]) is not int or not 0 <= row[key] <= bound)
               for key, bound in (("input_tokens", 100_000_000), ("output_tokens", 100_000_000), ("duration_ms", 120_000)))
        or timezone.is_naive(row["step__created_at"]) or timezone.is_naive(row["attempted_at"])
        or not job["created_at"] <= row["step__created_at"] <= row["attempted_at"] <= assessed
        or (row["status"] == "attempted") != (row["finished_at"] is None)
        or row["finished_at"] is not None and (timezone.is_naive(row["finished_at"])
            or not row["attempted_at"] <= row["finished_at"] <= assessed)):
        raise ValidationError("Recorded AI observation binding needs review.")
    return {"status": row["status"], "input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"],
            "duration_ms": row["duration_ms"], "estimated_cost_usd": _cost(row["estimated_cost_usd"]),
            "reported_cost_usd": _cost(row["reported_cost_usd"]), "attempted_at": row["attempted_at"].isoformat(),
            "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None}


def _projection(organization_id, project_id, job_id):
    assessed = timezone.now()
    jobs = JobRun.objects.filter(pk=job_id, organization_id=organization_id, project_id=project_id,
        project__organization_id=organization_id).values(*AI_JOB_FIELDS)
    original_job = jobs.first()
    if original_job is None: raise PermissionDenied
    job = job_reference_row(original_job, assessed)
    records = AIUsageRecord.objects.filter(job_id=job_id).values(*FIELDS)
    original = records.first()
    observation = _observation(original, original_job, assessed)
    digest = hashlib.sha256(json.dumps([original_job, original], sort_keys=True, separators=(",", ":"),
        default=str, allow_nan=False).encode()).hexdigest()
    result = {"method_version": METHOD, "project_id": project_id, "scope": SCOPE, "job": job,
              "state": "retained_ai_observation" if original else "unavailable_no_retained_ai_observation",
              "observation": observation, "source_digest": digest}
    if jobs.first() != original_job or records.first() != original:
        raise ValidationError("Recorded AI observations changed during inspection.")
    return result


def require_staff_ai_usage_delivery(*, request, organization_id, project_id, original):
    require_ai_usage_staff(request)
    _scope(organization_id, project_id)
    if _projection(organization_id, project_id, original["job"]["id"]) != original:
        raise ValidationError("Recorded AI observations changed before delivery.")
    _scope(organization_id, project_id)
    require_ai_usage_staff(request)


def inspect_staff_ai_usage(*, request, organization_id, project_id, job_id, reason):
    for identity in (organization_id, project_id, job_id): _safe_id(identity)
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Choose a categorical AI observation investigation reason.")
    actor = require_ai_usage_staff(request)
    _scope(organization_id, project_id)
    with transaction.atomic():
        Organization.objects.select_for_update().values_list("pk", flat=True).get(pk=organization_id)
        Project.objects.select_for_update().values_list("pk", flat=True).get(pk=project_id, organization_id=organization_id)
        _scope(organization_id, project_id)
        result = _projection(organization_id, project_id, job_id)
        AuditEvent.objects.create(organization_id=organization_id, project_id=project_id, actor=actor,
            event_type=AuditEventType.STAFF_AI_USAGE_INSPECTED, details={"job_id": job_id, "reason": reason,
                "state": result["observation"]["status"] if result["observation"] else "unavailable"})
        require_staff_ai_usage_delivery(request=request, organization_id=organization_id, project_id=project_id, original=result)
        return result
