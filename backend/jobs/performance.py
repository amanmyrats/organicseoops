import json
import math
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import ValidationError

from tenancy.models import normalize_origin

from .crawling import CrawlScope, FetchDenied


CRUX_METRICS = {
    "largest_contentful_paint": ("LCP", "ms", Decimal(2500), Decimal(4000)),
    "interaction_to_next_paint": ("INP", "ms", Decimal(200), Decimal(500)),
    "cumulative_layout_shift": ("CLS", "unitless", Decimal("0.1"), Decimal("0.25")),
    "experimental_time_to_first_byte": ("TTFB", "ms", None, None),
}
LAB_AUDITS = {
    "largest-contentful-paint": "ms",
    "cumulative-layout-shift": "unitless",
    "total-blocking-time": "ms",
    "speed-index": "ms",
}
FORM_FACTORS = frozenset({"PHONE", "TABLET", "DESKTOP"})


def _object(payload, limit):
    if type(payload) is not dict:
        raise ValidationError("Performance evidence must be a JSON object.")
    try:
        data = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
    except (ValueError, TypeError):
        raise ValidationError("Performance evidence must contain finite JSON values.") from None
    if len(data) > limit:
        raise ValidationError("Performance response exceeds the bounded evidence limit.")
    return payload


def _scoped_url(project, value, *, origin=False):
    try:
        parsed = urlsplit(value)
        if not isinstance(value, str) or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError
        normalized = CrawlScope.for_project(project).validate_url(value)
        scope = normalize_origin(urlunsplit((parsed.scheme, parsed.netloc, "", "", "")))
    except (ValueError, TypeError, FetchDenied, ValidationError):
        raise ValidationError("Performance evidence URL must match the current exact project origin scope.") from None
    if scope not in {project.canonical_origin, *project.domain_aliases.values_list("origin", flat=True)}:
        raise ValidationError("Performance evidence URL must match the current exact project origin scope.")
    return scope if origin else normalized


def _period(value):
    if type(value) is not dict or set(value) != {"firstDate", "lastDate"}:
        raise ValidationError("CrUX collection dates are required.")

    def parse(part):
        if type(part) is not dict or set(part) != {"year", "month", "day"} or any(type(number) is not int for number in part.values()):
            raise ValidationError("CrUX collection dates are invalid.")
        try:
            return date(part["year"], part["month"], part["day"])
        except ValueError:
            raise ValidationError("CrUX collection dates are invalid.") from None

    start, end = parse(value["firstDate"]), parse(value["lastDate"])
    if start > end or end > date.today() + timedelta(days=1):
        raise ValidationError("CrUX collection dates are invalid.")
    return {"start": start.isoformat(), "end": end.isoformat(), "eligible_days": "unknown"}


def _p75(value, metric_name):
    if value is None or value == "NaN":
        return {"state": "unavailable", "p75": None, "grade": "unknown"}
    label, unit, good, poor = CRUX_METRICS[metric_name]
    if unit == "ms" and (type(value) is not int or not 0 <= value <= 10_000_000):
        raise ValidationError("Invalid millisecond percentile in CrUX response.")
    if unit == "unitless" and (type(value) is not str or len(value) > 20):
        raise ValidationError("Invalid CLS percentile in CrUX response.")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValidationError("Invalid CrUX percentile.") from None
    if not number.is_finite() or number < 0 or (unit == "unitless" and number > 100):
        raise ValidationError("Invalid CrUX percentile.")
    return {
        "state": "observed", "p75": str(number) if unit == "unitless" else value,
        "unit": unit, "grade": "not_evaluated" if good is None else "good" if number <= good else "poor" if number > poor else "needs_improvement",
        "method": "field_p75_not_a_lab_score", "metric": label,
    }


