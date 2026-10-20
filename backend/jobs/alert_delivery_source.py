"""Read-only daily operational candidates; no sender, incident/severity or SEO claim."""
from datetime import timedelta, timezone as utc

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from tenancy.email_feedback import is_email_suppressed
from tenancy.models import Organization
from tenancy.services import Action, require_entitlement_capacity, require_project_action
from .alert_preferences import _preference
from .failure_source import _row
from .models import JobRun, JobStatus, ProjectAlertPreference
from .weekly_summary import _recipient


METHOD = "optional-daily-crawl-failure-source-v1"
SCOPE = "post_intent_root_crawl_status_updates_not_incident_severity_regression_or_send_authority"


def _binding(project, recipient, family="crawl_failure"):
    require_project_action(project=project, user=recipient, action=Action.VIEW_PROJECT)
    preference = ProjectAlertPreference.objects.filter(project=project, user=recipient).first()
    intent = _preference(preference)
    if intent["frequency"] != "daily" or family not in intent["source_families"]:
        return None
    if timezone.is_naive(preference.updated_at) or preference.updated_at > timezone.now():
        raise ValidationError("Current alert preference date needs review.")
    _recipient(project, recipient)
    email = get_user_model().objects.values_list("email", flat=True).get(pk=recipient.pk)
    address = EmailAddress.objects.filter(user_id=recipient.pk, email=email, primary=True, verified=True).first()
    if address is None or is_email_suppressed(email):
        raise PermissionDenied
    require_entitlement_capacity(organization=Organization.objects.get(pk=project.organization_id))
    return (preference.pk, preference.revision, tuple(intent["source_families"]), preference.updated_at,
            address.pk, email)


def _snapshot(project, start, end, intent_at):
    return list(JobRun.objects.filter(project_id=project.pk, organization_id=project.organization_id,
        handler="crawl_site", method_version__in=["crawl-http-v1", "crawl-http-v2"], status=JobStatus.FAILED,
        retry_of__isnull=True, retries__isnull=True, schedule__isnull=True,
        created_at__gte=intent_at, updated_at__gte=start, updated_at__lt=end).order_by("-updated_at", "-pk").values(
            "id", "organization_id", "project_id", "actor_id", "handler", "status", "method_version",
            "retry_of_id", "schedule_id", "scheduled_for", "created_at", "updated_at", "error_category")[:21])


def current_daily_crawl_alert_source(*, project, recipient):
    original = _binding(project, recipient)
    if original is None:
        require_project_action(project=project, user=recipient, action=Action.VIEW_PROJECT)
        return {"method_version": METHOD, "project_id": project.pk, "scope": SCOPE,
                "state": "unavailable_crawl_alert_intent", "preference_revision": None,
                "intent_updated_at": None, "day_start": None, "day_end": None,
                "assessed_at": None, "rows": [], "has_more": False}
    assessed = timezone.now().astimezone(utc.utc)
    end = assessed.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=1)
    rows = _snapshot(project, start, end, original[3])
    result = {"method_version": METHOD, "project_id": project.pk, "scope": SCOPE,
              "state": "available_failure_candidates_not_sent" if rows else "unavailable_no_failure_candidates",
              "preference_revision": original[1], "intent_updated_at": original[3].isoformat(),
              "day_start": start.isoformat(), "day_end": end.isoformat(), "assessed_at": assessed.isoformat(),
              "rows": [_row(row, assessed) for row in rows[:20]], "has_more": len(rows) > 20}
    if _snapshot(project, start, end, original[3]) != rows:
        raise ValidationError("Current daily crawl failure selection changed during inspection.")
    if _binding(project, recipient) != original:
        raise PermissionDenied
    return result
