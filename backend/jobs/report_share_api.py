from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.utils import timezone

from tenancy.services import Action, require_project_action

from .findings_api import _error, _payload, _response
from .models import ProjectReportShare
from .report_api import _access, report_file_response
from .report_shares import create_report_share, read_shared_report, revoke_report_share


def _share_summary(share):
    now = timezone.now()
    return {"id": share.pk, "report_id": share.report_id, "intended_recipient": share.intended_recipient,
            "expires_at": share.expires_at.isoformat(), "revoked_at": share.revoked_at.isoformat() if share.revoked_at else None,
            "state": "revoked" if share.revoked_at else "expired" if share.expires_at <= now else "active"}


def _owner_access(request, organization_id, project_id):
    project, error = _access(request, organization_id, project_id)
    if error:
        return None, error
    try:
        require_project_action(project=project, user=request.user, action=Action.CREATE_EXTERNAL_SHARE)
    except PermissionDenied:
        return None, _error("Project report shares are unavailable.", HTTPStatus.FORBIDDEN)
    return project, None


@require_http_methods(["GET", "POST"])
def project_report_shares(request, organization_id, project_id):
    project, error = _owner_access(request, organization_id, project_id)
    if error:
        return error
    if request.method == "GET":
        shares = list(ProjectReportShare.objects.filter(project=project).order_by("-created_at", "-pk")[:51])
        return _response({"shares": [_share_summary(share) for share in shares[:50]], "has_more": len(shares) > 50,
                          "disclosure": "Anyone holding a link can download that report until it expires or is revoked. Already downloaded copies cannot be erased."})
    if not ratelimit.consume(request, action="report_share_create", user=request.user):
        return _error("Too many share requests. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        body = _payload(request, {"report_id", "request_key", "intended_recipient", "expires_hours",
                                  "acknowledge_link_access"})
        share, token = create_report_share(project=project, actor=request.user, report_id=body["report_id"],
            request_key=body["request_key"], recipient_email=body["intended_recipient"],
            expires_hours=body["expires_hours"], acknowledge_link_access=body["acknowledge_link_access"],
            request_id=getattr(request, "request_id", ""))
    except PermissionDenied:
        return _error("Report unavailable for external sharing.", HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Choose one current report, recipient, expiry and acknowledge bearer-link access.",
                      HTTPStatus.CONFLICT)
    payload = {"share": _share_summary(share), "disclosure": "Anyone holding a link can download this report until it expires or is revoked. Already downloaded copies cannot be erased."}
    if token is not None:
        payload["link_path"] = f"/api/reports/shared/{token}/"
    else:
        payload["link_unavailable"] = "This request was already issued; revoke and create a new share if the original link was lost."
    return _response(payload, HTTPStatus.CREATED if token else HTTPStatus.OK)


@require_POST
def project_report_share_revoke(request, organization_id, project_id, share_id):
    project, error = _owner_access(request, organization_id, project_id)
    if error:
        return error
    if not ratelimit.consume(request, action="report_share_revoke", user=request.user):
        return _error("Too many share requests. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        _payload(request, set())
        share = revoke_report_share(project=project, actor=request.user, share_id=share_id,
                                    request_id=getattr(request, "request_id", ""))
    except PermissionDenied:
        return _error("Share not found.", HTTPStatus.NOT_FOUND)
    except ValidationError:
        return _error("Invalid revocation request.", HTTPStatus.BAD_REQUEST)
    return _response({"share": _share_summary(share)})


@require_GET
def shared_report_download(request, token):
    if not ratelimit.consume(request, action="report_share_read"):
        return _error("Too many share requests. Try again later.", HTTPStatus.TOO_MANY_REQUESTS)
    try:
        share, data = read_shared_report(token)
    except PermissionDenied:
        return _error("Shared report unavailable.", HTTPStatus.NOT_FOUND)
    except ValidationError:
        return _error("Shared report unavailable.", HTTPStatus.SERVICE_UNAVAILABLE)
    return report_file_response(share.report, data)
