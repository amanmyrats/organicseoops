import hashlib
import secrets
from datetime import timedelta
from enum import StrEnum

from allauth.account.models import EmailAddress
from allauth.account.internal.flows.reauthentication import did_recently_authenticate
from allauth.usersessions.models import UserSession
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import UserManager
from accounts.staff_access import require_staff_permissions

from .billing_state import paid_access_state
from .models import (
    AutomaticTrialEligibility,
    AuditEvent,
    AuditEventType,
    DomainAlias,
    InvitationProject,
    InvitationState,
    MembershipRole,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    OrganizationTrial,
    PaddleCheckoutAttempt,
    PaddleSubscription,
    OwnershipTransfer,
    Project,
    ProjectConfiguration,
    ProjectMembership,
    ProjectOriginVerification,
    TrialState,
    normalize_origin,
    retained_content_window,
)


class Action(StrEnum):
    VIEW_PROJECT = "view_project"
    LAUNCH_JOB = "launch_job"
    APPROVE = "approve"
    MANAGE_PROJECT = "manage_project"
    CREATE_PROJECT = "create_project"
    MANAGE_PROJECT_ACCESS = "manage_project_access"
    MANAGE_MEMBERS = "manage_members"
    GRANT_PRIVILEGED_ROLE = "grant_privileged_role"
    CREATE_EXTERNAL_SHARE = "create_external_share"
    MANAGE_BILLING = "manage_billing"
    MANAGE_PROVIDER_CREDENTIAL = "manage_provider_credential"
    ORGANIZATION_EXPORT = "organization_export"
    ORGANIZATION_SETTINGS = "organization_settings"


_ACTION_ROLES = {
    Action.VIEW_PROJECT: frozenset(MembershipRole.values),
    Action.LAUNCH_JOB: frozenset({MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.MEMBER}),
    Action.APPROVE: frozenset({MembershipRole.OWNER, MembershipRole.ADMIN}),
    Action.MANAGE_PROJECT: frozenset({MembershipRole.OWNER, MembershipRole.ADMIN}),
    Action.CREATE_PROJECT: frozenset({MembershipRole.OWNER, MembershipRole.ADMIN}),
    Action.MANAGE_PROJECT_ACCESS: frozenset({MembershipRole.OWNER, MembershipRole.ADMIN}),
    Action.MANAGE_MEMBERS: frozenset({MembershipRole.OWNER, MembershipRole.ADMIN}),
    Action.GRANT_PRIVILEGED_ROLE: frozenset({MembershipRole.OWNER}),
    Action.CREATE_EXTERNAL_SHARE: frozenset({MembershipRole.OWNER, MembershipRole.ADMIN}),
    Action.MANAGE_BILLING: frozenset({MembershipRole.OWNER}),
    Action.MANAGE_PROVIDER_CREDENTIAL: frozenset({MembershipRole.OWNER, MembershipRole.ADMIN}),
    Action.ORGANIZATION_EXPORT: frozenset({MembershipRole.OWNER}),
    Action.ORGANIZATION_SETTINGS: frozenset({MembershipRole.OWNER}),
}
_PROJECT_ACTIONS = frozenset({
    Action.VIEW_PROJECT,
    Action.LAUNCH_JOB,
    Action.APPROVE,
    Action.MANAGE_PROJECT,
    Action.MANAGE_PROJECT_ACCESS,
    Action.CREATE_EXTERNAL_SHARE,
})
_PRIVILEGED_ROLES = frozenset({MembershipRole.OWNER, MembershipRole.ADMIN})


class InvitationError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class ConfigurationConflict(Exception):
    pass


class TrialAllowanceError(ValidationError):
    def __init__(self, message, *, code):
        self.code = code
        super().__init__(message, code=code)


ORIGIN_VERIFICATION_PATH = "/.well-known/organicseoops-verification.txt"
TRIAL_OFFER_VERSION = "agency-launch-v1"
TRIAL_DURATION = timedelta(days=30)
TRIAL_EXTENSION_DURATION = timedelta(days=7)
TRIAL_PROJECT_LIMIT = 1
TRIAL_MEMBER_LIMIT = 3
TRIAL_UNIT_LIMIT = 40
PAID_PROJECT_LIMIT = 3
PAID_MEMBER_LIMIT = 10
PAID_UNIT_LIMIT = 100


def active_trial_for_policy(*, organization):
    trial = OrganizationTrial.objects.filter(organization=organization).first()
    now = timezone.now()
    if (
        organization.is_suspended
        or PaddleSubscription.objects.filter(organization=organization).exists()
        or PaddleCheckoutAttempt.objects.filter(organization=organization, paid_verified_at__isnull=False).exists()
        or trial is None
        or trial.state != TrialState.ACTIVE
        or trial.started_at is None
        or trial.ends_at is None
        or not trial.started_at <= now < trial.ends_at
        or (
            trial.offer_version,
            trial.project_limit,
            trial.member_limit,
            trial.unit_limit,
        ) != (
            TRIAL_OFFER_VERSION,
            TRIAL_PROJECT_LIMIT,
            TRIAL_MEMBER_LIMIT,
            TRIAL_UNIT_LIMIT,
        )
    ):
        return None
    original_end = trial.started_at + TRIAL_DURATION
    if trial.ends_at == original_end:
        return trial
    if (
        trial.ends_at == original_end + TRIAL_EXTENSION_DURATION
        and AuditEvent.objects.filter(
            organization=organization,
            event_type=AuditEventType.TRIAL_EXTENDED,
        ).exists()
    ):
        return trial
    return None


