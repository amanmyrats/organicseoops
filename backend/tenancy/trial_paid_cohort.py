"""D158 complete retained operational source; no analytics copy or public funnel."""
import re
from datetime import datetime, timezone as utc_timezone
from types import SimpleNamespace

from allauth.account.authentication import get_authentication_records
from allauth.mfa.models import Authenticator
from allauth.mfa.utils import is_mfa_enabled
from django.conf import settings
from django.contrib.auth import HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.dateparse import parse_datetime

from .models import Organization
from .paddle_activation import _first_active_observation_history
from .trial_activation import _trial_activation_history
from .trial_paid_window import WINDOW, _original_trial_paid_window


METHOD = "retained-monthly-trial-paid-window-v1"
COLLECTION_LIMIT = 500
MINIMUM_CELL = 5
COUNT_FIELDS = ("eligible_organizations", "mature_organizations", "observed_within_window",
                "not_observed_within_window", "immature_organizations", "unknown_paid_coverage",
                "unassigned_unknown_trial")


def _require_staff_source_request(request):
    if not request.user.is_authenticated or not request.session.session_key:
        raise PermissionDenied
    actor = get_user_model().objects.filter(pk=request.user.pk, is_active=True, is_staff=True, is_superuser=True).first()
    # Reload the persisted session, not cached request assurance, so revocation during reads denies.
    session = request.session.load()
    if (actor is None or session.get(SESSION_KEY) != str(actor.pk)
        or not constant_time_compare(session.get(HASH_SESSION_KEY, ""), actor.get_session_auth_hash())):
        raise PermissionDenied
    if settings.STAFF_MFA_REQUIRED and (not is_mfa_enabled(actor, types=[Authenticator.Type.TOTP])
        or not any(record.get("method") == "mfa" for record in
                   get_authentication_records(SimpleNamespace(session=session)))):
        raise PermissionDenied


def _month_range(month, assessed):
    if month is None:
        year, number = (assessed.year, assessed.month - 1) if assessed.month > 1 else (assessed.year - 1, 12)
    elif type(month) is str and re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
        year, number = map(int, month.split("-"))
    else:
        raise ValidationError("Choose a completed UTC cohort month.")
    try:
        start = datetime(year, number, 1, tzinfo=utc_timezone.utc)
        end = datetime(year + (number == 12), number % 12 + 1, 1, tzinfo=utc_timezone.utc)
    except ValueError:
        raise ValidationError("Choose a completed UTC cohort month.") from None
    if end > assessed:
        raise ValidationError("Choose a completed UTC cohort month.")
    return start, end


def _retained_originals():
    # ponytail: complete scan capped at500; use a proven consistent paged source if volume requires it.
    organizations = list(Organization.objects.order_by("pk")[:COLLECTION_LIMIT + 1])
    if len(organizations) > COLLECTION_LIMIT:
        return None
    return [(organization, _trial_activation_history(organization), _first_active_observation_history(organization))
            for organization in organizations]


def _snapshot(originals):
    return [(organization.pk, organization.created_at, trial, paid) for organization, trial, paid in originals]


def inspect_retained_trial_paid_cohort(*, request, month=None):
    """Trusted staff request only; submitted originals/IDs/assessment are never accepted."""
    _require_staff_source_request(request)
    assessed = timezone.now().astimezone(utc_timezone.utc)
    start, end = _month_range(month, assessed)
    result = {"method": METHOD, "basis": "current_retained_original_operational_sources", "grain": "organization",
              "month": start.strftime("%Y-%m"), "starts_at": start.isoformat(), "ends_at": end.isoformat(),
              "assessed_at": assessed.isoformat(), "window_days": WINDOW.days, "collection_limit": COLLECTION_LIMIT,
              "minimum_cell": MINIMUM_CELL, "rates_available": False, "state": "capacity_exceeded",
              **dict.fromkeys(COUNT_FIELDS)}
    originals = _retained_originals()
    if originals is None:
        _require_staff_source_request(request)
        return result
    counts = dict.fromkeys(COUNT_FIELDS, 0)
    for organization, trial, paid in originals:
        if trial["state"] != "recorded":
            counts["unassigned_unknown_trial"] += 1
            continue
        started = parse_datetime(trial["activation"]["started_at"])
        if not start <= started < end:
            continue
        counts["eligible_organizations"] += 1
        window = _original_trial_paid_window(organization=organization, trial=trial, paid=paid, assessed=assessed)
        if window["state"] == "unknown":
            counts["unknown_paid_coverage"] += 1
        elif window["state"] == "immature":
            counts["immature_organizations"] += 1
        else:
            counts["mature_organizations"] += 1
            counts[window["outcome"]] += 1
    final = _retained_originals()
    _require_staff_source_request(request)
    if final is None or _snapshot(final) != _snapshot(originals):
        raise PermissionDenied
    # Suppress complementary leaf cells together, never leave a subtractable hidden singleton.
    suppressed = any(0 < counts[key] < MINIMUM_CELL for key in COUNT_FIELDS
                     if key not in {"eligible_organizations", "mature_organizations"})
    result.update(state="suppressed" if suppressed else "available")
    if not suppressed:
        result.update(counts)
    return result
