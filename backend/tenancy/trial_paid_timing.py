"""D155 original operational trial-to-paid server timing, not a cohort."""
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .paddle_activation import inspect_first_active_observation
from .paddle_checkout_delivery import checkout_source_digest
from .trial_activation import inspect_trial_activation


METHOD = "trial-to-first-paid-server-timing-v1"


def inspect_trial_paid_timing(*, organization, actor):
    trial = inspect_trial_activation(organization=organization, actor=actor)
    paid = inspect_first_active_observation(organization=organization, actor=actor)
    result = {"method": METHOD, "state": "unknown", "precision": "whole_milliseconds_rounded_down",
        "interpretation": "audited_trial_start_to_first_paid_server_observation_not_provider_activation_or_cohort",
        "trial_started_at": None, "observed_at": None, "activation_method": None,
        "trial_source_digest": None, "paid_source_digest": None, "source_digest": None, "elapsed_milliseconds": None}
    if trial["state"] == "recorded":
        if paid["state"] == "not_observed":
            result["state"] = "not_observed"
        elif paid["state"] == "recorded":
            activation, observation = trial["activation"], paid["observation"]
            started, observed = parse_datetime(activation["started_at"]), parse_datetime(observation["observed_at"])
            if (started is None or observed is None or timezone.is_naive(started) or timezone.is_naive(observed)
                or not started <= observed <= timezone.now()):
                raise ValidationError("Original trial and paid dates need billing review.")
            elapsed = (observed - started) // timedelta(microseconds=1) // 1000
            if not 0 <= elapsed < 2**53:
                raise ValidationError("Original trial-paid timing exceeds its supported precision.")
            source = {"method": METHOD, "organization_id": organization.pk,
                "trial_started_at": activation["started_at"], "observed_at": observation["observed_at"],
                "activation_method": activation["activation_method"], "trial_source_digest": activation["source_digest"],
                "paid_source_digest": observation["source_digest"]}
            result.update(state="recorded", elapsed_milliseconds=elapsed, source_digest=checkout_source_digest(source),
                **{key: value for key, value in source.items() if key not in {"method", "organization_id"}})
    if (inspect_trial_activation(organization=organization, actor=actor) != trial
        or inspect_first_active_observation(organization=organization, actor=actor) != paid):
        raise PermissionDenied
    return result
