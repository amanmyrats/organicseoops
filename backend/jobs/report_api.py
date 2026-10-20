from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.views.decorators.http import require_GET, require_http_methods
from config.artifacts import ArtifactStorageError

from tenancy.services import Action, require_project_action

from .findings_api import _error, _payload, _project, _response
from .models import ProjectReportSnapshot
from .reporting import create_project_report, read_project_report


def _access(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return None, _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return None, _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
    except PermissionDenied:
        return None, _error("Project reports are unavailable.", HTTPStatus.FORBIDDEN)
    return project, None


def _summary(row):
    return {"id": row.pk, "format": row.content_format, "size_bytes": row.size_bytes,
            "source_counts": {"findings": len(row.finding_ids), "actions": len(row.action_review_ids),
                              "outcomes": len(row.outcome_ids)},
            "created_at": row.created_at.isoformat(), "state": "private_snapshot"}


@require_http_methods(["GET", "POST"])
def project_reports(request, organization_id, project_id):
    project, error = _access(request, organization_id, project_id)
    if error:
        return error
    if request.method == "GET":
        rows = list(ProjectReportSnapshot.objects.filter(project=project).order_by("-created_at", "-pk")[:51])
        return _response({"project_id": project.pk, "reports": [_summary(row) for row in rows[:50]],
                          "has_more": len(rows) > 50})
    if not ratelimit.consume(request, action="report_export", user=request.user):
        return _error("Too many report requests. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        body = _payload(request, {"request_key", "format", "finding_ids", "action_review_ids", "outcome_ids"})
        snapshot = create_project_report(project=project, actor=request.user,
                                         request_key=body["request_key"], content_format=body["format"],
                                         finding_ids=body["finding_ids"], action_review_ids=body["action_review_ids"],
                                         outcome_ids=body["outcome_ids"])
    except PermissionDenied:
        return _error("Report sources are unavailable in this project.", HTTPStatus.NOT_FOUND)
    except ArtifactStorageError:
        return _error("Report capture is busy or unavailable. Try again later.", HTTPStatus.SERVICE_UNAVAILABLE)
    except ValidationError:
        return _error("Choose bounded current project report sources.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "report": _summary(snapshot)}, HTTPStatus.CREATED)


@require_GET
def project_report_download(request, organization_id, project_id, report_id):
    project, error = _access(request, organization_id, project_id)
    if error:
        return error
    report = ProjectReportSnapshot.objects.filter(pk=report_id, project=project).first()
    if report is None:
        return _error("Report not found.", HTTPStatus.NOT_FOUND)
    try:
        data = read_project_report(project=project, actor=request.user, snapshot=report)
    except PermissionDenied:
        return _error("Report not found.", HTTPStatus.NOT_FOUND)
    except ValidationError:
        return _error("Private report is unavailable.", HTTPStatus.SERVICE_UNAVAILABLE)
    return report_file_response(report, data)


def report_file_response(report, data):
    response = HttpResponse(data, content_type="application/json" if report.content_format == "json"
                            else "text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="project-report-{report.pk}.{report.content_format}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'"
    return response