def parse_crux(*, project, requested_url, requested_grain, form_factor, payload, history=False):
    _object(payload, 256 * 1024)
    if form_factor not in FORM_FACTORS or requested_grain not in {"page", "origin"} or type(history) is not bool:
        raise ValidationError("Choose a supported CrUX form factor and report type.")
    if requested_grain == "origin" and (not isinstance(requested_url, str) or urlsplit(requested_url).path not in {"", "/"}):
        raise ValidationError("Origin-level CrUX requests cannot contain a page path.")
    requested = _scoped_url(project, requested_url, origin=requested_grain == "origin")
    record = payload.get("record")
    if type(record) is not dict or type(record.get("key")) is not dict or type(record.get("metrics")) is not dict:
        raise ValidationError("CrUX record is unavailable or malformed.")
    key = record["key"]
    if key.get("formFactor") != form_factor or ("url" in key) == ("origin" in key):
        raise ValidationError("CrUX record dimensions do not match the request.")
    grain = "page" if "url" in key else "origin"
    observed = _scoped_url(project, key["origin"], origin=True) if grain == "origin" else _scoped_url(project, key["url"])
    if requested_grain == "origin" and grain != "origin":
        raise ValidationError("CrUX returned a page for an origin-level request.")
    normalization = payload.get("urlNormalizationDetails")
    if normalization is not None:
        if type(normalization) is not dict or (
            normalization.get("originalUrl") is not None and _scoped_url(project, normalization["originalUrl"]) != _scoped_url(project, requested_url)
        ) or (
            normalization.get("normalizedUrl") is not None and _scoped_url(project, normalization["normalizedUrl"]) != (
                _scoped_url(project, key["url"]) if grain == "page" else _scoped_url(project, key["origin"])
            )
        ):
            raise ValidationError("CrUX normalization does not match the requested project scope.")
    elif grain == "page" and observed != requested:
        raise ValidationError("CrUX changed the page URL without normalization evidence.")
    periods = record.get("collectionPeriods") if history else [record.get("collectionPeriod")]
    if not isinstance(periods, list) or not 1 <= len(periods) <= (40 if history else 1):
        raise ValidationError("CrUX collection periods are unavailable.")
    windows = [_period(item) for item in periods]
    if any(windows[index]["end"] <= windows[index - 1]["end"] for index in range(1, len(windows))):
        raise ValidationError("CrUX collection periods must be chronological.")
    metrics = []
    for metric_name, (label, unit, _good, _poor) in CRUX_METRICS.items():
        value = record["metrics"].get(metric_name)
        if value is not None and type(value) is not dict:
            raise ValidationError("CrUX metric shape is invalid.")
        if history:
            percentiles = value.get("percentilesTimeseries", {}) if value else {}
            if type(percentiles) is not dict:
                raise ValidationError("CrUX historical percentile shape is invalid.")
            values = percentiles.get("p75s") if value else None
            if values is not None and (not isinstance(values, list) or len(values) != len(windows)):
                raise ValidationError("CrUX historical percentiles do not match collection periods.")
        else:
            percentiles = value.get("percentiles", {}) if value else {}
            if type(percentiles) is not dict:
                raise ValidationError("CrUX percentile shape is invalid.")
            values = [percentiles.get("p75")]
        for index, percentile in enumerate(values if values is not None else [None] * len(windows)):
            metric = _p75(percentile, metric_name)
            metrics.append({"name": label, "unit": unit, "period": windows[index], **metric})
    return {
        "source": "crux_history_api" if history else "crux_api",
        "method": "crux-p75-v1", "requested_url": requested,
        "requested_grain": requested_grain, "observed_grain": grain,
        "observed_key": observed, "origin_fallback": requested_grain == "page" and grain == "origin",
        "url_normalization": "provider_normalized" if grain == "page" and observed != requested else "none",
        "form_factor": form_factor, "collection_periods": windows,
        "collection_timezone": "PST_fixed_UTC_minus_8",
        "rolling_windows_overlap": bool(history and len(windows) > 1),
        "metrics": metrics, "missing_is_not_passing": True,
    }


