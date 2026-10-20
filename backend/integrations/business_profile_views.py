"""Private GBP control/status API; returned content is never replayable from status."""
from http import HTTPStatus
import json
import re
from urllib.parse import urlencode

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.db.models import Exists, OuterRef
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_http_methods

from jobs.models import JobCancellation, JobRun
from jobs.services import cancel_job
from jobs.usage import UsageLimitError
from jobs.models import LocalBusinessAssessment
from providers.google_app import google_business_oauth_client
from tenancy.models import Project, ProjectConfiguration, ProjectOriginVerification
from tenancy.services import Action, require_project_action
from .business_profile import MEMORY_SECONDS, POLICY_VERSION, SCOPE
from .business_profile_oauth import (begin_business_oauth_intent, consume_business_oauth_intent,
                                      require_business_grant, revoke_business_grant)
from .business_profile_read import HANDLER, BusinessRequestError, complete_business_consent, read_business_profile
from .google_tokens import GoogleTokenError, _reject_constant, _unique_object
from .models import BusinessProfileOAuthGrant
from .oauth import OAuthStateError
from .oauth_views import _origin_matches_callback, _redirect, _response


def _result(data, status=HTTPStatus.OK):
    response = _response(data, status)
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _payload(request, fields):
    if len(request.body) > 4096:
        raise ValidationError("Choose bounded Business Profile fields.")
    value = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if type(value) is not dict or set(value) != fields:
        raise ValidationError("Choose exact Business Profile command fields.")
    return value


def _grant(project, value):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValidationError("Choose an exact project Business Profile grant.")
    grant = BusinessProfileOAuthGrant.objects.filter(pk=value, project=project, organization_id=project.organization_id).first()
    if grant is None:
        raise PermissionDenied
    return grant


