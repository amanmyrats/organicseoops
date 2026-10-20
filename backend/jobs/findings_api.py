import json
from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from integrations.models import ImportRun, IntegrationConnection
from integrations.services import require_connection_capability
from tenancy.models import Project
from tenancy.services import Action, require_project_action

from .findings import (indexation_finding_current, performance_finding_current,
                        record_csv_findings, record_indexation_findings, record_query_change_findings,
                        record_page_change_findings, record_performance_findings, record_technical_findings,
                       review_finding, technical_finding_current)
from .indexation import reconcile_indexation_reports
from .models import (Finding, IndexationEvidenceSnapshot, Opportunity,
                     PerformanceObservationSnapshot, TechnicalDiagnosticsSnapshot)


def _response(data, status=HTTPStatus.OK):
    result = JsonResponse(data, status=status)
    result["Cache-Control"] = "private, no-store"
    return result


def _error(message, status):
    return _response({"errors": [{"message": message}]}, status)


def _project(request, organization_id, project_id):
    return Project.objects.for_user(request.user).filter(pk=project_id, organization_id=organization_id).first()


def _payload(request, keys):
    if len(request.body) > 4096:
        raise ValidationError("Choose bounded finding fields.")
    try:
        data = json.loads(request.body)
    except (UnicodeError, ValueError):
        raise ValidationError("Choose valid finding fields.") from None
    if type(data) is not dict or set(data) != keys:
        raise ValidationError("Choose exact finding fields.")
    return data


