"""D154 audited retained trial activation, without capture or funnel inference."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import AuditEvent, AuditEventType, Organization, OrganizationTrial, TrialState
from .paddle_checkout_delivery import checkout_source_digest
from .services import (Action, TRIAL_DURATION, TRIAL_MEMBER_LIMIT, TRIAL_OFFER_VERSION,
                       TRIAL_PROJECT_LIMIT, TRIAL_UNIT_LIMIT, require_organization_action)


METHOD = "audited-trial-activation-v1"


def _trial_activation_history(organization):
    result = {"method": METHOD, "state": "unknown", "activation": None}
    trial = OrganizationTrial.objects.select_related("automatic_eligibility").filter(organization=organization).first()
    if trial is None:
        return result
    policy = {"offer_version": TRIAL_OFFER_VERSION, "duration_days": TRIAL_DURATION.days,
              "project_limit": TRIAL_PROJECT_LIMIT, "member_limit": TRIAL_MEMBER_LIMIT, "unit_limit": TRIAL_UNIT_LIMIT}
    audits = list(AuditEvent.objects.filter(organization=organization,
        event_type__in=[AuditEventType.TRIAL_GRANTED, AuditEventType.TRIAL_APPROVED]).order_by("pk")[:2])
    if not audits:
        if trial.started_at is None and trial.state == TrialState.PENDING_REVIEW and trial.offer_version == TRIAL_OFFER_VERSION:
            pending = list(AuditEvent.objects.filter(organization=organization,
                event_type=AuditEventType.TRIAL_REVIEW_REQUIRED).order_by("pk")[:2])
            if (len(pending) == 1 and pending[0].details == policy and pending[0].actor_id is not None
                and pending[0].actor_id == pending[0].subject_user_id
                and organization.created_at <= trial.created_at <= pending[0].created_at <= timezone.now()):
                result["state"] = "not_activated"
        return result  # No original proof means unknown; inspection never creates it.
    if (len(audits) != 1 or trial.started_at is None or trial.offer_version != TRIAL_OFFER_VERSION
        or timezone.is_naive(trial.started_at)):
        raise ValidationError("Original trial activation needs review.")
    audit = audits[0]
    if (audit.actor_id is None or not organization.created_at <= trial.created_at <= audit.created_at <= timezone.now()
        or not organization.created_at <= trial.started_at <= audit.created_at):
        raise ValidationError("Original trial activation needs review.")
    if audit.event_type == AuditEventType.TRIAL_GRANTED:
        eligibility = trial.automatic_eligibility
        if (eligibility is None or eligibility.organization_id != organization.pk
            or eligibility.offer_version != trial.offer_version or eligibility.granted_at != trial.started_at
            or eligibility.user_id != audit.actor_id or audit.subject_user_id != audit.actor_id
            or audit.details != policy or trial.started_at > trial.created_at):
            raise ValidationError("Original automatic trial activation needs review.")
        activation_method = "automatic"
    else:
        details = audit.details
        try:
            after = details["after"]
            started, ended = parse_datetime(after["started_at"]), parse_datetime(after["ends_at"])
            if (trial.automatic_eligibility_id is not None or audit.subject_user_id is not None
                or type(details) is not dict or set(details) != {"before", "after", "reason", "offer_version"}
                or details["offer_version"] != trial.offer_version
                or details["before"] != {"state": "pending_review", "started_at": None, "ends_at": None}
                or type(after) is not dict or set(after) != {"state", "started_at", "ends_at"} or after["state"] != "active"
                or type(details["reason"]) is not str or not 1 <= len(details["reason"].strip()) <= 250
                or started is None or ended is None or timezone.is_naive(started) or timezone.is_naive(ended)
                or started != trial.started_at or ended != started + TRIAL_DURATION or trial.created_at > started):
                raise ValueError
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValidationError("Original approved trial activation needs review.") from None
        activation_method = "staff_approved"
    source = {"method": METHOD, "organization_id": organization.pk, "trial_id": trial.pk,
        "eligibility_id": trial.automatic_eligibility_id, "audit_id": audit.pk, "original_actor_id": audit.actor_id,
        "activation_method": activation_method, "offer_version": trial.offer_version,
        "started_at": trial.started_at.isoformat(), "audited_at": audit.created_at.isoformat()}
    result.update(state="recorded", activation={key: source[key] for key in (
        "activation_method", "offer_version", "started_at", "audited_at")})
    result["activation"]["source_digest"] = checkout_source_digest(source)
    return result


def inspect_trial_activation(*, organization, actor):
    """Current owner-only historical read; later status/extension/original role are not source resets."""
    organization = Organization.objects.get(pk=organization.pk)
    require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
    result = _trial_activation_history(organization)
    organization = Organization.objects.get(pk=organization.pk)
    require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
    if _trial_activation_history(organization) != result:
        raise PermissionDenied
    require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
    return result
