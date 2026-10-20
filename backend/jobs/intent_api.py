from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.http import require_http_methods

from tenancy.models import ProjectConfiguration
from tenancy.services import Action, require_project_action

from .findings_api import _error, _payload, _project, _response
from .intent_mapping import current_query_findings, review_intent_cluster
from .models import IntentClusterReview


def _require_project(request, organization_id, project_id, *, edit=False):
    if not request.user.is_authenticated or not request.user.is_active:
        return None, _error("Authentication required.", HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return None, _error("Project not found.", HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
                               action=Action.MANAGE_PROJECT if edit else Action.VIEW_PROJECT)
    except PermissionDenied:
        return None, _error("Intent mapping is unavailable.", HTTPStatus.FORBIDDEN)
    return project, None


def _serialize(project, review):
    findings = list(review.source_finding_ids)
    if review.manual_topics:
        config = ProjectConfiguration.objects.filter(project=project).first()
        source_current = bool(config and all(topic in config.seed_topics for topic in review.manual_topics))
        queries = list(review.manual_topics) if source_current else []
        source_kind = "manual_seed_no_search_observation"
    else:
        try:
            sources = {finding.pk: finding.subject for finding in current_query_findings(project, findings)}
            queries = [sources[pk] for pk in findings]
            source_current = True
        except (PermissionDenied, ValidationError):
            queries, source_current = [], False
        source_kind = "csv_query_candidate_not_joined_to_page"
    return {"review_id": review.pk, "cluster_id": str(review.cluster_id), "revision": review.revision,
            "label": review.label, "market": review.market, "language": review.language,
            "intent": review.intent, "page_kind": review.page_kind,
            "preferred_page": review.preferred_page, "reason": review.reason,
            "proposed_action": review.proposed_action, "action_reason": review.action_reason,
            "affected_page": review.affected_page, "proposal_state": "unapproved_human_proposal",
            "source_finding_ids": findings, "manual_topics": review.manual_topics,
            "source_terms": queries, "source_kind": source_kind,
            "source_current": source_current,
            "page_attribution": "human_selected_no_joint_query_page_evidence",
            "actor_id": review.actor_id, "created_at": review.created_at.isoformat()}


@require_http_methods(["GET", "POST"])
def project_intent_clusters(request, organization_id, project_id):
    project, error = _require_project(request, organization_id, project_id, edit=request.method == "POST")
    if error:
        return error
    if request.method == "GET":
        reviews = list(IntentClusterReview.objects.filter(project=project)
                       .order_by("cluster_id", "-revision").distinct("cluster_id")[:51])
        return _response({"project_id": project.pk, "clusters": [_serialize(project, row) for row in reviews[:50]],
                          "has_more": len(reviews) > 50})
    if not ratelimit.consume(request, action="intent_review", user=request.user):
        return _error("Too many intent reviews. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
    keys = {"request_key", "label", "source_finding_ids", "manual_topics", "intent", "page_kind",
            "preferred_page", "reason", "language", "proposed_action", "action_reason", "affected_page"}
    try:
        data = _payload(request, keys)
        review = review_intent_cluster(project=project, actor=request.user, **data)
    except PermissionDenied:
        return _error("Source findings are unavailable.", HTTPStatus.NOT_FOUND)
    except ValidationError:
        return _error("Review a current project query source and page decision.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "cluster": _serialize(project, review)}, HTTPStatus.CREATED)


@require_http_methods(["GET", "POST"])
def project_intent_cluster(request, organization_id, project_id, cluster_id):
    project, error = _require_project(request, organization_id, project_id, edit=request.method == "POST")
    if error:
        return error
    reviews = IntentClusterReview.objects.filter(project=project, cluster_id=cluster_id)
    if request.method == "GET":
        rows = list(reviews.order_by("-revision")[:21])
        if not rows:
            return _error("Intent cluster not found.", HTTPStatus.NOT_FOUND)
        return _response({"project_id": project.pk, "history": [_serialize(project, row) for row in rows[:20]],
                          "has_more": len(rows) > 20})
    if not reviews.exists():
        return _error("Intent cluster not found.", HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="intent_review", user=request.user):
        return _error("Too many intent reviews. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
    keys = {"request_key", "expected_revision", "label", "source_finding_ids", "manual_topics", "intent",
            "page_kind", "preferred_page", "reason", "language", "proposed_action", "action_reason", "affected_page"}
    try:
        data = _payload(request, keys)
        review = review_intent_cluster(project=project, actor=request.user, cluster_id=cluster_id, **data)
    except PermissionDenied:
        return _error("Source findings are unavailable.", HTTPStatus.NOT_FOUND)
    except ValidationError:
        return _error("Intent mapping changed or its source is unavailable.", HTTPStatus.CONFLICT)
    return _response({"project_id": project.pk, "cluster": _serialize(project, review)})
