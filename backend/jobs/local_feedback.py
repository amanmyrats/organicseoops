"""D125 independent customer-owned feedback and exact human reply approval. No network."""
from datetime import datetime
import json
import re
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import URLValidator
from django.utils import timezone

from tenancy.models import normalize_origin

POLICY_VERSION = "local-owned-feedback-v1"
SOURCE_KIND = "customer_owned_web_feedback"
MAX_BYTES = 32768
FIELDS = {"policy_version", "source_kind", "assessment_id", "configuration_revision", "source_url",
          "feedback_reference", "received_at", "feedback_excerpt", "theme", "reply_draft", "evidence_note",
          "storage_permission", "not_api_derived"}


def _text(value, limit, *, required=False):
    if (type(value) is not str or len(value) > limit or required and not value.strip()
        or any((ord(char) < 32 and char not in "\n\r\t") or 0xD800 <= ord(char) <= 0xDFFF for char in value)):
        raise ValidationError("Local feedback requires bounded, valid customer-supplied text.")


def validate_owned_website_url(value, *, approved_origin):
    """Pure shared exact-origin URL check for independent customer-owned manual sources."""
    _text(value, 1024, required=True)
    try:
        URLValidator(schemes=["https"])(value)
        parts = urlsplit(value)
        if (type(approved_origin) is not str or normalize_origin(approved_origin) != approved_origin
            or parts.scheme != "https" or normalize_origin(f"{parts.scheme}://{parts.netloc}") != approved_origin
            or parts.username or parts.password or parts.query or parts.fragment
            or any(ord(char) < 33 or char == "\\" for char in value)):
            raise ValueError
    except (ValidationError, ValueError, TypeError):
        raise ValidationError("Choose an exact approved HTTPS project website source, without secrets or query parameters.") from None
    return value


def validate_local_feedback(data, *, approved_origin, as_of=None):
    """Validate scalar input only. Caller must establish current actor/business/source authority."""
    as_of = timezone.now() if as_of is None else as_of
    if (not isinstance(as_of, datetime) or timezone.is_naive(as_of)
        or type(data) is not dict or set(data) != FIELDS
        or data["policy_version"] != POLICY_VERSION or data["source_kind"] != SOURCE_KIND
        or data["storage_permission"] is not True or data["not_api_derived"] is not True
        or type(data["assessment_id"]) is not int or not 1 <= data["assessment_id"] <= 2**53 - 1
        or type(data["configuration_revision"]) is not int or not 0 <= data["configuration_revision"] <= 2**31 - 1):
        raise ValidationError("Choose exact customer-owned feedback fields, current declared scope and independent storage rights.")
    for key, limit, required in (("source_url", 1024, True), ("feedback_reference", 64, True),
        ("received_at", 64, True), ("feedback_excerpt", 2000, True), ("theme", 500, False),
        ("reply_draft", 2000, False), ("evidence_note", 500, True)):
        _text(data[key], limit, required=required)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", data["feedback_reference"]):
        raise ValidationError("Use a bounded opaque customer feedback reference, without contact or provider fields.")
    validate_owned_website_url(data["source_url"], approved_origin=approved_origin)
    try:
        received_at = datetime.fromisoformat(data["received_at"])
        if timezone.is_naive(received_at) or received_at > as_of:
            raise ValueError
        if len(json.dumps(data, allow_nan=False).encode()) > MAX_BYTES:
            raise ValueError
    except (ValueError, TypeError, UnicodeError):
        raise ValidationError("Feedback needs an aware nonfuture received time and a bounded serialized record.") from None
    # All accepted fields are scalars. Freeze the dictionary, preserve entered evidence/text/timezone.
    return dict(data)


def require_feedback_authority(*, project, actor, intake):
    """Resolve real current manual business and exact origin; no GBP identity/eligibility dependency."""
    from .local_assessment import require_local_business_authority
    if type(intake) is not dict or type(intake.get("source_url")) is not str:
        raise PermissionDenied
    try:
        parts = urlsplit(intake["source_url"])
        origin = normalize_origin(parts.scheme + "://" + parts.netloc)
    except (ValidationError, ValueError):
        raise ValidationError("Choose a current exact verified website source.") from None
    data = validate_local_feedback(intake, approved_origin=origin)
    assessment, verification = require_local_business_authority(project=project, actor=actor,
        assessment_id=data["assessment_id"], configuration_revision=data["configuration_revision"], origin=origin)
    return assessment, verification, origin, data


