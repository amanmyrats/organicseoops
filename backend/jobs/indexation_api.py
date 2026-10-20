import json
from http import HTTPStatus

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from tenancy.models import Project
from tenancy.services import Action, require_project_action

from .indexation import build_indexation_evidence, reconcile_indexation_reports
from .models import CrawlRun, IndexationEvidenceSnapshot, JobStatus


def _response(data, status=HTTPStatus.OK):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _error(message, status):
    return _response({"errors": [{"message": message}]}, status)


@require_http_methods(["GET", "POST"])
def project_indexation(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = Project.objects.for_user(request.user).filter(pk=project_id, organization_id=organization_id).first()
    if project is None:
        return _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
                               action=Action.MANAGE_PROJECT if request.method == "POST" else Action.VIEW_PROJECT)
    except PermissionDenied:
        return _error("Project evidence is unavailable.", HTTPStatus.FORBIDDEN)
    if request.method == "POST":
        try:
            if len(request.body) > 1024:
                raise ValidationError("Choose one crawl.")
            data = json.loads(request.body)
            if type(data) is not dict or set(data) != {"crawl_run_id"} or type(data["crawl_run_id"]) is not int or data["crawl_run_id"] < 1:
                raise ValidationError("Choose one crawl.")
            run = CrawlRun.objects.filter(pk=data["crawl_run_id"], project=project,
                completed_at__isnull=False, job__status__in=[JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED]).first()
            if run is None:
                return _error("Crawl not found.", HTTPStatus.NOT_FOUND)
            existed = IndexationEvidenceSnapshot.objects.filter(project=project, crawl_run=run).exists()
            snapshot = build_indexation_evidence(run.pk)
        except (UnicodeError, ValueError, TypeError, ValidationError, PermissionDenied):
            return _error("Crawl evidence is unavailable or changed.", HTTPStatus.CONFLICT)
        return _response({"project_id": project.pk, "crawl_run_id": run.pk,
                          "snapshot_id": snapshot.pk}, HTTPStatus.OK if existed else HTTPStatus.CREATED)
    choices = list(CrawlRun.objects.filter(project=project, completed_at__isnull=False,
        job__status__in=[JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED])
        .order_by("-completed_at", "-pk").values("id", "completed_at")[:21])
    selected = request.GET.get("crawl_run_id")
    if selected is not None and (not selected.isascii() or not selected.isdecimal() or len(selected) > 18):
        return _error("Choose a crawl from this project.", HTTPStatus.BAD_REQUEST)
    crawl_id = int(selected) if selected is not None else (choices[0]["id"] if choices else None)
    if selected is not None and crawl_id < 1:
        return _error("Choose a crawl from this project.", HTTPStatus.BAD_REQUEST)
    report = None
    if crawl_id is not None:
        if not CrawlRun.objects.filter(pk=crawl_id, project=project).exists():
            return _error("Crawl not found.", HTTPStatus.NOT_FOUND)
        if IndexationEvidenceSnapshot.objects.filter(project=project, crawl_run_id=crawl_id).exists():
            try:
                report = reconcile_indexation_reports(project=project, user=request.user, crawl_run_id=crawl_id)
            except (PermissionDenied, ValidationError):
                return _error("Project evidence is unavailable.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "crawl_run_id": crawl_id,
                      "crawls": [{"id": row["id"], "completed_at": row["completed_at"].isoformat()} for row in choices[:20]],
                      "has_more": len(choices) > 20, "report": report})
