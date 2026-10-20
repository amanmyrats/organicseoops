"""Separately authorized retained first-active provenance, never current paid authority."""
import hashlib
import json
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.staff_access import require_staff_permissions
from .models import AuditEvent, AuditEventType, Organization, PaddleEnvironment, PaddleFirstActiveObservation
from .paddle_activation import OBSERVATION_FIELDS, OBSERVATION_METHOD, _first_active_history_dependencies, _first_active_observation_history
from .paddle_checkout_delivery import checkout_source_digest
from .staff_checkout_link_investigation import _original_date
from .staff_subscription_investigation import _date
from .support_requests import _safe_id


METHOD = "exact-staff-retained-first-active-v1"
SCOPE = "historical_first_active_server_observation_not_current_paid_provider_activation_lifetime_conversion_or_retry_authority"
REASONS = {"customer_request", "investigation"}
SOURCE_FIELDS = {"method", "organization_id", "tracking_started_at", "attempt_id", "attempt_created_at",
    "attempt_sent_at", "request_actor_id", "environment", "offer_version", "product_id", "price_id", "transaction_id",
    "customer_id", "provider_subscription_id", "currency_code", "payment_verified_at", "payment_audit_id",
    "payment_audited_at", "payment_receipt", "subscription_verified_at", "subscription_audit_id",
    "subscription_audited_at", "reconciliation_receipt", "period_starts_at", "period_ends_at", "observed_at", "interpretation"}
RECEIPT_FIELDS = {"id", "event_id", "event_type", "entity_id", "raw_digest", "occurred_at", "received_at", "claimed_at", "processed_at"}


def require_first_active_staff(request):
    return require_staff_permissions(request, permissions=("tenancy.view_organization", "tenancy.view_paddlefirstactiveobservation"))


def _source(organization_id, observation_id):
    row = PaddleFirstActiveObservation.objects.filter(pk=observation_id, organization_id=organization_id).values(*OBSERVATION_FIELDS).first()
    org = Organization.objects.filter(pk=organization_id).order_by("pk").values(
        "id", "created_at", "paid_activation_tracking", "is_suspended", "closed_at").first()
    if row is None or org is None: raise PermissionDenied
    return {"observation": row, "organization": org}


