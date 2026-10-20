"""Private deliberate D132 collection commands and exact current-source readback."""
from http import HTTPStatus
import json
import re

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.db.models import Exists, OuterRef
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from integrations.google_tokens import GoogleTokenError, _reject_constant, _unique_object
from integrations.oauth import _verified
from tenancy.services import Action, require_project_action
from .authority_link_collection import (HANDLER, compare_static_link_observations, current_mention_review, mention_selection,
    queue_static_link_collection, read_static_destination_candidate, read_static_link_observation, read_static_mention_candidate,
    require_current_mention_delivery, selection_snapshot, validate_job, COLLECTION_METHOD, REFERENCE_COLLECTION_METHOD)
from .api import _error, _response
from .local_assessment_api import _project_access
from .models import AuthorityLinkReview, AuthorityProspectReview, JobCancellation, JobRun, JobStatus, UsageReservation
from .services import cancel_job
from .usage import UsageLimitError, require_billable_access

KEY = r"[A-Za-z0-9][A-Za-z0-9._-]{7,63}"


def _query_ids(request, fields):
    if (set(request.GET) != fields or any(len(values) != 1 for _, values in request.GET.lists())
        or any(not re.fullmatch(r"[1-9][0-9]{0,15}", request.GET[key]) for key in fields)):
        raise ValidationError("Choose exact positive source IDs.")
    values = {key: int(request.GET[key]) for key in fields}
    if any(value >= 2**53 for value in values.values()):
        raise ValidationError("Choose exact safe-integer source IDs.")
    return values