def require_entitlement_capacity(*, organization, resource=None):
    trial = active_trial_for_policy(organization=organization)
    if trial is None:
        linked = PaddleSubscription.objects.filter(
            organization=organization, environment=getattr(settings, "PADDLE_ENVIRONMENT", ""),
        ).first()
        state = paid_access_state(linked)
        if organization.is_suspended or state not in {
            "paid_active", "cancellation_scheduled", "payment_grace",
        }:
            code = ("billing_review_hold" if state == "billing_review_hold" else
                    "paid_unavailable" if linked else "trial_unavailable")
            raise TrialAllowanceError("Organization access is unavailable.", code=code)
    if resource is None:
        return
    if resource == "project":
        count = Project.objects.filter(organization=organization).count()
        limit = trial.project_limit if trial else PAID_PROJECT_LIMIT
    elif resource == "member":
        count = OrganizationMembership.objects.filter(organization=organization).count()
        limit = trial.member_limit if trial else PAID_MEMBER_LIMIT
    else:
        raise ValueError("Unknown organization resource.")
    if count >= limit:
        label = "Trial" if trial else "Paid plan"
        raise TrialAllowanceError(f"{label} {resource} limit reached.", code=f"{resource}_limit")


def _require_organization_role(*, organization, user, action):
    if (
        not getattr(user, "is_authenticated", False)
        or not getattr(user, "is_active", False)
    ):
        raise PermissionDenied
    try:
        membership = OrganizationMembership.objects.get(
            organization_id=organization.pk, user_id=user.pk, user__is_active=True,
            organization__is_suspended=False, organization__closed_at__isnull=True,
        )
    except OrganizationMembership.DoesNotExist:
        raise PermissionDenied from None
    if membership.role not in _ACTION_ROLES[action]:
        raise PermissionDenied
    return membership


def require_organization_action(*, organization, user, action):
    if action in _PROJECT_ACTIONS:
        raise PermissionDenied
    membership = _require_organization_role(organization=organization, user=user, action=action)
    if action == Action.ORGANIZATION_EXPORT and not Organization.objects.filter(pk=organization.pk).filter(
        retained_content_window()
    ).exists():
        raise PermissionDenied
    return membership


def require_project_action(*, project, user, action):
    if action not in _PROJECT_ACTIONS:
        raise PermissionDenied
    if not Project.objects.for_user(user).filter(pk=project.pk, organization_id=project.organization_id).exists():
        raise PermissionDenied
    return _require_organization_role(organization=project.organization, user=user, action=action)


def require_owner(*, organization, user):
    return require_organization_action(organization=organization, user=user, action=Action.ORGANIZATION_SETTINGS)


def create_organization(*, user, name):
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=user.pk)
        if not user.is_active or not EmailAddress.objects.filter(user=user, email=user.email, verified=True).exists():
            raise ValidationError("Verify your email address before creating an organization.")
        organization = Organization(name=name, paid_activation_tracking="first-active-observation-v1",
                                    first_audit_tracking="bounded-first-audit-completion-v1",
                                    first_value_tracking="bounded-audit-usefulness-ack-v1")
        organization.full_clean()
        organization.save()
        membership = OrganizationMembership(organization=organization, user=user, role=MembershipRole.OWNER)
        membership.full_clean()
        membership.save()
        now = timezone.now()
        from accounts.identity_retention import has_retained_trial_identity
        automatic = (not AutomaticTrialEligibility.objects.filter(user=user).exists()
                     and not has_retained_trial_identity(user.email, now=now))
        eligibility = None
        if automatic:
            eligibility = AutomaticTrialEligibility(
                user=user,
                organization=organization,
                offer_version=TRIAL_OFFER_VERSION,
                granted_at=now,
            )
            eligibility.full_clean()
            eligibility.save()
        trial = OrganizationTrial(
            organization=organization,
            automatic_eligibility=eligibility,
            offer_version=TRIAL_OFFER_VERSION,
            state=TrialState.ACTIVE if automatic else TrialState.PENDING_REVIEW,
            started_at=now if automatic else None,
            ends_at=now + TRIAL_DURATION if automatic else None,
            project_limit=TRIAL_PROJECT_LIMIT,
            member_limit=TRIAL_MEMBER_LIMIT,
            unit_limit=TRIAL_UNIT_LIMIT,
        )
        trial.full_clean()
        trial.save()
        _audit(
            organization=organization,
            event_type=AuditEventType.TRIAL_GRANTED if automatic else AuditEventType.TRIAL_REVIEW_REQUIRED,
            actor=user,
            subject_user=user,
            details={
                "offer_version": TRIAL_OFFER_VERSION,
                "duration_days": TRIAL_DURATION.days,
                "project_limit": TRIAL_PROJECT_LIMIT,
                "member_limit": TRIAL_MEMBER_LIMIT,
                "unit_limit": TRIAL_UNIT_LIMIT,
            },
        )
    return organization


def _trial_correction_actor(request, actor):
    current = require_staff_permissions(request, permissions=("tenancy.change_organizationtrial",))
    if current.pk != actor.pk:
        raise PermissionDenied
    return current


def _trial_correction_source(trial):
    return {
        "trial": OrganizationTrial.objects.filter(pk=trial.pk).values(
            "id", "organization_id", "automatic_eligibility_id", "offer_version", "state", "started_at", "ends_at",
            "project_limit", "member_limit", "unit_limit", "created_at", "updated_at").first(),
        "organization": Organization.objects.filter(pk=trial.organization_id).values("id", "is_suspended", "closed_at").first(),
        "eligibility": AutomaticTrialEligibility.objects.filter(pk=trial.automatic_eligibility_id).values(
            "id", "user_id", "organization_id", "offer_version", "granted_at").first(),
        "paid": (PaddleSubscription.objects.filter(organization_id=trial.organization_id).exists()
            or PaddleCheckoutAttempt.objects.filter(organization_id=trial.organization_id, paid_verified_at__isnull=False).exists()),
    }


