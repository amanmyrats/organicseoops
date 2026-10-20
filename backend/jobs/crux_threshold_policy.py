"""Versioned product material-change heuristics, never statistical or delivery authority."""
from decimal import Decimal, localcontext
from hashlib import sha256

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from . import crux_history_source as history


METHOD = "material-crux-threshold-candidate-v1"
ABSOLUTE_FLOORS = {"LCP": "500", "INP": "50", "CLS": "0.05"}
RELATIVE_FLOOR = "0.20"


def _rows(source):
    rows = []
    for comparison in source["comparisons"]:
        metric = comparison["metric"]
        row = {"metric": metric, "unit": comparison["unit"], "state": comparison["state"],
               "minimum_absolute_increase": ABSOLUTE_FLOORS[metric],
               "minimum_relative_increase_fraction": RELATIVE_FLOOR,
               "absolute_increase": None, "absolute_floor_met": None, "relative_floor_met": None,
               "sample_sufficiency": "unknown", "statistical_significance": "unknown"}
        if comparison["state"] == "threshold_worsening_candidate":
            previous, current = (Decimal(item["p75"]) for item in comparison["observations"])
            floor = Decimal(ABSOLUTE_FLOORS[metric])
            if previous == 0:
                row["state"] = "unknown_relative_zero_baseline"
            else:
                # Bound exact arithmetic before allocating a context for exotic source exponents.
                precision = max(0, previous.adjusted(), current.adjusted(), floor.adjusted()) - min(
                    previous.as_tuple().exponent, current.as_tuple().exponent, floor.as_tuple().exponent) + 4
                if precision > 64:
                    row["state"] = "unknown_exact_numeric_precision"
                else:
                    with localcontext() as context:
                        context.prec = precision
                        increase = current - previous
                        absolute_met = increase >= floor
                        relative_met = increase * 5 >= previous  # Exact >=20%, no division/rounded ratio.
                    row.update(absolute_increase=str(increase), absolute_floor_met=absolute_met,
                               relative_floor_met=relative_met,
                               state="material_threshold_worsening_candidate" if absolute_met and relative_met
                               else "below_material_change_floor")
        rows.append(row)
    return rows


def current_material_crux_source(*, project, actor, observation_id):
    if type(observation_id) is not int or not 1 <= observation_id < 2**53:
        raise ValidationError("Choose one original CrUX history observation.")
    assessed = timezone.now()
    _, original = history._source(project, actor, observation_id, assessed)
    source = history.current_crux_history_source(project=project, actor=actor, observation_id=observation_id)
    result = {"method_version": METHOD, "source": {key: value for key, value in source.items() if key != "assessed_at"},
              "state": "unknown_original_raw_integrity" if source["state"] == "unknown_original_raw_integrity"
              else "assessed_original_field_threshold_candidates", "rows": _rows(source),
              "interpretation": "product_material_change_heuristic_not_statistical_seo_regression_causality_consent_or_delivery"}
    result["source_fingerprint"] = sha256(history._encoded({
        "original_source_sha256": sha256(original).hexdigest(), "policy": result})).hexdigest()
    if history._source(project, actor, observation_id, assessed)[1] != original:
        raise PermissionDenied
    return {**result, "assessed_at": source["assessed_at"]}
