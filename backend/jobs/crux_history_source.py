"""Original field-history threshold candidates, not alert or causal-regression authority."""
from datetime import date, timedelta, timezone as utc
from hashlib import sha256
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from config.artifacts import ArtifactNotFound, ArtifactStorageError, ArtifactValidationError, read_private_artifact
from providers.performance_key import performance_key_reference
from tenancy.models import Project
from tenancy.services import Action, require_project_action

from .models import JobStatus, JobStep, PerformanceObservationSnapshot
from .performance import parse_crux
from .performance_job import METHOD as JOB_METHOD, validate_performance_selection
from .performance_transport import LIMITS, _reject_json_constant, _unique_json_object

METHOD = "current-crux-history-threshold-source-v1"


def _invalid():
    raise ValidationError("Original CrUX history source needs review.")


def _encoded(value):
    try:
        result = json.dumps(value, allow_nan=False, sort_keys=True,
                            separators=(",", ":")).encode()
        if len(result) > 512 * 1024:
            _invalid()
        return result
    except (TypeError, ValueError, RecursionError, OverflowError):
        _invalid()


def _fields(row):
    values = {field.attname: getattr(row, field.attname) for field in row._meta.concrete_fields}
    return {key: value.isoformat() if isinstance(value, date) else value for key, value in values.items()}


def _source(project, actor, observation_id, assessed):
    project = Project.objects.select_related("organization").filter(
        pk=project.pk, organization_id=project.organization_id).first()
    if project is None:
        raise PermissionDenied
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    source = PerformanceObservationSnapshot.objects.select_related("job__actor", "raw_artifact").filter(
        pk=observation_id, project=project, job__project=project,
        job__organization_id=project.organization_id, source="crux_history").first()
    if source is None:
        raise PermissionDenied
    job = source.job
    data = validate_performance_selection(job.input_snapshot)
    if (job.handler != "audit_performance" or job.method_version != JOB_METHOD
        or job.status not in {JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED}
        or job.actor_id is None or "crux_history" not in data["sources"] or type(job.config_snapshot) is not dict):
        _invalid()
    require_project_action(project=project, user=job.actor, action=Action.LAUNCH_JOB)
    if job.config_snapshot.get("performance_credential") != performance_key_reference(organization=project.organization):
        raise PermissionDenied
    source.project = project
    source.full_clean()
    if not 1 <= source.raw_artifact.size_bytes <= LIMITS["crux_history"]:
        _invalid()
    step = JobStep.objects.filter(job=job, sequence=data["sources"].index("crux_history") + 1).first()
    if (step is None or step.name != "Collect performance source" or step.status != JobStep.Status.SUCCEEDED
        or step.error_category or _encoded(step.output) != _encoded({
            "source": "crux_history", "state": "recorded", "snapshot_id": source.pk})
        or not job.created_at <= step.created_at <= source.collected_at <= job.updated_at <= assessed
        or not job.created_at <= source.raw_artifact.created_at <= source.collected_at):
        _invalid()
    original = _encoded({"source": _fields(source), "job": _fields(job), "step": _fields(step),
                         "artifact": _fields(source.raw_artifact), "origin": project.canonical_origin,
                         "aliases": list(project.domain_aliases.order_by("origin").values_list("origin", flat=True))})
    return source, original


def _comparisons(output):
    periods = output["collection_periods"][-2:]
    windows = [{**period, "calendar_days": (date.fromisoformat(period["end"]) -
                date.fromisoformat(period["start"])).days + 1} for period in periods]
    overlap = None
    comparable = False
    if len(windows) == 2:
        previous, current = windows
        starts = [date.fromisoformat(item["start"]) for item in windows]
        ends = [date.fromisoformat(item["end"]) for item in windows]
        overlap = max(0, (min(ends) - max(starts)).days + 1)
        comparable = (all(item["calendar_days"] == 28 for item in windows)
                      and (starts[1] - starts[0]).days == (ends[1] - ends[0]).days == 7)
    rows = []
    rank = {"good": 0, "needs_improvement": 1, "poor": 2}
    for name in ("LCP", "INP", "CLS"):
        observations = [item for item in output["metrics"] if item["name"] == name][-2:]
        state = ("unknown_insufficient_eligible_periods" if len(observations) < 2 or
                 any(item["state"] != "observed" for item in observations)
                 else "incomparable_source_periods" if not comparable
                 else "threshold_worsening_candidate" if rank[observations[1]["grade"]] > rank[observations[0]["grade"]]
                 else "no_threshold_worsening_observed")
        rows.append({"metric": name, "state": state, "unit": observations[-1]["unit"],
                     "observations": [{"period": windows[index], "p75": item["p75"], "grade": item["grade"],
                                       "state": item["state"]} for index, item in enumerate(observations)],
                     "overlap_calendar_days": overlap,
                     "period_contract": "weekly_28_day_windows" if comparable else "not_comparable",
                     "sample_count": "unknown", "interpretation": "field_threshold_candidate_not_confirmed_seo_regression_or_causal_change"})
    return rows


def current_crux_history_source(*, project, actor, observation_id):
    if type(observation_id) is not int or not 1 <= observation_id < 2**53:
        _invalid()
    assessed = timezone.now()
    source, original = _source(project, actor, observation_id, assessed)
    result = {"method_version": METHOD, "project_id": project.pk, "observation_id": source.pk,
              "job_id": source.job_id, "assessed_at": assessed.isoformat(),
              "collected_at": source.collected_at.isoformat(), "raw_sha256": source.raw_sha256,
              "state": "unknown_original_raw_integrity", "comparisons": []}
    if source.raw_sha256 is not None:
        try:
            raw = read_private_artifact(source.raw_artifact.key)
            if (type(raw) is not bytes or not 1 <= len(raw) <= LIMITS["crux_history"]
                or len(raw) != source.raw_artifact.size_bytes or sha256(raw).hexdigest() != source.raw_sha256):
                _invalid()
            payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_object,
                                 parse_constant=_reject_json_constant)
            if _encoded(payload) != raw:
                _invalid()
            output = parse_crux(project=source.project, requested_url=source.target, requested_grain=source.grain,
                form_factor={"mobile": "PHONE", "desktop": "DESKTOP", "tablet": "TABLET"}[source.strategy],
                payload=payload, history=True)
            if _encoded(output) != _encoded(source.output):
                _invalid()
            original_source_day = (source.collected_at.astimezone(utc.utc) - timedelta(hours=8)).date()
            if any(date.fromisoformat(period["end"]) > original_source_day for period in output["collection_periods"]):
                _invalid()
            result.update(state="available_original_field_history", source_method=output["method"],
                form_factor=output["form_factor"], requested_grain=output["requested_grain"],
                observed_grain=output["observed_grain"], origin_fallback=output["origin_fallback"],
                url_normalization=output["url_normalization"], collection_timezone=output["collection_timezone"],
                source_period_count=len(output["collection_periods"]), comparisons=_comparisons(output))
        except (ArtifactNotFound, ArtifactStorageError, ArtifactValidationError, UnicodeError,
                ValueError, TypeError, KeyError, RecursionError, OverflowError):
            _invalid()
    if _source(project, actor, observation_id, assessed)[1] != original:
        raise PermissionDenied
    return result
