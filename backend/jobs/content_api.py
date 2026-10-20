from http import HTTPStatus
import json

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.db.models import OuterRef, Subquery
from django.http import HttpResponse
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from tenancy.services import Action, require_project_action
from .ai_text_api import _project
from .content import record_content, require_current_brief
from .content_brief import read_content_brief
from .models import ContentItem, ContentRevision
from .research_api import _result


def _revision(row, text=True):
    result = {key: getattr(row, key) for key in ("id", "project_id", "item_id", "brief_id", "revision", "state", "kind",
        "title", "reason", "actor_id", "generating_job_id", "reviewed_revision_id", "approved_by_id", "publication_url")}
    result.update({key: getattr(row, key).isoformat() if getattr(row, key) else None
                   for key in ("created_at", "approved_at", "published_at")})
    if text:
        result.update(body=row.body, meta_description=row.meta_description)
    return result


@require_http_methods(["GET", "POST"])
def project_content(request, organization_id, project_id, item_id=None, download=False):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
    except PermissionDenied:
        return _result({"message": "Content unavailable."}, HTTPStatus.FORBIDDEN)
    item = ContentItem.objects.filter(project=project, pk=item_id).first() if item_id else None
    if item_id and item is None:
        return _result({"message": "Content unavailable."}, HTTPStatus.NOT_FOUND)
    if request.method == "POST":
        if download:
            return _result({"message": "Read-only export."}, HTTPStatus.METHOD_NOT_ALLOWED)
        if not ratelimit.consume(request, action="ai_text_request", user=request.user):
            return _result({"message": "Too many content requests."}, HTTPStatus.TOO_MANY_REQUESTS)
        try:
            if len(request.body) > 200000:
                raise ValidationError("Text exceeds the editor ceiling.")
            data = json.loads(request.body)
            required = {"request_key", "brief_id", "kind", "title", "body", "meta_description", "state", "reason"}
            if item:
                required.add("expected_revision")
            if type(data) is not dict or not required <= set(data) or set(data) - required - {"publication_url", "published_at"}:
                raise ValidationError("Choose exact native-text revision fields.")
            if "published_at" in data:
                data["published_at"] = parse_datetime(data["published_at"])
            row = record_content(project=project, actor=request.user, item_id=item_id, **data)
        except PermissionDenied:
            return _result({"message": "Content role or source access unavailable."}, HTTPStatus.FORBIDDEN)
        except (ValidationError, ValueError, TypeError, IntegrityError):
            return _result({"message": "Content/source changed or review is incomplete. Reload the current revision; changed text needs a new draft."}, HTTPStatus.CONFLICT)
        return _result({"project_id": project.pk, "revision": _revision(row)}, HTTPStatus.CREATED)
    if item is None:
        try:
            before_item = int(request.GET.get("before", "9223372036854775807"))
            if before_item <= 0:
                raise ValueError
        except ValueError:
            return _result({"message": "Choose a content inventory cursor."}, HTTPStatus.BAD_REQUEST)
        latest = ContentRevision.objects.filter(item_id=OuterRef("item_id")).order_by("-revision").values("pk")[:1]
        rows = list(ContentRevision.objects.filter(project=project, item_id__lt=before_item, pk=Subquery(latest)).order_by("-item_id")[:21])
        return _result({"project_id": project.pk, "items": [_revision(row, False) for row in rows[:20]],
            "next_before": rows[19].item_id if len(rows) > 20 else None})
    try:
        after = int(request.GET.get("before", "2147483647"))
        if after <= 0:
            raise ValueError
    except ValueError:
        return _result({"message": "Choose a revision history cursor."}, HTTPStatus.BAD_REQUEST)
    current = ContentRevision.objects.filter(item=item).order_by("-revision").first()
    if current is None:
        return _result({"message": "Content unavailable."}, HTTPStatus.NOT_FOUND)
    if download:
        response = HttpResponse(json.dumps({"version": "manual-content-export-v1", "scope": "private_text_no_site_change",
            "revision": _revision(current)}, ensure_ascii=False), content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="content-{item.pk}-revision-{current.revision}.json"'
        response["Cache-Control"] = "private, no-store"
        response["X-Robots-Tag"] = "noindex, nofollow"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'"
        return response
    rows = list(ContentRevision.objects.filter(item=item, revision__lt=after).order_by("-revision")[:11])
    try:
        evidence = read_content_brief(project=project, actor=request.user, brief=current.brief)
        try:
            require_current_brief(project, request.user, current.brief)
            source_state = "current_review_still_required"
        except (PermissionDenied, ValidationError, KeyError, TypeError):
            source_state = "stale_prepare_new_brief_before_review"
    except ValidationError:
        evidence, source_state = None, "private_brief_unavailable"
    return _result({"project_id": project.pk, "current": _revision(current), "history": [_revision(row) for row in rows[:10]],
        "next_before": rows[9].revision if len(rows) > 10 else None, "brief": evidence, "source_state": source_state})
