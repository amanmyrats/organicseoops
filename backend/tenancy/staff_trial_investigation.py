"""Retained trial scalars, never effective entitlement, usage or correction authority."""
import hashlib
import json
from datetime import datetime

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.staff_access import require_staff_permissions
from .models import AutomaticTrialEligibility, AuditEvent, AuditEventType, Organization, OrganizationTrial, TrialState
from .support_requests import _safe_id


METHOD = "exact-staff-retained-organization-trial-v1"
SCOPE = "recorded_trial_not_effective_paid_access_remaining_usage_activation_extension_history_or_correction_authority"
REASONS = {"customer_request", "investigation"}
FIELDS = ("id", "organization_id", "automatic_eligibility_id", "offer_version", "state", "started_at", "ends_at",
          "project_limit", "member_limit", "unit_limit", "created_at", "updated_at")


def require_trial_staff(request):
    return require_staff_permissions(request, permissions=("tenancy.view_organization", "tenancy.view_organizationtrial",
                                                          "tenancy.view_automatictrialeligibility"))


def _date(value):
    return isinstance(value, datetime) and not timezone.is_naive(value)


def _source(organization_id, trial_id):
    trial = OrganizationTrial.objects.filter(pk=trial_id, organization_id=organization_id).values(*FIELDS).first()
    organization = Organization.objects.filter(pk=organization_id).order_by("pk").values("id", "is_suspended", "closed_at", "created_at").first()
    if trial is None or organization is None:
        raise PermissionDenied
    eligibility = AutomaticTrialEligibility.objects.filter(pk=trial["automatic_eligibility_id"]).values(
        "id", "user_id", "organization_id", "offer_version", "granted_at").first()
    return {"trial": trial, "organization": organization, "eligibility": eligibility}


def _record(source, assessed):
    row, org, eligibility = (source[key] for key in ("trial", "organization", "eligibility"))
    for identity in (row["id"], row["organization_id"], org["id"]): _safe_id(identity)
    pending = row["state"] == TrialState.PENDING_REVIEW
    if (row["organization_id"] != org["id"] or type(org["is_suspended"]) is not bool
        or not _date(org["created_at"]) or not _date(row["created_at"]) or not _date(row["updated_at"])
        or not org["created_at"] <= row["created_at"] <= row["updated_at"] <= assessed
        or org["closed_at"] is not None and (not _date(org["closed_at"]) or not org["is_suspended"]
            or not org["created_at"] <= org["closed_at"] <= assessed)
        or row["state"] not in TrialState.values
        or type(row["offer_version"]) is not str or not row["offer_version"].strip() or len(row["offer_version"]) > 64
        or any(type(row[key]) is not int or not 1 <= row[key] <= maximum for key, maximum in (
            ("project_limit", 32767), ("member_limit", 32767), ("unit_limit", 2147483647)))
        or pending and any(row[key] is not None for key in ("started_at", "ends_at", "automatic_eligibility_id"))
        or not pending and (not _date(row["started_at"]) or not _date(row["ends_at"])
            or not org["created_at"] <= row["started_at"] <= row["updated_at"]
            or row["ends_at"] <= row["started_at"])):
        raise ValidationError("Retained trial observation needs review.")
    if row["automatic_eligibility_id"] is not None:
        _safe_id(row["automatic_eligibility_id"])
        if (eligibility is None or eligibility["id"] != row["automatic_eligibility_id"]
            or eligibility["organization_id"] != org["id"] or eligibility["offer_version"] != row["offer_version"]
            or not _date(eligibility["granted_at"]) or eligibility["granted_at"] != row["started_at"]
            or eligibility["granted_at"] > row["created_at"]):
            raise ValidationError("Retained trial eligibility linkage needs review.")
        _safe_id(eligibility["id"]); _safe_id(eligibility["user_id"])
    elif eligibility is not None:
        raise ValidationError("Retained trial eligibility linkage needs review.")
    return {key: row[key].isoformat() if key.endswith("_at") and row[key] is not None else row[key]
            for key in FIELDS if key not in {"organization_id", "automatic_eligibility_id"}}


def _projection(organization_id, trial_id):
    original = _source(organization_id, trial_id)
    trial = _record(original, timezone.now())
    digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()
    result = {"method_version": METHOD, "organization_id": organization_id, "scope": SCOPE,
              "trial": trial, "source_digest": digest}
    if _source(organization_id, trial_id) != original:
        raise ValidationError("Retained trial changed during inspection.")
    return result


def require_staff_trial_delivery(*, request, original):
    require_trial_staff(request)
    if _projection(original["organization_id"], original["trial"]["id"]) != original:
        raise ValidationError("Retained trial changed before delivery.")
    require_trial_staff(request)


def inspect_staff_trial(*, request, organization_id, trial_id, reason):
    for identity in (organization_id, trial_id): _safe_id(identity)
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Choose a categorical trial investigation reason.")
    actor = require_trial_staff(request)
    with transaction.atomic():
        if not Organization.objects.select_for_update().filter(pk=organization_id).order_by("pk").values_list("pk", flat=True).first():
            raise PermissionDenied
        result = _projection(organization_id, trial_id)
        AuditEvent.objects.create(organization_id=organization_id, actor=actor, event_type=AuditEventType.STAFF_TRIAL_INSPECTED,
            details={"trial_id": trial_id, "reason": reason, "state": result["trial"]["state"]})
        require_staff_trial_delivery(request=request, original=result)
        return result