@require_GET
def project_findings(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
    except PermissionDenied:
        return _error("Findings are unavailable.", HTTPStatus.FORBIDDEN)
    findings = list(Finding.objects.filter(project=project, source_passive_header__isnull=True,
        source_passive_resource__isnull=True, source_passive_tls__isnull=True, source_passive_redirect__isnull=True,
        source_passive_redirect_chain__isnull=True).select_related("source_metric__import_run__connection",
        "source_indexation", "source_diagnostics__crawl_run__job__actor", "source_performance__job__actor")
                    .order_by("-detected_at", "-pk")[:51])
    reviews = {item.finding_id: item for item in Opportunity.objects.filter(finding__in=findings[:50], project=project)
               .order_by("finding_id", "-revision").distinct("finding_id")}
    rows = []
    indexation_reports = {}
    for finding in findings[:50]:
        source = finding.source_metric
        current = False
        if source is not None and source.import_run.project_id == project.pk:
            connection = source.import_run.connection
            try:
                require_connection_capability(connection, "query_metrics" if source.query else "page_metrics",
                                              dimensions=[source.dimension])
                current = True
            except (PermissionDenied, ValidationError):
                pass
        elif finding.source_indexation_id and finding.source_indexation.project_id == project.pk:
            snapshot = finding.source_indexation
            if snapshot.pk not in indexation_reports:
                try:
                    indexation_reports[snapshot.pk] = reconcile_indexation_reports(
                        project=project, user=request.user, crawl_run_id=snapshot.crawl_run_id)
                except (PermissionDenied, ValidationError):
                    indexation_reports[snapshot.pk] = None
            report = indexation_reports[snapshot.pk]
            if report is not None:
                current = indexation_finding_current(project=project, user=request.user,
                                                     finding=finding, report=report)
        elif finding.source_diagnostics_id:
            current = technical_finding_current(project=project, finding=finding)
        elif finding.source_performance_id:
            current = performance_finding_current(project=project, finding=finding)
        review = reviews.get(finding.pk)
        rows.append({"id": finding.pk, "detector": finding.detector,
                     "method_version": finding.method_version, "subject": finding.subject,
                     "source_metric_id": finding.source_metric_id,
                     "source_indexation_id": finding.source_indexation_id,
                     "source_diagnostics_id": finding.source_diagnostics_id,
                     "source_performance_id": finding.source_performance_id,
                     "source_import_id": source.import_run_id if source else None,
                     "source_connection_id": source.import_run.connection_id if source else None,
                     "source_current": current, "confidence": finding.confidence,
                     "evidence": finding.evidence, "detected_at": finding.detected_at.isoformat(),
                     "review": None if review is None else {"id": review.pk, "revision": review.revision,
                         "priority": review.priority, "estimated_effort": review.estimated_effort,
                         "business_relevance": review.business_relevance,
                         "review_reason": review.review_reason}})
    return _response({"project_id": project.pk, "findings": rows, "has_more": len(findings) > 50})


@require_POST
def project_import_findings(request, organization_id, project_id, connection_id, import_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
    except PermissionDenied:
        return _error("You cannot record findings for this project.", HTTPStatus.FORBIDDEN)
    connection = IntegrationConnection.objects.filter(pk=connection_id, project=project).first()
    if connection is None or not ImportRun.objects.filter(pk=import_id, connection=connection, project=project).exists():
        return _error("Source import not found.", HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="finding_materialize", user=request.user):
        return _error("Finding requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        _payload(request, set())
        records, truncated = record_csv_findings(project=project, actor=request.user,
                                                 connection=connection, import_id=import_id)
    except PermissionDenied:
        return _error("Source authorization changed.", HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Complete current source evidence is required.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "connection_id": connection.pk, "import_id": import_id,
                      "finding_ids": [item.pk for item in records], "truncated_candidates": truncated,
                      "status": "recorded_candidate_evidence_not_prioritized"}, HTTPStatus.CREATED)


@require_POST
@require_POST
def project_page_change_findings(request, organization_id, project_id, connection_id):
    return _project_comparison_findings(request, organization_id, project_id, connection_id,
                                        record_page_change_findings)


@require_POST
def project_query_change_findings(request, organization_id, project_id, connection_id):
    return _project_comparison_findings(request, organization_id, project_id, connection_id,
                                        record_query_change_findings)


def _project_comparison_findings(request, organization_id, project_id, connection_id, recorder):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
    except PermissionDenied:
        return _error("You cannot record query changes.", HTTPStatus.FORBIDDEN)
    connection = IntegrationConnection.objects.filter(pk=connection_id, project=project).first()
    if connection is None:
        return _error("Source connection not found.", HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="finding_materialize", user=request.user):
        return _error("Finding requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        data = _payload(request, {"previous_import_id", "current_import_id"})
        if any(type(value) is not int or value < 1 for value in data.values()):
            raise ValidationError("Choose two source imports.")
        findings, truncated = recorder(project=project, actor=request.user,
            connection=connection, **data)
    except PermissionDenied:
        return _error("Source authorization changed.", HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Comparable current query imports are required.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "connection_id": connection.pk,
                      "finding_ids": [finding.pk for finding in findings],
                      "truncated_candidates": truncated,
                      "status": "recorded_candidate_evidence_not_prioritized"}, HTTPStatus.CREATED)


@require_POST
def project_indexation_findings(request, organization_id, project_id, crawl_run_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
    except PermissionDenied:
        return _error("You cannot record indexation findings.", HTTPStatus.FORBIDDEN)
    if not IndexationEvidenceSnapshot.objects.filter(project=project, crawl_run_id=crawl_run_id).exists():
        return _error("Crawl evidence not found.", HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="finding_materialize", user=request.user):
        return _error("Finding requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        _payload(request, set())
        findings, source_status, truncated = record_indexation_findings(project=project, actor=request.user,
                                                              crawl_run_id=crawl_run_id)
    except PermissionDenied:
        return _error("Indexation source authorization changed.", HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Current crawl or engine evidence is unavailable.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "crawl_run_id": crawl_run_id,
                      "finding_ids": [finding.pk for finding in findings],
                      "engine_report_scope": source_status, "truncated_candidates": truncated,
                      "status": "recorded_candidate_evidence_not_prioritized"}, HTTPStatus.CREATED)


@require_POST
def project_technical_findings(request, organization_id, project_id, diagnostics_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
    except PermissionDenied:
        return _error("You cannot record technical findings.", HTTPStatus.FORBIDDEN)
    if not TechnicalDiagnosticsSnapshot.objects.filter(pk=diagnostics_id, project=project).exists():
        return _error("Technical evidence not found.", HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="finding_materialize", user=request.user):
        return _error("Finding requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        _payload(request, set())
        findings, truncated = record_technical_findings(project=project, actor=request.user,
                                                        diagnostics_id=diagnostics_id)
    except PermissionDenied:
        return _error("Technical source authorization changed.", HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Current technical evidence is unavailable.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "diagnostics_id": diagnostics_id,
                      "finding_ids": [finding.pk for finding in findings],
                      "truncated_candidates": truncated,
                      "status": "recorded_candidate_evidence_not_prioritized"}, HTTPStatus.CREATED)


@require_POST
def project_performance_findings(request, organization_id, project_id, observation_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
    except PermissionDenied:
        return _error("You cannot record performance findings.", HTTPStatus.FORBIDDEN)
    if not PerformanceObservationSnapshot.objects.filter(pk=observation_id, project=project).exists():
        return _error("Performance evidence not found.", HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="finding_materialize", user=request.user):
        return _error("Finding requests are temporarily limited.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        _payload(request, set())
        findings, truncated = record_performance_findings(project=project, actor=request.user,
                                                           observation_id=observation_id)
    except PermissionDenied:
        return _error("Performance source authorization changed.", HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Current parsed performance evidence is unavailable.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "observation_id": observation_id,
                      "finding_ids": [finding.pk for finding in findings],
                      "truncated_candidates": truncated,
                      "status": "recorded_candidate_evidence_not_prioritized"}, HTTPStatus.CREATED)


@require_POST
def project_finding_review(request, organization_id, project_id, finding_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
    except PermissionDenied:
        return _error("You cannot prioritize this project evidence.", HTTPStatus.FORBIDDEN)
    if not Finding.objects.filter(pk=finding_id, project=project).exists():
        return _error("Finding not found.", HTTPStatus.NOT_FOUND)
    try:
        data = _payload(request, {"expected_revision", "priority", "estimated_effort", "business_relevance", "reason"})
        review = review_finding(project=project, actor=request.user, finding_id=finding_id,
            expected_revision=data["expected_revision"], priority=data["priority"],
            estimated_effort=data["estimated_effort"], business_relevance=data["business_relevance"],
            reason=data["reason"])
    except PermissionDenied:
        return _error("Finding source is outside current project scope.", HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Opportunity review changed or its source is unavailable.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "finding_id": finding_id,
                      "review": {"id": review.pk, "revision": review.revision, "priority": review.priority,
                                 "estimated_effort": review.estimated_effort,
                                 "business_relevance": review.business_relevance,
                                 "review_reason": review.review_reason},
                      "recommendation": None, "approved_action": None}, HTTPStatus.CREATED)
