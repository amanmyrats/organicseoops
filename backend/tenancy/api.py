import json
import logging
import re
from http import HTTPStatus

from allauth.core import ratelimit
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import F, Q, Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from jobs.usage import UsageLimitError
from accounts.staff_access import require_staff_permissions
from accounts.localization import product_email_language

from .models import (
    InvitationState,
    MembershipRole,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    OrganizationTrial,
    OwnershipTransfer,
    Project,
    ProjectConfiguration,
    ProjectOriginVerification,
    TrialState,
)
from .services import (
    Action,
    ConfigurationConflict,
    InvitationError,
    TrialAllowanceError,
    accept_invitation,
    approve_organization_trial,
    create_invitation,
    create_origin_verification,
    create_organization,
    create_project,
    extend_organization_trial,
    accept_ownership_transfer,
    cancel_ownership_transfer,
    leave_organization,
    propose_ownership_transfer,
    ORIGIN_VERIFICATION_PATH,
    require_project_action,
    remove_membership,
    require_organization_action,
    revoke_invitation,
    revoke_origin_verification,
    set_organization_suspension,
    set_user_suspension,
    update_membership,
    update_organization,
    update_project,
    update_project_configuration,
)

logger = logging.getLogger(__name__)


@require_http_methods(["GET"])
def platform_acquisition_milestones(request):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    if not request.user.is_staff or not request.user.is_superuser:
        return _error("Platform permission required.", status=HTTPStatus.FORBIDDEN)
    from .acquisition import acquisition_milestones
    return _response(acquisition_milestones())


