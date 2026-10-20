"""Explicit expiring bearer shares for one immutable private report."""
from datetime import timedelta
from hashlib import sha256
import re
from secrets import token_urlsafe

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from tenancy.models import AuditEvent, AuditEventType, Organization, Project
from tenancy.services import Action, require_project_action

from .models import ProjectReportShare, ProjectReportSnapshot
from .usage import UsageLimitError, require_billable_access
from .reporting import read_project_report, require_ordinary_report_findings


def create_report_share(*, project, actor, report_id, request_key, recipient_email, expires_hours,
                        acknowledge_link_access, request_id=""):
    if (type(report_id) is not int or report_id < 1
        or type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key)
        or type(recipient_email) is not str or len(recipient_email) > 254
        or type(expires_hours) is not int or not 1 <= expires_hours <= 168
        or acknowledge_link_access is not True):
        raise ValidationError("Disclose the recipient, bearer-link risk and bounded expiry before sharing.")
    try:
        validate_email(recipient_email)
    except ValidationError:
        raise ValidationError("Choose a valid intended recipient.") from None
    recipient_email = recipient_email.strip().lower()
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.CREATE_EXTERNAL_SHARE)
        try:
            require_billable_access(organization=organization)
        except UsageLimitError:
            raise PermissionDenied from None
        report = ProjectReportSnapshot.objects.filter(pk=report_id, project=project).first()
        if report is None:
            raise PermissionDenied
        require_ordinary_report_findings(project, report.finding_ids)
        existing = ProjectReportShare.objects.filter(project=project, request_key=request_key).first()
        if existing:
            if (existing.report_id != report.pk or existing.creator_id != actor.pk
                or existing.intended_recipient != recipient_email):
                raise ValidationError("Share request key belongs to a different report or recipient.")
            return existing, None  # Never replay a bearer token after an uncertain response.
        now = timezone.now()
        if ProjectReportShare.objects.filter(project=project, revoked_at__isnull=True, expires_at__gt=now).count() >= 10:
            raise ValidationError("Review or revoke existing active shares before issuing another.")
        token = token_urlsafe(32)
        share = ProjectReportShare.objects.create(project=project, report=report, creator=actor,
            request_key=request_key, token_digest=sha256(token.encode()).hexdigest(),
            intended_recipient=recipient_email, expires_at=now + timedelta(hours=expires_hours),
            disclosure_confirmed_at=now)
        AuditEvent.objects.create(organization=organization, project=project, actor=actor,
            event_type=AuditEventType.REPORT_SHARE_CREATED, request_id=request_id,
            details={"share_id": share.pk, "report_id": report.pk, "expires_at": share.expires_at.isoformat()})
        return share, token


def revoke_report_share(*, project, actor, share_id, request_id=""):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.CREATE_EXTERNAL_SHARE)
        share = ProjectReportShare.objects.select_for_update().filter(pk=share_id, project=project).first()
        if share is None:
            raise PermissionDenied
        if share.revoked_at is not None:
            return share
        share.revoked_at = timezone.now()
        share.save(update_fields=["revoked_at"])
        AuditEvent.objects.create(organization=organization, project=project, actor=actor,
            event_type=AuditEventType.REPORT_SHARE_REVOKED, request_id=request_id,
            details={"share_id": share.pk, "report_id": share.report_id})
        return share


def _current_report_share(token_digest):
    share = ProjectReportShare.objects.select_related("project__organization", "report", "creator").filter(
        token_digest=token_digest, revoked_at__isnull=True,
        expires_at__gt=timezone.now()).first()
    if share is None or share.report.project_id != share.project_id:
        raise PermissionDenied
    try:
        require_project_action(project=share.project, user=share.creator, action=Action.CREATE_EXTERNAL_SHARE)
        require_billable_access(organization=share.project.organization)
    except (PermissionDenied, UsageLimitError):
        raise PermissionDenied from None
    return share


def read_shared_report(token):
    if type(token) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise PermissionDenied
    digest = sha256(token.encode()).hexdigest()
    share = _current_report_share(digest)
    data = read_project_report(project=share.project, actor=share.creator, snapshot=share.report)
    final = _current_report_share(digest)
    if (final.pk, final.project_id, final.report_id, final.creator_id) != (share.pk, share.project_id, share.report_id, share.creator_id):
        raise PermissionDenied
    return final, data
