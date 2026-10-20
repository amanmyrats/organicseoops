"""Fixed private competitor-root commands; reads and previews never fetch a site."""
from hashlib import sha256
from http import HTTPStatus
import re

from allauth.account import app_settings as account_settings
from allauth.core.internal import ratelimit
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from integrations.google_tokens import GoogleTokenError
from integrations.oauth import _verified
from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action
from . import competitor_collection as collection, competitor_lab_fetch as lab_fetch
from .authority_link_collection_api import _query_ids
from .competitor_comparison import _read_pair_sources, compare_competitor_roots
from .competitor_page_comparison import compare_competitor_pages
from .competitor_schema_comparison import compare_competitor_schema_roots
from .competitor_links_comparison import compare_competitor_links_roots
from .competitor_headings_comparison import compare_competitor_page_headings
from .competitor_destinations_comparison import compare_competitor_page_destinations
from .competitor_dates_comparison import compare_competitor_page_dates
from .competitor_date_candidate_comparison import compare_competitor_date_candidates
from .competitor_formats_comparison import compare_competitor_page_formats
from .competitor_formats_structure import read_competitor_formats_structure
from .competitor_headings_structure import read_competitor_headings_structure
from .competitor_lab_comparison import compare_competitor_lab
from .competitor_reference_structure import read_competitor_reference_structure
from .competitor_destination_inventory import read_competitor_destination_inventory
from .findings_api import _project
from .first_audit_api import _response
from .models import JobCancellation, JobRun, JobStatus
from .passive_header_api import KEY, _payload, _status as _base_status
from .services import cancel_job
from .usage import UsageLimitError, require_billable_access


INPUT_FIELDS = {"origin", "collection_permission", "use_permission", "storage_permission"}


def _digest(selection):
    return sha256(collection._encode(selection)).hexdigest()


def _current(project, actor):
    require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
    if not _verified(actor): raise PermissionDenied


def _status(job):
    status = _base_status(job)
    category = job.error_category or job.dispatch_error
    if type(category) is str and category in (lab_fetch.ERRORS if job.handler == collection.LIGHTHOUSE_HANDLER else collection.ERRORS): status["error_category"] = category
    return status


def _metadata(job_id):
    return {"source": collection._read_metadata(job_id),
        "cancellation": JobCancellation.objects.filter(job_id=job_id).values().first()}


@sensitive_variables()
def project_competitor_comparison(request, organization_id, project_id):
    return _project_competitor_comparison(request, organization_id, project_id)


@sensitive_variables()
def project_competitor_page_comparison(request, organization_id, project_id):
    return _project_competitor_comparison(request, organization_id, project_id, page=True)


@sensitive_variables()
def project_competitor_schema_comparison(request, organization_id, project_id):
    return _project_competitor_comparison(request, organization_id, project_id, schema=True)


@sensitive_variables()
def project_competitor_links_comparison(request, organization_id, project_id):
    return _project_competitor_comparison(request, organization_id, project_id, links=True)


@sensitive_variables()
def project_competitor_headings_comparison(request, organization_id, project_id):
    return _project_competitor_comparison(request, organization_id, project_id, headings=True)


@sensitive_variables()
def project_competitor_destinations_comparison(request, organization_id, project_id):
    return _project_competitor_comparison(request, organization_id, project_id, destinations=True)


@sensitive_variables()
def project_competitor_reference_structure(request, organization_id, project_id):
    return _project_competitor_comparison(request, organization_id, project_id, destinations=True, structure=True)


@sensitive_variables()
def project_competitor_destination_inventory(request, organization_id, project_id):
    return _project_competitor_comparison(request, organization_id, project_id, destinations=True, inventory=True)


@sensitive_variables()
def project_competitor_dates_comparison(request, organization_id, project_id):
    return _project_competitor_comparison(request, organization_id, project_id, dates=True)


@sensitive_variables()
def project_competitor_date_candidate_comparison(request, organization_id, project_id):
    return _project_competitor_comparison(request, organization_id, project_id, dates=True, date_candidates=True)


@sensitive_variables()
def project_competitor_formats_comparison(request, organization_id, project_id):
    return _project_competitor_comparison(request, organization_id, project_id, formats=True)


@sensitive_variables()
def project_competitor_formats_structure(request, organization_id, project_id):
    return _project_competitor_comparison(request, organization_id, project_id, formats=True, structure=True)


@sensitive_variables()
def project_competitor_headings_structure(request, organization_id, project_id):
    return _project_competitor_comparison(request, organization_id, project_id, headings=True, structure=True)


@sensitive_variables()
def project_competitor_lighthouse_comparison(request, organization_id, project_id):
    return _project_competitor_comparison(request, organization_id, project_id, lighthouse=True)


