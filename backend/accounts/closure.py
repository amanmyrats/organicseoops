"""Separate irreversible access shutdown and reviewed account-identity cleanup."""
import secrets

from allauth.usersessions.internal.flows.sessions import end_sessions
from allauth.usersessions.models import UserSession
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import AuditEvent, AuditEventType, OrganizationMembership
from tenancy.services import _recent_authentication


def close_personal_access(*, actor, request):
    _recent_authentication(request, actor)
    with transaction.atomic():
        organization_ids = list(OrganizationMembership.objects.filter(user=actor).values_list(
            "organization_id", flat=True).order_by("organization_id"))
        from tenancy.models import Organization
        list(Organization.objects.select_for_update().filter(pk__in=organization_ids).order_by("pk"))
        user = get_user_model().objects.select_for_update().get(pk=actor.pk)
        if not user.is_active or user.is_staff or user.is_superuser or user.closed_at is not None:
            raise PermissionDenied
        if OrganizationMembership.objects.filter(user=user, organization__closed_at__isnull=True).exists():
            raise ValidationError("Leave or transfer active organizations before closing personal access.")
        user.closed_at = timezone.now()
        user.is_active = False
        user.session_version = secrets.token_hex(16)
        user.set_unusable_password()
        user.first_name = user.last_name = ""
        user.save(update_fields=["closed_at", "is_active", "session_version", "password",
                                  "first_name", "last_name"])
        _clear_personal_resources(user)
        AuditEvent.objects.create(actor=user, subject_user=user, event_type=AuditEventType.ACCOUNT_CLOSED,
            details={"state": "access_revoked", "retained_identity": "restricted_trial_and_audit_review"})
        sessions = list(UserSession.objects.filter(user=user))
        transaction.on_commit(lambda: end_sessions(request, sessions))
        return user


def _clear_personal_resources(user):
    from jobs.models import (ProjectAlertDelivery, ProjectAlertEpisodeClaim, ProjectAlertPreference,
                             ProjectCruxAlertPreference, ProjectCruxAlertDelivery, ProjectCruxEpisodeClaim,
                             ProjectSummaryDelivery, ProjectSummaryPreference)
    from tenancy.models import SupportRequest, SupportRequestUpdate
    ProjectCruxEpisodeClaim.objects.filter(recipient=user).delete()
    ProjectCruxAlertDelivery.objects.filter(recipient=user).delete()
    ProjectAlertEpisodeClaim.objects.filter(recipient=user).delete()
    ProjectAlertDelivery.objects.filter(recipient=user).delete()
    ProjectSummaryDelivery.objects.filter(recipient=user).delete()
    ProjectSummaryPreference.objects.filter(user=user).delete()
    ProjectAlertPreference.objects.filter(user=user).delete()
    ProjectCruxAlertPreference.objects.filter(user=user).delete()
    SupportRequestUpdate.objects.filter(request__requester=user).delete()
    SupportRequest.objects.filter(requester=user).delete()


def erase_closed_account_identity(*, request, user_id, policy_reference):
    """Clean only the account; independent organization content and restricted lineage remain."""
    from allauth.account.models import EmailAddress
    from allauth.mfa.models import Authenticator
    from .identity_retention import identity_digest, reviewed_identity_policy
    from .models import RetainedTrialIdentity
    from .staff_access import require_staff_permissions
    from tenancy.models import AutomaticTrialEligibility, Organization, OrganizationNotice

    if type(user_id) is not int or not 1 <= user_id <= 2**53 - 1:
        raise ValidationError("Choose one exact closed account.")
    with transaction.atomic():
        actor = require_staff_permissions(request, permissions=("accounts.change_user",))
        policy = reviewed_identity_policy()
        reference, duration, key, key_id = policy
        if policy_reference != reference:
            raise ValidationError("Acknowledge the current reviewed policy reference.")
        list(Organization.objects.select_for_update().filter(memberships__user_id=user_id).order_by("pk"))
        user = get_user_model().objects.select_for_update().get(pk=user_id)
        now = timezone.now()
        if (user.is_active or user.is_staff or user.is_superuser or user.closed_at is None
            or user.closed_at > now or OrganizationMembership.objects.filter(
                user=user, organization__closed_at__isnull=True).exists()):
            raise ValidationError("Close personal access and leave active organizations before identity cleanup.")
        if user.identity_erased_at is not None:
            return user
        addresses = list(EmailAddress.objects.select_for_update().filter(user=user))
        if AutomaticTrialEligibility.objects.filter(user=user).exists():
            verified = {address.email for address in addresses if address.verified}
            if not verified:
                raise ValidationError("Reconcile verified trial identity before cleanup.")
            if RetainedTrialIdentity.objects.filter(expires_at__gt=now).exclude(key_id=key_id).exists():
                raise ValidationError("Reconcile retained identity keys before cleanup.")
            try:
                expires_at = now + duration
            except OverflowError as exc:
                raise ValidationError("Identity-retention duration is invalid.") from exc
            for email in verified:
                retained, created = RetainedTrialIdentity.objects.get_or_create(
                    digest=identity_digest(email, key), defaults={"key_id": key_id,
                        "policy_reference": reference, "expires_at": expires_at})
                if not created and retained.expires_at < expires_at:
                    retained.key_id, retained.policy_reference, retained.expires_at = key_id, reference, expires_at
                    retained.save(update_fields=["key_id", "policy_reference", "expires_at"])
        _clear_personal_resources(user)
        OrganizationNotice.objects.filter(recipient=user).delete()
        for session in UserSession.objects.filter(user=user):
            session.end()
        Authenticator.objects.filter(user=user).delete()
        EmailAddress.objects.filter(user=user).delete()  # Includes confirmation/mail/suppression children.
        user.groups.clear()
        user.user_permissions.clear()
        user.email = f"closed-{secrets.token_hex(16)}@accounts.invalid"
        user.first_name = user.last_name = ""
        user.first_email_verified_at = user.registration_origin = user.last_login = None
        user.session_version = secrets.token_hex(16)
        user.set_unusable_password()
        user.identity_erased_at = now
        user.save(update_fields=["email", "first_name", "last_name", "first_email_verified_at", "registration_origin",
                                 "last_login", "session_version", "password", "identity_erased_at"])
        AuditEvent.objects.create(actor=actor, subject_user=user, event_type=AuditEventType.ACCOUNT_CLOSED,
            details={"state": "account_identity_erased", "policy_reference": reference,
                     "restricted_lineage": "retained", "independent_organization_content": "unchanged",
                     "trial_identity_retention_days": duration.days})
        require_staff_permissions(request, permissions=("accounts.change_user",))
        if reviewed_identity_policy() != policy:
            raise ValidationError("Identity cleanup policy changed during execution.")
        return user
