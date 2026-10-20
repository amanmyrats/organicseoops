"""D156 original fixed follow-up source; no cohort aggregate or analytics copy."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .paddle_activation import inspect_first_active_observation
from .paddle_checkout_delivery import checkout_source_digest
from .services import TRIAL_DURATION, TRIAL_EXTENSION_DURATION
from .trial_activation import inspect_trial_activation


METHOD = "original-trial-paid-observation-window-v1"
WINDOW = TRIAL_DURATION + TRIAL_EXTENSION_DURATION


def _original_trial_paid_window(*, organization, trial, paid, assessed):
    """Pure calculation over trusted checked originals; never a read-authority entrypoint."""
    result = {"method": METHOD, "state": "unknown", "window_days": WINDOW.days,
        "interpretation": "fixed_half_open_original_trial_paid_server_window_not_provider_activation_or_conversion_rate",
        "assessed_at": assessed.isoformat(), "trial_started_at": None, "window_ends_at": None,
        "paid_observed_at": None, "trial_source_digest": None, "paid_source_digest": None,
        "source_digest": None, "outcome": None}
    if trial["state"] == "recorded" and paid["state"] in {"recorded", "not_observed"}:
        activation, observation = trial["activation"], paid["observation"]
        started = parse_datetime(activation["started_at"])
        observed = parse_datetime(observation["observed_at"]) if observation else None
        if (started is None or timezone.is_naive(started) or started > assessed
            or observation and (observed is None or timezone.is_naive(observed) or not started <= observed <= assessed)):
            raise ValidationError("Original trial-paid window dates need billing review.")
        ended = started + WINDOW
        mature = assessed >= ended
        outcome = ("observed_within_window" if observed is not None and observed < ended
                   else "not_observed_within_window") if mature else None
        source = {"method": METHOD, "organization_id": organization.pk, "window_days": WINDOW.days,
            "assessed_at": assessed.isoformat(), "trial_started_at": activation["started_at"],
            "window_ends_at": ended.isoformat(), "paid_observed_at": observation["observed_at"] if observation else None,
            "trial_source_digest": activation["source_digest"],
            "paid_source_digest": observation["source_digest"] if observation else None,
            "paid_state": paid["state"], "state": "mature" if mature else "immature", "outcome": outcome}
        result.update({key: value for key, value in source.items() if key not in {"organization_id", "paid_state"}})
        result["source_digest"] = checkout_source_digest(source)
    return result


def inspect_trial_paid_window(*, organization, actor):
    assessed = timezone.now()
    trial = inspect_trial_activation(organization=organization, actor=actor)
    paid = inspect_first_active_observation(organization=organization, actor=actor)
    result = _original_trial_paid_window(organization=organization, trial=trial, paid=paid, assessed=assessed)
    if (inspect_trial_activation(organization=organization, actor=actor) != trial
        or inspect_first_active_observation(organization=organization, actor=actor) != paid):
        raise PermissionDenied
    return result
