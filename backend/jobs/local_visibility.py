"""D126 offline customer-reported local organic observations; not a search/API collector."""
from datetime import datetime
import json
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from tenancy.models import normalize_origin
from .local_feedback import _text, validate_owned_website_url

METHOD = "local-manual-organic-v1"
SOURCE = "customer_manual_organic_observation"
MAX_BYTES = 16 * 1024
FIELDS = {"method_version", "source_kind", "platform", "surface", "assessment_id", "configuration_revision",
    "origin", "observation_reference", "query", "observed_at", "requested_location", "requested_language",
    "requested_device", "applied_location", "applied_language", "applied_device", "inspection_limit",
    "inspected_count", "status", "ordinal", "matched_url", "evidence_note", "storage_permission", "not_api_derived"}


def validate_local_visibility(data, *, approved_origin, as_of=None):
    """Scalar validation only. The future service must resolve real current business/source/actor authority."""
    as_of = timezone.now() if as_of is None else as_of
    if (not isinstance(as_of, datetime) or timezone.is_naive(as_of)
        or type(data) is not dict or set(data) != FIELDS
        or data["method_version"] != METHOD or data["source_kind"] != SOURCE
        or data["platform"] != "google_search" or data["surface"] != "organic_links"
        or data["storage_permission"] is not True or data["not_api_derived"] is not True
        or type(data["assessment_id"]) is not int or not 1 <= data["assessment_id"] <= 2**53 - 1
        or type(data["configuration_revision"]) is not int or not 0 <= data["configuration_revision"] <= 2**31 - 1
        or type(data["inspection_limit"]) is not int or not 1 <= data["inspection_limit"] <= 20
        or type(data["inspected_count"]) is not int or not 0 <= data["inspected_count"] <= data["inspection_limit"]):
        raise ValidationError("Choose exact bounded customer-reported local organic observation fields and rights.")
    for key, limit, required in (("origin", 512, True), ("observation_reference", 64, True), ("query", 240, True),
        ("observed_at", 64, True), ("requested_location", 240, True), ("requested_language", 35, True),
        ("requested_device", 16, True), ("applied_location", 240, False), ("applied_language", 35, False),
        ("applied_device", 16, True), ("status", 32, True), ("matched_url", 1024, False), ("evidence_note", 500, True)):
        _text(data[key], limit, required=required)
    if (data["origin"] != approved_origin or normalize_origin(data["origin"]) != data["origin"]
        or not data["origin"].startswith("https://")
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", data["observation_reference"])
        or data["requested_device"] not in {"desktop", "mobile", "unknown"}
        or data["applied_device"] not in {"desktop", "mobile", "unknown"}
        or data["requested_language"] != "unknown" and not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", data["requested_language"])
        or data["applied_language"] and not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", data["applied_language"])):
        raise ValidationError("Use exact approved website scope and separately declared requested/applied context.")
    if data["status"] == "observed":
        if type(data["ordinal"]) is not int or not 1 <= data["ordinal"] <= data["inspected_count"]:
            raise ValidationError("A human observed ordinal must fall inside the actually inspected organic set.")
        validate_owned_website_url(data["matched_url"], approved_origin=approved_origin)
    elif data["status"] in {"not_seen_in_inspected_set", "unavailable"}:
        if (data["ordinal"] is not None or data["matched_url"]
            or data["status"] == "not_seen_in_inspected_set" and not data["inspected_count"]
            or data["status"] == "unavailable" and data["inspected_count"]):
            raise ValidationError("Partial not-seen/unavailable observations have no ordinal or matched URL; never rank zero.")
    else:
        raise ValidationError("Choose observed, partial not-seen, or unavailable coverage, not a universal ranking claim.")
    try:
        observed_at = datetime.fromisoformat(data["observed_at"])
        if timezone.is_naive(observed_at) or observed_at > as_of or len(json.dumps(data, allow_nan=False).encode()) > MAX_BYTES:
            raise ValueError
    except (ValueError, TypeError, UnicodeError):
        raise ValidationError("Use an aware nonfuture observation time and a bounded serialized scalar report.") from None
    return dict(data)  # Preserve exact query/context/date/text; no SQL, source fetch or normalization of claims.


def require_visibility_authority(*, project, actor, intake):
    from tenancy.models import ProjectConfiguration
    from .local_assessment import require_local_business_authority
    if type(intake) is not dict or type(intake.get("origin")) is not str:
        raise ValidationError("Choose exact declared website scope.")
    data = validate_local_visibility(intake, approved_origin=intake["origin"])
    assessment, verification = require_local_business_authority(project=project, actor=actor,
        assessment_id=data["assessment_id"], configuration_revision=data["configuration_revision"], origin=data["origin"])
    config = ProjectConfiguration.objects.get(project_id=project.pk)
    if (data["requested_location"] not in assessment.service_areas
        and (not assessment.location_label or data["requested_location"] != assessment.location_label)
        or data["requested_language"] != "unknown" and data["requested_language"] not in config.target_languages):
        raise PermissionDenied
    return assessment, verification, data


def visibility_source_current(row):
    try:
        assessment, verification, _data = require_visibility_authority(project=row.project, actor=row.actor, intake=row.intake)
        return assessment.pk == row.assessment_id and verification.pk == row.verification_id and verification.verified_at == row.verified_at
    except (PermissionDenied, ValidationError):
        return False


def record_local_visibility(*, project, actor, request_key, intake, reason, observation_id=None, expected_revision=None):
    from uuid import UUID, uuid4
    from django.db import transaction
    from tenancy.models import Organization, Project
    from .models import LocalVisibilityObservation
    if (type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key)
        or (observation_id is None) != (expected_revision is None)
        or expected_revision is not None and (type(expected_revision) is not int or not 1 <= expected_revision < 2**31 - 1)):
        raise ValidationError("Choose an exact current local observation correction and request key.")
    _text(reason, 500, required=True)
    if observation_id is not None:
        try:
            observation_id = UUID(str(observation_id))
        except (ValueError, TypeError):
            raise ValidationError("Choose a project-owned current local observation.") from None
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        assessment, verification, data = require_visibility_authority(project=project, actor=actor, intake=intake)
        previous = None
        if observation_id is not None:
            previous = LocalVisibilityObservation.objects.filter(project=project, observation_id=observation_id).order_by("-revision").first()
            if previous is None:
                raise PermissionDenied
        existing = LocalVisibilityObservation.objects.filter(project=project, request_key=request_key).first()
        if existing:
            latest = LocalVisibilityObservation.objects.filter(project=project, observation_id=existing.observation_id).order_by("-revision").first()
            if (latest.pk != existing.pk or existing.actor_id != actor.pk or existing.intake != data or existing.reason != reason
                or observation_id is not None and observation_id != existing.observation_id
                or existing.revision != (expected_revision + 1 if observation_id else 1)
                or not visibility_source_current(existing)):
                raise ValidationError("Observation request key belongs to another or stale decision.")
            return existing
        if previous and previous.revision != expected_revision:
            raise ValidationError("Observation changed; inspect the latest immutable revision before correction.")
        return LocalVisibilityObservation.objects.create(project=project, actor=actor, assessment=assessment,
            verification=verification, verified_at=verification.verified_at, observation_id=observation_id or uuid4(),
            revision=previous.revision + 1 if previous else 1, request_key=request_key, intake=data, reason=reason)
