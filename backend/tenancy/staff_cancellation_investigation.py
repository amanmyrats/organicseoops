"""Retained closure cancellation attempt, never current paid/deletion or replay authority."""
import hashlib
import json
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.staff_access import require_staff_permissions
from .models import AuditEvent, AuditEventType, Organization, OrganizationBillingCancellation, PaddleEnvironment
from .staff_subscription_investigation import _date
from .support_requests import _safe_id


METHOD = "exact-staff-retained-closure-cancellation-v1"
SCOPE = "recorded_closure_attempt_not_current_paid_access_identity_deletion_eligibility_or_retry_authority"
REASONS = {"customer_request", "investigation"}
FIELDS = ("id", "organization_id", "subscription_id", "actor_id", "environment", "customer_id",
          "provider_subscription_id", "state", "attempted_at", "confirmed_at", "error_category", "created_at")
CATEGORIES = {"provider_unconfirmed", "credential_unavailable", "redirect_denied", "authorization_unavailable",
              "catalog_unavailable", "quota_limited", "provider_unavailable", "provider_request_rejected",
              "malformed_response", "egress_denied", "timeout", "tls_verification_failed", "network_error", "dns_error"}


def require_cancellation_staff(request):
    return require_staff_permissions(request, permissions=("tenancy.view_organization", "tenancy.view_organizationbillingcancellation"))


def _source(organization_id, cancellation_id):
    cancellation = OrganizationBillingCancellation.objects.filter(pk=cancellation_id, organization_id=organization_id).values(*FIELDS).first()
    organization = Organization.objects.filter(pk=organization_id).order_by("pk").values("id", "is_suspended", "closed_at", "created_at").first()
    if cancellation is None or organization is None: raise PermissionDenied
    return {"cancellation": cancellation, "organization": organization}


def _record(source, assessed):
    row, org = source["cancellation"], source["organization"]
    for identity in (row["id"], row["organization_id"], row["subscription_id"], row["actor_id"], org["id"]): _safe_id(identity)
    if (row["organization_id"] != org["id"] or type(org["is_suspended"]) is not bool
        or not _date(org["created_at"]) or org["created_at"] > assessed
        or org["closed_at"] is not None and (not _date(org["closed_at"]) or not org["is_suspended"]
            or not org["created_at"] <= org["closed_at"] <= assessed)
        or row["environment"] not in PaddleEnvironment.values or row["state"] not in OrganizationBillingCancellation.State.values
        or any(type(row[key]) is not str or not re.fullmatch(pattern, row[key]) for key, pattern in (
            ("customer_id", r"ctm_[a-z0-9]{26}"), ("provider_subscription_id", r"sub_[a-z0-9]{26}")))
        or type(row["error_category"]) is not str or len(row["error_category"]) > 32
        or not _date(row["created_at"]) or row["created_at"] > assessed):
        raise ValidationError("Retained closure cancellation needs review.")
    state, attempted, confirmed = (row[key] for key in ("state", "attempted_at", "confirmed_at"))
    if (any(value is not None and not _date(value) for value in (attempted, confirmed))
        or (state == "reserved") != (attempted is None)
        or (state == "confirmed") != (confirmed is not None)
        or state != "unknown" and row["error_category"]
        or attempted is not None and not row["created_at"] <= attempted <= assessed
        or confirmed is not None and confirmed > assessed):
        raise ValidationError("Recorded cancellation dates need review.")
    # confirmed_at is the provider's cancellation date, not local observation time.
    category = (row["error_category"] if row["error_category"] in CATEGORIES else "unclassified_failure") if state == "unknown" else None
    return {"id": row["id"], "environment": row["environment"], "state": state, "error_category": category,
            **{key: row[key].isoformat() if row[key] is not None else None for key in ("created_at", "attempted_at", "confirmed_at")}}


def _projection(organization_id, cancellation_id):
    original = _source(organization_id, cancellation_id)
    cancellation = _record(original, timezone.now())
    digest = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()
    result = {"method_version": METHOD, "organization_id": organization_id, "scope": SCOPE,
              "cancellation": cancellation, "source_digest": digest}
    if _source(organization_id, cancellation_id) != original:
        raise ValidationError("Retained closure cancellation changed during inspection.")
    return result


def require_staff_cancellation_delivery(*, request, original):
    require_cancellation_staff(request)
    if _projection(original["organization_id"], original["cancellation"]["id"]) != original:
        raise ValidationError("Retained closure cancellation changed before delivery.")
    require_cancellation_staff(request)


def inspect_staff_cancellation(*, request, organization_id, cancellation_id, reason):
    for identity in (organization_id, cancellation_id): _safe_id(identity)
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Choose a categorical cancellation investigation reason.")
    actor = require_cancellation_staff(request)
    with transaction.atomic():
        if not Organization.objects.select_for_update().filter(pk=organization_id).order_by("pk").values_list("pk", flat=True).first():
            raise PermissionDenied
        result = _projection(organization_id, cancellation_id)
        AuditEvent.objects.create(organization_id=organization_id, actor=actor, event_type=AuditEventType.STAFF_CANCELLATION_INSPECTED,
            details={"cancellation_id": cancellation_id, "reason": reason, "state": result["cancellation"]["state"]})
        require_staff_cancellation_delivery(request=request, original=result)
        return result