@require_http_methods(["GET"])
def platform_trial_paid_cohort(request, month=None):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    if not request.user.is_staff or not request.user.is_superuser:
        return _error("Platform permission required.", status=HTTPStatus.FORBIDDEN)
    if (request.META.get("QUERY_STRING") or request.body
        or month is not None and not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month)):
        return _error("Cohort inspection unavailable.")
    from allauth.account import app_settings
    from allauth.core.internal import ratelimit as bounded_ratelimit
    from .trial_paid_cohort import inspect_retained_trial_paid_cohort
    if bounded_ratelimit.consume(request, config=app_settings.RATE_LIMITS, limit_get=True,
            action="trial_paid_cohort_read", user=request.user) is None:
        return _error("Cohort inspection unavailable.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        result = inspect_retained_trial_paid_cohort(request=request, month=month)
    except PermissionDenied:
        return _error("Cohort inspection unavailable.", status=HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Cohort inspection unavailable.", status=HTTPStatus.CONFLICT)
    return _response(result)


def _response(payload, *, status=HTTPStatus.OK):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _error(message, *, status=HTTPStatus.BAD_REQUEST, code=None):
    error = {"message": message}
    if code:
        error["code"] = code
    return _response({"errors": [error]}, status=status)


def _authenticated(request):
    return request.user.is_authenticated and request.user.is_active


def _payload(request, *, allowed, required=()):
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValidationError("Enter valid JSON.") from None
    if not isinstance(payload, dict) or set(payload) - set(allowed) or set(required) - set(payload):
        raise ValidationError("Check the submitted fields.")
    return payload


def _organization_fields(payload):
    if not isinstance(payload.get("name"), str) or not payload["name"].strip():
        raise ValidationError("Check the submitted fields.")


def _project_fields(payload, *, require_identity=False):
    if require_identity and not {"name", "canonical_origin"} <= set(payload):
        raise ValidationError("Check the submitted fields.")
    if "name" in payload and (not isinstance(payload["name"], str) or not payload["name"].strip()):
        raise ValidationError("Check the submitted fields.")
    if "canonical_origin" in payload and not isinstance(payload["canonical_origin"], str):
        raise ValidationError("Check the submitted fields.")
    if "aliases" in payload and (
        not isinstance(payload["aliases"], list)
        or any(not isinstance(alias, str) for alias in payload["aliases"])
    ):
        raise ValidationError("Check the submitted fields.")
    if "access_restricted" in payload and not isinstance(payload["access_restricted"], bool):
        raise ValidationError("Check the submitted fields.")


def _trial_context(organization, role):
    try:
        trial = organization.trial
    except OrganizationTrial.DoesNotExist:
        return "unavailable", None

    stored_state = trial.state
    state = stored_state
    if state == TrialState.READ_ONLY or (
        state in [TrialState.ACTIVE, TrialState.SUSPENDED]
        and trial.ends_at is not None
        and trial.ends_at <= timezone.now()
    ):
        state = TrialState.EXPIRED
    if organization.is_suspended or stored_state == TrialState.SUSPENDED:
        access_state = TrialState.SUSPENDED
    elif state == TrialState.EXPIRED:
        access_state = TrialState.READ_ONLY
    else:
        access_state = state

    if role != MembershipRole.OWNER:
        return access_state, None
    if not hasattr(organization, "_trial_settled_units"):
        _attach_trial_usage([organization])
    return access_state, {
        "state": state,
        "access_state": access_state,
        "offer_version": trial.offer_version,
        "started_at": trial.started_at.isoformat() if trial.started_at else None,
        "ends_at": trial.ends_at.isoformat() if trial.ends_at else None,
        "project_limit": trial.project_limit,
        "member_limit": trial.member_limit,
        "unit_limit": trial.unit_limit,
        "settled_units": organization._trial_settled_units,
        "reserved_units": organization._trial_reserved_units,
    }


def _attach_trial_usage(organizations):
    from jobs.models import UsageReservation

    organizations = list(organizations)
    totals = {
        row["organization_id"]: row
        for row in UsageReservation.objects.filter(
            organization_id__in=[organization.pk for organization in organizations],
            created_at__gte=F("organization__trial__started_at"),
            created_at__lt=F("organization__trial__ends_at"),
        ).values("organization_id").annotate(
            settled_units=Sum(
                "actual_units",
                filter=Q(state=UsageReservation.State.SETTLED),
                default=0,
            ),
            reserved_units=Sum(
                "reserved_units",
                filter=Q(state=UsageReservation.State.RESERVED),
                default=0,
            ),
        )
    }
    for organization in organizations:
        usage = totals.get(organization.pk, {})
        organization._trial_settled_units = usage.get("settled_units", 0)
        organization._trial_reserved_units = usage.get("reserved_units", 0)


def _organization_payload(organization, role):
    access_state, trial = _trial_context(organization, role)
    return {
        "id": organization.pk,
        "name": organization.name,
        "role": role,
        "is_suspended": organization.is_suspended,
        "access_state": access_state,
        "trial": trial,
    }


def _project_payload(project, role):
    return {
        "id": project.pk,
        "organization_id": project.organization_id,
        "name": project.name,
        "canonical_origin": project.canonical_origin,
        "aliases": [alias.origin for alias in project.domain_aliases.all()],
        "access_restricted": project.access_restricted,
        "role": role,
    }


_CONFIGURATION_STRING_FIELDS = {
    "target_country", "business_goal", "timezone", "audience", "offer", "brand_voice",
    "contact_details", "business_hours", "local_eligibility_notes", "measurement_notes", "source_choice", "current_step",
}
_CONFIGURATION_LIST_FIELDS = {
    "target_languages", "seed_topics", "prohibited_claims", "conversion_goals", "brand_aliases",
    "competitor_origins", "research_allowed_origins", "research_blocked_origins", "business_locations",
    "service_areas", "profile_urls", "ignored_query_parameters", "pagination_query_parameters",
    "facet_query_parameters", "rss_feed_urls",
}
_CONFIGURATION_INTEGER_FIELDS = {"crawl_page_limit", "query_variant_limit"}
_CONFIGURATION_FIELDS = _CONFIGURATION_STRING_FIELDS | _CONFIGURATION_LIST_FIELDS | _CONFIGURATION_INTEGER_FIELDS


def _configuration_fields(payload):
    if type(payload.get("revision")) is not int or payload["revision"] < 0:
        raise ValidationError("Check the submitted fields.")
    if any(field in payload and not isinstance(payload[field], str) for field in _CONFIGURATION_STRING_FIELDS):
        raise ValidationError("Check the submitted fields.")
    if any(
        field in payload and (
            not isinstance(payload[field], list) or any(not isinstance(value, str) for value in payload[field])
        )
        for field in _CONFIGURATION_LIST_FIELDS
    ):
        raise ValidationError("Check the submitted fields.")
    if "crawl_page_limit" in payload and (
        payload["crawl_page_limit"] is not None and type(payload["crawl_page_limit"]) is not int
    ):
        raise ValidationError("Check the submitted fields.")
    if "query_variant_limit" in payload and type(payload["query_variant_limit"]) is not int:
        raise ValidationError("Check the submitted fields.")


def _configuration_payload(project, configuration=None):
    configuration = configuration or ProjectConfiguration(project=project)
    return {
        "project_id": project.pk,
        "canonical_origin": project.canonical_origin,
        "target_country": configuration.target_country,
        "target_languages": configuration.target_languages,
        "business_goal": configuration.business_goal,
        "timezone": configuration.timezone,
        "audience": configuration.audience,
        "offer": configuration.offer,
        "brand_voice": configuration.brand_voice,
        "seed_topics": configuration.seed_topics,
        "prohibited_claims": configuration.prohibited_claims,
        "conversion_goals": configuration.conversion_goals,
        "brand_aliases": configuration.brand_aliases,
        "measurement_notes": configuration.measurement_notes,
        "competitor_origins": configuration.competitor_origins,
        "research_allowed_origins": configuration.research_allowed_origins,
        "research_blocked_origins": configuration.research_blocked_origins,
        "rss_feed_urls": configuration.rss_feed_urls,
        "crawl_page_limit": configuration.crawl_page_limit,
        "ignored_query_parameters": configuration.ignored_query_parameters,
        "pagination_query_parameters": configuration.pagination_query_parameters,
        "facet_query_parameters": configuration.facet_query_parameters,
        "query_variant_limit": configuration.query_variant_limit,
        "business_locations": configuration.business_locations,
        "service_areas": configuration.service_areas,
        "contact_details": configuration.contact_details,
        "business_hours": configuration.business_hours,
        "profile_urls": configuration.profile_urls,
        "local_eligibility_notes": configuration.local_eligibility_notes,
        "source_choice": configuration.source_choice,
        "source_state": {
            ProjectConfiguration.SourceChoice.UNDECIDED: "not_selected",
            ProjectConfiguration.SourceChoice.CONNECT_SEARCH_CONSOLE: "disconnected",
            ProjectConfiguration.SourceChoice.IMPORT_SEARCH_CONSOLE: "awaiting_import",
            ProjectConfiguration.SourceChoice.SKIP: "skipped",
            ProjectConfiguration.SourceChoice.SYNTHETIC_DEMO: "synthetic_demo",
        }[configuration.source_choice],
        "current_step": configuration.current_step,
        "revision": configuration.revision,
        "updated_at": configuration.updated_at.isoformat() if configuration.pk else None,
    }


def _origin_verification_payload(verification):
    return {
        "id": verification.pk,
        "project_id": verification.project_id,
        "origin": verification.origin,
        "method": verification.method,
        "state": verification.state,
        "challenge_path": ORIGIN_VERIFICATION_PATH,
        "verified_at": verification.verified_at.isoformat() if verification.verified_at else None,
        "revoked_at": verification.revoked_at.isoformat() if verification.revoked_at else None,
        "created_at": verification.created_at.isoformat(),
        "updated_at": verification.updated_at.isoformat(),
    }


def _get_organization(request, organization_id):
    return Organization.objects.for_user(request.user).select_related("trial").filter(pk=organization_id).first()


def _get_project(request, organization_id, project_id):
    return Project.objects.for_user(request.user).filter(
        organization_id=organization_id,
        pk=project_id,
    ).first()


def _role(organization, user):
    return OrganizationMembership.objects.only("role").get(organization=organization, user=user).role


def _request_id(request):
    return getattr(request, "_organicseoops_request_id", "")


def _member_payload(membership, visible_project_ids=None):
    project_ids = list(membership.project_memberships.values_list("project_id", flat=True))
    if visible_project_ids is not None:
        project_ids = [project_id for project_id in project_ids if project_id in visible_project_ids]
    return {
        "id": membership.pk,
        "user_id": membership.user_id,
        "email": membership.user.email,
        "role": membership.role,
        "project_ids": project_ids,
    }


def _invitation_payload(invitation, visible_project_ids=None):
    project_ids = list(invitation.project_grants.values_list("project_id", flat=True))
    if visible_project_ids is not None:
        project_ids = [project_id for project_id in project_ids if project_id in visible_project_ids]
    return {
        "id": invitation.pk,
        "email": invitation.email,
        "role": invitation.role,
        "state": invitation.state,
        "expires_at": invitation.expires_at.isoformat(),
        "project_ids": project_ids,
    }


@require_http_methods(["GET", "POST"])
def organizations(request):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    if request.method == "GET":
        memberships = list(
            OrganizationMembership.objects.filter(user=request.user)
            .select_related("organization", "organization__trial")
            .order_by("organization__name", "organization_id")[:101]
        )
        visible_memberships = memberships[:100]
        _attach_trial_usage([
            membership.organization
            for membership in visible_memberships
            if membership.role == MembershipRole.OWNER
        ])
        return _response({
            "organizations": [
                _organization_payload(membership.organization, membership.role)
                for membership in visible_memberships
            ],
            "has_more": len(memberships) > 100,
        })
    try:
        payload = _payload(request, allowed={"name"}, required={"name"})
        _organization_fields(payload)
        organization = create_organization(user=request.user, name=payload["name"])
    except (IntegrityError, TypeError, ValidationError):
        return _error("Check the submitted organization details.")
    return _response(
        {"organization": _organization_payload(organization, MembershipRole.OWNER)},
        status=HTTPStatus.CREATED,
    )


@require_http_methods(["GET", "PATCH"])
def organization_detail(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = _get_organization(request, organization_id)
    if organization is None:
        return _error("Organization not found.", status=HTTPStatus.NOT_FOUND)
    role = _role(organization, request.user)
    if request.method == "GET":
        return _response({"organization": _organization_payload(organization, role)})
    try:
        payload = _payload(request, allowed={"name"}, required={"name"})
        _organization_fields(payload)
        organization = update_organization(organization=organization, user=request.user, name=payload["name"])
    except PermissionDenied:
        return _error("You cannot change these organization settings.", status=HTTPStatus.FORBIDDEN)
    except (IntegrityError, TypeError, ValidationError):
        return _error("Check the submitted organization details.")
    return _response({"organization": _organization_payload(organization, role)})


@require_http_methods(["GET", "POST"])
def projects(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = _get_organization(request, organization_id)
    if organization is None:
        return _error("Organization not found.", status=HTTPStatus.NOT_FOUND)
    role = _role(organization, request.user)
    if request.method == "GET":
        visible = list(
            Project.objects.for_user(request.user)
            .filter(organization=organization)
            .prefetch_related("domain_aliases")[:101]
        )
        return _response({
            "organization": _organization_payload(organization, role),
            "projects": [_project_payload(project, role) for project in visible[:100]],
            "has_more": len(visible) > 100,
        })
    try:
        payload = _payload(
            request,
            allowed={"name", "canonical_origin", "aliases", "access_restricted"},
            required={"name", "canonical_origin"},
        )
        _project_fields(payload, require_identity=True)
        project = create_project(
            organization=organization,
            user=request.user,
            name=payload["name"],
            canonical_origin=payload["canonical_origin"],
            aliases=payload.get("aliases", []),
            access_restricted=payload.get("access_restricted", False),
        )
    except PermissionDenied:
        return _error("You cannot create projects in this organization.", status=HTTPStatus.FORBIDDEN)
    except TrialAllowanceError as error:
        return _error(error.messages[0], status=HTTPStatus.CONFLICT, code=error.code)
    except (IntegrityError, TypeError, ValidationError):
        return _error("Check the submitted project details.")
    return _response({"project": _project_payload(project, role)}, status=HTTPStatus.CREATED)


@require_http_methods(["GET", "PATCH"])
def project_detail(request, organization_id, project_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    project = _get_project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", status=HTTPStatus.NOT_FOUND)
    role = _role(project.organization, request.user)
    if request.method == "GET":
        return _response({
            "organization": _organization_payload(project.organization, role),
            "project": _project_payload(project, role),
        })
    try:
        payload = _payload(
            request,
            allowed={"name", "canonical_origin", "aliases", "access_restricted"},
        )
        if not payload:
            raise ValidationError("Check the submitted fields.")
        _project_fields(payload)
        project = update_project(
            project=project,
            user=request.user,
            name=payload.get("name"),
            canonical_origin=payload.get("canonical_origin"),
            aliases=payload.get("aliases") if "aliases" in payload else None,
            access_restricted=payload.get("access_restricted") if "access_restricted" in payload else None,
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return _error("You cannot change these project settings.", status=HTTPStatus.FORBIDDEN)
    except (IntegrityError, TypeError, ValidationError):
        return _error("Check the submitted project details.")
    return _response({
        "organization": _organization_payload(project.organization, role),
        "project": _project_payload(project, role),
    })


@require_http_methods(["GET", "PATCH"])
def project_onboarding(request, organization_id, project_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    project = _get_project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", status=HTTPStatus.NOT_FOUND)
    configuration = ProjectConfiguration.objects.filter(project=project).first()
    if request.method == "GET":
        return _response({
            "project": _project_payload(project, _role(project.organization, request.user)),
            "configuration": _configuration_payload(project, configuration),
        })
    try:
        payload = _payload(
            request,
            allowed=_CONFIGURATION_FIELDS | {"revision"},
            required={"revision"},
        )
        if len(payload) == 1:
            raise ValidationError("Check the submitted fields.")
        _configuration_fields(payload)
        configuration = update_project_configuration(
            project=project,
            user=request.user,
            expected_revision=payload.pop("revision"),
            changes=payload,
        )
    except PermissionDenied:
        return _error("You cannot change this project onboarding.", status=HTTPStatus.FORBIDDEN)
    except ConfigurationConflict:
        current = ProjectConfiguration.objects.filter(project=project).first()
        return _response(
            {
                "errors": [{"message": "This onboarding was changed in another session. Reload the latest version."}],
                "configuration": _configuration_payload(project, current),
            },
            status=HTTPStatus.CONFLICT,
        )
    except (IntegrityError, TypeError, ValidationError):
        return _error("Check the submitted onboarding details.")
    return _response({"configuration": _configuration_payload(project, configuration)})


@require_http_methods(["GET", "POST"])
def project_origin_verifications(request, organization_id, project_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    project = _get_project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", status=HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
    except PermissionDenied:
        return _error("You cannot manage origin verification.", status=HTTPStatus.FORBIDDEN)
    if request.method == "GET":
        records = ProjectOriginVerification.objects.filter(project=project).order_by("origin", "id")[:101]
        return _response({
            "verifications": [_origin_verification_payload(item) for item in records[:100]],
            "has_more": len(records) > 100,
        })
    try:
        payload = _payload(request, allowed={"origin"}, required={"origin"})
        if not isinstance(payload["origin"], str):
            raise ValidationError("Check the submitted fields.")
        if not ratelimit.consume(request, action="origin_verification", user=request.user):
            return _error("Too many verification changes. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
        verification, challenge = create_origin_verification(
            project=project,
            user=request.user,
            origin=payload["origin"],
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return _error("You cannot manage origin verification.", status=HTTPStatus.FORBIDDEN)
    except (IntegrityError, TypeError, ValidationError):
        return _error("Check the origin verification request.")
    return _response({
        "verification": _origin_verification_payload(verification),
        "challenge": {"path": ORIGIN_VERIFICATION_PATH, "content": challenge},
    }, status=HTTPStatus.CREATED)


@require_http_methods(["POST", "DELETE"])
def project_origin_verification_detail(request, organization_id, project_id, verification_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    project = _get_project(request, organization_id, project_id)
    if project is None:
        return _error("Project not found.", status=HTTPStatus.NOT_FOUND)
    verification = ProjectOriginVerification.objects.filter(
        pk=verification_id,
        project=project,
        organization_id=organization_id,
    ).select_related("project", "project__organization").first()
    if verification is None:
        return _error("Origin verification not found.", status=HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user, action=Action.MANAGE_PROJECT)
        if request.method == "DELETE":
            verification, changed = revoke_origin_verification(
                verification=verification,
                user=request.user,
                request_id=_request_id(request),
            )
            return _response({"verification": _origin_verification_payload(verification), "revoked": changed})
        payload = _payload(request, allowed={"idempotency_key"}, required={"idempotency_key"})
        if not ratelimit.consume(request, action="origin_verification", user=request.user):
            return _error("Too many verification checks. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
        from jobs.security import queue_origin_verification
        job = queue_origin_verification(
            verification=verification,
            actor=request.user,
            idempotency_key=payload["idempotency_key"],
        )
    except PermissionDenied:
        return _error("You cannot manage origin verification.", status=HTTPStatus.FORBIDDEN)
    except UsageLimitError as error:
        return _error(
            "Internal verification capacity is currently limited.",
            status=HTTPStatus.TOO_MANY_REQUESTS,
            code=error.category,
        )
    except (IntegrityError, TypeError, ValidationError):
        return _error("This origin verification cannot be queued.", status=HTTPStatus.CONFLICT)
    return _response({
        "verification": _origin_verification_payload(verification),
        "job": {"id": job.pk, "handler": job.handler, "status": job.status},
    }, status=HTTPStatus.ACCEPTED)


@require_http_methods(["GET", "POST"])
def team(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = _get_organization(request, organization_id)
    if organization is None:
        return _error("Organization not found.", status=HTTPStatus.NOT_FOUND)
    try:
        require_organization_action(
            organization=organization,
            user=request.user,
            action=Action.MANAGE_MEMBERS,
        )
    except PermissionDenied:
        return _error("You cannot manage this team.", status=HTTPStatus.FORBIDDEN)
    if request.method == "GET":
        memberships = list(
            OrganizationMembership.objects.filter(organization=organization)
            .select_related("user")
            .prefetch_related("project_memberships")
            .order_by("user__email")[:101]
        )
        invitations = list(
            OrganizationInvitation.objects.filter(
                organization=organization,
                state=InvitationState.PENDING,
                expires_at__gt=timezone.now(),
            ).prefetch_related("project_grants").order_by("email")[:101]
        )
        visible_project_ids = set(
            Project.objects.for_user(request.user).filter(organization=organization).values_list("pk", flat=True)
        )
        return _response({
            "members": [_member_payload(item, visible_project_ids) for item in memberships[:100]],
            "invitations": [_invitation_payload(item, visible_project_ids) for item in invitations[:100]],
            "has_more": len(memberships) > 100 or len(invitations) > 100,
        })
    try:
        payload = _payload(request, allowed={"email", "role", "project_ids"}, required={"email", "role"})
        if not isinstance(payload["email"], str) or not isinstance(payload["role"], str):
            raise ValidationError("Check the submitted fields.")
        if not ratelimit.consume(
            request,
            action="invite_member",
            key=payload["email"].strip().lower(),
            user=request.user,
        ):
            return _error("Too many invitation attempts. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
        invitation, token = create_invitation(
            organization=organization,
            actor=request.user,
            email=payload["email"],
            role=payload["role"],
            project_ids=payload.get("project_ids", []),
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return _error("You cannot grant that team access.", status=HTTPStatus.FORBIDDEN)
    except IntegrityError:
        return _error("A pending invitation already exists.", status=HTTPStatus.CONFLICT)
    except (TypeError, ValidationError):
        return _error("Check the submitted invitation details.")
    return _response(
        {"invitation": _invitation_payload(invitation), "delivery": _deliver_invitation(organization, invitation, token)},
        status=HTTPStatus.CREATED,
    )


def _deliver_invitation(organization, invitation, token):
    link = f"{settings.FRONTEND_ORIGIN}/account/invitation#{token}"
    recipient = get_user_model().objects.filter(email=invitation.email).first()
    subject = "[OrganicSEOOps] Organization invitation"
    body = f"You were invited to {organization.name}. Open this link to accept: {link}"
    if product_email_language(recipient) == "tr":
        subject = "[OrganicSEOOps] Kuruluş daveti (Türkçe taslak)"
        body = f"{organization.name} kuruluşuna davet edildiniz. Kabul etmek için bu bağlantıyı açın: {link}"
    try:
        send_mail(
            subject,
            body,
            None,
            [invitation.email],
        )
    except Exception:
        logger.exception("invitation.delivery_failed")
        return "failed"
    return "sent"


@require_http_methods(["PATCH", "DELETE"])
def member_detail(request, organization_id, membership_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = _get_organization(request, organization_id)
    if organization is None:
        return _error("Organization not found.", status=HTTPStatus.NOT_FOUND)
    try:
        require_organization_action(organization=organization, user=request.user, action=Action.MANAGE_MEMBERS)
    except PermissionDenied:
        return _error("Member not found.", status=HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="manage_team", user=request.user):
        return _error("Too many team changes. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    membership = OrganizationMembership.objects.filter(
        organization=organization,
        pk=membership_id,
    ).select_related("user").first()
    if membership is None:
        return _error("Member not found.", status=HTTPStatus.NOT_FOUND)
    try:
        if request.method == "DELETE":
            try:
                remove_membership(
                    membership=membership, actor=request.user, request=request,
                    request_id=_request_id(request),
                )
            except ValidationError:
                return _error("Transfer ownership before removing the last active owner.", status=HTTPStatus.CONFLICT)
            return _response({}, status=HTTPStatus.NO_CONTENT)
        payload = _payload(request, allowed={"role", "project_ids"})
        if not payload:
            raise ValidationError("Check the submitted fields.")
        if "role" in payload and not isinstance(payload["role"], str):
            raise ValidationError("Check the submitted fields.")
        membership = update_membership(
            membership=membership,
            actor=request.user,
            role=payload.get("role"),
            project_ids=payload.get("project_ids") if "project_ids" in payload else None,
            request=request,
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return _error("You cannot change that membership.", status=HTTPStatus.FORBIDDEN)
    except (IntegrityError, TypeError, ValidationError):
        return _error("Check the submitted membership details.")
    visible_project_ids = set(
        Project.objects.for_user(request.user).filter(organization=organization).values_list("pk", flat=True)
    )
    return _response({"member": _member_payload(membership, visible_project_ids)})


@require_http_methods(["POST", "DELETE"])
def invitation_detail(request, organization_id, invitation_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = _get_organization(request, organization_id)
    if organization is None:
        return _error("Organization not found.", status=HTTPStatus.NOT_FOUND)
    try:
        require_organization_action(organization=organization, user=request.user, action=Action.MANAGE_MEMBERS)
    except PermissionDenied:
        return _error("Invitation not found.", status=HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="manage_team", user=request.user):
        return _error("Too many team changes. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    invitation = OrganizationInvitation.objects.filter(
        organization=organization,
        pk=invitation_id,
    ).first()
    if invitation is None:
        return _error("Invitation not found.", status=HTTPStatus.NOT_FOUND)
    try:
        if request.method == "POST":
            try:
                _payload(request, allowed=set())
            except ValidationError:
                return _error("Check the submitted invitation request.")
            if not ratelimit.consume(request, action="invite_member", key=invitation.email, user=request.user):
                return _error("Too many invitation attempts. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
            with transaction.atomic():
                project_ids = list(invitation.project_grants.values_list("project_id", flat=True))
                revoke_invitation(invitation=invitation, actor=request.user, request_id=_request_id(request))
                replacement, token = create_invitation(
                    organization=organization, actor=request.user, email=invitation.email,
                    role=invitation.role, project_ids=project_ids, request_id=_request_id(request),
                )
            return _response({
                "invitation": _invitation_payload(replacement),
                "delivery": _deliver_invitation(organization, replacement, token),
            }, status=HTTPStatus.CREATED)
        revoke_invitation(
            invitation=invitation,
            actor=request.user,
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return _error("You cannot revoke that invitation.", status=HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("That invitation cannot be revoked.", status=HTTPStatus.CONFLICT)
    return _response({}, status=HTTPStatus.NO_CONTENT)


@require_http_methods(["POST"])
def invitation_accept(request):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    if not ratelimit.consume(request, action="invitation_accept", user=request.user):
        return _error("Too many invitation attempts. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        payload = _payload(request, allowed={"token"}, required={"token"})
        membership, invitation, created = accept_invitation(
            user=request.user,
            token=payload["token"],
            request_id=_request_id(request),
        )
    except InvitationError as error:
        status = {
            "invalid": HTTPStatus.NOT_FOUND,
            "wrong_identity": HTTPStatus.FORBIDDEN,
            "conflict": HTTPStatus.CONFLICT,
            "expired": HTTPStatus.GONE,
            "revoked": HTTPStatus.GONE,
            "suspended": HTTPStatus.FORBIDDEN,
            "trial_unavailable": HTTPStatus.FORBIDDEN,
            "member_limit": HTTPStatus.CONFLICT,
        }[error.code]
        return _error(str(error), status=status, code=error.code)
    except (TypeError, ValidationError):
        return _error("Check the submitted invitation.")
    return _response(
        {
            "organization": _organization_payload(invitation.organization, membership.role),
            "accepted": created,
        }
    )


@require_http_methods(["GET", "POST"])
def ownership_transfer(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = _get_organization(request, organization_id)
    if organization is None:
        return _error("Organization not found.", status=HTTPStatus.NOT_FOUND)
    if request.method == "GET":
        transfer = OwnershipTransfer.objects.filter(
            organization=organization, state=OwnershipTransfer.State.PENDING,
        ).select_related("from_user", "to_user").first()
        return _response({"transfer": {
            "id": transfer.pk, "from_email": transfer.from_user.email, "to_email": transfer.to_user.email,
        } if transfer and request.user.pk in {transfer.from_user_id, transfer.to_user_id} else None})
    if not ratelimit.consume(request, action="manage_team", user=request.user):
        return _error("Too many team changes. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        payload = _payload(request, allowed={"member_id"}, required={"member_id"})
        if type(payload["member_id"]) is not int:
            raise ValidationError("Choose an existing member.")
        member = OrganizationMembership.objects.filter(organization=organization, pk=payload["member_id"]).select_related("user").first()
        if member is None:
            return _error("Member not found.", status=HTTPStatus.NOT_FOUND)
        transfer = propose_ownership_transfer(
            organization=organization, actor=request.user, target=member.user,
            request=request, request_id=_request_id(request),
        )
    except PermissionDenied:
        return _error("Reauthenticate as an owner before proposing a transfer.", status=HTTPStatus.FORBIDDEN)
    except (IntegrityError, TypeError, ValidationError):
        return _error("Select an active verified non-owner member; resolve any pending transfer first.")
    return _response({"transfer": {"id": transfer.pk}}, status=HTTPStatus.CREATED)


@require_http_methods(["POST"])
def ownership_accept(request, organization_id, transfer_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = _get_organization(request, organization_id)
    if organization is None:
        return _error("Organization not found.", status=HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="manage_team", user=request.user):
        return _error("Too many team changes. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    transfer = OwnershipTransfer.objects.filter(organization=organization, pk=transfer_id, to_user=request.user).first()
    if transfer is None:
        return _error("Transfer not found.", status=HTTPStatus.NOT_FOUND)
    try:
        _payload(request, allowed=set())
        accept_ownership_transfer(transfer=transfer, user=request.user, request=request, request_id=_request_id(request))
    except PermissionDenied:
        return _error("Reauthenticate or ask the current owner to start a new transfer.", status=HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Check the submitted transfer.")
    return _response({"accepted": True})


@require_http_methods(["DELETE"])
def ownership_cancel(request, organization_id, transfer_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = _get_organization(request, organization_id)
    if organization is None:
        return _error("Organization not found.", status=HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="manage_team", user=request.user):
        return _error("Too many team changes. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    transfer = OwnershipTransfer.objects.filter(organization=organization, pk=transfer_id).first()
    if transfer is None:
        return _error("Transfer not found.", status=HTTPStatus.NOT_FOUND)
    try:
        cancel_ownership_transfer(transfer=transfer, user=request.user, request=request, request_id=_request_id(request))
    except PermissionDenied:
        return _error("Reauthenticate to cancel this transfer.", status=HTTPStatus.FORBIDDEN)
    return _response({}, status=HTTPStatus.NO_CONTENT)


@require_http_methods(["POST"])
def organization_leave(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = _get_organization(request, organization_id)
    if organization is None:
        return _error("Organization not found.", status=HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="manage_team", user=request.user):
        return _error("Too many team changes. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        _payload(request, allowed=set())
    except ValidationError:
        return _error("Check the submitted leave request.")
    try:
        leave_organization(organization=organization, user=request.user, request=request, request_id=_request_id(request))
    except PermissionDenied:
        return _error("Reauthenticate before leaving this organization.", status=HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Transfer ownership or close the organization before leaving.", status=HTTPStatus.CONFLICT)
    return _response({}, status=HTTPStatus.NO_CONTENT)


def _suspension_payload(request):
    payload = _payload(request, allowed={"suspended", "reason"}, required={"suspended", "reason"})
    if type(payload["suspended"]) is not bool or not isinstance(payload["reason"], str) or not payload["reason"].strip():
        raise ValidationError("Provide a suspension state and reason.")
    return payload


@require_http_methods(["POST"])
def platform_organization_suspension(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    if not request.user.is_staff or not request.user.has_perm("tenancy.change_organization"):
        return _error("Staff permission required.", status=HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="platform_suspension", user=request.user):
        return _error("Too many suspension changes. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    organization = Organization.objects.filter(pk=organization_id).first()
    if organization is None:
        return _error("Organization not found.", status=HTTPStatus.NOT_FOUND)
    try:
        payload = _suspension_payload(request)
        organization = set_organization_suspension(
            organization=organization, actor=request.user, suspended=payload["suspended"],
            reason=payload["reason"], request_id=_request_id(request),
        )
    except ValidationError:
        return _error("Provide a suspension state and reason.")
    return _response({"is_suspended": organization.is_suspended})


@require_http_methods(["POST"])
def platform_trial_approval(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    try:
        require_staff_permissions(request, permissions=("tenancy.change_organizationtrial",))
    except PermissionDenied:
        return _error("Staff trial permission required.", status=HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="platform_trial", user=request.user):
        return _error("Too many trial changes. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    organization = Organization.objects.filter(pk=organization_id).first()
    if organization is None:
        return _error("Organization not found.", status=HTTPStatus.NOT_FOUND)
    try:
        payload = _payload(request, allowed={"reason"}, required={"reason"})
        if not isinstance(payload["reason"], str) or not payload["reason"].strip() or len(payload["reason"].strip()) > 250:
            raise ValidationError("Provide a bounded approval reason.")
    except ValidationError:
        return _error("Provide a bounded approval reason.")
    try:
        trial = approve_organization_trial(
            organization=organization,
            actor=request.user,
            reason=payload["reason"],
            request=request,
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return _error("Staff trial permission required.", status=HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Only a pending trial for an active organization can be approved.", status=HTTPStatus.CONFLICT)
    return _response({
        "trial": {
            "organization_id": trial.organization_id,
            "state": trial.state,
            "offer_version": trial.offer_version,
            "started_at": trial.started_at.isoformat(),
            "ends_at": trial.ends_at.isoformat(),
        },
    })


@require_http_methods(["POST"])
def platform_trial_extension(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    try:
        require_staff_permissions(request, permissions=("tenancy.change_organizationtrial",))
    except PermissionDenied:
        return _error("Staff trial permission required.", status=HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="platform_trial", user=request.user):
        return _error("Too many trial changes. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    organization = Organization.objects.filter(pk=organization_id).first()
    if organization is None:
        return _error("Organization not found.", status=HTTPStatus.NOT_FOUND)
    try:
        payload = _payload(request, allowed={"reason"}, required={"reason"})
        if not isinstance(payload["reason"], str) or not payload["reason"].strip() or len(payload["reason"].strip()) > 250:
            raise ValidationError("Provide a bounded extension reason.")
    except ValidationError:
        return _error("Provide a bounded extension reason.")
    try:
        trial = extend_organization_trial(
            organization=organization,
            actor=request.user,
            reason=payload["reason"],
            request=request,
            request_id=_request_id(request),
        )
    except PermissionDenied:
        return _error("Staff trial permission required.", status=HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Only an eligible trial can be extended.", status=HTTPStatus.CONFLICT)
    return _response({
        "trial": {
            "organization_id": trial.organization_id,
            "state": trial.state,
            "offer_version": trial.offer_version,
            "started_at": trial.started_at.isoformat(),
            "ends_at": trial.ends_at.isoformat(),
        },
    })


@require_http_methods(["POST"])
def platform_user_suspension(request, user_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    if not request.user.is_staff or not request.user.has_perm("accounts.change_user"):
        return _error("Staff permission required.", status=HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="platform_suspension", user=request.user):
        return _error("Too many suspension changes. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None:
        return _error("User not found.", status=HTTPStatus.NOT_FOUND)
    try:
        payload = _suspension_payload(request)
        user = set_user_suspension(
            user=user, actor=request.user, suspended=payload["suspended"],
            reason=payload["reason"], request_id=_request_id(request),
        )
    except PermissionDenied:
        return _error("This account cannot be suspended by this staff member.", status=HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Transfer ownership before suspending the last active owner.", status=HTTPStatus.CONFLICT)
    return _response({"is_active": user.is_active})
