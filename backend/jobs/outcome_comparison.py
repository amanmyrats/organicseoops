"""Source-compatible before/after page metrics; observation is not causation."""
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from integrations.models import ImportRun, IntegrationConnection, SearchMetricObservation, SourceDimension
from integrations.services import require_connection_capability
from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action

from .intent_mapping import _project_page
from .models import ActionOutcomeSnapshot, ActionReview


def _change(before, after):
    if before is None or after is None:
        return {"state": "unavailable", "previous": None if before is None else str(before),
                "current": None if after is None else str(after), "absolute_change": None,
                "relative_change": None}
    difference = after - before
    return {"state": "zero_baseline" if before == 0 else "observed",
            "previous": str(before), "current": str(after), "absolute_change": str(difference),
            "relative_change": None if before == 0 else str(
                (Decimal(difference) / Decimal(before)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))}


def compare_page_rows(previous, current):
    """Each argument is one same-property, page-only, web observation or None."""
    if previous is None or current is None:
        return {"state": "unavailable_missing_export_row_not_zero", "clicks": _change(None, None),
                "impressions": _change(None, None), "ctr": _change(None, None),
                "average_position": _change(None, None)}
    old_ctr = previous.ctr if previous.impressions and previous.ctr is not None else None
    new_ctr = current.ctr if current.impressions and current.ctr is not None else None
    return {"state": "observed_source_rows_not_causal",
            "clicks": _change(previous.clicks, current.clicks),
            "impressions": _change(previous.impressions, current.impressions),
            "ctr": {**_change(old_ctr, new_ctr), "unit": "fraction; absolute change is fraction points"},
            "average_position": {**_change(previous.position, current.position),
                                 "unit": "source average position; lower is not universal observed rank"}}


def compare_action_page_windows(*, project, actor, action_id, connection_id, previous_import_id, current_import_id,
                                now=None):
    project = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    try:
        action_id = UUID(str(action_id))
    except ValueError:
        raise ValidationError("Select one current action.") from None
    action = ActionReview.objects.filter(project=project, action_id=action_id).order_by("-revision").first()
    if action is None:
        raise PermissionDenied
    if action.state not in {ActionReview.State.IMPLEMENTED, ActionReview.State.VERIFIED,
                            ActionReview.State.OUTCOME_REVIEWED} or not action.implemented_at:
        raise ValidationError("Only a logged implementation can have a follow-up comparison.")
    page = _project_page(project, action.affected_urls[-1])
    connection = IntegrationConnection.objects.filter(pk=connection_id, project=project).first()
    if connection is None:
        raise PermissionDenied
    require_connection_capability(connection, "page_metrics", dimensions=[SourceDimension.PAGE])
    if type(previous_import_id) is not int or type(current_import_id) is not int or previous_import_id == current_import_id:
        raise ValidationError("Choose two distinct page exports from one source.")
    runs = list(ImportRun.objects.filter(project=project, connection=connection,
                                         pk__in=[previous_import_id, current_import_id]))
    if len(runs) != 2:
        raise PermissionDenied
    by_id = {row.pk: row for row in runs}
    before_run, after_run = by_id[previous_import_id], by_id[current_import_id]
    if any(run.status != ImportRun.Status.SUCCEEDED or run.coverage_state != ImportRun.CoverageState.COMPLETE
           or run.row_errors or run.observation_dimensions != [SourceDimension.PAGE]
           for run in (before_run, after_run)):
        raise ValidationError("Two complete page-only CSV exports are required.")
    if (before_run.date_end - before_run.date_start != after_run.date_end - after_run.date_start
        or any(getattr(before_run, key) != getattr(after_run, key) for key in (
            "provider", "external_property_id", "source_format", "source_semantics",
            "source_semantics_version", "source_timezone", "source_currency"))):
        raise ValidationError("Source, property, grain, timezone, currency and window lengths must match.")
    local_day = action.implemented_at.astimezone(ZoneInfo(after_run.source_timezone)).date()
    if (before_run.date_end >= local_day or after_run.date_start <= local_day
        or before_run.created_at > action.implemented_at):
        raise ValidationError("A recorded pre-change baseline and post-change window must bracket implementation.")
    def row(run):
        results = list(SearchMetricObservation.objects.filter(import_run=run, page=page,
                       search_type=SearchMetricObservation.SearchType.WEB).order_by("pk")[:2])
        if len(results) > 1:
            raise ValidationError("Page export has ambiguous duplicate web rows.")
        return results[0] if results else None

    before, after = row(before_run), row(after_run)
    now = now or timezone.now()
    return {"method_version": "gsc-csv-page-outcome-v1", "project_id": project.pk,
            "action_id": str(action_id), "action_revision": action.revision,
            "connection_id": connection.pk, "provider": connection.provider,
            "property": before_run.external_property_id, "page": page,
            "source_semantics": before_run.source_semantics,
            "source_semantics_version": before_run.source_semantics_version,
            "timezone": after_run.source_timezone, "currency": after_run.source_currency,
            "before": {"import_id": before_run.pk, "start": before_run.date_start.isoformat(),
                       "end": before_run.date_end.isoformat(), "observation_id": before.pk if before else None},
            "after": {"import_id": after_run.pk, "start": after_run.date_start.isoformat(),
                      "end": after_run.date_end.isoformat(), "observation_id": after.pk if after else None},
            "implementation_date": local_day.isoformat(),
            "gap_days": (after_run.date_start - before_run.date_end).days - 1,
            "reporting_lag_days": max(0, (now.astimezone(ZoneInfo(after_run.source_timezone)).date()
                                          - after_run.date_end).days),
            "coverage": "uploaded_file_rows_complete_provider_top_rows_unknown",
            "search_metrics": compare_page_rows(before, after),
            "conversion": {"state": "unavailable_no_exact_origin_ga4_source"},
            "interpretation": "observed_comparable_page_rows_not_causal_uplift"}


def record_page_outcome(*, project, actor, action_id, connection_id, previous_import_id, current_import_id):
    try:
        action_id = UUID(str(action_id))
    except ValueError:
        raise ValidationError("Select a current action.") from None
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        action = ActionReview.objects.filter(project=project, action_id=action_id).order_by("-revision").first()
        if action is None:
            raise PermissionDenied
        existing = ActionOutcomeSnapshot.objects.filter(action_review=action, project=project).first()
        if existing:
            if (existing.actor_id != actor.pk or existing.connection_id != connection_id
                or existing.previous_import_id != previous_import_id
                or existing.current_import_id != current_import_id):
                raise ValidationError("A different comparison was already recorded for this action revision.")
            return existing
        report = compare_action_page_windows(project=project, actor=actor, action_id=action_id,
            connection_id=connection_id, previous_import_id=previous_import_id, current_import_id=current_import_id)
        connection = IntegrationConnection.objects.get(pk=connection_id, project=project)
        before = ImportRun.objects.get(pk=previous_import_id, project=project, connection=connection)
        after = ImportRun.objects.get(pk=current_import_id, project=project, connection=connection)
        return ActionOutcomeSnapshot.objects.create(project=project, action_review=action, actor=actor,
            connection=connection, previous_import=before, current_import=after,
            method_version=report["method_version"], page=report["page"], report=report)