def _finish_trial_correction(*, request, actor, trial, expected):
    if (_trial_correction_source(trial) != expected or expected["paid"]
        or not expected["trial"]["started_at"] <= timezone.now() < expected["trial"]["ends_at"]):
        raise ValidationError("Trial changed during correction.")
    _trial_correction_actor(request, actor)


def approve_organization_trial(*, organization, actor, reason, request, request_id=""):
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 250:
        raise PermissionDenied
    with transaction.atomic():
        actor = _trial_correction_actor(request, actor)
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        trial = OrganizationTrial.objects.select_for_update().filter(organization=organization).first()
        if (
            trial is None
            or organization.is_suspended
            or PaddleSubscription.objects.filter(organization=organization).exists()
            or PaddleCheckoutAttempt.objects.filter(organization=organization, paid_verified_at__isnull=False).exists()
            or trial.state != TrialState.PENDING_REVIEW
            or (
                trial.offer_version,
                trial.project_limit,
                trial.member_limit,
                trial.unit_limit,
            ) != (
                TRIAL_OFFER_VERSION,
                TRIAL_PROJECT_LIMIT,
                TRIAL_MEMBER_LIMIT,
                TRIAL_UNIT_LIMIT,
            )
        ):
            raise ValidationError("Only a pending trial for an active organization can be approved.")
        now = timezone.now()
        expected = _trial_correction_source(trial)
        before = {"state": trial.state, "started_at": None, "ends_at": None}
        trial.state = TrialState.ACTIVE
        trial.started_at = now
        trial.ends_at = now + TRIAL_DURATION
        trial.full_clean()
        trial.save(update_fields=["state", "started_at", "ends_at", "updated_at"])
        expected["trial"].update(state=TrialState.ACTIVE, started_at=now, ends_at=now + TRIAL_DURATION,
            updated_at=trial.updated_at)
        _audit(
            organization=organization,
            event_type=AuditEventType.TRIAL_APPROVED,
            actor=actor,
            details={
                "before": before,
                "after": {
                    "state": trial.state,
                    "started_at": trial.started_at.isoformat(),
                    "ends_at": trial.ends_at.isoformat(),
                },
                "reason": reason.strip(),
                "offer_version": trial.offer_version,
            },
            request_id=request_id,
        )
        _finish_trial_correction(request=request, actor=actor, trial=trial, expected=expected)
    return trial


def extend_organization_trial(*, organization, actor, reason, request, request_id=""):
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 250:
        raise PermissionDenied
    with transaction.atomic():
        actor = _trial_correction_actor(request, actor)
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        trial = OrganizationTrial.objects.select_for_update().filter(organization=organization).first()
        if trial is None or trial.started_at is None or trial.started_at > timezone.now():
            raise ValidationError("Only an eligible trial can be extended.")
        original_end = trial.started_at + TRIAL_DURATION
        extended_end = original_end + TRIAL_EXTENSION_DURATION
        if (
            organization.is_suspended
            or PaddleSubscription.objects.filter(organization=organization).exists()
            or PaddleCheckoutAttempt.objects.filter(organization=organization, paid_verified_at__isnull=False).exists()
            or trial.state not in {TrialState.ACTIVE, TrialState.EXPIRED, TrialState.READ_ONLY}
            or (
                trial.offer_version,
                trial.project_limit,
                trial.member_limit,
                trial.unit_limit,
            ) != (
                TRIAL_OFFER_VERSION,
                TRIAL_PROJECT_LIMIT,
                TRIAL_MEMBER_LIMIT,
                TRIAL_UNIT_LIMIT,
            )
            or trial.ends_at != original_end
            or extended_end <= timezone.now()
            or AuditEvent.objects.filter(
                organization=organization,
                event_type=AuditEventType.TRIAL_EXTENDED,
            ).exists()
        ):
            raise ValidationError("Only an eligible trial can be extended.")
        before = {"state": trial.state, "ends_at": trial.ends_at.isoformat()}
        expected = _trial_correction_source(trial)
        trial.state = TrialState.ACTIVE
        trial.ends_at = extended_end
        trial.full_clean()
        trial.save(update_fields=["state", "ends_at", "updated_at"])
        expected["trial"].update(state=TrialState.ACTIVE, ends_at=extended_end, updated_at=trial.updated_at)
        _audit(
            organization=organization,
            event_type=AuditEventType.TRIAL_EXTENDED,
            actor=actor,
            details={
                "before": before,
                "after": {"state": trial.state, "ends_at": trial.ends_at.isoformat()},
                "reason": reason.strip(),
                "extension_days": TRIAL_EXTENSION_DURATION.days,
                "offer_version": trial.offer_version,
            },
            request_id=request_id,
        )
        _finish_trial_correction(request=request, actor=actor, trial=trial, expected=expected)
    return trial


def update_organization(*, organization, user, name):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=user, action=Action.ORGANIZATION_SETTINGS)
        organization.name = name
        organization.full_clean()
        organization.save(update_fields=["name", "updated_at"])
    return organization


def _normalized_aliases(aliases):
    if not isinstance(aliases, list) or len(aliases) > 50 or any(not isinstance(alias, str) for alias in aliases):
        raise ValidationError("Aliases must be a list of at most 50 origins.")
    normalized = [normalize_origin(alias) for alias in aliases]
    if len(normalized) != len(set(normalized)):
        raise ValidationError("Domain aliases must be unique.")
    return normalized