def parse_pagespeed_lab(*, project, requested_url, strategy, payload):
    _object(payload, 2 * 1024 * 1024)
    requested = _scoped_url(project, requested_url)
    if strategy not in {"mobile", "desktop"}:
        raise ValidationError("Choose a supported PageSpeed strategy.")
    lighthouse = payload.get("lighthouseResult")
    if type(lighthouse) is not dict or type(lighthouse.get("configSettings")) is not dict:
        raise ValidationError("Lighthouse lab evidence is unavailable.")
    if lighthouse["configSettings"].get("formFactor") != strategy:
        raise ValidationError("Lighthouse device strategy does not match the request.")
    if _scoped_url(project, lighthouse.get("requestedUrl")) != requested:
        raise ValidationError("Lighthouse result does not match the requested page.")
    try:
        final_url = _scoped_url(project, lighthouse["finalUrl"])
    except (KeyError, ValidationError):
        return {"source": "pagespeed_insights", "kind": "lighthouse_lab", "status": "outside_project_scope",
                "requested_url": requested, "strategy": strategy, "field_data": "not_used"}
    return _lighthouse_lab(lighthouse=lighthouse, requested=requested, final_url=final_url, strategy=strategy)


def _lighthouse_lab(*, lighthouse, requested, final_url, strategy):
    moment = lighthouse.get("fetchTime")
    if not isinstance(moment, str) or len(moment) > 48:
        raise ValidationError("Lighthouse lab observation time is missing.")
    try:
        timestamp = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError("Lighthouse lab observation time is invalid.") from None
    if timestamp.tzinfo is None:
        raise ValidationError("Lighthouse lab observation time needs a timezone.")
    if lighthouse.get("runtimeError"):
        code = lighthouse["runtimeError"].get("code", "") if isinstance(lighthouse["runtimeError"], dict) else ""
        return {"source": "pagespeed_insights", "kind": "lighthouse_lab", "status": "runtime_failed",
                "error_category": code if isinstance(code, str) and re.fullmatch(r"[A-Z_]{1,64}", code) else "lab_runtime_error",
                "requested_url": requested, "final_url": final_url, "strategy": strategy,
                "observed_at": timestamp.isoformat(), "field_data": "not_used"}
    categories = lighthouse.get("categories")
    audits = lighthouse.get("audits")
    if type(categories) is not dict or type(audits) is not dict:
        raise ValidationError("Lighthouse categories and audits are required.")
    scores = {}
    for name in ("performance", "accessibility", "best-practices", "seo"):
        category = categories.get(name, {})
        value = category.get("score") if isinstance(category, dict) else None
        if value is not None and (type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1):
            raise ValidationError("Invalid Lighthouse lab score.")
        scores[name] = value
    observations = {}
    for name, unit in LAB_AUDITS.items():
        audit = audits.get(name, {})
        value = audit.get("numericValue") if isinstance(audit, dict) else None
        if value is not None and (type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 10_000_000):
            raise ValidationError("Invalid Lighthouse audit value.")
        observations[name] = {"value": value, "unit": unit, "state": "observed" if value is not None else "unavailable"}
    version = lighthouse.get("lighthouseVersion")
    return {
        "source": "pagespeed_insights", "kind": "lighthouse_lab", "status": "observed",
        "requested_url": requested, "final_url": final_url, "strategy": strategy,
        "lighthouse_version": version if isinstance(version, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version) else "unknown",
        "observed_at": timestamp.isoformat(), "scores": scores, "audits": observations,
        "score_method": "lighthouse_lab_score_not_field_p75", "field_data": "not_used",
    }


def compare_crux_history(history, metric):
    if (type(history) is not dict or history.get("source") != "crux_history_api"
        or metric not in {item[0] for item in CRUX_METRICS.values()}):
        raise ValidationError("Choose comparable CrUX history and a supported metric.")
    observations = [item for item in history["metrics"] if item["name"] == metric]
    if len(observations) < 2 or any(item["state"] != "observed" for item in observations[-2:]):
        return {"state": "unknown_insufficient_eligible_periods", "metric": metric}
    previous, current = observations[-2:]
    rank = {"good": 0, "needs_improvement": 1, "poor": 2}
    if metric == "TTFB" or current["grade"] not in rank or previous["grade"] not in rank:
        return {"state": "not_evaluated", "metric": metric}
    return {
        "state": "regression_candidate" if rank[current["grade"]] > rank[previous["grade"]]
        else "no_threshold_regression_observed",
        "metric": metric,
        "previous": {"period": previous["period"], "p75": previous["p75"], "grade": previous["grade"]},
        "current": {"period": current["period"], "p75": current["p75"], "grade": current["grade"]},
        "interpretation": "overlapping_28_day_field_windows_not_causal_change",
    }
