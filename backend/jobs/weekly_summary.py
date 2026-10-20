"""Read-only retained report metadata, not weekly SEO changes or mail authority."""
from datetime import datetime, timedelta, timezone as utc
import json
import re

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from tenancy.services import Action, require_project_action
from .models import ActionOutcomeSnapshot, ActionReview, Finding, ProjectReportSnapshot
from .reporting import _render_report, read_project_report


METHOD = "retained-report-weekly-source-v1"
LIMITS = "selected_source_rows_only_not_complete_provider_coverage_or_causal_uplift"
_COMMON = {"kind", "source_id", "id", "recorded_at", "summary", "coverage"}
_EXTRA = {
    "candidate": {"method_version", "confidence"},
    "human_action": {"state", "criteria", "implementation_at", "verification_at", "outcome_at"},
    "observed_page_outcome": {"method_version", "search_metrics", "conversion", "interpretation"},
}


def _invalid():
    raise ValidationError("Retained weekly report source needs review.")


def _date(value):
    if type(value) is not str or len(value) > 40:
        _invalid()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        _invalid()
    if timezone.is_naive(parsed):
        _invalid()
    return parsed.astimezone(utc.utc)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _recipient(project, recipient):
    require_project_action(project=project, user=recipient, action=Action.VIEW_PROJECT)
    email = get_user_model().objects.values_list("email", flat=True).get(pk=recipient.pk)
    if not EmailAddress.objects.filter(user_id=recipient.pk, email=email, primary=True, verified=True).exists():
        raise PermissionDenied


def _original_rows(snapshot):
    snapshot.clean()
    # Reuse the real report renderer to bind historical IDs, dates and coverage without another schema.
    return json.loads(_render_report(snapshot.project,
        list(Finding.objects.filter(project=snapshot.project, pk__in=snapshot.finding_ids).order_by("pk")),
        list(ActionReview.objects.filter(project=snapshot.project, pk__in=snapshot.action_review_ids).order_by("pk")),
        list(ActionOutcomeSnapshot.objects.filter(project=snapshot.project, pk__in=snapshot.outcome_ids).order_by("pk")),
        "json"))["rows"]


def _rows(body, snapshot):
    if (type(body) is not dict or set(body) != {"version", "project_id", "created_at", "rows", "limits"}
        or body["version"] != "project-report-v1" or type(body["project_id"]) is not int
        or body["project_id"] != snapshot.project_id or body["limits"] != LIMITS
        or type(body["rows"]) is not list or not 1 <= len(body["rows"]) <= 60):
        _invalid()
    rendered = _date(body["created_at"])
    if rendered > snapshot.created_at:
        _invalid()
    expected = {"candidate": snapshot.finding_ids, "human_action": snapshot.action_review_ids,
                "observed_page_outcome": snapshot.outcome_ids}
    seen = {kind: [] for kind in expected}
    rows = []
    for row in body["rows"]:
        if type(row) is not dict or type(row.get("kind")) is not str or row["kind"] not in expected:
            _invalid()
        kind = row["kind"]
        if (set(row) != _COMMON | _EXTRA[kind] or type(row["id"]) is not int or row["id"] < 1
            or type(row["source_id"]) is not int or row["source_id"] < 1
            or type(row["summary"]) is not str or not 1 <= len(row["summary"]) <= 8192
            or type(row["coverage"]) not in (str, dict)
            or len(json.dumps(row["coverage"], allow_nan=False).encode()) > 4096):
            _invalid()
        recorded = _date(row["recorded_at"])
        if recorded > rendered:
            _invalid()
        item = {key: row[key] for key in ("kind", "id", "source_id", "recorded_at", "coverage")}
        if kind == "human_action":
            if (row["state"] not in ActionReview.State.values or type(row["criteria"]) is not str
                or not 1 <= len(row["criteria"]) <= 500):
                _invalid()
            stages = {"implemented": 1, "verified": 2, "outcome_reviewed": 3}
            dates = [row[key] for key in ("implementation_at", "verification_at", "outcome_at")]
            required = stages.get(row["state"], 0)
            if any((value is not None) != (index < required) for index, value in enumerate(dates)):
                _invalid()
            ordered = [_date(value) for value in dates[:required]] + [recorded]
            if ordered != sorted(ordered):
                _invalid()
            item.update({key: row[key] for key in ("state", "implementation_at", "verification_at", "outcome_at")})
        else:
            if type(row["method_version"]) is not str or not 1 <= len(row["method_version"]) <= 64:
                _invalid()
            item["method_version"] = row["method_version"]
            if kind == "candidate":
                if type(row["confidence"]) is not str or not 1 <= len(row["confidence"]) <= 40:
                    _invalid()
                item["confidence"] = row["confidence"]
            elif (type(row["search_metrics"]) is not dict or type(row["conversion"]) is not dict
                  or row["interpretation"] != "observed_comparable_page_rows_not_causal_uplift"):
                _invalid()
        seen[kind].append(row["id"])
        rows.append(item)
    if any(sorted(seen[kind]) != sorted(ids) for kind, ids in expected.items()):
        _invalid()
    return rendered, rows


def retained_weekly_report_source(*, project, recipient):
    assessed = timezone.now().astimezone(utc.utc)
    end = assessed.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=assessed.weekday())
    start = end - timedelta(days=7)
    _recipient(project, recipient)
    candidates = ProjectReportSnapshot.objects.filter(project_id=project.pk, content_format="json",
        created_at__gte=start, created_at__lt=end).order_by("-created_at", "-pk")
    snapshot = candidates.first()
    result = {"method_version": METHOD, "project_id": project.pk, "assessed_at": assessed.isoformat(),
              "week_start": start.isoformat(), "week_end": end.isoformat(),
              "week_basis": "report_creation_not_seo_change_occurrence", "limits": LIMITS,
              "state": "unavailable_no_report", "report_id": None, "report_created_at": None,
              "body_created_at": None, "source_sha256": None, "source_counts": None, "rows": []}
    if snapshot is None:
        _recipient(project, recipient)
        if candidates.exists():
            _invalid()
        return result
    original = {field.attname: getattr(snapshot, field.attname) for field in snapshot._meta.concrete_fields}
    if (not 1 <= snapshot.size_bytes <= 131072 or not re.fullmatch(r"[0-9a-f]{64}", snapshot.content_sha256)
        or snapshot.created_at > assessed):
        _invalid()
    original_rows = _original_rows(snapshot)
    data = read_project_report(project=project, actor=recipient, snapshot=snapshot)
    if not 1 <= len(data) <= 131072:
        _invalid()
    try:
        body = json.loads(data.decode("utf-8"), object_pairs_hook=_object,
                          parse_constant=lambda value: _invalid())
        rendered, rows = _rows(body, snapshot)
        if body["rows"] != original_rows:
            _invalid()
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError):
        _invalid()
    # Readback is historical source integrity, not permission to reuse the original actors/sources.
    if (not ProjectReportSnapshot.objects.filter(**original).exists()
        or candidates.values_list("pk", flat=True).first() != snapshot.pk):
        raise PermissionDenied
    if _original_rows(snapshot) != original_rows:
        _invalid()
    _recipient(project, recipient)
    result.update(state="available_selected_snapshot", report_id=snapshot.pk,
                  report_created_at=snapshot.created_at.isoformat(), body_created_at=rendered.isoformat(),
                  source_sha256=snapshot.content_sha256, rows=rows,
                  source_counts={"findings": len(snapshot.finding_ids), "actions": len(snapshot.action_review_ids),
                                 "outcomes": len(snapshot.outcome_ids)})
    return result