def _validate_origins(*, organization, canonical_origin, aliases, project=None):
    canonical_origin = normalize_origin(canonical_origin)
    aliases = _normalized_aliases(aliases)
    if canonical_origin in aliases:
        raise ValidationError("A domain alias must differ from the canonical origin.")
    origins = [canonical_origin, *aliases]
    projects = Project.objects.filter(organization=organization, canonical_origin__in=origins)
    domain_aliases = DomainAlias.objects.filter(organization=organization, origin__in=origins)
    if project is not None:
        projects = projects.exclude(pk=project.pk)
        domain_aliases = domain_aliases.exclude(project=project)
    if projects.exists() or domain_aliases.exists():
        raise ValidationError("An origin is already configured in this organization.")
    return canonical_origin, aliases


def create_project(*, organization, user, name, canonical_origin, access_restricted=False, aliases=None):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        membership = require_organization_action(organization=organization, user=user, action=Action.CREATE_PROJECT)
        require_entitlement_capacity(organization=organization, resource="project")
        canonical_origin, aliases = _validate_origins(
            organization=organization,
            canonical_origin=canonical_origin,
            aliases=[] if aliases is None else aliases,
        )
        project = Project(
            organization=organization,
            name=name,
            canonical_origin=canonical_origin,
            access_restricted=access_restricted,
        )
        project.full_clean()
        project.save()
        for origin in aliases:
            DomainAlias.objects.create(organization=organization, project=project, origin=origin)
        if access_restricted and membership.role == MembershipRole.ADMIN:
            ProjectMembership.objects.create(project=project, organization_membership=membership)
    return project


def update_project(
    *,
    project,
    user,
    name=None,
    canonical_origin=None,
    access_restricted=None,
    aliases=None,
    request_id="",
):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().select_related("organization").get(
            pk=project.pk,
            organization=organization,
        )
        membership = require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        desired_aliases = list(project.domain_aliases.values_list("origin", flat=True)) if aliases is None else aliases
        canonical_origin, desired_aliases = _validate_origins(
            organization=organization,
            canonical_origin=project.canonical_origin if canonical_origin is None else canonical_origin,
            aliases=desired_aliases,
            project=project,
        )
        if name is not None:
            project.name = name
        project.canonical_origin = canonical_origin
        previous_access = project.access_restricted
        if access_restricted is not None:
            project.access_restricted = access_restricted
        project.full_clean()
        project.save()
        if project.access_restricted and membership.role == MembershipRole.ADMIN:
            ProjectMembership.objects.get_or_create(project=project, organization_membership=membership)
        if project.access_restricted != previous_access:
            _audit(
                organization=organization,
                project=project,
                event_type=AuditEventType.PROJECT_ACCESS_CHANGED,
                actor=user,
                details={"before": previous_access, "after": project.access_restricted},
                request_id=request_id,
            )
        if aliases is not None:
            project.domain_aliases.all().delete()
            for origin in desired_aliases:
                DomainAlias.objects.create(organization=organization, project=project, origin=origin)
        allowed_origins = {project.canonical_origin, *desired_aliases}
        now = timezone.now()
        for verification in ProjectOriginVerification.objects.select_for_update().filter(
            project=project,
            organization=organization,
        ).exclude(state=ProjectOriginVerification.State.REVOKED).exclude(origin__in=allowed_origins):
            verification.state = ProjectOriginVerification.State.REVOKED
            verification.revoked_at = now
            verification.save(update_fields=["state", "revoked_at", "updated_at"])
            _audit(
                organization=organization,
                project=project,
                event_type=AuditEventType.ORIGIN_VERIFICATION_REVOKED,
                actor=user,
                details={
                    "verification_id": verification.pk,
                    "origin": verification.origin,
                    "reason": "project_scope_changed",
                },
                request_id=request_id,
            )
    return project


def update_project_configuration(*, project, user, expected_revision, changes):
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValidationError("Check the configuration revision.")
    if not isinstance(changes, dict) or set(changes) - ProjectConfiguration.MUTABLE_FIELDS:
        raise ValidationError("Check the configuration fields.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().select_related("organization").get(
            pk=project.pk,
            organization=organization,
        )
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        configuration = ProjectConfiguration.objects.select_for_update().filter(project=project).first()
        current_revision = configuration.revision if configuration else 0
        if expected_revision != current_revision:
            raise ConfigurationConflict
        if configuration is None:
            configuration = ProjectConfiguration(project=project)
        for field, value in changes.items():
            setattr(configuration, field, value)
        configuration.revision = current_revision + 1
        configuration.full_clean()
        configuration.save()
    return configuration


def project_has_origin(project, origin):
    return origin == project.canonical_origin or DomainAlias.objects.filter(
        project=project,
        organization_id=project.organization_id,
        origin=origin,
    ).exists()


def require_passive_security_scope(*, project, user, origin):
    require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
    origin = normalize_origin(origin)
    verification = ProjectOriginVerification.objects.filter(
        organization_id=project.organization_id,
        project=project,
        origin=origin,
        state=ProjectOriginVerification.State.VERIFIED,
        verified_at__isnull=False,
        revoked_at__isnull=True,
    ).first()
    if verification is None or not project_has_origin(project, origin):
        raise PermissionDenied
    return verification


def create_origin_verification(*, project, user, origin, request_id=""):
    origin = normalize_origin(origin)
    challenge = secrets.token_urlsafe(32)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().select_related("organization").get(
            pk=project.pk,
            organization=organization,
        )
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        if not project_has_origin(project, origin):
            raise ValidationError("Choose the project's current domain or alias.")
        verification = ProjectOriginVerification.objects.select_for_update().filter(
            project=project,
            origin=origin,
        ).first()
        if verification is None:
            verification = ProjectOriginVerification(organization=organization, project=project, origin=origin)
        verification.challenge_digest = hashlib.sha256(challenge.encode()).hexdigest()
        verification.state = ProjectOriginVerification.State.PENDING
        verification.verified_at = None
        verification.revoked_at = None
        verification.save()
        _audit(
            organization=organization,
            project=project,
            event_type=AuditEventType.ORIGIN_VERIFICATION_CREATED,
            actor=user,
            details={"verification_id": verification.pk, "origin": origin, "method": verification.method},
            request_id=request_id,
        )
    return verification, challenge


