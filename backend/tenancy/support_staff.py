"""Exact-scoped staff support with live permission/session assurance and payload-free audits."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.staff_access import require_staff_permissions

from .models import AuditEvent, AuditEventType, Organization, Project, SupportRequest, SupportRequestUpdate, retained_content_window
from .support_requests import FIELDS, _row, _safe_id, validate_support_command


UPDATE_FIELDS = ("id", "request_id", "staff_id", "revision", "status", "response", "request_key", "created_at")
REASONS = {"customer_request", "investigation", "accessibility"}


def require_support_staff(request, *, change=False):
    permissions = ("tenancy.view_supportrequest", "tenancy.change_supportrequest") if change else ("tenancy.view_supportrequest",)
    return require_staff_permissions(request, permissions=permissions)


def validate_staff_update(command):
    if (type(command) is not dict or set(command) != {"request_key", "expected_revision", "status", "response"}
        or type(command["expected_revision"]) is not int or not 0 <= command["expected_revision"] < 2**31 - 1
        or type(command["status"]) is not str or command["status"] not in {"received", "in_progress", "resolved"}):
        raise ValidationError("Choose one exact current support response.")
    validate_support_command({"request_key": command["request_key"], "category": "other", "question": command["response"],
                              "job_id": None, "no_sensitive_data": True})
    return dict(command)


def support_update_history(request_id, original_created, assessed, *, detail):
    queryset = SupportRequestUpdate.objects.filter(request_id=request_id).order_by("-revision").values(*UPDATE_FIELDS)
    original = list(queryset[:21])
    history = []
    previous_revision, later_date = None, assessed
    for row in original:
        _safe_id(row["id"])
        validate_staff_update(dict(request_key=row["request_key"], expected_revision=row["revision"] - 1,
                                   status=row["status"], response=row["response"]))
        if (timezone.is_naive(row["created_at"]) or not original_created <= row["created_at"] <= later_date
            or previous_revision is not None and row["revision"] != previous_revision - 1):
            raise ValidationError("Support response history needs review.")
        history.append({"revision": row["revision"], "status": row["status"], "response": row["response"],
                        "created_at": row["created_at"].isoformat()})
        previous_revision, later_date = row["revision"], row["created_at"]
    if original and len(original) <= 20 and original[-1]["revision"] != 1:
        raise ValidationError("Support response history is incomplete.")
    result = {"revision": original[0]["revision"] if original else 0, "status": original[0]["status"] if original else "received"}
    if detail:
        result.update(updates=history[:20], updates_has_more=len(original) > 20)
    if list(queryset[:21]) != original:
        raise ValidationError("Support responses changed during inspection.")
    return result


def _scope(organization_id, project_id):
    if not Project.objects.filter(pk=project_id, organization_id=organization_id,
        organization__is_suspended=False, organization__closed_at__isnull=True).filter(
            retained_content_window(organization_prefix="organization__")).exists():
        raise PermissionDenied


def inspect_staff_support(*, request, organization_id, project_id, request_id, reason, command=None):
    for identity in (organization_id, project_id, request_id): _safe_id(identity)
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Choose a categorical support access reason.")
    if command is not None: command = validate_staff_update(command)
    actor = require_support_staff(request, change=command is not None)
    _scope(organization_id, project_id)
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        project = Project.objects.select_for_update().get(pk=project_id, organization_id=organization_id)
        _scope(organization_id, project_id)
        queryset = SupportRequest.objects.filter(pk=request_id, project=project).values(*FIELDS)
        original = queryset.first()
        if original is None: raise PermissionDenied
        result = _row(original, timezone.now(), detail=True)
        before = support_update_history(request_id, original["created_at"], timezone.now(), detail=True)
        if command is not None:
            existing = SupportRequestUpdate.objects.filter(request_id=request_id, request_key=command["request_key"]).values(*UPDATE_FIELDS).first()
            if existing:
                if (existing["staff_id"] != actor.pk or existing["revision"] != command["expected_revision"] + 1
                    or existing["status"] != command["status"] or existing["response"] != command["response"]):
                    raise ValidationError("Support response key already belongs to another command.")
            else:
                if command["expected_revision"] != before["revision"]:
                    raise ValidationError("Refresh current support history before responding.")
                update = SupportRequestUpdate.objects.create(request_id=request_id, staff=actor,
                    revision=before["revision"] + 1, status=command["status"], response=command["response"], request_key=command["request_key"])
                AuditEvent.objects.create(organization=project.organization, project=project, actor=actor,
                    event_type=AuditEventType.SUPPORT_REQUEST_UPDATED,
                    details={"request_id": request_id, "reason": reason,
                             "before": {key: before[key] for key in ("status", "revision")},
                             "after": {"status": update.status, "revision": update.revision}})
        result.update(support_update_history(request_id, original["created_at"], timezone.now(), detail=True))
        AuditEvent.objects.create(organization=project.organization, project=project, actor=actor,
            event_type=AuditEventType.SUPPORT_REQUEST_ACCESSED,
            details={"request_id": request_id, "reason": reason, "status": result["status"], "revision": result["revision"]})
        if queryset.first() != original:
            raise ValidationError("Original support request changed during inspection.")
        _scope(organization_id, project_id)
        require_support_staff(request, change=command is not None)
        return {"method_version": "scoped-staff-support-request-v1", "project_id": project_id,
                "scope": "exact_support_request_not_job_export_billing_credential_or_impersonation_authority", "request": result}


def require_staff_support_delivery(*, request, organization_id, project_id, original):
    """Fence lazily rendered Admin bytes against the already audited original projection."""
    require_support_staff(request)
    _scope(organization_id, project_id)
    row = SupportRequest.objects.filter(pk=original["id"], project_id=project_id,
        project__organization_id=organization_id).values(*FIELDS).first()
    if row is None:
        raise PermissionDenied
    current = {**_row(row, timezone.now(), detail=True),
               **support_update_history(row["id"], row["created_at"], timezone.now(), detail=True)}
    if current != original:
        raise ValidationError("Support content changed before delivery.")
    _scope(organization_id, project_id)
    require_support_staff(request)
