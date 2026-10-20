from datetime import timedelta
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError

from tenancy.models import Project, ProjectConfiguration
from tenancy.services import Action, require_project_action

from .models import ImportRun, IntegrationConnection, SearchMetricObservation, SourceDimension
from .services import require_connection_capability


def query_growth_signals(*, project, user, connection, previous_import_id, current_import_id):
    return _comparison_signals(project=project, user=user, connection=connection,
        previous_import_id=previous_import_id, current_import_id=current_import_id, dimension=SourceDimension.QUERY)


def page_change_signals(*, project, user, connection, previous_import_id, current_import_id):
    return _comparison_signals(project=project, user=user, connection=connection,
        previous_import_id=previous_import_id, current_import_id=current_import_id, dimension=SourceDimension.PAGE)


def _comparison_signals(*, project, user, connection, previous_import_id, current_import_id, dimension):
    project = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    require_project_action(project=project, user=user, action=Action.VIEW_PROJECT)
    connection = IntegrationConnection.objects.filter(pk=connection.pk, project=project).first()
    if connection is None:
        raise PermissionDenied
    require_connection_capability(connection, "query_metrics" if dimension == SourceDimension.QUERY else "page_metrics",
                                  dimensions=[dimension])
    runs = list(ImportRun.objects.filter(
        project=project, connection=connection, pk__in=[previous_import_id, current_import_id],
    ))
    if len(runs) != 2 or previous_import_id == current_import_id:
        raise ValidationError("Choose two imports from the same current project source.")
    by_id = {run.pk: run for run in runs}
    previous, current = by_id[previous_import_id], by_id[current_import_id]
    if any(
        run.status != ImportRun.Status.SUCCEEDED or run.coverage_state != ImportRun.CoverageState.COMPLETE
        or run.observation_dimensions != [dimension] or run.row_errors
        for run in (previous, current)
    ):
        raise ValidationError("Comparison requires two complete single-grain exports.")
    duration = current.date_end - current.date_start
    if (previous.date_end - previous.date_start != duration or previous.date_end + timedelta(days=1) != current.date_start
        or any(getattr(previous, field) != getattr(current, field) for field in (
            "provider", "external_property_id", "source_format", "source_semantics", "source_semantics_version",
            "source_timezone", "source_currency",
        ))):
        raise ValidationError("Comparison requires adjacent comparable source/date windows.")
    key = "query" if dimension == SourceDimension.QUERY else "page"
    prior = list(SearchMetricObservation.objects.filter(import_run=previous, **{key + "__gt": ""}).order_by("pk")[:1001])
    latest = list(SearchMetricObservation.objects.filter(import_run=current, **{key + "__gt": ""}).order_by("pk")[:1001])
    if len(prior) > 1000 or len(latest) > 1000:
        raise ValidationError("Query windows exceed the bounded export comparison.")
    if {row.search_type for row in prior} != {row.search_type for row in latest}:
        raise ValidationError("Query windows must use the same search type.")
    previous_by_key = {(getattr(row, key), row.search_type): row for row in prior}
    settings = ProjectConfiguration.objects.filter(project=project).first()
    compared = []
    changes = []
    missing_previous = 0
    unavailable_metrics = 0
    ambiguous_zero_rows = 0
    for row in latest:
        subject = getattr(row, key)
        if dimension == SourceDimension.PAGE and (urlsplit(subject).query or urlsplit(subject).fragment):
            continue
        before = previous_by_key.get((subject, row.search_type))
        if before is None:
            missing_previous += 1
            continue
        if any(metric is None for metric in (row.clicks, row.impressions, before.clicks, before.impressions)):
            unavailable_metrics += 1
            continue
        if 0 in (row.clicks, row.impressions, before.clicks, before.impressions):
            ambiguous_zero_rows += 1
            continue
        for metric in ("clicks", "impressions"):
            old, new = getattr(before, metric), getattr(row, metric)
            if old != new:
                changes.append({key: subject, "search_type": row.search_type,
                                "metric": metric, "direction": "increased" if new > old else "decreased",
                                "previous_observation_id": before.pk, "current_observation_id": row.pk,
                                "previous": old, "current": new})
        if (before.position is not None and row.position is not None
            and before.position > 0 and row.position > before.position):
            changes.append({key: subject, "search_type": row.search_type,
                            "metric": "average_position", "direction": "worsened",
                            "previous_observation_id": before.pk, "current_observation_id": row.pk,
                            "previous": str(before.position), "current": str(row.position)})
        if dimension != SourceDimension.QUERY or row.clicks <= before.clicks and row.impressions <= before.impressions:
            continue
        compared.append({
            "query": row.query,
            "search_type": row.search_type,
            "previous_observation_id": before.pk,
            "current_observation_id": row.pk,
            "clicks_previous": before.clicks,
            "clicks_current": row.clicks,
            "click_change": row.clicks - before.clicks,
            "click_relative_change": (row.clicks - before.clicks) / before.clicks,
            "impressions_previous": before.impressions,
            "impressions_current": row.impressions,
            "impression_change": row.impressions - before.impressions,
        })
    return {
        "method": "gsc-query-growth-v1" if dimension == SourceDimension.QUERY else "gsc-page-change-v1",
        "project_id": project.pk,
        "connection_id": connection.pk,
        "provider": connection.provider,
        "property": connection.external_property_id,
        "source_semantics": connection.source_semantics,
        "source_semantics_version": connection.source_semantics_version,
        "timezone": current.source_timezone,
        "market": settings.target_country if settings else "",
        "languages": settings.target_languages if settings else [],
        "previous": {"import_id": previous.pk, "start": previous.date_start.isoformat(),
                     "end": previous.date_end.isoformat(), "collected_at": previous.created_at.isoformat()},
        "current": {"import_id": current.pk, "start": current.date_start.isoformat(),
                    "end": current.date_end.isoformat(), "collected_at": current.created_at.isoformat()},
        "coverage": {"source_completeness": "provider_export_unknown", "hidden_queries": "unknown",
                     ("missing_previous_queries" if dimension == SourceDimension.QUERY else "missing_previous_pages"): missing_previous,
                     "unavailable_metrics": unavailable_metrics, "ambiguous_zero_rows": ambiguous_zero_rows,
                     "growth_is_not_business_relevance" if dimension == SourceDimension.QUERY else "changes_are_not_causal": True},
        "candidates": sorted(compared, key=lambda item: (-item["click_change"], -item["impression_change"], item["query"]))[:100],
        "truncated_candidates": len(compared) > 100,
        "observed_changes": changes[:300],
        "truncated_observed_changes": len(changes) > 300,
    }