def revoke_origin_verification(*, verification, user, request_id=""):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=verification.organization_id)
        project = Project.objects.select_for_update().select_related("organization").get(
            pk=verification.project_id,
            organization=organization,
        )
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        verification = ProjectOriginVerification.objects.select_for_update().get(
            pk=verification.pk,
            project=project,
            organization=organization,
        )
        if verification.state == ProjectOriginVerification.State.REVOKED:
            return verification, False
        verification.state = ProjectOriginVerification.State.REVOKED
        verification.revoked_at = timezone.now()
        verification.save(update_fields=["state", "revoked_at", "updated_at"])
        _audit(
            organization=organization,
            project=project,
            event_type=AuditEventType.ORIGIN_VERIFICATION_REVOKED,
            actor=user,
            details={"verification_id": verification.pk, "origin": verification.origin},
            request_id=request_id,
        )
    return verification, True


def _project_ids(value):
    if not isinstance(value, list) or len(value) > 100 or any(type(item) is not int for item in value):
        raise ValidationError("Project access must be a list of at most 100 project IDs.")
    if len(value) != len(set(value)):
        raise ValidationError("Project access must not contain duplicates.")
    return value


def _manageable_projects(*, organization, actor, project_ids):
    project_ids = _project_ids(project_ids)
    projects = list(
        Project.objects.for_user(actor)
        .filter(organization=organization, pk__in=project_ids)
        .order_by("pk")
    )
    if len(projects) != len(project_ids):
        raise PermissionDenied
    return projects


def _audit(*, organization, event_type, actor=None, subject_user=None, invitation=None, project=None, details=None, request_id=""):
    return AuditEvent.objects.create(
        organization=organization,
        event_type=event_type,
        actor=actor,
        subject_user=subject_user,
        invitation=invitation,
        project=project,
        details=details or {},
        request_id=request_id or "",
    )


def _can_grant_role(actor_membership, role):
    if actor_membership.role == MembershipRole.OWNER:
        return role in {MembershipRole.ADMIN, MembershipRole.MEMBER, MembershipRole.VIEWER}
    return actor_membership.role == MembershipRole.ADMIN and role in {MembershipRole.MEMBER, MembershipRole.VIEWER}


def create_invitation(*, organization, actor, email, role, project_ids, request_id=""):
    email = UserManager.normalize_email(email)
    token = secrets.token_urlsafe(32)
    now = timezone.now()
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        actor_membership = require_organization_action(
            organization=organization,
            user=actor,
            action=Action.MANAGE_MEMBERS,
        )
        if role not in MembershipRole.values:
            raise ValidationError("Select a valid membership role.")
        if not _can_grant_role(actor_membership, role):
            raise PermissionDenied
        if OrganizationMembership.objects.filter(organization=organization, user__email=email).exists():
            raise ValidationError("This account is already an organization member.")
        expired = list(
            OrganizationInvitation.objects.select_for_update().filter(
                organization=organization,
                email=email,
                state=InvitationState.PENDING,
                expires_at__lte=now,
            )
        )
        for invitation in expired:
            invitation.state = InvitationState.EXPIRED
            invitation.expired_at = now
            invitation.save(update_fields=["state", "expired_at"])
            _audit(
                organization=organization,
                event_type=AuditEventType.INVITATION_EXPIRED,
                actor=actor,
                invitation=invitation,
                request_id=request_id,
            )
        if OrganizationInvitation.objects.filter(
            organization=organization,
            email=email,
            state=InvitationState.PENDING,
        ).exists():
            raise ValidationError("A pending invitation already exists for this address.")
        projects = _manageable_projects(organization=organization, actor=actor, project_ids=project_ids)
        invitation = OrganizationInvitation(
            organization=organization,
            email=email,
            role=role,
            inviter=actor,
            token_digest=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=now + timedelta(days=settings.ORGANIZATION_INVITATION_EXPIRE_DAYS),
        )
        invitation.full_clean()
        invitation.save()
        for project in projects:
            InvitationProject.objects.create(invitation=invitation, project=project)
        _audit(
            organization=organization,
            event_type=AuditEventType.INVITATION_CREATED,
            actor=actor,
            invitation=invitation,
            details={"role": role, "project_ids": project_ids},
            request_id=request_id,
        )
    return invitation, token


def revoke_invitation(*, invitation, actor, request_id=""):
    expired = False
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=invitation.organization_id)
        actor_membership = require_organization_action(
            organization=organization,
            user=actor,
            action=Action.MANAGE_MEMBERS,
        )
        invitation = OrganizationInvitation.objects.select_for_update().get(
            pk=invitation.pk,
            organization=organization,
        )
        if invitation.state == InvitationState.REVOKED:
            return invitation
        if invitation.state != InvitationState.PENDING:
            raise ValidationError("Accepted invitations cannot be revoked.")
        now = timezone.now()
        if invitation.expires_at <= now:
            invitation.state = InvitationState.EXPIRED
            invitation.expired_at = now
            invitation.save(update_fields=["state", "expired_at"])
            _audit(
                organization=organization,
                event_type=AuditEventType.INVITATION_EXPIRED,
                invitation=invitation,
                request_id=request_id,
            )
            expired = True
        if not expired:
            if not _can_grant_role(actor_membership, invitation.role):
                raise PermissionDenied
            invitation.state = InvitationState.REVOKED
            invitation.revoked_by = actor
            invitation.revoked_at = now
            invitation.save(update_fields=["state", "revoked_by", "revoked_at"])
            _audit(
                organization=organization,
                event_type=AuditEventType.INVITATION_REVOKED,
                actor=actor,
                invitation=invitation,
                request_id=request_id,
            )
    if expired:
        raise ValidationError("Expired invitations cannot be revoked.")
    return invitation