@sensitive_variables()
@require_http_methods(["GET"])
def project_static_link_comparison(request, organization_id, project_id):
    project, error = _project_access(request, organization_id, project_id, edit=True)
    if error:
        return error
    try:
        pair = _query_ids(request, {"previous_job_id", "current_job_id"})
        if pair["previous_job_id"] == pair["current_job_id"]:
            raise ValidationError("Select distinct source jobs.")
    except ValidationError:
        return _error("Choose two exact positive distinct selected-source job IDs.", HTTPStatus.BAD_REQUEST)
    try:
        comparison = compare_static_link_observations(project=project, actor=request.user, **pair)
    except UsageLimitError as error:
        return _error("Current-use source comparison access is unavailable.", HTTPStatus.FORBIDDEN, code=error.category)
    except PermissionDenied:
        return _error("Current exact source observations and authority are required.", HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Exact private dated same-source comparison is unavailable.", HTTPStatus.CONFLICT)
    return _response({"organization_id": project.organization_id, "project_id": project.pk, "comparison": comparison})


@sensitive_variables()
@require_http_methods(["GET"])
def project_static_destination_candidate(request, organization_id, project_id):
    project, error = _project_access(request, organization_id, project_id, edit=True)
    if error:
        return error
    try:
        selection = _query_ids(request, {"static_job_id"})
    except ValidationError:
        return _error("Choose one exact positive saved static-source job ID.", HTTPStatus.BAD_REQUEST)
    try:
        candidate = read_static_destination_candidate(project=project, actor=request.user, **selection)
    except UsageLimitError as error:
        return _error("Current-use destination candidate access is unavailable.", HTTPStatus.FORBIDDEN, code=error.category)
    except PermissionDenied:
        return _error("Current exact source, destination and authority are required.", HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Exact private separately dated destination candidate is unavailable.", HTTPStatus.CONFLICT)
    return _response({"organization_id": project.organization_id, "project_id": project.pk, "candidate": candidate})


@sensitive_variables()
@require_http_methods(["GET"])
def project_static_mention_candidates(request, organization_id, project_id):
    project, error = _project_access(request, organization_id, project_id, edit=True)
    if error:
        return error
    pair = None
    if request.GET:
        try:
            pair = _query_ids(request, {"prospect_review_id", "static_job_id"})
        except ValidationError:
            return _error("Choose an exact human mention review and static-source job.", HTTPStatus.BAD_REQUEST)
    try:
        if not _verified(request.user):
            raise PermissionDenied
        require_billable_access(organization=project.organization)
        if pair:
            data = {"candidate": read_static_mention_candidate(project=project, actor=request.user, **pair)}
        else:
            newer = AuthorityProspectReview.objects.filter(project=project, prospect_id=OuterRef("prospect_id"), revision__gt=OuterRef("revision"))
            rows = list(AuthorityProspectReview.objects.filter(project=project, state__in=["approved", "reported"], intake__proposed_action="mention")
                .annotate(newer=Exists(newer)).filter(newer=False).order_by("-pk")[:21])
            candidates, resolved = [], []
            for row in rows[:20]:
                try:
                    current = current_mention_review(project=project, actor=request.user, prospect_review_id=row.pk)
                    candidates.append(mention_selection(current))
                    resolved.append(current)
                except (PermissionDenied, ValidationError):
                    continue
            for row in resolved:
                require_current_mention_delivery(row, actor=request.user)
            require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
            if not _verified(request.user):
                raise PermissionDenied
            require_billable_access(organization=project.organization)
            data = {"candidates": candidates, "has_more": len(rows) > 20,
                    "basis": "human_selected_mentions_require_exact_body_matched_static_observation_not_verified_unlinked_proof"}
    except UsageLimitError as error:
        return _error("Current-use mention access is unavailable.", HTTPStatus.FORBIDDEN, code=error.category)
    except PermissionDenied:
        return _error("Current exact mention and static-source authority are required.", HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Exact same-body dated human mention/static candidate is unavailable.", HTTPStatus.CONFLICT)
    return _response({"organization_id": project.organization_id, "project_id": project.pk, **data})


def _payload(request, fields, *, optional=()):
    if request.content_type != "application/json" or len(request.body) > 2048:
        raise ValidationError("Choose bounded JSON collection fields.")
    data = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if type(data) is not dict or not fields <= set(data) or set(data) - fields - set(optional):
        raise ValidationError("Choose exact source collection fields.")
    return data


def _context(project, actor):
    allowed, can_cancel, denial = False, False, "source_or_actor_unavailable"
    try:
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        if not _verified(actor):
            raise PermissionDenied
        can_cancel = True
        require_billable_access(organization=project.organization)
        allowed, denial = True, ""
    except UsageLimitError as error:
        denial = error.category
    except PermissionDenied:
        pass
    candidates, more = [], False
    if allowed:
        newer = AuthorityLinkReview.objects.filter(project=project, link_id=OuterRef("link_id"), revision__gt=OuterRef("revision"))
        rows = list(AuthorityLinkReview.objects.filter(project=project, state__in=["approved", "reported"], proposal__action="verify_source")
                    .annotate(newer=Exists(newer)).filter(newer=False).order_by("-pk")[:21])
        more = len(rows) > 20
        for row in rows[:20]:
            try:
                # Eligibility only: GET never records or supplies the separate POST consent.
                config = selection_snapshot(project, actor, {"link_review_id": row.pk, "source_collection_permission": True})
                binding = {key: value for key, value in config["binding"].items() if key != "source_collection_permission"}
                candidates.append({"link_review_id": row.pk, "binding": binding,
                                   "requires_separate_collection_permission": True})
            except (PermissionDenied, ValidationError):
                continue
    return {"organization_id": project.organization_id, "project_id": project.pk, "can_collect": allowed, "can_cancel": can_cancel,
        "denial_category": denial, "candidates": candidates, "candidates_has_more": more,
        "estimate_units": 1, "unit_semantics": "bounded_operation_including_unknown_attempt_not_provider_charge",
        "collection_methods": [COLLECTION_METHOD, REFERENCE_COLLECTION_METHOD],
        "source_limit": 1, "sending": "unavailable", "scheduling": "unavailable",
        "coverage": "selected_static_html_not_rendered_or_whole_site", "lost_unlinked_links": "not_established"}


def _job(job, actor, *, detailed=False):
    reservation = UsageReservation.objects.filter(job=job).first()
    current = False
    try:
        validate_job(job, current=True)
        caller = selection_snapshot(job.project, actor, job.input_snapshot)
        caller["binding"]["actor_id"] = job.actor_id
        if caller != job.config_snapshot:
            raise PermissionDenied
        require_billable_access(organization=job.organization)
        current = True
    except (PermissionDenied, ValidationError):
        pass
    data = {"id": job.pk, "project_id": job.project_id, "status": job.status,
        "link_review_id": job.input_snapshot["link_review_id"], "idempotency_key": job.idempotency_key,
        "selection": job.config_snapshot,
        "created_at": job.created_at.isoformat(), "updated_at": job.updated_at.isoformat(),
        "cancel_requested": JobCancellation.objects.filter(job=job).exists(),
        "error_category": job.error_category or job.dispatch_error, "estimate_units": 1,
        "attempted_units": int(job.steps.exists()), "source_current": current,
        "usage": {"state": reservation.state, "actual_units": reservation.actual_units} if reservation else None,
        "evidence": None, "evidence_state": "not_collected"}
    if detailed and job.status == JobStatus.SUCCEEDED:
        try:
            data["evidence"] = read_static_link_observation(project=job.project, actor=actor, job_id=job.pk)
            data["evidence_state"] = "current_private_readback_checked"
        except (PermissionDenied, ValidationError):
            data["evidence_state"] = "retained_current_use_unavailable"
    return data


@sensitive_post_parameters()
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def project_static_link_sources(request, organization_id, project_id, job_id=None):
    project, error = _project_access(request, organization_id, project_id, edit=request.method == "POST")
    if error:
        return error
    rows = JobRun.objects.filter(project=project, handler=HANDLER).select_related("project__organization", "actor")
    job = rows.filter(pk=job_id).first() if job_id is not None else None
    if job_id is not None and job is None:
        return _error("Static-source job not found.", HTTPStatus.NOT_FOUND)
    if request.method == "POST":
        action = "authority_source_cancel" if job else "authority_source_request"
        if not ratelimit.consume(request, action=action, user=request.user):
            return _error("Too many source collection commands. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
        try:
            if job:
                _payload(request, set())
                job, _changed, _requested = cancel_job(job=job, actor=request.user)
            else:
                data = _payload(request, {"link_review_id", "source_collection_permission", "idempotency_key"}, optional={"collection_method"})
                key = data.pop("idempotency_key")
                if type(key) is not str or not re.fullmatch(KEY, key):
                    raise ValidationError("Choose a bounded exact collection request key.")
                job = queue_static_link_collection(project=project, actor=request.user, data=data, idempotency_key=key)
        except PermissionDenied:
            return _error("Current exact approved source and separate collection permission are required.", HTTPStatus.FORBIDDEN)
        except UsageLimitError as error:
            return _error("Source collection allowance is unavailable.", HTTPStatus.TOO_MANY_REQUESTS, code=error.category)
        except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, IntegrityError, RecursionError):
            return _error("Refresh the exact current source or reconcile this request from history.", HTTPStatus.CONFLICT)
        return _response({"organization_id": project.organization_id, "project_id": project.pk,
                          "job": _job(job, request.user)}, HTTPStatus.ACCEPTED)
    if job:
        if request.GET:
            return _error("Choose the exact source job without additional fields.", HTTPStatus.BAD_REQUEST)
        return _response({"organization_id": project.organization_id, "project_id": project.pk,
                          "job": _job(job, request.user, detailed=True)})
    if set(request.GET) - {"idempotency_key"} or any(len(values) != 1 for _, values in request.GET.lists()):
        return _error("Choose one bounded exact request lookup.", HTTPStatus.BAD_REQUEST)
    key = request.GET.get("idempotency_key")
    if key is not None and not re.fullmatch(KEY, key):
        return _error("Choose a bounded exact request key.", HTTPStatus.BAD_REQUEST)
    if key:
        rows = rows.filter(idempotency_key=key)
    jobs = list(rows.order_by("-pk")[:21])
    return _response({**_context(project, request.user), "jobs": [_job(row, request.user) for row in jobs[:20]],
                      "has_more": len(jobs) > 20, "lookup": "found" if key and jobs else "not_found" if key else None})
