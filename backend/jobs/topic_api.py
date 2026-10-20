from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.views.decorators.http import require_http_methods

from integrations.models import ImportRun, IntegrationConnection
from tenancy.models import ProjectConfiguration
from tenancy.services import Action, require_project_action
from .ai_text_api import _payload, _project
from .models import JobCancellation, JobRun, TopicCandidateSnapshot, TopicReview
from .research_api import _result
from .topic_discovery import _step_count, queue_topic_discovery
from .topic_review import current_topic_candidate, current_topic_review, review_topic
from .usage import UsageLimitError
from .services import cancel_job
from .news import SUPPORTED_PHRASE


def _review(row):
    return {"id": row.pk, "project_id": row.project_id, "snapshot_id": row.snapshot_id,
        "candidate_index": row.candidate_index, "revision": row.revision, "label": row.label,
        "classification": row.classification, "language": row.language, "market": row.market,
        "intent_review_id": row.intent_cluster_id, "judgments": row.judgments, "reason": row.reason,
        "report": row.report, "created_at": row.created_at.isoformat()}


@require_http_methods(["GET", "POST"])
def project_topic_job(request, organization_id, project_id, job_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    job = JobRun.objects.filter(project=project, pk=job_id, handler="discover_topics").first() if project else None
    if job is None:
        return _result({"message": "Discovery job unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
        if request.method == "POST":
            if not ratelimit.consume(request, action="ai_text_request", user=request.user):
                return _result({"message": "Too many topic requests."}, HTTPStatus.TOO_MANY_REQUESTS)
            _payload(request, set())
            job, _changed, _pending = cancel_job(job=job, actor=request.user)
    except PermissionDenied:
        return _result({"message": "Discovery role unavailable."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError):
        return _result({"message": "Discovery cancellation unavailable."}, HTTPStatus.CONFLICT)
    snapshot = TopicCandidateSnapshot.objects.filter(job=job, project=project).first()
    steps = list(job.steps.order_by("sequence")[:7])
    return _result({"project_id": project.pk, "job": {"id": job.pk, "project_id": project.pk,
        "status": job.status, "error_category": job.error_category or job.dispatch_error,
        "cancel_requested": JobCancellation.objects.filter(job=job).exists(),
        "snapshot_id": snapshot.pk if snapshot else None, "output": job.output,
        "estimated_units": len(job.input_snapshot["feeds"]) + int(job.input_snapshot["connection_id"] is not None) + int(job.input_snapshot.get("news") is not None),
        "attempted_units": _step_count(job), "steps": [{"name": step.name, "status": step.status,
            "error_category": step.error_category} for step in steps]}})


@require_http_methods(["GET"])
def project_topic_review(request, organization_id, project_id, review_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    row = TopicReview.objects.filter(project=project, pk=review_id).select_related("snapshot").first() if project else None
    if row is None:
        return _result({"message": "Topic review unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        current_topic_review(project=project, actor=request.user, review_id=row.pk)
    except PermissionDenied:
        return _result({"message": "Topic review access unavailable."}, HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _result({"message": "Topic review or source changed; select current evidence."}, HTTPStatus.CONFLICT)
    return _result({"project_id": project.pk, "review": _review(row), "source_current": True,
        "evidence": row.snapshot.output["candidates"][row.candidate_index]})


@require_http_methods(["GET", "POST"])
def project_topics(request, organization_id, project_id, snapshot_id=None, candidate_index=None):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.VIEW_PROJECT)
    except PermissionDenied:
        return _result({"message": "Topic access unavailable."}, HTTPStatus.FORBIDDEN)
    snapshot = TopicCandidateSnapshot.objects.filter(pk=snapshot_id, project=project).first() if snapshot_id else None
    if snapshot_id and snapshot is None:
        return _result({"message": "Topic source unavailable."}, HTTPStatus.NOT_FOUND)
    if snapshot and candidate_index is not None and not 0 <= candidate_index < len(snapshot.output["candidates"]):
        return _result({"message": "Topic candidate unavailable."}, HTTPStatus.NOT_FOUND)
    if request.method == "POST":
        if not ratelimit.consume(request, action="ai_text_request", user=request.user):
            return _result({"message": "Too many topic requests."}, HTTPStatus.TOO_MANY_REQUESTS)
        try:
            if snapshot and candidate_index is not None:
                data = _payload(request, {"expected_revision", "request_key", "label", "classification", "language", "intent_review_id", "judgments", "reason"})
                row = review_topic(project=project, actor=request.user, snapshot_id=snapshot.pk, candidate_index=candidate_index, **data)
                return _result({"project_id": project.pk, "review": _review(row)}, HTTPStatus.CREATED)
            if snapshot:
                raise ValidationError("Choose a specific candidate.")
            data = _payload(request, {"feeds", "connection_id", "previous_import_id", "current_import_id", "idempotency_key"}, optional={"news"})
            connection = None
            if data["connection_id"] is not None:
                if type(data["connection_id"]) is not int or data["connection_id"] < 1:
                    raise ValidationError("Select an actual project connection.")
                connection = IntegrationConnection.objects.filter(pk=data["connection_id"], project=project).first()
                if connection is None:
                    raise PermissionDenied
            job = queue_topic_discovery(project=project, actor=request.user, feeds=data["feeds"], connection=connection,
                previous_import_id=data["previous_import_id"], current_import_id=data["current_import_id"], idempotency_key=data["idempotency_key"], news=data.get("news"))
            return _result({"project_id": project.pk, "job_id": job.pk, "status": job.status,
                             "estimated_units": len(data["feeds"]) + int(connection is not None) + int(data.get("news") is not None)}, HTTPStatus.ACCEPTED)
        except PermissionDenied:
            return _result({"message": "Topic source or role unavailable."}, HTTPStatus.FORBIDDEN)
        except UsageLimitError as error:
            return _result({"message": "Discovery allowance unavailable.", "code": error.category}, HTTPStatus.TOO_MANY_REQUESTS)
        except (ValidationError, ValueError, TypeError, UnicodeError, IntegrityError):
            return _result({"message": "Choose current source windows/mapping and bounded human judgments; reload corrected history."}, HTTPStatus.CONFLICT)
    if snapshot is None:
        rows = list(TopicCandidateSnapshot.objects.filter(project=project).order_by("-pk")[:21])
        config = ProjectConfiguration.objects.filter(project=project).first()
        connections = list(IntegrationConnection.objects.filter(project=project, state="active", capabilities__contains=["query_metrics"]).order_by("pk")[:20])
        imports = list(ImportRun.objects.filter(project=project, connection__in=connections, status="succeeded",
            coverage_state="complete", observation_dimensions=["query"], row_errors=0).order_by("-pk")[:40])
        jobs = list(JobRun.objects.filter(project=project, handler="discover_topics").order_by("-pk")[:10])
        return _result({"project_id": project.pk, "snapshots": [{"id": row.pk, "created_at": row.created_at.isoformat(),
            "candidate_count": len(row.output["candidates"]), "coverage": row.output["coverage"]} for row in rows[:20]],
            "has_more": len(rows) > 20, "feeds": config.rss_feed_urls if config else [], "languages": config.target_languages if config else [],
            "news": {"provider": "gdelt", "phrases": [value for value in config.seed_topics if SUPPORTED_PHRASE.fullmatch(value) and value == value.strip()] if config else [],
                "publisher_origins": [value for value in config.research_allowed_origins if value.startswith("https://") and value not in config.research_blocked_origins] if config else [],
                "attribution_url": "https://www.gdeltproject.org/", "record_limit": 20, "live_verified": False},
            "optional_sources": {"youtube": "separate_response_only_search_requires_dedicated_key", "google_trends": "unavailable_no_supported_contract_configured"},
            "connections": [{"id": row.pk, "provider": row.provider, "property": row.external_property_id} for row in connections],
            "imports": [{"id": row.pk, "connection_id": row.connection_id, "start": row.date_start.isoformat(), "end": row.date_end.isoformat()} for row in imports],
            "jobs": [{"id": job.pk, "status": job.status, "error_category": job.error_category, "output": job.output} for job in jobs]})
    if candidate_index is None:
        latest = {row.candidate_index: row for row in TopicReview.objects.filter(snapshot=snapshot)
                  .order_by("candidate_index", "-revision").distinct("candidate_index")}
        return _result({"project_id": project.pk, "snapshot_id": snapshot.pk, "coverage": snapshot.output["coverage"],
            "candidates": [{"index": index, "evidence": row, "review": _review(latest[index]) if index in latest else None}
                for index, row in enumerate(snapshot.output["candidates"])]})
    rows = list(TopicReview.objects.filter(snapshot=snapshot, candidate_index=candidate_index).order_by("-revision")[:20])
    try:
        current_topic_candidate(project=project, actor=request.user, snapshot_id=snapshot.pk, candidate_index=candidate_index)
        if rows:
            current_topic_review(project=project, actor=request.user, review_id=rows[0].pk)
        source_current = True
    except (PermissionDenied, ValidationError):
        source_current = False
    return _result({"project_id": project.pk, "snapshot_id": snapshot.pk, "candidate_index": candidate_index,
        "evidence": snapshot.output["candidates"][candidate_index], "history": [_review(row) for row in rows], "source_current": source_current})