def require_current_feedback(row, *, actor=None):
    assessment, verification, origin, data = require_feedback_authority(
        project=row.project, actor=row.source_actor, intake=row.intake)
    if (assessment.pk != row.assessment_id or verification.pk != row.verification_id
        or verification.verified_at != row.verified_at or origin != row.origin):
        raise PermissionDenied
    require_feedback_authority(project=row.project, actor=row.actor, intake=data)
    if actor is not None:
        require_feedback_authority(project=row.project, actor=actor, intake=data)
    if row.reviewed_revision_id:
        require_feedback_authority(project=row.project, actor=row.reviewed_revision.actor, intake=data)
        require_feedback_authority(project=row.project, actor=row.approved_by, intake=data)


def feedback_source_current(row):
    try:
        require_current_feedback(row)
        return True
    except (PermissionDenied, ValidationError):
        return False


def record_local_feedback(*, project, actor, request_key, intake, state, reason,
                          feedback_id=None, expected_revision=None, executed_at=None, execution_note=""):
    from uuid import UUID, uuid4
    from django.db import transaction
    from tenancy.models import Organization, Project
    from .models import LocalFeedbackReview
    if (type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key)
        or type(state) is not str or state not in LocalFeedbackReview.State.values
        or (feedback_id is None) != (expected_revision is None)
        or expected_revision is not None and (type(expected_revision) is not int or not 1 <= expected_revision < 2**31 - 1)):
        raise ValidationError("Choose an exact current feedback revision and request key.")
    _text(reason, 500, required=True)
    _text(execution_note, 500, required=state == "reported")
    if feedback_id is not None:
        try:
            feedback_id = UUID(str(feedback_id))
        except (ValueError, TypeError):
            raise ValidationError("Choose a current project-owned feedback review.") from None
    if state != "reported" and (executed_at is not None or execution_note):
        raise ValidationError("Execution is a separate actual manual report, not approval.")
    if state == "reported" and (not isinstance(executed_at, datetime) or timezone.is_naive(executed_at)
                                or executed_at > timezone.now()):
        raise ValidationError("Report the actual aware nonfuture manual execution time.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        assessment, verification, origin, data = require_feedback_authority(project=project, actor=actor, intake=intake)
        previous = None
        if feedback_id is not None:
            previous = LocalFeedbackReview.objects.filter(project=project, feedback_id=feedback_id).order_by("-revision").first()
            if previous is None:
                raise PermissionDenied
        existing = LocalFeedbackReview.objects.filter(project=project, request_key=request_key).first()
        if existing:
            latest = LocalFeedbackReview.objects.filter(project=project, feedback_id=existing.feedback_id).order_by("-revision").first()
            if (latest.pk != existing.pk or existing.actor_id != actor.pk
                or feedback_id is not None and existing.feedback_id != feedback_id
                or existing.revision != (expected_revision + 1 if feedback_id else 1)
                or (existing.intake, existing.state, existing.reason, existing.executed_at, existing.execution_note)
                   != (data, state, reason, executed_at, execution_note)):
                raise ValidationError("Request key belongs to another or stale feedback decision.")
            require_current_feedback(existing, actor=actor)
            return existing
        if previous:
            transitions = {"draft": {"draft", "review"}, "review": {"draft", "approved"},
                           "approved": {"draft", "reported"}, "reported": {"draft"}}
            if previous.revision != expected_revision or state not in transitions[previous.state]:
                raise ValidationError("Feedback changed; inspect the latest revision and allowed state.")
            if state != "draft":
                require_current_feedback(previous, actor=actor)
                if previous.intake != data:
                    raise ValidationError("Changed source, target or text requires a draft and fresh human review.")
        elif state != "draft":
            raise ValidationError("New feedback must begin as an unapproved human draft.")
        reviewed = approver = approved_at = None
        if state == "approved":
            reviewed, approver, approved_at = previous, actor, timezone.now()
        elif state == "reported":
            reviewed, approver, approved_at = previous.reviewed_revision, previous.approved_by, previous.approved_at
            if executed_at < approved_at:
                raise ValidationError("Manual execution must follow exact human approval.")
        return LocalFeedbackReview.objects.create(project=project, actor=actor,
            source_actor=actor if state == "draft" else previous.source_actor,
            assessment=assessment, verification=verification, verified_at=verification.verified_at,
            origin=origin, intake=data, request_key=request_key, feedback_id=feedback_id or uuid4(),
            revision=previous.revision + 1 if previous else 1, state=state, reason=reason,
            reviewed_revision=reviewed, approved_by=approver, approved_at=approved_at,
            executed_at=executed_at, execution_note=execution_note)