def accept_invitation(*, user, token, request_id=""):
    if not isinstance(token, str) or not token or len(token) > 256:
        raise InvitationError("invalid", "Invitation not found.")
    digest = hashlib.sha256(token.encode()).hexdigest()
    organization_id = OrganizationInvitation.objects.filter(token_digest=digest).values_list(
        "organization_id",
        flat=True,
    ).first()
    if organization_id is None:
        raise InvitationError("invalid", "Invitation not found.")
    terminal_error = None
    membership = None
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization_id)
        invitation = OrganizationInvitation.objects.select_for_update().select_related("organization", "inviter").filter(
            token_digest=digest,
            organization=organization,
        ).first()
        if invitation is None:
            raise InvitationError("invalid", "Invitation not found.")
        user = get_user_model().objects.select_for_update().filter(
            pk=user.pk, is_active=True, closed_at__isnull=True).first()
        if user is None:
            raise InvitationError("invalid", "Invitation not found.")
        if organization.is_suspended:
            raise InvitationError("suspended", "This organization is suspended.")
        if invitation.state == InvitationState.ACCEPTED:
            if invitation.accepted_by_id != user.pk:
                raise InvitationError("invalid", "Invitation not found.")
            membership = OrganizationMembership.objects.filter(organization=organization, user=user).first()
            if membership is None:
                raise InvitationError("revoked", "This invitation is no longer available.")
            return membership, invitation, False
        if invitation.state == InvitationState.REVOKED:
            raise InvitationError("revoked", "This invitation is no longer available.")
        if invitation.state == InvitationState.EXPIRED:
            raise InvitationError("expired", "This invitation has expired.")
        now = timezone.now()
        if invitation.expires_at <= now:
            invitation.state = InvitationState.EXPIRED
            invitation.expired_at = now
            invitation.save(update_fields=["state", "expired_at"])
            _audit(
                organization=invitation.organization,
                event_type=AuditEventType.INVITATION_EXPIRED,
                invitation=invitation,
                request_id=request_id,
            )
            terminal_error = InvitationError("expired", "This invitation has expired.")
        elif UserManager.normalize_email(user.email) != invitation.email or not EmailAddress.objects.filter(
            user=user,
            email=invitation.email,
            verified=True,
        ).exists():
            raise InvitationError("wrong_identity", "Sign in with the verified invited email address.")
        else:
            try:
                inviter_membership = require_organization_action(
                    organization=invitation.organization,
                    user=invitation.inviter,
                    action=Action.MANAGE_MEMBERS,
                )
                if not _can_grant_role(inviter_membership, invitation.role):
                    raise PermissionDenied
                grant_ids = list(invitation.project_grants.values_list("project_id", flat=True))
                grant_projects = _manageable_projects(
                    organization=invitation.organization,
                    actor=invitation.inviter,
                    project_ids=grant_ids,
                )
            except PermissionDenied:
                invitation.state = InvitationState.REVOKED
                invitation.revoked_at = now
                invitation.save(update_fields=["state", "revoked_at"])
                _audit(
                    organization=invitation.organization,
                    event_type=AuditEventType.INVITATION_REVOKED,
                    invitation=invitation,
                    request_id=request_id,
                )
                terminal_error = InvitationError("revoked", "This invitation is no longer available.")
            if terminal_error is None:
                membership = OrganizationMembership.objects.filter(
                    organization=invitation.organization,
                    user=user,
                ).first()
                if membership is not None and membership.role != invitation.role:
                    raise InvitationError("conflict", "Your organization membership has changed.")
                try:
                    require_entitlement_capacity(
                        organization=organization,
                        resource="member" if membership is None else None,
                    )
                except TrialAllowanceError as error:
                    raise InvitationError(error.code, error.messages[0]) from None
                if membership is None:
                    membership = OrganizationMembership.objects.create(
                        organization=invitation.organization, user=user, role=invitation.role,
                    )
                for project in grant_projects:
                    ProjectMembership.objects.get_or_create(project=project, organization_membership=membership)
                invitation.state = InvitationState.ACCEPTED
                invitation.accepted_by = user
                invitation.accepted_at = now
                invitation.save(update_fields=["state", "accepted_by", "accepted_at"])
                _audit(
                    organization=invitation.organization,
                    event_type=AuditEventType.INVITATION_ACCEPTED,
                    actor=user,
                    subject_user=user,
                    invitation=invitation,
                    details={"role": invitation.role, "project_ids": grant_ids},
                    request_id=request_id,
                )
    if terminal_error is not None:
        raise terminal_error
    return membership, invitation, True