def _record(source, assessed):
    row, org = source["observation"], source["organization"]
    original = row["source"]
    for identity in (row["id"], row["organization_id"], row["attempt_id"], row["receipt_id"], org["id"]): _safe_id(identity)
    if (row["organization_id"] != org["id"] or org["paid_activation_tracking"] != OBSERVATION_METHOD
        or type(org["is_suspended"]) is not bool or not _date(org["created_at"]) or org["created_at"] > assessed
        or org["closed_at"] is not None and (not _date(org["closed_at"]) or not org["is_suspended"]
            or not org["created_at"] <= org["closed_at"] <= assessed)
        or not _date(row["observed_at"]) or row["observed_at"] > assessed
        or type(original) is not dict or set(original) != SOURCE_FIELDS):
        raise ValidationError("Retained first active observation needs review.")
    for key in ("organization_id", "attempt_id", "request_actor_id", "payment_audit_id", "subscription_audit_id"): _safe_id(original[key])
    if (original["method"] != OBSERVATION_METHOD or original["organization_id"] != org["id"]
        or original["attempt_id"] != row["attempt_id"] or original["environment"] not in PaddleEnvironment.values
        or original["offer_version"] != "agency-launch-v1"
        or original["interpretation"] != "first_prospectively_tracked_active_server_observation_not_provider_activation_time"
        or any(type(original[key]) is not str or not re.fullmatch(pattern, original[key]) for key, pattern in (
            ("product_id", r"pro_[a-z0-9]{26}"), ("price_id", r"pri_[a-z0-9]{26}"), ("transaction_id", r"txn_[a-z0-9]{26}"),
            ("customer_id", r"ctm_[a-z0-9]{26}"), ("provider_subscription_id", r"sub_[a-z0-9]{26}"), ("currency_code", r"[A-Z]{3}")))
        or type(row["source_digest"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", row["source_digest"])
        or row["source_digest"] != checkout_source_digest(original)):
        raise ValidationError("Original first active source needs review.")
    dates = {key: _original_date(original[key]) for key in SOURCE_FIELDS if key.endswith("_at")}
    receipts = {}
    for key in ("payment_receipt", "reconciliation_receipt"):
        receipt = original[key]
        if type(receipt) is not dict or set(receipt) != RECEIPT_FIELDS:
            raise ValidationError("Original signed first active receipts need review.")
        _safe_id(receipt["id"])
        if any(type(receipt[field]) is not str or not re.fullmatch(pattern, receipt[field]) for field, pattern in (
            ("event_id", r"evt_[a-z0-9]{26}"), ("raw_digest", r"[a-f0-9]{64}"), ("entity_id", r"(?:txn|sub)_[a-z0-9]{26}"))):
            raise ValidationError("Original signed first active identity needs review.")
        event = receipt["event_type"]
        if (type(event) is not str or not re.fullmatch(r"subscription\.[a-z_]{1,40}|transaction\.(?:paid|completed|payment_failed|past_due)", event)
            or key == "payment_receipt" and event not in {"transaction.paid", "transaction.completed"}):
            raise ValidationError("Original signed first active category needs review.")
        receipts[key] = {field: _original_date(receipt[field]) for field in RECEIPT_FIELDS if field.endswith("_at")}
    paid, reconciled = receipts["payment_receipt"], receipts["reconciliation_receipt"]
    observed = row["observed_at"]
    if (dates["tracking_started_at"] != org["created_at"] or dates["observed_at"] != observed
        or original["reconciliation_receipt"]["id"] != row["receipt_id"]
        or original["payment_receipt"]["entity_id"] != original["transaction_id"]
        or original["reconciliation_receipt"]["event_type"].startswith("subscription.")
            and original["reconciliation_receipt"]["entity_id"] != original["provider_subscription_id"]
        or original["reconciliation_receipt"]["event_type"].startswith("transaction.")
            and not original["reconciliation_receipt"]["entity_id"].startswith("txn_")
        or any(value > assessed for key, value in dates.items() if key != "period_ends_at")
        or any(value > assessed for value in (*paid.values(), *reconciled.values()))
        or not org["created_at"] <= dates["attempt_created_at"] <= dates["attempt_sent_at"] <= dates["payment_verified_at"]
        or not paid["received_at"] <= paid["claimed_at"] <= dates["payment_verified_at"] <= dates["payment_audited_at"] <= paid["processed_at"]
        or not paid["processed_at"] <= dates["subscription_verified_at"] <= dates["subscription_audited_at"] <= observed
        or not reconciled["received_at"] <= reconciled["claimed_at"] <= dates["subscription_verified_at"]
        or reconciled["processed_at"] != observed or not dates["period_starts_at"] <= observed < dates["period_ends_at"]):
        raise ValidationError("Original first active dates and linkage need review.")
    return {"id": row["id"], "attempt_id": row["attempt_id"], "observed_at": observed.isoformat(),
        "provider_occurred_at": original["reconciliation_receipt"]["occurred_at"], "environment": original["environment"],
        "offer_version": original["offer_version"], "currency_code": original["currency_code"], "original_source_digest": row["source_digest"]}


def _projection(organization_id, observation_id):
    original = _source(organization_id, observation_id)
    observation = _record(original, timezone.now())
    saved = PaddleFirstActiveObservation.objects.filter(pk=observation_id, organization_id=organization_id).first()
    if saved is None or {field: getattr(saved, field) for field in OBSERVATION_FIELDS} != original["observation"]:
        raise ValidationError("Original first active capture changed during inspection.")
    dependencies = _first_active_history_dependencies(saved)
    attempt = dependencies[0]
    if (attempt is None or any(saved.source[field] != attempt[field] for field in ("product_id", "price_id"))
        or saved.source["attempt_created_at"] != attempt["created_at"].isoformat()
        or attempt["sent_at"] is None or saved.source["attempt_sent_at"] != attempt["sent_at"].isoformat()):
        raise ValidationError("Original first active checkout provenance needs review.")
    history = _first_active_observation_history(saved.organization)
    if (history["state"] != "recorded" or history["observation"]["source_digest"] != observation["original_source_digest"]
        or history["observation"]["observed_at"] != observation["observed_at"]
        or _source(organization_id, observation_id) != original or _first_active_history_dependencies(saved) != dependencies):
        raise ValidationError("Retained first active provenance changed during inspection.")
    digest = hashlib.sha256(json.dumps({**original, "dependencies": dependencies}, sort_keys=True,
        separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()
    return {"method_version": METHOD, "organization_id": organization_id, "scope": SCOPE,
            "observation": observation, "source_digest": digest}


def require_staff_first_active_delivery(*, request, original):
    require_first_active_staff(request)
    if _projection(original["organization_id"], original["observation"]["id"]) != original:
        raise ValidationError("Retained first active source changed before delivery.")
    require_first_active_staff(request)


def inspect_staff_first_active(*, request, organization_id, observation_id, reason):
    for identity in (organization_id, observation_id): _safe_id(identity)
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Choose a categorical first active investigation reason.")
    actor = require_first_active_staff(request)
    with transaction.atomic():
        if not Organization.objects.select_for_update().filter(pk=organization_id).order_by("pk").values_list("pk", flat=True).first():
            raise PermissionDenied
        result = _projection(organization_id, observation_id)
        AuditEvent.objects.create(organization_id=organization_id, actor=actor,
            event_type=AuditEventType.STAFF_FIRST_ACTIVE_INSPECTED, details={"observation_id": observation_id, "reason": reason})
        require_staff_first_active_delivery(request=request, original=result)
        return result
