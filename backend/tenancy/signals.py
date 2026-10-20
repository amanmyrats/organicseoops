import secrets
import logging

from allauth.account.internal.flows.login import record_authentication
from allauth.account.signals import email_changed, email_confirmed, password_changed, password_reset, user_logged_in, user_logged_out
from allauth.mfa.models import Authenticator
from allauth.mfa.signals import (
    authenticator_added,
    authenticator_removed,
    authenticator_reset,
    authenticator_used,
)
from allauth.usersessions.models import UserSession
from django.contrib.auth import update_session_auth_hash
from django.db import transaction
from django.dispatch import receiver

from .models import AuditEvent, AuditEventType

logger = logging.getLogger("organicseoops.security")


def _audit_account(request, user, event_type):
    if user is None or not user.pk:
        return
    try:
        with transaction.atomic():
            AuditEvent.objects.create(event_type=event_type, actor=user, subject_user=user,
                request_id=getattr(request, "_organicseoops_request_id", ""))
    except Exception:
        # Audit storage failure must not interrupt password/session revocation.
        logger.error("account.security_audit_failed")


@receiver([user_logged_in, user_logged_out, password_changed, password_reset],
          dispatch_uid="tenancy.audit_account_security")
def audit_account_security(sender, request, user, signal, **kwargs):
    event_type = {
        user_logged_in: AuditEventType.ACCOUNT_LOGGED_IN,
        user_logged_out: AuditEventType.ACCOUNT_LOGGED_OUT,
        password_changed: AuditEventType.ACCOUNT_PASSWORD_CHANGED,
        password_reset: AuditEventType.ACCOUNT_PASSWORD_RESET,
    }[signal]
    _audit_account(request, user, event_type)


@receiver(email_confirmed, dispatch_uid="tenancy.audit_account_email_verified")
def audit_account_email_verified(sender, request, email_address, **kwargs):
    _audit_account(request, email_address.user, AuditEventType.ACCOUNT_EMAIL_VERIFIED)


@receiver(email_changed, dispatch_uid="tenancy.audit_account_email_changed")
def audit_account_email_changed(sender, request, user, from_email_address, to_email_address, **kwargs):
    if from_email_address is not None and from_email_address.email != to_email_address.email:
        _audit_account(request, user, AuditEventType.ACCOUNT_EMAIL_CHANGED)


def _audit(request, user, event_type, authenticator):
    if not user.is_staff:
        return
    try:
        AuditEvent.objects.create(
            event_type=event_type,
            actor=user,
            subject_user=user,
            details={"authenticator_type": authenticator.type},
            request_id=getattr(request, "_organicseoops_request_id", ""),
        )
    except Exception:
        logger.exception("staff_mfa.audit_failed", extra={"audit_event_type": event_type})


def _revoke_other_sessions(request, user):
    user.session_version = secrets.token_hex(16)
    user.save(update_fields=["session_version"])
    update_session_auth_hash(request, user)
    for session in UserSession.objects.filter(user=user).exclude(session_key=request.session.session_key):
        try:
            session.end()
        except Exception:
            logger.exception("staff_mfa.tracked_session_cleanup_failed")


@receiver(authenticator_added, dispatch_uid="tenancy.audit_staff_mfa_added")
def audit_staff_mfa_added(sender, request, user, authenticator, **kwargs):
    if user.is_staff and authenticator.type == Authenticator.Type.TOTP:
        record_authentication(
            request,
            user,
            method="mfa",
            id=authenticator.pk,
            type=authenticator.type,
        )
        _revoke_other_sessions(request, user)
    _audit(request, user, AuditEventType.STAFF_MFA_ADDED, authenticator)


@receiver(authenticator_removed, dispatch_uid="tenancy.audit_staff_mfa_removed")
def audit_staff_mfa_removed(sender, request, user, authenticator, **kwargs):
    _audit(request, user, AuditEventType.STAFF_MFA_REMOVED, authenticator)


@receiver(authenticator_reset, dispatch_uid="tenancy.audit_staff_mfa_reset")
def audit_staff_mfa_reset(sender, request, user, authenticator, **kwargs):
    if user.is_staff:
        _revoke_other_sessions(request, user)
    _audit(request, user, AuditEventType.STAFF_MFA_RECOVERY_RESET, authenticator)


@receiver(authenticator_used, dispatch_uid="tenancy.audit_staff_mfa_recovery_used")
def audit_staff_mfa_recovery_used(sender, request, user, authenticator, **kwargs):
    if authenticator.type == Authenticator.Type.RECOVERY_CODES:
        _audit(request, user, AuditEventType.STAFF_MFA_RECOVERY_USED, authenticator)