def update_membership(*, membership, actor, role=None, project_ids=None, request=None, request_id=""):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=membership.organization_id)
        actor_membership = require_organization_action(
            organization=organization,
            user=actor,
            action=Action.MANAGE_MEMBERS,
        )
        membership = OrganizationMembership.objects.select_for_update().select_related("user").get(
            pk=membership.pk,
            organization=organization,
        )
        if membership.role == MembershipRole.OWNER:
            if actor_membership.role != MembershipRole.OWNER or role is None or role == MembershipRole.OWNER:
                raise PermissionDenied
            _recent_authentication(request, actor)
            if not _another_active_owner(organization, membership.user):
                raise ValidationError("Transfer ownership before demoting the last active owner.")
        if actor_membership.role == MembershipRole.ADMIN and membership.role in _PRIVILEGED_ROLES:
            raise PermissionDenied
        if role is not None:
            if role not in MembershipRole.values:
                raise ValidationError("Select a valid membership role.")
            if not _can_grant_role(actor_membership, role):
                raise PermissionDenied
        desired_role = membership.role if role is None else role
        if project_ids is not None and desired_role != MembershipRole.OWNER:
            projects = _manageable_projects(organization=organization, actor=actor, project_ids=project_ids)
        else:
            projects = []
        if desired_role != membership.role:
            previous = membership.role
            membership.role = desired_role
            membership.full_clean()
            membership.save(update_fields=["role"])
            _audit(
                organization=organization,
                event_type=AuditEventType.MEMBERSHIP_ROLE_CHANGED,
                actor=actor,
                subject_user=membership.user,
                details={"before": previous, "after": desired_role},
                request_id=request_id,
            )
        if project_ids is not None or desired_role == MembershipRole.OWNER:
            before = set(membership.project_memberships.values_list("project_id", flat=True))
            after = {project.pk for project in projects}
            if actor_membership.role == MembershipRole.ADMIN and desired_role != MembershipRole.OWNER:
                manageable = set(Project.objects.for_user(actor).filter(organization=organization).values_list("pk", flat=True))
                after |= before - manageable
            if before != after:
                membership.project_memberships.exclude(project_id__in=after).delete()
                for project in projects:
                    ProjectMembership.objects.get_or_create(project=project, organization_membership=membership)
                _audit(
                    organization=organization,
                    event_type=AuditEventType.PROJECT_ACCESS_CHANGED,
                    actor=actor,
                    subject_user=membership.user,
                    details={"before": sorted(before), "after": sorted(after)},
                    request_id=request_id,
                )
    return membership


def remove_membership(*, membership, actor, request=None, request_id=""):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=membership.organization_id)
        actor_membership = require_organization_action(
            organization=organization,
            user=actor,
            action=Action.MANAGE_MEMBERS,
        )
        membership = OrganizationMembership.objects.select_for_update().select_related("user").get(
            pk=membership.pk,
            organization=organization,
        )
        if membership.role == MembershipRole.OWNER:
            if actor_membership.role != MembershipRole.OWNER:
                raise PermissionDenied
            _recent_authentication(request, actor)
            if not _another_active_owner(organization, membership.user):
                raise ValidationError("Transfer ownership before removing the last active owner.")
        if actor_membership.role == MembershipRole.ADMIN and membership.role in _PRIVILEGED_ROLES:
            raise PermissionDenied
        subject = membership.user
        previous_role = membership.role
        membership.delete()
        OwnershipTransfer.objects.filter(organization=organization, state=OwnershipTransfer.State.PENDING).filter(
            Q(from_user=subject) | Q(to_user=subject)
        ).update(state=OwnershipTransfer.State.CANCELLED)
        _audit(
            organization=organization,
            event_type=AuditEventType.MEMBERSHIP_REMOVED,
            actor=actor,
            subject_user=subject,
            details={"role": previous_role},
            request_id=request_id,
        )
        pending = list(OrganizationInvitation.objects.select_for_update().filter(
            organization=organization,
            inviter=subject,
            state=InvitationState.PENDING,
        ))
        now = timezone.now()
        for invitation in pending:
            invitation.state = InvitationState.REVOKED
            invitation.revoked_at = now
            invitation.save(update_fields=["state", "revoked_at"])
            _audit(
                organization=organization,
                event_type=AuditEventType.INVITATION_REVOKED,
                actor=actor,
                invitation=invitation,
                request_id=request_id,
            )
    return subject


def _recent_authentication(request, user):
    if request is None or request.user.pk != user.pk or not user.is_active or not did_recently_authenticate(request):
        raise PermissionDenied("Reauthenticate before changing ownership.")


def _another_active_owner(organization, user):
    return OrganizationMembership.objects.filter(
        organization=organization, role=MembershipRole.OWNER, user__is_active=True,
    ).exclude(user=user).exists()


def propose_ownership_transfer(*, organization, actor, target, request, request_id=""):
    _recent_authentication(request, actor)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.GRANT_PRIVILEGED_ROLE)
        target = get_user_model().objects.get(pk=target.pk)
        if (
            actor.pk == target.pk
            or not target.is_active
            or not EmailAddress.objects.filter(user=target, email=target.email, verified=True).exists()
            or not OrganizationMembership.objects.filter(organization=organization, user=target).exclude(role=MembershipRole.OWNER).exists()
        ):
            raise ValidationError("Choose an active verified existing non-owner member.")
        if OwnershipTransfer.objects.filter(organization=organization, state=OwnershipTransfer.State.PENDING).exists():
            raise ValidationError("An ownership transfer is already pending.")
        transfer = OwnershipTransfer.objects.create(organization=organization, from_user=actor, to_user=target)
        _audit(organization=organization, event_type=AuditEventType.OWNERSHIP_PROPOSED,
               actor=actor, subject_user=target, details={"from_user_id": actor.pk, "to_user_id": target.pk},
               request_id=request_id)
    return transfer


