"""Stable observed-period identities, not consent, persisted claims or delivery eligibility."""
from hashlib import sha256

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from . import crux_history_source as history, crux_threshold_policy as policy


METHOD = "material-crux-observed-period-episodes-v1"


def _episodes(source, material):
    episodes = []
    for index, row in enumerate(material["rows"]):
        if row["state"] != "material_threshold_worsening_candidate":
            continue
        identity = {"method_version": METHOD, "organization_id": source.job.organization_id,
                    "project_id": source.project_id, "metric": row["metric"],
                    **{key: source.output[key] for key in (
                        "source", "method", "form_factor", "observed_grain", "observed_key", "collection_timezone")},
                    "periods": [{key: value["period"][key] for key in ("start", "end")}
                                for value in material["source"]["comparisons"][index]["observations"]]}
        episodes.append({"metric": row["metric"], "episode_key": "crux:" + sha256(history._encoded(identity)).hexdigest()})
    return episodes


def current_material_crux_episodes(*, project, actor, observation_id):
    if type(observation_id) is not int or not 1 <= observation_id < 2**53:
        raise ValidationError("Choose one original CrUX history observation.")
    assessed = timezone.now()
    source, original = history._source(project, actor, observation_id, assessed)
    material = policy.current_material_crux_source(project=project, actor=actor, observation_id=observation_id)
    result = {"method_version": METHOD, "policy": {key: value for key, value in material.items() if key != "assessed_at"},
              "episodes": _episodes(source, material),
              "interpretation": "observed_source_period_identity_not_consent_claim_incident_time_or_delivery"}
    result["source_fingerprint"] = sha256(history._encoded({"original_source_sha256": sha256(original).hexdigest(),
                                                           "projection": result})).hexdigest()
    if history._source(project, actor, observation_id, assessed)[1] != original:
        raise PermissionDenied
    return {**result, "assessed_at": material["assessed_at"]}
