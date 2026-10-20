"""Exact current optional CrUX eligibility; no scan, persisted claim or sender."""
from datetime import timedelta, timezone as utc
from hashlib import sha256

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from tenancy.email_feedback import is_email_suppressed
from tenancy.models import Organization
from tenancy.services import Action, require_entitlement_capacity, require_project_action
from . import crux_episode_source as episodes, crux_history_source as history
from .crux_alert_preferences import _preference
from .models import ProjectCruxAlertPreference
from .weekly_summary import _recipient


METHOD = "optional-exact-crux-collection-day-source-v1"
SCOPE = "post_intent_exact_observation_collection_day_not_period_occurrence_incident_or_send_authority"


def _binding(project, recipient):
    require_project_action(project=project, user=recipient, action=Action.VIEW_PROJECT)
    preference = ProjectCruxAlertPreference.objects.filter(project=project, user=recipient).first()
    intent = _preference(preference)
    if intent["frequency"] != "daily":
        return None
    if timezone.is_naive(preference.updated_at) or preference.updated_at > timezone.now():
        raise ValidationError("Current CrUX intent date needs review.")
    _recipient(project, recipient)
    email = get_user_model().objects.values_list("email", flat=True).get(pk=recipient.pk)
    address = EmailAddress.objects.filter(user_id=recipient.pk, email=email, primary=True, verified=True).first()
    if address is None or is_email_suppressed(email):
        raise PermissionDenied
    require_entitlement_capacity(organization=Organization.objects.get(pk=project.organization_id))
    return preference.pk, preference.revision, preference.updated_at, address.pk, email


def _selected(source, start, end, intent_at):
    job = source.job
    return (start <= source.collected_at < end and job.created_at >= intent_at
            and job.schedule_id is None and job.scheduled_for is None
            and job.retry_of_id is None and not job.retries.exists())


def current_exact_crux_delivery_source(*, project, recipient, observation_id):
    if type(observation_id) is not int or not 1 <= observation_id < 2**53:
        raise ValidationError("Choose one exact original CrUX observation.")
    binding = _binding(project, recipient)
    result = {"method_version": METHOD, "project_id": project.pk, "scope": SCOPE,
              "state": "unavailable_crux_intent", "preference_revision": None, "intent_updated_at": None,
              "day_start": None, "day_end": None, "source": None, "source_fingerprint": None, "assessed_at": None}
    if binding is None:
        require_project_action(project=project, user=recipient, action=Action.VIEW_PROJECT)
        return result
    assessed = timezone.now().astimezone(utc.utc)
    end = assessed.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=1)
    source, original = history._source(project, recipient, observation_id, assessed)
    selected = _selected(source, start, end, binding[2])
    material = episodes.current_material_crux_episodes(project=project, actor=recipient, observation_id=observation_id) if selected else None
    result.update(preference_revision=binding[1], intent_updated_at=binding[2].isoformat(),
                  day_start=start.isoformat(), day_end=end.isoformat(), assessed_at=assessed.isoformat(),
                  state="unavailable_source_day_or_intent" if not selected else "unavailable_no_material_candidate")
    if material is not None:
        result["source"] = {key: value for key, value in material.items() if key != "assessed_at"}
        result["source_fingerprint"] = sha256(history._encoded({
            "method_version": METHOD, "original_source_sha256": sha256(original).hexdigest(),
            "source": result["source"], "binding": [binding[0], binding[1], binding[2].isoformat(), binding[3], binding[4]],
            "day_start": result["day_start"], "day_end": result["day_end"]})).hexdigest()
        if material["episodes"]:
            result["state"] = "eligible_current_material_source_not_sent"
    fresh, current = history._source(project, recipient, observation_id, assessed)
    if current != original or _selected(fresh, start, end, binding[2]) != selected:
        raise PermissionDenied
    if _binding(project, recipient) != binding or timezone.now().astimezone(utc.utc).date() != end.date():
        raise PermissionDenied
    return result