def accept_ownership_transfer(*, transfer, user, request, request_id=""):
    _recent_authentication(request, user)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=transfer.organization_id)
        transfer = OwnershipTransfer.objects.select_for_update().get(pk=transfer.pk, organization=organization)
        if transfer.state != OwnershipTransfer.State.PENDING or transfer.to_user_id != user.pk:
            raise PermissionDenied
        require_organization_action(organization=organization, user=transfer.from_user,
                                    action=Action.GRANT_PRIVILEGED_ROLE)
        if not get_user_model().objects.filter(pk=user.pk, is_active=True).exists() or not EmailAddress.objects.filter(
            user=user, email=user.email, verified=True,
        ).exists():
            raise PermissionDenied
        target = OrganizationMembership.objects.select_for_update().filter(organization=organization, user=user).first()
        source = OrganizationMembership.objects.select_for_update().get(organization=organization, user=transfer.from_user)
        if target is None or target.role == MembershipRole.OWNER or source.role != MembershipRole.OWNER:
            raise PermissionDenied
        target.role = MembershipRole.OWNER
        target.save(update_fields=["role"])
        source.role = MembershipRole.ADMIN
        source.save(update_fields=["role"])
        granted = []
        for project in Project.objects.filter(organization=organization, access_restricted=True):
            _, created = ProjectMembership.objects.get_or_create(project=project, organization_membership=source)
            if created:
                granted.append(project.pk)
        if granted:
            _audit(organization=organization, event_type=AuditEventType.PROJECT_ACCESS_CHANGED,
                   actor=user, subject_user=source.user, details={"granted_project_ids": granted},
                   request_id=request_id)
        transfer.state = OwnershipTransfer.State.ACCEPTED
        transfer.accepted_at = timezone.now()
        transfer.save(update_fields=["state", "accepted_at"])
        _audit(organization=organization, event_type=AuditEventType.OWNERSHIP_ACCEPTED,
               actor=user, subject_user=user,
               details={"from_user_id": source.user_id, "to_user_id": user.pk, "before": "admin", "after": "owner"},
               request_id=request_id)
    return transfer


def cancel_ownership_transfer(*, transfer, user, request, request_id=""):
    _recent_authentication(request, user)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=transfer.organization_id)
        transfer = OwnershipTransfer.objects.select_for_update().get(pk=transfer.pk, organization=organization)
        if (transfer.state != OwnershipTransfer.State.PENDING
                or user.pk not in {transfer.from_user_id, transfer.to_user_id}):
            raise PermissionDenied
        if (organization.is_suspended
                or not get_user_model().objects.filter(pk=user.pk, is_active=True).exists()
                or not OrganizationMembership.objects.filter(organization=organization, user=user).exists()):
            raise PermissionDenied
        transfer.state = OwnershipTransfer.State.CANCELLED
        transfer.save(update_fields=["state"])
        _audit(organization=organization, event_type=AuditEventType.OWNERSHIP_CANCELLED,
               actor=user, subject_user=transfer.to_user,
               details={"from_user_id": transfer.from_user_id, "to_user_id": transfer.to_user_id},
               request_id=request_id)
    return transfer


def leave_organization(*, organization, user, request, request_id=""):
    _recent_authentication(request, user)
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        if organization.is_suspended or not user.is_active:
            raise PermissionDenied
        membership = OrganizationMembership.objects.select_for_update().get(organization=organization, user=user)
        if membership.role == MembershipRole.OWNER and not _another_active_owner(organization, user):
            raise ValidationError("Transfer ownership or close this organization before leaving.")
        role = membership.role
        membership.delete()
        OwnershipTransfer.objects.filter(organization=organization, state=OwnershipTransfer.State.PENDING).filter(
            Q(from_user=user) | Q(to_user=user)
        ).update(state=OwnershipTransfer.State.CANCELLED)
        _audit(organization=organization, event_type=AuditEventType.MEMBERSHIP_LEFT, actor=user,
               subject_user=user, details={"role": role}, request_id=request_id)
        now = timezone.now()
        for invitation in OrganizationInvitation.objects.select_for_update().filter(
            organization=organization, inviter=user, state=InvitationState.PENDING,
        ):
            invitation.state = InvitationState.REVOKED
            invitation.revoked_at = now
            invitation.save(update_fields=["state", "revoked_at"])
            _audit(organization=organization, event_type=AuditEventType.INVITATION_REVOKED,
                   actor=user, invitation=invitation, request_id=request_id)


def set_organization_suspension(*, organization, actor, suspended, reason, request_id=""):
    if (not actor.is_active or not actor.is_staff or not actor.has_perm("tenancy.change_organization")
            or type(suspended) is not bool or not isinstance(reason, str) or not reason.strip()):
        raise PermissionDenied
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        if organization.closed_at is not None:
            raise ValidationError("Closed organizations cannot be reactivated as suspensions.")
        previous = organization.is_suspended
        if previous != suspended:
            organization.is_suspended = suspended
            organization.save(update_fields=["is_suspended", "updated_at"])
            _audit(organization=organization, event_type=AuditEventType.ORGANIZATION_SUSPENDED,
                   actor=actor, details={"before": previous, "after": suspended, "reason": reason.strip()[:250]},
                   request_id=request_id)
    return organization


def set_user_suspension(*, user, actor, suspended, reason, request_id=""):
    if (not actor.is_active or not actor.is_staff or not actor.has_perm("accounts.change_user")
            or actor.pk == user.pk or (user.is_superuser and not actor.is_superuser)
            or type(suspended) is not bool or not isinstance(reason, str) or not reason.strip()):
        raise PermissionDenied
    with transaction.atomic():
        organizations = list(Organization.objects.select_for_update().filter(memberships__user=user).order_by("pk"))
        user = get_user_model().objects.select_for_update().get(pk=user.pk)
        if user.closed_at is not None:
            raise ValidationError("Closed personal accounts cannot be reactivated by suspension recovery.")
        if suspended and user.is_active and any(
            OrganizationMembership.objects.filter(organization=org, user=user, role=MembershipRole.OWNER).exists()
            and not _another_active_owner(org, user) for org in organizations
        ):
            raise ValidationError("Transfer ownership before suspending the last active owner.")
        if user.is_active == suspended:
            previous = user.is_active
            user.is_active = not suspended
            user.session_version = secrets.token_hex(16)
            user.save(update_fields=["is_active", "session_version"])
            if suspended:
                for session in UserSession.objects.filter(user=user):
                    session.end()
            _audit(organization=None, event_type=AuditEventType.USER_SUSPENDED,
                   actor=actor, subject_user=user,
                   details={"before": previous, "after": user.is_active, "reason": reason.strip()[:250]},
                   request_id=request_id)
    return user
