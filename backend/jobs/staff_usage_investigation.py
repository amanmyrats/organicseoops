"""Exact-scoped internal-unit history, never provider cost or entitlement correction."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.staff_access import require_staff_permissions
from tenancy.models import AuditEvent, AuditEventType, Organization, Project
from tenancy.support_requests import _safe_id
from .models import JobRun, UsageReservation
from .staff_job_investigation import JOB_FIELDS, REASONS, _scope
from .support_job_reference import _row as job_reference_row


METHOD = "scoped-staff-internal-unit-investigation-v1"
SCOPE = "recorded_internal_units_not_tokens_provider_currency_customer_charges_or_correction_authority"
FIELDS = ("id", "job_id", "organization_id", "project_id", "period_start", "state", "reserved_units", "actual_units", "created_at", "settled_at")


def require_usage_staff(request):
    return require_staff_permissions(request, permissions=("jobs.view_jobrun", "jobs.view_usagereservation"))


def _reservation(row, job, assessed):
    if row is None: return None
    _safe_id(row["id"])
    if (any(row[key] != job[key] for key in ("organization_id", "project_id")) or row["job_id"] != job["id"]
        or row["state"] not in UsageReservation.State.values
        or any(type(row[key]) is not int or not 0 <= row[key] <= 2**31 - 1 for key in ("reserved_units", "actual_units"))
        or row["period_start"].day != 1 or row["period_start"] > assessed.date()
        or timezone.is_naive(row["created_at"]) or not job["created_at"] <= row["created_at"] <= assessed
        or row["settled_at"] is not None and (timezone.is_naive(row["settled_at"]) or not row["created_at"] <= row["settled_at"] <= assessed)
        or row["state"] == "reserved" and (row["settled_at"] is not None or row["actual_units"] != 0)
        or row["state"] != "reserved" and row["settled_at"] is None
        or row["state"] == "released" and row["actual_units"] != 0
        or row["state"] == "settled" and row["actual_units"] == 0):
        raise ValidationError("Recorded internal-unit reservation needs review.")
    return {"state": row["state"], "period_start": row["period_start"].isoformat(),
            "reserved_units": row["reserved_units"], "actual_units": row["actual_units"],
            "created_at": row["created_at"].isoformat(), "settled_at": row["settled_at"].isoformat() if row["settled_at"] else None,
            "unit_meaning": "internal_units_not_provider_tokens_currency_or_customer_charges"}


def _projection(organization_id, project_id, job_id):
    assessed = timezone.now()
    jobs = JobRun.objects.filter(pk=job_id, organization_id=organization_id, project_id=project_id,
        project__organization_id=organization_id).values(*JOB_FIELDS)
    original_job = jobs.first()
    if original_job is None: raise PermissionDenied
    job = job_reference_row(original_job, assessed)
    reservations = UsageReservation.objects.filter(job_id=job_id).values(*FIELDS)
    original = reservations.first()
    reservation = _reservation(original, original_job, assessed)
    result = {"method_version": METHOD, "project_id": project_id, "scope": SCOPE, "job": job,
              "state": "retained_internal_unit_reservation" if original else "unavailable_no_retained_reservation", "reservation": reservation}
    if jobs.first() != original_job or reservations.first() != original:
        raise ValidationError("Recorded internal units changed during inspection.")
    return result


def require_staff_usage_delivery(*, request, organization_id, project_id, original):
    require_usage_staff(request)
    _scope(organization_id, project_id)
    if _projection(organization_id, project_id, original["job"]["id"]) != original:
        raise ValidationError("Recorded internal units changed before delivery.")
    _scope(organization_id, project_id)
    require_usage_staff(request)


def inspect_staff_usage(*, request, organization_id, project_id, job_id, reason):
    for identity in (organization_id, project_id, job_id): _safe_id(identity)
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Choose a categorical internal-unit investigation reason.")
    actor = require_usage_staff(request)
    _scope(organization_id, project_id)
    with transaction.atomic():
        Organization.objects.select_for_update().values_list("pk", flat=True).get(pk=organization_id)
        Project.objects.select_for_update().values_list("pk", flat=True).get(pk=project_id, organization_id=organization_id)
        _scope(organization_id, project_id)
        result = _projection(organization_id, project_id, job_id)
        AuditEvent.objects.create(organization_id=organization_id, project_id=project_id, actor=actor,
            event_type=AuditEventType.STAFF_USAGE_INSPECTED, details={"job_id": job_id, "reason": reason,
                "state": result["reservation"]["state"] if result["reservation"] else "unavailable"})
        require_staff_usage_delivery(request=request, organization_id=organization_id, project_id=project_id, original=result)
        return result