def _status(request, project):
    if set(request.GET) - {"before_id", "request_key"} or any(len(values) != 1 for _key, values in request.GET.lists()):
        raise ValidationError("Choose a bounded business status page or request key.")
    before = request.GET.get("before_id")
    request_key = request.GET.get("request_key")
    if (before is not None and not re.fullmatch(r"[1-9][0-9]{0,17}", before)
        or request_key is not None and not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", request_key)):
        raise ValidationError("Choose a bounded business status page or request key.")
    configured = False
    try:
        configured = _origin_matches_callback(request, google_business_oauth_client().redirect_uri)
    except (GoogleTokenError, ValidationError):
        pass
    config = ProjectConfiguration.objects.filter(project=project).first()
    newer = LocalBusinessAssessment.objects.filter(project=project, location_digest=OuterRef("location_digest"),
                                                   revision__gt=OuterRef("revision"))
    assessments = (list(LocalBusinessAssessment.objects.filter(project=project, configuration_revision=config.revision,
        eligibility="user_attested").annotate(newer=Exists(newer)).filter(newer=False).order_by("-pk")[:21]) if config else [])
    origins = {project.canonical_origin, *project.domain_aliases.values_list("origin", flat=True)}
    verified = list(ProjectOriginVerification.objects.filter(project=project, organization_id=project.organization_id,
        state="verified", origin__in=origins).order_by("pk").values_list("origin", flat=True)[:20])
    # Current/revocation-pending states sort before revoked history, so old cleanup
    # cannot be buried behind terminal grants in this bounded view.
    grants = list(BusinessProfileOAuthGrant.objects.filter(project=project, organization_id=project.organization_id).order_by("state", "-pk")[:21])
    grant_rows = []
    for grant in grants[:20]:
        try:
            require_business_grant(grant=grant, actor=request.user, expected_revision=grant.revision)
            current = True
        except (PermissionDenied, ValidationError, GoogleTokenError):
            current = False
        grant_rows.append({"id": grant.pk, "project_id": project.pk, "state": grant.state,
            "revision": grant.revision, "source_current": current, "selection": grant.intent.selection if current else None,
            "created_at": grant.created_at.isoformat(), "read_available": current and configured,
            "revoke_available": grant.state != "revoked"})
    jobs = JobRun.objects.filter(project=project, organization_id=project.organization_id, handler=HANDLER)
    if before:
        jobs = jobs.filter(pk__lt=int(before))
    if request_key:
        jobs = jobs.filter(idempotency_key=request_key)
    jobs = list(jobs.select_related("usage").order_by("-pk")[:21])
    return _result({"organization_id": project.organization_id, "project_id": project.pk,
        "policy_version": POLICY_VERSION, "memory_seconds": MEMORY_SECONDS, "live_verified": False,
        "configured": configured, "configuration_revision": config.revision if config else None,
        "verified_origins": verified, "assessments": [{"id": row.pk, "business_name": row.business_name,
            "profile_url": row.profile_url} for row in assessments[:20]], "assessments_has_more": len(assessments) > 20,
        "grants": grant_rows, "grants_has_more": len(grants) > 20,
        "attempts": [{"id": job.pk, "project_id": project.pk, "operation": job.input_snapshot["operation"],
            "status": job.status, "error_category": job.error_category,
            "cancel_requested": JobCancellation.objects.filter(job=job).exists(),
            "reserved_units": job.usage.reserved_units, "actual_units": job.usage.actual_units,
            "usage_state": job.usage.state, "created_at": job.created_at.isoformat()} for job in jobs[:20]],
        "attempts_has_more": len(jobs) > 20, "next_before_id": jobs[19].pk if len(jobs) > 20 else None,
        "rankings": "unavailable", "direct_writes": "unavailable", "returned_content": "not_stored_not_replayable"})


@sensitive_post_parameters()
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def project_business_profile(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = Project.objects.for_user(request.user).filter(pk=project_id, organization_id=organization_id).first()
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
        if request.method == "GET":
            return _status(request, project)
        if not ratelimit.consume(request, action="business_profile_request", user=request.user):
            return _result({"message": "Business Profile requests temporarily limited."}, HTTPStatus.TOO_MANY_REQUESTS)
        if len(request.body) > 4096:
            raise ValueError
        action = json.loads(request.body, object_pairs_hook=_unique_object, parse_constant=_reject_constant).get("action")
        fields = {"consent": {"selection", "policy_version"}, "read": {"grant_id", "grant_revision", "policy_version", "accepted", "request_key"},
                  "revoke": {"grant_id"}, "cancel": {"job_id"}}
        if type(action) is not str or action not in fields:
            raise ValueError
        data = _payload(request, fields[action] | {"action"})
        data.pop("action")
        if action == "consent":
            if not ratelimit.consume(request, action="google_oauth_start", user=request.user):
                return _result({"message": "Business consent temporarily limited."}, HTTPStatus.TOO_MANY_REQUESTS)
            client = google_business_oauth_client()
            if not _origin_matches_callback(request, client.redirect_uri):
                raise ValidationError("Business Profile callback must share this browser origin.")
            intent, state = begin_business_oauth_intent(project=project, actor=request.user,
                session_key=request.session.session_key, **data)
            client = google_business_oauth_client()
            if not _origin_matches_callback(request, client.redirect_uri) or client.redirect_uri != intent.redirect_uri:
                raise PermissionDenied
            return _result({"project_id": project.pk, "expires_at": intent.expires_at.isoformat(),
                "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
                    "client_id": client.client_id, "redirect_uri": intent.redirect_uri, "response_type": "code",
                    "scope": SCOPE, "access_type": "offline", "include_granted_scopes": "false", "prompt": "consent", "state": state})}, HTTPStatus.CREATED)
        if action == "read":
            _grant(project, data["grant_id"])
            result = read_business_profile(project=project, actor=request.user, **data)
            # Final private delivery recheck after settlement/activation, before serialization.
            require_business_grant(grant=_grant(project, result["grant_id"]), actor=request.user,
                                   expected_revision=result["grant_revision"])
            return _result(result)
        if action == "revoke":
            grant = revoke_business_grant(grant=_grant(project, data["grant_id"]), actor=request.user)
            return _result({"project_id": project.pk, "grant_id": grant.pk, "state": grant.state, "revision": grant.revision})
        if type(data["job_id"]) is not int or not 1 <= data["job_id"] <= 2**63 - 1:
            raise ValueError
        job = JobRun.objects.filter(project=project, organization_id=project.organization_id, handler=HANDLER, pk=data["job_id"]).first()
        if job is None:
            raise PermissionDenied
        cancel_job(job=job, actor=request.user)
        return _result({"project_id": project.pk, "job_id": job.pk, "cancel_requested": True})
    except PermissionDenied:
        return _result({"message": "Current business authority or project role unavailable."}, HTTPStatus.FORBIDDEN)
    except UsageLimitError as error:
        return _result({"message": "Business Profile allowance unavailable.", "code": error.category}, HTTPStatus.TOO_MANY_REQUESTS)
    except (BusinessRequestError, GoogleTokenError) as error:
        return _result({"message": "Business Profile request unavailable. No returned content is stored or retried.",
            "code": error.category}, HTTPStatus.CONFLICT)
    except (ValidationError, ValueError, TypeError, AttributeError, UnicodeError, IntegrityError):
        return _result({"message": "Check exact current business fields, authority and policy acceptance."}, HTTPStatus.CONFLICT)


@sensitive_variables()
@require_GET
def business_profile_callback(request):
    if not request.user.is_authenticated or not request.user.is_active or not request.session.session_key:
        return _redirect("/account/login")
    try:
        if (set(request.GET) - {"state", "code", "error", "scope", "authuser", "prompt", "error_description"}
            or any(len(values) != 1 for _key, values in request.GET.lists())
            or not ratelimit.consume(request, action="google_oauth_callback", user=request.user)):
            raise OAuthStateError("Business callback is invalid.")
        callback = google_business_oauth_client().redirect_uri
        if request.build_absolute_uri(request.path) != callback:
            raise OAuthStateError("Business callback origin did not match.")
        data = dict(actor=request.user, session_key=request.session.session_key,
                    state=request.GET.get("state", ""), callback_url=callback)
        if request.GET.get("error"):
            intent, _client = consume_business_oauth_intent(**data, provider_denied=True)
            return _redirect(f"/app/business-profile/{intent.organization_id}/{intent.project_id}")
        grant = complete_business_consent(**data, code=request.GET.get("code", ""))
        return _redirect(f"/app/business-profile/{grant.organization_id}/{grant.project_id}")
    except (PermissionDenied, ValidationError, OAuthStateError, GoogleTokenError, BusinessRequestError,
            ValueError, TypeError, UnicodeError, IntegrityError):
        return _redirect("/app")
