from http import HTTPStatus

from allauth.core import ratelimit
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.http import require_POST

from integrations.models import RepositoryGrant, YandexOAuthGrant, BusinessProfileOAuthGrant, GA4OAuthGrant, GoogleOAuthGrant

from .api import _authenticated, _error, _payload, _response
from .closure import close_organization_locally
from .closure_grants import revoke_closed_repository_grant, revoke_closed_yandex_grant, revoke_closed_analytics_grant, revoke_closed_business_grant, revoke_closed_search_console_grant
from .deletion import prepare_customer_data_deletion
from .models import (AuditEvent, AuditEventType, MembershipRole, Organization,
                     OrganizationBillingCancellation, OrganizationMembership)
from .paddle_cancellation import (execute_billing_cancellation, prepare_billing_cancellation,
                                  reconcile_billing_cancellation)
from .services import Action, _recent_authentication, require_organization_action


def _private_response(payload, status=HTTPStatus.OK):
    response = _response(payload, status=status)
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_POST
def organization_close(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    if not settings.SELF_SERVICE_CLOSURE_ENABLED:
        return _error("Organization closure is not yet available.", status=HTTPStatus.SERVICE_UNAVAILABLE)
    organization = Organization.objects.filter(pk=organization_id).first()
    if organization is None:
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    if organization.closed_at is not None:
        if not AuditEvent.objects.filter(organization=organization, actor=request.user,
                                         event_type=AuditEventType.ORGANIZATION_CLOSED).exists():
            return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
        return _private_response({"state": "closed", "organization_id": organization.pk,
                                  "status_path": f"/api/organizations/{organization.pk}/closure-status/"})
    if not OrganizationMembership.objects.filter(organization=organization, user=request.user).exists():
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    try:
        require_organization_action(organization=organization, user=request.user,
                                    action=Action.ORGANIZATION_SETTINGS)
    except PermissionDenied:
        return _error("Owner permission required.", status=HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="organization_close", user=request.user):
        return _error("Too many closure requests. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if len(request.body) > 512:
            raise ValidationError("Confirm irreversible organization closure.")
        body = _payload(request, allowed={"acknowledge_irreversible"},
                         required={"acknowledge_irreversible"})
        if body["acknowledge_irreversible"] is not True:
            raise ValidationError("Confirm irreversible organization closure.")
        _recent_authentication(request, request.user)
        attempt = prepare_billing_cancellation(organization=organization, actor=request.user)
        organization = close_organization_locally(organization=organization, actor=request.user, request=request,
            request_id=getattr(request, "_organicseoops_request_id", ""))
    except PermissionDenied:
        return _error("Reauthenticate as the current owner before closure.", status=HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Reconcile active billing, export and ownership before closing.", status=HTTPStatus.CONFLICT)
    state = "closed"
    cleanup_state = "prepared"
    try:
        prepare_customer_data_deletion(organization=organization)
    except (PermissionDenied, ValidationError):
        state = "closed_cleanup_review"
        cleanup_state = "needs_review"
    billing_state = "not_required"
    if attempt is not None:
        try:
            attempt = execute_billing_cancellation(attempt)
        except (PermissionDenied, ValidationError):
            attempt = OrganizationBillingCancellation.objects.get(pk=attempt.pk)
        billing_state = attempt.state
        if attempt.state != attempt.State.CONFIRMED:
            state = "closed_billing_review"
    return _private_response({"state": state, "organization_id": organization.pk,
        "status_path": f"/api/organizations/{organization.pk}/closure-status/",
        "cleanup_state": cleanup_state, "billing_state": billing_state,
        "already_downloaded_copies": "cannot_be_erased",
        "backup_expiry": "policy_only_unverified"}, status=HTTPStatus.ACCEPTED)


@require_POST
def organization_reconcile_closure_billing(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = Organization.objects.filter(pk=organization_id, closed_at__isnull=False,
                                               is_suspended=True).first()
    if organization is None:
        return _error("Organization closure unavailable.", status=HTTPStatus.NOT_FOUND)
    if not (OrganizationMembership.objects.filter(organization=organization, user=request.user,
             role=MembershipRole.OWNER).exists() or AuditEvent.objects.filter(organization=organization, actor=request.user,
               event_type=AuditEventType.ORGANIZATION_CLOSED).exists()):
        return _error("Organization closure unavailable.", status=HTTPStatus.NOT_FOUND)
    try:
        _recent_authentication(request, request.user)
    except PermissionDenied:
        return _error("Reauthenticate before reconciling billing.", status=HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="organization_closure_reconcile", user=request.user):
        return _error("Too many billing checks. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if len(request.body) > 128 or _payload(request, allowed=set(), required=set()) != {}:
            raise ValidationError("Choose a bounded billing check.")
        attempt = OrganizationBillingCancellation.objects.filter(organization=organization).first()
        if attempt is None:
            raise PermissionDenied
        attempt = reconcile_billing_cancellation(attempt)
    except PermissionDenied:
        return _error("Billing cancellation unavailable.", status=HTTPStatus.NOT_FOUND)
    except ValidationError:
        return _error("Provider billing state requires review.", status=HTTPStatus.SERVICE_UNAVAILABLE)
    return _private_response({"state": attempt.state, "error_category": attempt.error_category,
        "organization_id": organization.pk,
        "status_path": f"/api/organizations/{organization.pk}/closure-status/"})


@require_POST
def organization_revoke_pending_grant(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = Organization.objects.filter(pk=organization_id).first()
    if organization is None:
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    membership = OrganizationMembership.objects.filter(organization=organization, user=request.user,
                                                        role=MembershipRole.OWNER).exists()
    audited_closer = AuditEvent.objects.filter(organization=organization, actor=request.user,
                                               event_type=AuditEventType.ORGANIZATION_CLOSED).exists()
    if not membership and not audited_closer:
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    try:
        _recent_authentication(request, request.user)
    except PermissionDenied:
        return _error("Reauthenticate before provider revocation.", status=HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="organization_closure_revoke", user=request.user):
        return _error("Too many revocation requests. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if len(request.body) > 128:
            raise ValidationError("Select one pending provider grant.")
        body = _payload(request, allowed={"provider", "grant_id", "remote_revocation_completed"}, required={"provider", "grant_id"})
        provider, grant_id = body["provider"], body["grant_id"]
        if type(grant_id) is not int or grant_id < 1 or provider not in {"search_console", "analytics", "business_profile", "yandex", "repository"}:
            raise ValidationError("Select one pending provider grant.")
        model, revoke = {"repository": (RepositoryGrant, revoke_closed_repository_grant), "yandex": (YandexOAuthGrant, revoke_closed_yandex_grant), "search_console": (GoogleOAuthGrant, revoke_closed_search_console_grant),
                         "analytics": (GA4OAuthGrant, revoke_closed_analytics_grant),
                         "business_profile": (BusinessProfileOAuthGrant, revoke_closed_business_grant)}[provider]
        if not model.objects.filter(pk=grant_id, organization=organization).exists():
            raise PermissionDenied
        if "remote_revocation_completed" in body:
            if provider != "repository" or body["remote_revocation_completed"] is not True:
                raise ValidationError("Only an actual completed GitHub authorization revocation may be reported.")
            from integrations.repository_oauth import report_grant_revoked
            grant = report_grant_revoked(grant_id=grant_id, actor=request.user, closed=True)
        else:
            grant = revoke(grant_id=grant_id, invoked_by=request.user)
    except PermissionDenied:
        return _error("Pending grant unavailable.", status=HTTPStatus.NOT_FOUND)
    except ValidationError:
        return _error("Review current provider revocation state.", status=HTTPStatus.CONFLICT)
    return _private_response({"organization_id": organization.pk, "provider": provider,
        "state": grant.state, "status_path": f"/api/organizations/{organization.pk}/closure-status/"})


@require_POST
def organization_report_repository_consent_revoked(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = Organization.objects.filter(pk=organization_id).first()
    if organization is None or not (OrganizationMembership.objects.filter(organization=organization, user=request.user,
            role=MembershipRole.OWNER).exists() or AuditEvent.objects.filter(organization=organization,
            actor=request.user, event_type=AuditEventType.ORGANIZATION_CLOSED).exists()):
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    try:
        _recent_authentication(request, request.user)
        if not ratelimit.consume(request, action="organization_closure_revoke", user=request.user):
            return _error("Too many revocation decisions.", status=HTTPStatus.TOO_MANY_REQUESTS)
        if len(request.body) > 128:
            raise ValidationError("Use one exact consent report.")
        body = _payload(request, allowed={"consent_id", "remote_revocation_completed"}, required={"consent_id", "remote_revocation_completed"})
        if type(body["consent_id"]) is not int or body["consent_id"] < 1 or body["remote_revocation_completed"] is not True:
            raise ValidationError("Record only actual completed remote revocation.")
        from integrations.repository_models import RepositoryConsent
        from integrations.repository_oauth import report_unknown_revoked
        if not RepositoryConsent.objects.filter(pk=body["consent_id"], organization=organization).exists():
            raise PermissionDenied
        report_unknown_revoked(consent_id=body["consent_id"], actor=request.user, closed=True)
        return _private_response({"organization_id": organization.pk, "state": "human_reported_not_provider_verified"})
    except PermissionDenied:
        return _error("Current closure/deletion recovery authority required.", status=HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Wait for in-flight consent and record remote revocation you completed.", status=HTTPStatus.CONFLICT)
