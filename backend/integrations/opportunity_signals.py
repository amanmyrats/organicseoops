from decimal import Decimal
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError

from tenancy.models import Project, ProjectConfiguration
from tenancy.services import Action, require_project_action

from .models import ImportRun, IntegrationConnection, SearchMetricObservation, SourceDimension
from .services import require_connection_capability


METHOD = "gsc-csv-opportunity-v1"


def search_opportunity_signals(*, project, user, connection, import_id):
    """Candidate observations, not proven intent conflicts or action recommendations."""
    project = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    require_project_action(project=project, user=user, action=Action.VIEW_PROJECT)
    connection = IntegrationConnection.objects.filter(pk=connection.pk, project=project).first()
    if connection is None or connection.provider != "google_search_console":
        raise PermissionDenied
    run = ImportRun.objects.filter(pk=import_id, project=project, connection=connection).first()
    if run is None or run.source_format != ImportRun.SourceFormat.SEARCH_CONSOLE_CSV:
        raise ValidationError("Choose a current project Search Console export.")
    if (run.status != ImportRun.Status.SUCCEEDED or run.coverage_state != ImportRun.CoverageState.COMPLETE
        or run.row_errors or run.observation_dimensions not in ([SourceDimension.QUERY], [SourceDimension.PAGE])
        or run.provider != connection.provider or run.external_property_id != connection.external_property_id
        or run.source_semantics != connection.source_semantics
        or run.source_semantics_version != connection.source_semantics_version):
        raise ValidationError("Opportunity signals require one complete comparable source export.")
    dimension = run.observation_dimensions[0]
    require_connection_capability(connection, "query_metrics" if dimension == SourceDimension.QUERY else "page_metrics",
                                  dimensions=[dimension])
    rows = list(SearchMetricObservation.objects.filter(import_run=run).order_by("pk")[:1001])
    if len(rows) > 1000:
        raise ValidationError("Search Console export exceeds the bounded detector input.")
    omissions = {"missing_metrics": 0, "ambiguous_zero": 0, "unsupported_search_type": 0,
                 "unsafe_page_url": 0}
    candidates = []
    for row in rows:
        if row.search_type != SearchMetricObservation.SearchType.WEB or row.dimension != dimension:
            omissions["unsupported_search_type"] += 1
            continue
        if any(value is None for value in (row.clicks, row.impressions, row.ctr, row.position)):
            omissions["missing_metrics"] += 1
            continue
        if not row.clicks or not row.impressions or row.ctr == 0:
            omissions["ambiguous_zero"] += 1
            continue
        if dimension == SourceDimension.PAGE and (urlsplit(row.page).query or urlsplit(row.page).fragment):
            omissions["unsafe_page_url"] += 1
            continue
        rules = []
        if Decimal(4) <= row.position <= Decimal(20):
            rules.append("web_position_4_to_20_candidate")
        if row.impressions >= 100 and row.ctr < Decimal("0.03"):
            rules.append("web_high_impressions_low_ctr_candidate")
        for rule in rules:
            candidates.append({"detector": rule, "observation_id": row.pk,
                "query": row.query if dimension == SourceDimension.QUERY else None,
                "page": row.page if dimension == SourceDimension.PAGE else None,
                "clicks": row.clicks, "impressions": row.impressions,
                "ctr": str(row.ctr), "position": str(row.position),
                "evidence_kind": "csv_export_row_top_rows_only", "confidence": "candidate_not_proven_business_value"})
    config = ProjectConfiguration.objects.filter(project=project).first()
    return {"method": METHOD, "project_id": project.pk, "connection_id": connection.pk,
            "provider": run.provider, "property": run.external_property_id,
            "source_format": run.source_format, "source_semantics": run.source_semantics,
            "source_semantics_version": run.source_semantics_version, "dimension": dimension,
            "search_type": "web", "timezone": run.source_timezone,
            "market": config.target_country if config else "", "languages": config.target_languages if config else [],
            "window": {"start": run.date_start.isoformat(), "end": run.date_end.isoformat(),
                       "import_id": run.pk, "collected_at": run.created_at.isoformat()},
            "thresholds": {"position_inclusive": [4, 20], "min_impressions": 100, "ctr_below": "0.03"},
            "coverage": {"file": "complete", "provider_top_rows": "incomplete_unknown",
                         "hidden_queries": "unknown", "omissions": omissions,
                         "separate_query_and_page_grains": True},
            "candidates": sorted(candidates, key=lambda item: (-item["impressions"], item["detector"],
                                                               item["query"] or item["page"]))[:100],
            "truncated_candidates": len(candidates) > 100}
