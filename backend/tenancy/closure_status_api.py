from datetime import timedelta
from http import HTTPStatus

from allauth.core import ratelimit
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.views.decorators.http import require_GET
from django.utils import timezone

from integrations.models import RepositoryConsent, RepositoryGrant, YandexOAuthGrant, BusinessProfileOAuthGrant, GA4OAuthGrant, GoogleOAuthGrant

from .api import _authenticated, _error, _response
from .models import (AuditEvent, AuditEventType, MembershipRole, Organization,
                     OrganizationBillingCancellation, OrganizationDeletionRun, OrganizationMembership)
from .services import Action, require_organization_action


@require_GET
def organization_closure_status(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = Organization.objects.filter(pk=organization_id).first()
    if organization is None:
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    membership = OrganizationMembership.objects.filter(organization=organization, user=request.user).first()
    closing_actor = AuditEvent.objects.filter(organization=organization, actor=request.user,
                                              event_type=AuditEventType.ORGANIZATION_CLOSED).exists()
    if membership is None and not closing_actor:
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    if organization.closed_at is None:
        try:
            require_organization_action(organization=organization, user=request.user,
                                        action=Action.ORGANIZATION_SETTINGS)
        except PermissionDenied:
            return _error("Closure status unavailable.", status=HTTPStatus.FORBIDDEN)
    elif not (membership is not None and membership.role == MembershipRole.OWNER or closing_actor):
        return _error("Closure status unavailable.", status=HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="organization_closure_status", user=request.user):
        return _error("Too many status requests. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    deletion = OrganizationDeletionRun.objects.filter(organization=organization).first()
    cancellation = OrganizationBillingCancellation.objects.filter(organization=organization).first()
    result = {"organization_id": organization.pk,
              "closed_at": organization.closed_at.isoformat() if organization.closed_at else None,
              "state": "closed" if organization.closed_at else "retention_cleanup" if deletion else "open",
              "close_action_available": (settings.SELF_SERVICE_CLOSURE_ENABLED
                                         and organization.closed_at is None and deletion is None),
              "deletion": ({"source": deletion.source, "state": deletion.state,
                            "eligible_at": deletion.eligible_at.isoformat(), "due_at": deletion.due_at.isoformat(),
                            "completed_at": deletion.completed_at.isoformat() if deletion.completed_at else None,
                            "error_category": deletion.last_error_category,
                            "backup_latest_expiry_bound_at": (deletion.completed_at + timedelta(days=35)).isoformat()
                                                             if deletion.completed_at else None}
                           if deletion else None),
              "billing_cancellation": ({"state": cancellation.state,
                                        "error_category": cancellation.error_category}
                                       if cancellation else None),
              "repository_unknown_exchanges": [{"id": row.pk,
                  "can_report_revoked": row.used_at <= timezone.now() - timedelta(minutes=10)}
                  for row in RepositoryConsent.objects.filter(organization=organization, status="consumed",
                      repositorygrant__isnull=True, user_reported_revoked_at__isnull=True).order_by("pk")[:20]],
              "remote_revocation_pending": {
                  "repository": RepositoryGrant.objects.filter(organization=organization, state="revocation_pending").count(),
                  "yandex": YandexOAuthGrant.objects.filter(organization=organization, state="revocation_pending").count(),
                  "search_console": GoogleOAuthGrant.objects.filter(organization=organization,
                      state=GoogleOAuthGrant.State.REVOCATION_PENDING).count(),
                  "analytics": GA4OAuthGrant.objects.filter(organization=organization,
                      state=GA4OAuthGrant.State.REVOCATION_PENDING).count(),
                  "business_profile": BusinessProfileOAuthGrant.objects.filter(organization=organization,
                      state="revocation_pending").count()},
              "pending_grants": {
                  "repository": list(RepositoryGrant.objects.filter(organization=organization, state="revocation_pending").order_by("pk").values_list("pk", flat=True)[:20]),
                  "yandex": list(YandexOAuthGrant.objects.filter(organization=organization, state="revocation_pending").order_by("pk").values_list("pk", flat=True)[:20]),
                  "search_console": list(GoogleOAuthGrant.objects.filter(organization=organization,
                      state=GoogleOAuthGrant.State.REVOCATION_PENDING).order_by("pk").values_list("pk", flat=True)[:20]),
                  "analytics": list(GA4OAuthGrant.objects.filter(organization=organization,
                      state=GA4OAuthGrant.State.REVOCATION_PENDING).order_by("pk").values_list("pk", flat=True)[:20]),
                  "business_profile": list(BusinessProfileOAuthGrant.objects.filter(organization=organization,
                      state="revocation_pending").order_by("pk").values_list("pk", flat=True)[:20])},
              "limitations": "Already downloaded copies cannot be erased. Actual S3 version and backup expiry require hosted verification."}
    response = _response(result)
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    return response