@sensitive_variables()
def _project_competitor_comparison(request, organization_id, project_id, *, page=False, schema=False, links=False, headings=False, destinations=False, dates=False, lighthouse=False, structure=False, inventory=False, formats=False, date_candidates=False):
    handler = "collect_competitor_page_formats" if formats else collection.LIGHTHOUSE_HANDLER if lighthouse else "collect_competitor_page_dates" if dates else "collect_competitor_page_destinations" if destinations else "collect_competitor_page_headings" if headings else "collect_competitor_schema_root" if schema else "collect_competitor_links_root" if links else "collect_competitor_page" if page else collection.HANDLER
    family = "competitor_page_formats" if formats else "competitor_lighthouse" if lighthouse else "competitor_page_dates" if dates else "competitor_page_destinations" if destinations else "competitor_page_headings" if headings else "competitor_schema_root" if schema else "competitor_links_root" if links else "competitor_page" if page else "competitor_root"
    if request.method != "GET":
        response = _response({"message": "Read an explicit saved competitor pair."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = "GET"
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if request.body or not all(type(value) is int and 1 <= value < 2**53 for value in (organization_id, project_id)):
        return _response({"message": "Choose exact saved competitor jobs."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None: return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True,
        action=family + "_read", user=request.user) is None:
        return _response({"message": "Too many " + family.replace("_", "-") + " commands."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        pair = _query_ids(request, {"first_job_id", "second_job_id"} if structure or inventory else {"previous_job_id", "current_job_id"})
        if len(set(pair.values())) != 2: raise ValidationError("Choose distinct original competitor jobs.")
    except ValidationError:
        return _response({"message": "Choose two exact distinct saved competitor job IDs."}, HTTPStatus.BAD_REQUEST)
    try:
        _current(project, request.user)
        rows = list(JobRun.objects.select_related("project", "actor").filter(pk__in=pair.values(),
            project_id=project_id, organization_id=organization_id, handler=handler, status=JobStatus.SUCCEEDED))
        if len(rows) != 2: raise PermissionDenied
        callers = _read_pair_sources(rows, project, request.user)
        original = {row.pk: _metadata(row.pk) for row in rows}
        compare = read_competitor_headings_structure if headings and structure else compare_competitor_date_candidates if dates and date_candidates else read_competitor_formats_structure if formats and structure else compare_competitor_page_formats if formats else read_competitor_destination_inventory if inventory else read_competitor_reference_structure if structure else compare_competitor_lab if lighthouse else compare_competitor_page_dates if dates else compare_competitor_page_destinations if destinations else compare_competitor_page_headings if headings else compare_competitor_schema_roots if schema else compare_competitor_links_roots if links else compare_competitor_pages if page else compare_competitor_roots
        comparison = compare(project=project, actor=request.user, **pair)
        response = _response({"organization_id": organization_id, "project_id": project_id, "inventory" if inventory else "structure" if structure else "comparison": comparison})
        if any(_metadata(row.pk) != original[row.pk] for row in rows): raise PermissionDenied
        fresh = (JobRun.objects.select_related("project", "actor").get(pk=row.pk, handler=handler) for row in rows)
        if _read_pair_sources(fresh, project, request.user) != callers: raise PermissionDenied
        if any(_metadata(row.pk) != original[row.pk] for row in rows): raise PermissionDenied
        # The final metadata read can change source authority checked earlier.
        fresh = (JobRun.objects.select_related("project", "actor").get(pk=row.pk, handler=handler) for row in rows)
        if _read_pair_sources(fresh, project, request.user) != callers: raise PermissionDenied
        if any(_metadata(row.pk) != original[row.pk] for row in rows): raise PermissionDenied
        if {row.pk: collection._read_source(JobRun.objects.select_related("project", "actor").get(pk=row.pk, handler=handler),
            project, request.user) for row in rows} != callers: raise PermissionDenied
        if any(collection._read_metadata(row.pk) != original[row.pk]["source"] for row in rows): raise PermissionDenied
        if JobCancellation.objects.filter(job_id__in=pair.values()).exists(): raise PermissionDenied
        _current(project, request.user)
        require_billable_access(organization=project.organization)
        return response
    except (UsageLimitError, PermissionDenied, ObjectDoesNotExist):
        return _response({"message": "Current exact competitor pair and authority are required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, RecursionError):
        return _response({"message": "Exact private two-page heading samples unavailable." if headings and structure else "Exact private two-page element samples unavailable." if formats and structure else "Exact private two-page reference samples unavailable." if structure or inventory else "Exact private dated same-URI comparison unavailable."}, HTTPStatus.CONFLICT)


@sensitive_post_parameters()
@sensitive_variables()
def project_competitor_roots(request, organization_id, project_id, job_id=None, selection=False, *, handler=collection.HANDLER):
    collection._collection_contract(handler)
    input_fields = INPUT_FIELDS | {"url"} if handler in {"collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats"} else INPUT_FIELDS
    if handler == collection.LIGHTHOUSE_HANDLER:
        input_fields = INPUT_FIELDS | {"url", "strategy", "provider_processing_permission"}
    observation = "competitor-page-elements" if handler == "collect_competitor_page_formats" else "competitor-lighthouse" if handler == collection.LIGHTHOUSE_HANDLER else "competitor-page-dates" if handler == "collect_competitor_page_dates" else "competitor-page-destinations" if handler == "collect_competitor_page_destinations" else "competitor-page-headings" if handler == "collect_competitor_page_headings" else "competitor-page" if handler == "collect_competitor_page" else "competitor-root"
    methods = {"POST"} if selection else {"GET", "POST"}
    if request.method not in methods:
        response = _response({"message": f"Use an explicit {observation} command."}, HTTPStatus.METHOD_NOT_ALLOWED)
        response["Allow"] = ", ".join(sorted(methods))
        return response
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if (not all(type(value) is int and 1 <= value < 2**53 for value in (organization_id, project_id))
        or job_id is not None and (type(job_id) is not int or not 1 <= job_id < 2**53)
        or request.method == "POST" and request.GET or request.method == "GET" and request.body):
        return _response({"message": f"Choose exact {observation} fields."}, HTTPStatus.BAD_REQUEST)
    project = _project(request, organization_id, project_id)
    if project is None: return _response({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    action = ("competitor_page_formats_" if handler == "collect_competitor_page_formats" else "competitor_lighthouse_" if handler == collection.LIGHTHOUSE_HANDLER else "competitor_page_dates_" if handler == "collect_competitor_page_dates" else "competitor_page_destinations_" if handler == "collect_competitor_page_destinations" else "competitor_page_headings_" if handler == "collect_competitor_page_headings" else "competitor_page_" if handler == "collect_competitor_page" else
        "competitor_links_root_" if handler == "collect_competitor_links_root" else
        "competitor_schema_root_" if handler == "collect_competitor_schema_root" else "competitor_root_") + (("selection" if selection else "cancel" if job_id is not None else "request")
        if request.method == "POST" else "read")
    if ratelimit.consume(request, config=account_settings.RATE_LIMITS, limit_get=True, action=action, user=request.user) is None:
        return _response({"message": f"Too many {observation} commands."}, HTTPStatus.TOO_MANY_REQUESTS)
    rows = JobRun.objects.filter(organization_id=organization_id, project_id=project_id, handler=handler)
    try:
        _current(project, request.user)
        if request.method == "POST":
            with transaction.atomic():
                org = Organization.objects.select_for_update().get(pk=organization_id)
                project = Project.objects.select_for_update().get(pk=project_id, organization=org)
                if selection:
                    data = _payload(request, input_fields)
                    require_billable_access(organization=org)
                    original = collection.selection_snapshot(project, request.user, data, handler=handler)
                    response = _response({"organization_id": organization_id, "project_id": project_id,
                        "selection": original, "selection_digest": _digest(original), "estimate_units": 1})
                    if collection.selection_snapshot(project, request.user, data, handler=handler) != original: raise PermissionDenied
                    require_billable_access(organization=org)
                elif job_id is not None:
                    _payload(request, set())
                    job = rows.select_related("project", "actor").filter(pk=job_id).first()
                    if job is None: raise PermissionDenied
                    job, _changed, _requested = cancel_job(job=job, actor=request.user)
                    saved = _metadata(job.pk)
                    response = _response({"organization_id": organization_id, "project_id": project_id,
                        "job": _status(job)}, HTTPStatus.ACCEPTED)
                    if _metadata(job.pk) != saved: raise PermissionDenied
                else:
                    data = _payload(request, input_fields | {"idempotency_key", "selection_digest"})
                    key, expected = data.pop("idempotency_key"), data.pop("selection_digest")
                    if (type(key) is not str or not re.fullmatch(KEY, key) or type(expected) is not str
                        or not re.fullmatch(r"[a-f0-9]{64}", expected)): raise ValidationError
                    original = collection.selection_snapshot(project, request.user, data, handler=handler)
                    if _digest(original) != expected: raise PermissionDenied
                    job = collection.queue_competitor_collection(project=project, actor=request.user, data=data, idempotency_key=key, handler=handler)
                    saved = _metadata(job.pk)
                    response = _response({"organization_id": organization_id, "project_id": project_id,
                        "job": _status(job)}, HTTPStatus.ACCEPTED)
                    if _metadata(job.pk) != saved: raise PermissionDenied
                    if collection.selection_snapshot(project, request.user, data, handler=handler) != original: raise PermissionDenied
                    collection.validate_job(JobRun.objects.select_related("project", "actor").get(pk=job.pk, handler=handler), current=True)
                    if JobCancellation.objects.filter(job=job).values().first() != saved["cancellation"]: raise PermissionDenied
                    require_billable_access(organization=org)
                _current(project, request.user)
                if selection or job_id is None: require_billable_access(organization=org)
                return response
        if job_id is not None:
            if request.GET: raise ValidationError
            job = rows.select_related("project", "actor").filter(pk=job_id).first()
            if job is None: raise PermissionDenied
            original = _metadata(job.pk)
            caller = collection._read_source(job, project, request.user) if job.status == JobStatus.SUCCEEDED else None
            evidence = collection.read_competitor_observation(project=project, actor=request.user,
                job_id=job.pk, handler=handler) if job.status == JobStatus.SUCCEEDED else None
            response = _response({"organization_id": organization_id, "project_id": project_id,
                "job": _status(job), "evidence": evidence})
            if _metadata(job.pk) != original: raise PermissionDenied
            if evidence:
                fresh = rows.select_related("project", "actor").get(pk=job.pk)
                if collection._read_source(fresh, project, request.user) != caller: raise PermissionDenied
                if _metadata(job.pk) != original or JobCancellation.objects.filter(job=job).exists(): raise PermissionDenied
                if collection._read_source(rows.select_related("project", "actor").get(pk=job.pk), project, request.user) != caller: raise PermissionDenied
        else:
            if set(request.GET) - {"idempotency_key"} or any(len(values) != 1 for _, values in request.GET.lists()): raise ValidationError
            key = request.GET.get("idempotency_key")
            if key is not None:
                if not re.fullmatch(KEY, key): raise ValidationError
                rows = rows.filter(idempotency_key=key, actor=request.user)
            rows = rows.order_by("-pk")
            original = list(rows.values()[:21])
            cancellations = JobCancellation.objects.filter(job_id__in=[row["id"] for row in original]).order_by("pk")
            original_cancellations = list(cancellations.values())
            jobs = list(rows[:21])
            response = _response({"organization_id": organization_id, "project_id": project_id,
                "jobs": [_status(job) for job in jobs[:20]], "has_more": len(jobs) > 20, "lookup": key})
            if list(rows.values()[:21]) != original or list(cancellations.values()) != original_cancellations: raise PermissionDenied
        _current(project, request.user)
        if job_id is not None and evidence: require_billable_access(organization=project.organization)
        return response
    except (UsageLimitError, PermissionDenied, ObjectDoesNotExist):
        return _response({"message": "Current exact competitor source and authority are required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, GoogleTokenError, UnicodeError, ValueError, TypeError, IntegrityError, RecursionError):
        return _response({"message": "Refresh the exact selection or reconcile the original request."}, HTTPStatus.CONFLICT)


def project_competitor_schema_roots(request, organization_id, project_id, job_id=None, selection=False):
    return project_competitor_roots(request, organization_id, project_id, job_id=job_id,
        selection=selection, handler="collect_competitor_schema_root")


def project_competitor_links_roots(request, organization_id, project_id, job_id=None, selection=False):
    return project_competitor_roots(request, organization_id, project_id, job_id=job_id,
        selection=selection, handler="collect_competitor_links_root")


def project_competitor_pages(request, organization_id, project_id, job_id=None, selection=False):
    return project_competitor_roots(request, organization_id, project_id, job_id=job_id,
        selection=selection, handler="collect_competitor_page")


def project_competitor_page_headings(request, organization_id, project_id, job_id=None, selection=False):
    return project_competitor_roots(request, organization_id, project_id, job_id=job_id,
        selection=selection, handler="collect_competitor_page_headings")


def project_competitor_page_destinations(request, organization_id, project_id, job_id=None, selection=False):
    return project_competitor_roots(request, organization_id, project_id, job_id=job_id,
        selection=selection, handler="collect_competitor_page_destinations")


def project_competitor_page_formats(request, organization_id, project_id, job_id=None, selection=False):
    return project_competitor_roots(request, organization_id, project_id, job_id=job_id,
        selection=selection, handler="collect_competitor_page_formats")


def project_competitor_page_dates(request, organization_id, project_id, job_id=None, selection=False):
    return project_competitor_roots(request, organization_id, project_id, job_id=job_id,
        selection=selection, handler="collect_competitor_page_dates")


def project_competitor_lighthouse(request, organization_id, project_id, job_id=None, selection=False):
    return project_competitor_roots(request, organization_id, project_id, job_id=job_id,
        selection=selection, handler=collection.LIGHTHOUSE_HANDLER)
