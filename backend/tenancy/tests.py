from tenancy.customer_artifact_barrier import project_artifact_barrier
import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from allauth.usersessions.models import UserSession
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.artifacts import ArtifactValidationError, save_private_artifact
from config.test_foundations import TEST_STORAGES
from jobs.models import JobRun, UsageReservation

from .artifacts import (list_project_artifact_keys, project_artifact_scope,
                        read_project_artifact, save_project_artifact)
from .models import (
    AutomaticTrialEligibility,
    AuditEvent,
    AuditEventType,
    DomainAlias,
    InvitationState,
    MembershipRole,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    OrganizationTrial,
    PaddleEnvironment,
    PaddleStatus,
    PaddleSubscription,
    OwnershipTransfer,
    Project,
    ProjectConfiguration,
    ProjectMembership,
    TrialState,
    normalize_origin,
)
from .services import (
    Action,
    ConfigurationConflict,
    InvitationError,
    TrialAllowanceError,
    accept_invitation,
    approve_organization_trial,
    create_invitation,
    create_organization,
    create_project,
    extend_organization_trial,
    leave_organization,
    propose_ownership_transfer,
    require_organization_action,
    require_project_action,
    set_organization_suspension,
    set_user_suspension,
    update_membership,
    remove_membership,
    update_project,
    update_project_configuration,
)

from .test_trial_corrections import staff_trial_request

User = get_user_model()


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "tenancy-tests"}},
    SECURE_SSL_REDIRECT=False,
    STORAGES=TEST_STORAGES,
    ARTIFACT_MAX_BYTES=1024,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/plain"}),
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class TenancyTests(TransactionTestCase):
    session_url = "/_allauth/browser/v1/auth/session"

    def setUp(self):
        dispatch = patch("jobs.tasks.execute_job_task.apply_async", return_value=None)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        cache.clear()
        self.password = f"A-{secrets.token_urlsafe(24)}"
        self.owner = self.create_user("owner@example.com")
        self.outsider = self.create_user("outsider@example.com")
        self.member = self.create_user("member@example.com")
        self.other_member = self.create_user("other-member@example.com")
        self.staff = self.create_user("staff@example.com", is_staff=True, is_superuser=True)
        self.organization = create_organization(user=self.owner, name="Primary organization")
        self.other_organization = create_organization(user=self.outsider, name="Other organization")
        self.member_record = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.member,
            role=MembershipRole.MEMBER,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.other_member,
            role=MembershipRole.VIEWER,
        )
        self.open_project = create_project(
            organization=self.organization,
            user=self.owner,
            name="Open project",
            canonical_origin="https://open.example.com",
            aliases=["https://www.open.example.com"],
        )
        self.restricted_project = Project.objects.create(
            organization=self.organization,
            name="Restricted project",
            canonical_origin="https://restricted.example.com",
            access_restricted=True,
        )
        ProjectMembership.objects.create(
            project=self.restricted_project,
            organization_membership=self.member_record,
        )

    def create_user(self, email, **fields):
        user = User.objects.create_user(email=email, password=self.password, **fields)
        EmailAddress.objects.create(user=user, email=email, verified=True, primary=True)
        return user

    def client_for(self, user):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        response = client.get(self.session_url, secure=True)
        self.assertEqual(response.status_code, 200)
        return client

    def request(self, client, method, path, payload=None, *, csrf=True):
        headers = {"HTTP_REFERER": "https://testserver/"}
        if csrf:
            headers["HTTP_X_CSRFTOKEN"] = client.cookies["csrftoken"].value
        kwargs = {"secure": True, **headers}
        if payload is not None:
            kwargs.update(data=json.dumps(payload), content_type="application/json")
        return getattr(client, method)(path, **kwargs)

    def trial_client(self):
        client = self.client_for(self.staff)
        staff_trial_request(self.staff, client)
        return client

    def test_closed_organization_denies_existing_members_projects_and_staff_reactivation(self):
        self.assertTrue(Organization.objects.for_user(self.owner).filter(pk=self.organization.pk).exists())
        self.organization.closed_at = timezone.now()
        self.organization.is_suspended = True
        self.organization.save(update_fields=["closed_at", "is_suspended"])
        self.assertFalse(Organization.objects.for_user(self.owner).filter(pk=self.organization.pk).exists())
        self.assertFalse(Project.objects.for_user(self.owner).filter(pk=self.open_project.pk).exists())
        self.assertTrue(Organization.objects.for_user(self.outsider).filter(pk=self.other_organization.pk).exists())
        with self.assertRaises(PermissionDenied):
            require_project_action(project=self.open_project, user=self.owner, action=Action.VIEW_PROJECT)
        with self.assertRaises(PermissionDenied):
            require_organization_action(organization=self.organization, user=self.owner,
                                        action=Action.ORGANIZATION_EXPORT)
        with self.assertRaises(ValidationError):
            set_organization_suspension(organization=self.organization, actor=self.staff, suspended=False,
                                        reason="Cannot reopen a closed tenant")
        self.organization.is_suspended = False
        with self.assertRaises(ValidationError):
            self.organization.save(update_fields=["is_suspended"])
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Organization.objects.filter(pk=self.organization.pk).update(is_suspended=False)
        self.assertEqual(self.client_for(self.owner).get(
            f"/api/organizations/{self.organization.pk}/projects/{self.open_project.pk}/", secure=True).status_code, 404)

    def test_project_and_owner_export_access_stop_at_retention_boundary_without_hiding_billing(self):
        trial_end = self.organization.trial.ends_at
        for instant, allowed in ((trial_end + timedelta(days=90, microseconds=-1), True),
                                 (trial_end + timedelta(days=90), False)):
            with self.subTest(instant=instant), patch("tenancy.models.timezone.now", return_value=instant):
                self.assertEqual(Project.objects.for_user(self.owner).filter(pk=self.open_project.pk).exists(), allowed)
                self.assertTrue(Organization.objects.for_user(self.owner).filter(pk=self.organization.pk).exists())
                if allowed:
                    require_project_action(project=self.open_project, user=self.owner, action=Action.VIEW_PROJECT)
                    require_organization_action(organization=self.organization, user=self.owner,
                                                action=Action.ORGANIZATION_EXPORT)
                else:
                    with self.assertRaises(PermissionDenied):
                        require_project_action(project=self.open_project, user=self.owner,
                                               action=Action.VIEW_PROJECT)
                    with self.assertRaises(PermissionDenied):
                        require_organization_action(organization=self.organization, user=self.owner,
                                                    action=Action.ORGANIZATION_EXPORT)
                require_organization_action(organization=self.organization, user=self.owner,
                                            action=Action.MANAGE_BILLING)
        self.assertTrue(Organization.objects.for_user(self.outsider).filter(
            pk=self.other_organization.pk).exists())

    @override_settings(PADDLE_ENVIRONMENT="sandbox")
    def test_verified_paid_lapse_overrides_old_trial_without_resetting_retention(self):
        future = self.organization.trial.ends_at + timedelta(days=120)
        subscription = PaddleSubscription.objects.create(
            organization=self.organization, environment=settings.PADDLE_ENVIRONMENT,
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26,
            status=PaddleStatus.ACTIVE, verified_at=future - timedelta(days=130),
            period_starts_at=future - timedelta(days=1), period_ends_at=future + timedelta(days=29),
            currency_code="USD")
        with patch("tenancy.models.timezone.now", return_value=future):
            self.assertTrue(Project.objects.for_user(self.owner).filter(pk=self.open_project.pk).exists())
        subscription.status = PaddleStatus.CANCELED
        subscription.canceled_at = future - timedelta(days=90) + timedelta(microseconds=1)
        subscription.save(update_fields=["status", "canceled_at"])
        with patch("tenancy.models.timezone.now", return_value=future):
            self.assertTrue(Project.objects.for_user(self.owner).filter(pk=self.open_project.pk).exists())
        subscription.canceled_at = future - timedelta(days=90)
        subscription.save(update_fields=["canceled_at"])
        with patch("tenancy.models.timezone.now", return_value=future):
            self.assertFalse(Project.objects.for_user(self.owner).filter(pk=self.open_project.pk).exists())
            with self.assertRaises(PermissionDenied):
                require_organization_action(organization=self.organization, user=self.owner,
                                            action=Action.ORGANIZATION_EXPORT)
        subscription.status = PaddleStatus.ACTIVE
        subscription.refunded_at = future - timedelta(days=90)
        subscription.save(update_fields=["status", "refunded_at"])
        with patch("tenancy.models.timezone.now", return_value=future):
            self.assertFalse(Project.objects.for_user(self.owner).filter(pk=self.open_project.pk).exists())

    def test_origin_normalization_is_exact_and_rejects_url_scope_expansion(self):
        self.assertEqual(normalize_origin(" HTTPS://Exämple.COM.:443/ "), "https://xn--exmple-cua.com")
        self.assertEqual(normalize_origin("http://example.com:80"), "http://example.com")
        self.assertEqual(normalize_origin("https://example.com:8443"), "https://example.com:8443")
        self.assertNotEqual(normalize_origin("https://example.com"), normalize_origin("https://www.example.com"))
        for value in (
            "ftp://example.com",
            "https://user@example.com",
            "https://*.example.com",
            "https://example.com/path",
            "https://example.com/?query=1",
            "https://example.com/#fragment",
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                normalize_origin(value)

    def test_scoped_querysets_enforce_organization_and_restricted_project_access(self):
        self.assertEqual(set(Project.objects.for_user(self.owner)), {self.open_project, self.restricted_project})
        self.assertEqual(set(Project.objects.for_user(self.member)), {self.open_project, self.restricted_project})
        self.assertEqual(set(Project.objects.for_user(self.other_member)), {self.open_project})
        self.assertFalse(Project.objects.for_user(self.outsider).filter(organization=self.organization).exists())
        self.assertFalse(Project.objects.for_user(self.staff).exists())
        self.assertFalse(Organization.objects.for_user(self.staff).exists())

        foreign_membership = OrganizationMembership.objects.get(
            organization=self.other_organization,
            user=self.outsider,
        )
        ProjectMembership.objects.bulk_create([
            ProjectMembership(
                project=self.restricted_project,
                organization_membership=foreign_membership,
            ),
        ])
        self.assertNotIn(self.restricted_project, Project.objects.for_user(self.outsider))

    def test_cross_organization_relationships_and_duplicate_origins_are_rejected(self):
        foreign_membership = OrganizationMembership.objects.get(
            organization=self.other_organization,
            user=self.outsider,
        )
        with self.assertRaisesRegex(ValidationError, "within one organization"):
            ProjectMembership(
                project=self.restricted_project,
                organization_membership=foreign_membership,
            ).save()
        with self.assertRaisesRegex(ValidationError, "within one organization"):
            DomainAlias(
                organization=self.other_organization,
                project=self.open_project,
                origin="https://alias.example.com",
            ).save()
        with self.assertRaises(ValidationError):
            update_project(
                project=self.restricted_project,
                user=self.owner,
                canonical_origin="https://www.open.example.com",
            )
        with self.assertRaises(ValidationError):
            DomainAlias.objects.create(
                organization=self.organization,
                project=self.restricted_project,
                origin=self.open_project.canonical_origin,
            )
        with self.assertRaises(ValidationError):
            Project.objects.create(
                organization=self.organization,
                name="Alias collision",
                canonical_origin="https://www.open.example.com",
            )

    def test_organization_owner_bootstrap_is_atomic_and_requires_verified_email(self):
        trial = self.organization.trial
        self.assertEqual(trial.state, TrialState.ACTIVE)
        self.assertEqual(trial.offer_version, "agency-launch-v1")
        self.assertEqual((trial.project_limit, trial.member_limit, trial.unit_limit), (1, 3, 40))
        self.assertEqual(trial.ends_at - trial.started_at, timedelta(days=30))
        self.assertEqual(trial.automatic_eligibility.user, self.owner)
        self.assertEqual(
            AuditEvent.objects.filter(organization=self.organization, event_type=AuditEventType.TRIAL_GRANTED).count(),
            1,
        )

        later = create_organization(user=self.owner, name="Later organization")
        self.assertEqual(later.trial.state, TrialState.PENDING_REVIEW)
        self.assertIsNone(later.trial.automatic_eligibility)
        self.assertIsNone(later.trial.started_at)
        self.assertIsNone(later.trial.ends_at)
        trial.refresh_from_db()
        self.assertEqual(trial.state, TrialState.ACTIVE)
        self.assertEqual(
            AuditEvent.objects.filter(organization=later, event_type=AuditEventType.TRIAL_REVIEW_REQUIRED).count(),
            1,
        )

        unverified = User.objects.create_user(email="unverified@example.com", password=self.password)
        with self.assertRaisesRegex(ValidationError, "Verify"):
            create_organization(user=unverified, name="Not created")
        self.assertFalse(OrganizationTrial.objects.filter(organization__name="Not created").exists())

        with patch("tenancy.services.OrganizationMembership.save", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                create_organization(user=self.owner, name="Rolled back")
        self.assertFalse(Organization.objects.filter(name="Rolled back").exists())

        with patch("tenancy.services.OrganizationTrial.save", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                create_organization(user=self.owner, name="Trial rolled back")
        self.assertFalse(Organization.objects.filter(name="Trial rolled back").exists())

        fresh = self.create_user("fresh-trial@example.com")
        with patch("tenancy.services._audit", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                create_organization(user=fresh, name="Audit rolled back")
        self.assertFalse(Organization.objects.filter(name="Audit rolled back").exists())
        self.assertFalse(AutomaticTrialEligibility.objects.filter(user=fresh).exists())
        retried = create_organization(user=fresh, name="Audit retry")
        self.assertEqual(retried.trial.state, TrialState.ACTIVE)

        closure_user = self.create_user("closed-trial@example.com")
        closed = create_organization(user=closure_user, name="Closed organization")
        eligibility_id = closed.trial.automatic_eligibility_id
        AuditEvent.objects.filter(organization=closed).delete()
        closed.delete()
        eligibility = AutomaticTrialEligibility.objects.get(pk=eligibility_id)
        self.assertIsNone(eligibility.organization_id)
        replacement = create_organization(user=closure_user, name="Replacement organization")
        self.assertEqual(replacement.trial.state, TrialState.PENDING_REVIEW)

        mismatch_user = self.create_user("mismatched-trial@example.com")
        eligibility_organization = Organization.objects.create(name="Eligibility organization")
        trial_organization = Organization.objects.create(name="Mismatched trial organization")
        eligibility = AutomaticTrialEligibility.objects.create(
            user=mismatch_user,
            organization=eligibility_organization,
            offer_version="agency-launch-v1",
            granted_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            OrganizationTrial(
                organization=trial_organization,
                automatic_eligibility=eligibility,
                offer_version="agency-launch-v1",
                state=TrialState.ACTIVE,
                started_at=timezone.now(),
                ends_at=timezone.now() + timedelta(days=30),
                project_limit=1,
                member_limit=3,
                unit_limit=40,
            ).full_clean()

    def test_project_artifacts_require_the_exact_authorized_project_namespace(self):
        with project_artifact_barrier(self.restricted_project.organization_id, shared=True):
            key = save_project_artifact(
                project=self.restricted_project,
                content=b"{}",
                content_type="application/json",
            )
        self.assertEqual(read_project_artifact(project=self.restricted_project, key=key), b"{}")
        with self.assertRaises(ArtifactValidationError):
            read_project_artifact(project=self.open_project, key=key)
        with self.assertRaises(ValidationError):
            save_project_artifact(
                project=Project(pk=self.open_project.pk, organization_id=self.organization.pk),
                content=b"{}",
                content_type="application/json",
            )

    def test_project_artifact_inventory_includes_nested_job_files_and_uncommitted_orphans(self):
        with project_artifact_barrier(self.open_project.organization_id, shared=True):
            own = save_project_artifact(project=self.open_project, content=b"{}", content_type="application/json")
        with project_artifact_barrier(self.open_project.organization_id, shared=True):
            orphan = save_private_artifact(scope=f"{project_artifact_scope(self.open_project)}/jobs/123",
                                           content=b"{}", content_type="application/json")
        with project_artifact_barrier(self.restricted_project.organization_id, shared=True):
            foreign = save_project_artifact(project=self.restricted_project, content=b"{}",
                                            content_type="application/json")
        self.assertEqual(list_project_artifact_keys(project=self.open_project), sorted((own, orphan)))
        self.assertNotIn(foreign, list_project_artifact_keys(project=self.open_project))
        with self.assertRaises(ArtifactValidationError):
            list_project_artifact_keys(project=self.open_project, limit=1)

    def test_api_lists_only_authorized_scope_and_gives_staff_no_implicit_access(self):
        owner = self.client_for(self.owner)
        response = owner.get("/api/organizations/", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual([item["id"] for item in response.json()["organizations"]], [self.organization.pk])
        trial = response.json()["organizations"][0]["trial"]
        self.assertEqual((trial["state"], trial["access_state"]), (TrialState.ACTIVE, TrialState.ACTIVE))
        self.assertEqual(
            (trial["offer_version"], trial["project_limit"], trial["member_limit"], trial["unit_limit"]),
            ("agency-launch-v1", 1, 3, 40),
        )
        projects = owner.get(f"/api/organizations/{self.organization.pk}/projects/", secure=True)
        self.assertEqual({item["id"] for item in projects.json()["projects"]}, {
            self.open_project.pk,
            self.restricted_project.pk,
        })
        project_detail = owner.get(
            f"/api/organizations/{self.organization.pk}/projects/{self.open_project.pk}/",
            secure=True,
        ).json()
        self.assertEqual(project_detail["organization"]["trial"]["state"], TrialState.ACTIVE)

        outsider = self.client_for(self.outsider)
        hidden = outsider.get(f"/api/organizations/{self.organization.pk}/", secure=True)
        self.assertEqual(hidden.status_code, 404)
        nested = outsider.get(
            f"/api/organizations/{self.other_organization.pk}/projects/{self.open_project.pk}/",
            secure=True,
        )
        self.assertEqual(nested.status_code, 404)

        staff = self.client_for(self.staff)
        self.assertEqual(staff.get("/api/organizations/", secure=True).json(), {
            "organizations": [],
            "has_more": False,
        })

    def test_api_derives_expired_read_only_access_and_keeps_trial_details_owner_only(self):
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(
            state=TrialState.ACTIVE,
            started_at=now - timedelta(days=31),
            ends_at=now - timedelta(days=1),
        )

        owner_payload = self.client_for(self.owner).get(
            f"/api/organizations/{self.organization.pk}/", secure=True,
        ).json()["organization"]
        self.assertEqual(owner_payload["access_state"], TrialState.READ_ONLY)
        self.assertEqual(owner_payload["trial"]["state"], TrialState.EXPIRED)
        self.assertEqual(OrganizationTrial.objects.get(organization=self.organization).state, TrialState.ACTIVE)

        member_payload = self.client_for(self.member).get(
            f"/api/organizations/{self.organization.pk}/", secure=True,
        ).json()["organization"]
        self.assertEqual(member_payload["access_state"], TrialState.READ_ONLY)
        self.assertIsNone(member_payload["trial"])

        self.organization.is_suspended = True
        self.organization.save(update_fields=["is_suspended"])
        suspended = self.client_for(self.owner).get(
            "/api/organizations/", secure=True,
        ).json()["organizations"][0]
        self.assertEqual(suspended["access_state"], TrialState.SUSPENDED)

        OrganizationTrial.objects.filter(organization=self.organization).update(state=TrialState.SUSPENDED)
        suspended_trial = self.client_for(self.owner).get(
            "/api/organizations/", secure=True,
        ).json()["organizations"][0]
        self.assertEqual(suspended_trial["trial"]["state"], TrialState.EXPIRED)
        self.assertEqual(suspended_trial["trial"]["access_state"], TrialState.SUSPENDED)

    def test_trial_usage_is_owner_only_windowed_and_constant_query(self):
        now = timezone.now()
        started_at = now - timedelta(days=29)
        ends_at = now + timedelta(days=1)
        OrganizationTrial.objects.filter(organization=self.organization).update(
            started_at=started_at,
            ends_at=ends_at,
        )

        def record(*, organization, project, actor, state, units, created_at, reserved_units=None, settled_at=None):
            job = JobRun.objects.create(
                organization=organization,
                project=project,
                actor=actor,
                handler="diagnostic_probe",
                method_version="trial-usage-test",
                input_snapshot={"sample": "trial-usage"},
            )
            reservation = UsageReservation.objects.create(
                job=job,
                organization=organization,
                project=project,
                provider="synthetic",
                period_start=created_at.date().replace(day=1),
                reserved_units=units if reserved_units is None else reserved_units,
                actual_units=units if state == UsageReservation.State.SETTLED else 0,
                state=state,
                settled_at=(settled_at or created_at) if state != UsageReservation.State.RESERVED else None,
            )
            UsageReservation.objects.filter(pk=reservation.pk).update(created_at=created_at)

        record(
            organization=self.organization,
            project=self.open_project,
            actor=self.owner,
            state=UsageReservation.State.SETTLED,
            units=7,
            reserved_units=9,
            created_at=now - timedelta(days=28),
            settled_at=ends_at + timedelta(days=1),
        )
        record(
            organization=self.organization,
            project=self.open_project,
            actor=self.owner,
            state=UsageReservation.State.RESERVED,
            units=5,
            created_at=now - timedelta(days=1),
        )
        record(
            organization=self.organization,
            project=self.open_project,
            actor=self.owner,
            state=UsageReservation.State.RELEASED,
            units=9,
            created_at=now - timedelta(days=2),
        )
        record(
            organization=self.organization,
            project=self.open_project,
            actor=self.owner,
            state=UsageReservation.State.SETTLED,
            units=11,
            created_at=started_at - timedelta(seconds=1),
        )
        record(
            organization=self.organization,
            project=self.open_project,
            actor=self.owner,
            state=UsageReservation.State.SETTLED,
            units=17,
            created_at=ends_at,
        )
        foreign_project = create_project(
            organization=self.other_organization,
            user=self.outsider,
            name="Foreign usage",
            canonical_origin="https://foreign-usage.example.com",
        )
        record(
            organization=self.other_organization,
            project=foreign_project,
            actor=self.outsider,
            state=UsageReservation.State.SETTLED,
            units=13,
            created_at=now - timedelta(days=1),
        )

        owner = self.client_for(self.owner)
        payload = owner.get(f"/api/organizations/{self.organization.pk}/", secure=True).json()["organization"]
        self.assertEqual((payload["trial"]["settled_units"], payload["trial"]["reserved_units"]), (7, 5))
        member_payload = self.client_for(self.member).get(
            f"/api/organizations/{self.organization.pk}/",
            secure=True,
        ).json()["organization"]
        self.assertIsNone(member_payload["trial"])

        pending = create_organization(user=self.owner, name="Pending usage")
        pending_payload = owner.get(f"/api/organizations/{pending.pk}/", secure=True).json()["organization"]
        self.assertEqual((pending_payload["trial"]["settled_units"], pending_payload["trial"]["reserved_units"]), (0, 0))

        OrganizationTrial.objects.filter(organization=self.organization).update(ends_at=now - timedelta(hours=12))
        expired = owner.get(f"/api/organizations/{self.organization.pk}/", secure=True).json()["organization"]
        self.assertEqual(expired["trial"]["state"], TrialState.EXPIRED)
        self.assertEqual((expired["trial"]["settled_units"], expired["trial"]["reserved_units"]), (7, 5))

        with CaptureQueriesContext(connection) as baseline:
            self.assertEqual(owner.get("/api/organizations/", secure=True).status_code, 200)
        for index in range(3):
            create_organization(user=self.owner, name=f"Additional pending usage {index}")
        with CaptureQueriesContext(connection) as expanded:
            self.assertEqual(owner.get("/api/organizations/", secure=True).status_code, 200)
        self.assertLessEqual(len(expanded), len(baseline))

    def test_project_list_alias_prefetch_has_constant_query_count(self):
        owner = self.client_for(self.owner)
        path = f"/api/organizations/{self.organization.pk}/projects/"
        with CaptureQueriesContext(connection) as baseline:
            self.assertEqual(owner.get(path, secure=True).status_code, 200)

        projects = Project.objects.bulk_create([
            Project(
                organization=self.organization,
                name=f"Query project {index}",
                canonical_origin=f"https://query-{index}.example.com",
            )
            for index in range(10)
        ])
        DomainAlias.objects.bulk_create([
            DomainAlias(
                organization=self.organization,
                project=project,
                origin=f"https://www.query-{index}.example.com",
            )
            for index, project in enumerate(projects)
        ])
        with CaptureQueriesContext(connection) as expanded:
            self.assertEqual(owner.get(path, secure=True).status_code, 200)
        self.assertLessEqual(len(expanded), len(baseline) + 1)

    def test_api_list_limits_signal_more_results_with_stable_ordering(self):
        organizations = Organization.objects.bulk_create([
            Organization(name=f"Page organization {index:03}") for index in range(101)
        ])
        OrganizationMembership.objects.bulk_create([
            OrganizationMembership(organization=organization, user=self.owner, role=MembershipRole.MEMBER)
            for organization in organizations
        ])
        Project.objects.bulk_create([
            Project(
                organization=self.organization,
                name=f"Page project {index:03}",
                canonical_origin=f"https://page-{index:03}.example.com",
            )
            for index in range(99)
        ])

        owner = self.client_for(self.owner)
        first = owner.get("/api/organizations/", secure=True).json()
        second = owner.get("/api/organizations/", secure=True).json()
        self.assertEqual(len(first["organizations"]), 100)
        self.assertTrue(first["has_more"])
        self.assertEqual(
            [item["id"] for item in first["organizations"]],
            [item["id"] for item in second["organizations"]],
        )

        projects = owner.get(f"/api/organizations/{self.organization.pk}/projects/", secure=True).json()
        self.assertEqual(len(projects["projects"]), 100)
        self.assertTrue(projects["has_more"])

    def test_api_restricted_access_and_owner_only_mutations(self):
        member = self.client_for(self.member)
        projects = member.get(f"/api/organizations/{self.organization.pk}/projects/", secure=True)
        self.assertEqual({item["id"] for item in projects.json()["projects"]}, {
            self.open_project.pk,
            self.restricted_project.pk,
        })
        denied = self.request(
            member,
            "patch",
            f"/api/organizations/{self.organization.pk}/projects/{self.open_project.pk}/",
            {"name": "Not allowed"},
        )
        self.assertEqual(denied.status_code, 403)
        other_member = self.client_for(self.other_member)
        hidden = other_member.get(
            f"/api/organizations/{self.organization.pk}/projects/{self.restricted_project.pk}/",
            secure=True,
        )
        self.assertEqual(hidden.status_code, 404)

        denied_create = self.request(
            member,
            "post",
            f"/api/organizations/{self.organization.pk}/projects/",
            {"name": "Denied", "canonical_origin": "https://denied.example.com"},
        )
        self.assertEqual(denied_create.status_code, 403)
        denied_organization = self.request(
            member,
            "patch",
            f"/api/organizations/{self.organization.pk}/",
            {"name": "Denied"},
        )
        self.assertEqual(denied_organization.status_code, 403)
        outsider = self.client_for(self.outsider)
        hidden_write = self.request(
            outsider,
            "patch",
            f"/api/organizations/{self.organization.pk}/projects/{self.open_project.pk}/",
            {"name": "Hidden"},
        )
        self.assertEqual(hidden_write.status_code, 404)
        self.assertEqual(Client().get("/api/organizations/", secure=True).status_code, 401)

    def test_api_creates_and_updates_normalized_settings_without_trusting_foreign_keys(self):
        project_owner = self.create_user("project-settings-owner@example.com")
        organization = create_organization(user=project_owner, name="Project settings organization")
        owner = self.client_for(project_owner)
        path = f"/api/organizations/{organization.pk}/projects/"
        no_csrf = self.request(
            owner,
            "post",
            path,
            {"name": "No CSRF", "canonical_origin": "https://csrf.example.com"},
            csrf=False,
        )
        self.assertEqual(no_csrf.status_code, 403)
        rejected = self.request(
            owner,
            "post",
            path,
            {
                "name": "Injected",
                "canonical_origin": "https://injected.example.com",
                "organization_id": self.other_organization.pk,
            },
        )
        self.assertEqual(rejected.status_code, 400)

        created = self.request(
            owner,
            "post",
            path,
            {
                "name": "  New project  ",
                "canonical_origin": "HTTPS://New.Example.COM:443/",
                "aliases": ["https://www.new.example.com/"],
                "access_restricted": True,
            },
        )
        self.assertEqual(created.status_code, 201, created.content)
        project = Project.objects.get(pk=created.json()["project"]["id"])
        self.assertEqual(project.organization, organization)
        self.assertEqual(project.name, "New project")
        self.assertEqual(project.canonical_origin, "https://new.example.com")
        self.assertEqual(list(project.domain_aliases.values_list("origin", flat=True)), ["https://www.new.example.com"])

        access_updated = self.request(
            owner,
            "patch",
            f"{path}{project.pk}/",
            {"access_restricted": False},
        )
        self.assertEqual(access_updated.status_code, 200, access_updated.content)
        access_event = AuditEvent.objects.get(project=project, event_type=AuditEventType.PROJECT_ACCESS_CHANGED)
        self.assertEqual(access_event.details, {"before": True, "after": False})
        self.assertTrue(access_event.request_id)
        with patch("tenancy.services._audit", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                update_project(project=project, user=project_owner, access_restricted=True)
        project.refresh_from_db()
        self.assertFalse(project.access_restricted)

        updated = self.request(
            owner,
            "patch",
            f"{path}{project.pk}/",
            {"name": "Updated project", "aliases": []},
        )
        self.assertEqual(updated.status_code, 200, updated.content)
        project.refresh_from_db()
        self.assertEqual(project.name, "Updated project")
        self.assertFalse(project.domain_aliases.exists())

        original = project.name
        for payload in (
            {"name": 1},
            {"name": None},
            {"canonical_origin": {}},
            {"aliases": None},
            {"aliases": ["https://valid.example.com", 1]},
            {"access_restricted": "yes"},
        ):
            with self.subTest(payload=payload):
                response = self.request(owner, "patch", f"{path}{project.pk}/", payload)
                self.assertEqual(response.status_code, 400, response.content)
        project.refresh_from_db()
        self.assertEqual(project.name, original)

    def test_organization_creation_api_requires_csrf_and_verified_identity(self):
        verified = self.create_user("new-owner@example.com")
        client = self.client_for(verified)
        no_csrf = self.request(client, "post", "/api/organizations/", {"name": "New"}, csrf=False)
        self.assertEqual(no_csrf.status_code, 403)
        created = self.request(client, "post", "/api/organizations/", {"name": " New "})
        self.assertEqual(created.status_code, 201, created.content)
        organization = Organization.objects.get(pk=created.json()["organization"]["id"])
        self.assertEqual(organization.name, "New")
        self.assertTrue(OrganizationMembership.objects.filter(
            organization=organization,
            user=verified,
            role=MembershipRole.OWNER,
        ).exists())

        unverified = User.objects.create_user(email="api-unverified@example.com", password=self.password)
        denied = self.client_for(unverified)
        response = self.request(denied, "post", "/api/organizations/", {"name": "Denied"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Organization.objects.filter(name="Denied").exists())

    def test_onboarding_api_resumes_scoped_configuration_and_rejects_stale_or_invalid_updates(self):
        from jobs.models import JobRun, UsageReservation

        path = f"/api/organizations/{self.organization.pk}/projects/{self.open_project.pk}/onboarding/"
        owner = self.client_for(self.owner)
        initial = owner.get(path, secure=True)
        self.assertEqual(initial.status_code, 200)
        self.assertIn("no-store", initial.headers["Cache-Control"])
        self.assertEqual(initial.json()["configuration"], {
            "project_id": self.open_project.pk,
            "canonical_origin": self.open_project.canonical_origin,
            "target_country": "", "target_languages": [], "business_goal": "", "timezone": "UTC",
            "audience": "", "offer": "", "brand_voice": "", "seed_topics": [],
            "prohibited_claims": [], "conversion_goals": [], "brand_aliases": [], "measurement_notes": "",
            "competitor_origins": [], "research_allowed_origins": [], "research_blocked_origins": [], "rss_feed_urls": [],
            "crawl_page_limit": None, "business_locations": [], "service_areas": [],
            "ignored_query_parameters": [], "pagination_query_parameters": [], "facet_query_parameters": [],
            "query_variant_limit": 5,
            "contact_details": "", "business_hours": "", "profile_urls": [],
            "local_eligibility_notes": "", "source_choice": "undecided", "source_state": "not_selected",
            "current_step": "basics", "revision": 0, "updated_at": None,
        })
        self.assertFalse(ProjectConfiguration.objects.filter(project=self.open_project).exists())
        self.assertEqual(self.request(owner, "patch", path, {
            "revision": 0, "target_country": "Türkiye", "target_languages": ["tr"],
            "business_goal": "Increase qualified bookings", "current_step": "source",
        }, csrf=False).status_code, 403)

        saved = self.request(owner, "patch", path, {
            "revision": 0, "target_country": " Türkiye ", "target_languages": ["tr", "en-US"],
            "business_goal": " Increase qualified bookings ", "timezone": "Europe/Istanbul",
            "current_step": "source",
        })
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json()["configuration"]["revision"], 1)
        self.assertEqual(saved.json()["configuration"]["target_country"], "Türkiye")

        member = self.client_for(self.member)
        self.assertEqual(member.get(path, secure=True).json()["configuration"]["business_goal"], "Increase qualified bookings")
        self.assertEqual(self.request(member, "patch", path, {"revision": 1, "source_choice": "skip"}).status_code, 403)
        stale = self.request(owner, "patch", path, {"revision": 0, "source_choice": "skip"})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["configuration"]["revision"], 1)

        completed = self.request(owner, "patch", path, {
            "revision": 1,
            "source_choice": "synthetic_demo",
            "current_step": "complete",
            "audience": "Travelers arranging airport transfers",
            "offer": "Pre-booked transfers",
            "brand_voice": "Clear and practical",
            "seed_topics": ["airport transfer"],
            "prohibited_claims": ["guaranteed lowest price"],
            "conversion_goals": ["booking completed"],
            "brand_aliases": ["Example Transfers"],
            "measurement_notes": "GA4 conversion instrumentation not yet verified",
            "competitor_origins": ["HTTPS://Competitor.Example/"],
            "research_allowed_origins": ["https://trusted.example"],
            "rss_feed_urls": ["https://trusted.example/feed.xml"],
            "research_blocked_origins": ["https://blocked.example"],
            "crawl_page_limit": 250,
            "ignored_query_parameters": ["utm_source"],
            "pagination_query_parameters": ["page", "UTM_SOURCE"],
            "facet_query_parameters": ["filter[color]"],
            "query_variant_limit": 4,
            "business_locations": ["Istanbul Airport desk"],
            "service_areas": ["Istanbul"],
            "contact_details": "Use the verified business phone on the site.",
            "business_hours": "Every day, 08:00-22:00 local time",
            "profile_urls": ["https://profiles.example/example-transfers"],
            "local_eligibility_notes": "Confirm profile eligibility before connecting.",
        })
        self.assertEqual(completed.status_code, 200, completed.content)
        self.assertEqual(completed.json()["configuration"]["source_state"], "synthetic_demo")
        self.assertEqual(completed.json()["configuration"]["rss_feed_urls"], ["https://trusted.example/feed.xml"])
        self.assertEqual(completed.json()["configuration"]["measurement_notes"], "GA4 conversion instrumentation not yet verified")
        self.assertEqual(completed.json()["configuration"]["competitor_origins"], ["https://competitor.example"])
        self.assertEqual(completed.json()["configuration"]["pagination_query_parameters"], ["page", "UTM_SOURCE"])
        self.assertEqual(completed.json()["configuration"]["facet_query_parameters"], ["filter[color]"])
        self.assertFalse(JobRun.objects.filter(project=self.open_project).exists())
        self.assertFalse(UsageReservation.objects.filter(project=self.open_project).exists())

        invalid = self.request(owner, "patch", path, {
            "revision": 2, "target_languages": ["not a language"],
        })
        self.assertEqual(invalid.status_code, 400)
        malformed_url = self.request(owner, "patch", path, {"revision": 2, "profile_urls": ["https://["]})
        self.assertEqual(malformed_url.status_code, 400)
        duplicate_origin = self.request(owner, "patch", path, {
            "revision": 2, "competitor_origins": ["HTTPS://duplicate.example/", "https://duplicate.example:443"],
        })
        self.assertEqual(duplicate_origin.status_code, 400)
        overlapping_parameter = self.request(owner, "patch", path, {
            "revision": 2, "ignored_query_parameters": ["page"], "pagination_query_parameters": ["page"],
        })
        self.assertEqual(overlapping_parameter.status_code, 400)
        for unsafe_feed in ("https://outside.example/feed", "http://trusted.example/feed", "https://trusted.example:8443/feed",
                            "https://trusted.example/feed?key=secret",
                            "https://person@trusted.example/feed", "https://trusted.example/feed#fragment"):
            with self.subTest(feed=unsafe_feed):
                self.assertEqual(self.request(owner, "patch", path, {"revision": 2, "rss_feed_urls": [unsafe_feed]}).status_code, 400)
        for invalid_changes in (
            {"ignored_query_parameters": [" spaced"]},
            {"pagination_query_parameters": ["page", "page"]},
            {"facet_query_parameters": ["bad&name"]},
            {"query_variant_limit": 0},
            {"query_variant_limit": 26},
        ):
            with self.subTest(invalid_changes=invalid_changes):
                invalid_parameter = self.request(owner, "patch", path, {"revision": 2, **invalid_changes})
                self.assertEqual(invalid_parameter.status_code, 400)
        with self.assertRaises(ValidationError):
            update_project_configuration(
                project=self.open_project,
                user=self.owner,
                expected_revision=2,
                changes={"project": self.restricted_project},
            )
        self.assertEqual(ProjectConfiguration.objects.get(project=self.open_project).revision, 2)
        self.assertFalse(ProjectConfiguration.objects.filter(project=self.restricted_project).exists())
        outsider = self.client_for(self.outsider)
        self.assertEqual(outsider.get(path, secure=True).status_code, 404)
        self.assertEqual(self.request(outsider, "patch", path, {"revision": 2, "query_variant_limit": 5}).status_code, 404)

    def test_role_action_matrix_and_project_scope_are_deny_by_default(self):
        admin = self.create_user("admin@example.com")
        admin_record = OrganizationMembership.objects.create(
            organization=self.organization,
            user=admin,
            role=MembershipRole.ADMIN,
        )
        ProjectMembership.objects.create(
            project=self.restricted_project,
            organization_membership=admin_record,
        )
        actors = {
            MembershipRole.OWNER: self.owner,
            MembershipRole.ADMIN: admin,
            MembershipRole.MEMBER: self.member,
            MembershipRole.VIEWER: self.other_member,
        }
        expected = {
            Action.VIEW_PROJECT: set(MembershipRole.values),
            Action.LAUNCH_JOB: {MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.MEMBER},
            Action.APPROVE: {MembershipRole.OWNER, MembershipRole.ADMIN},
            Action.MANAGE_PROJECT: {MembershipRole.OWNER, MembershipRole.ADMIN},
            Action.CREATE_PROJECT: {MembershipRole.OWNER, MembershipRole.ADMIN},
            Action.MANAGE_PROJECT_ACCESS: {MembershipRole.OWNER, MembershipRole.ADMIN},
            Action.MANAGE_MEMBERS: {MembershipRole.OWNER, MembershipRole.ADMIN},
            Action.GRANT_PRIVILEGED_ROLE: {MembershipRole.OWNER},
            Action.CREATE_EXTERNAL_SHARE: {MembershipRole.OWNER, MembershipRole.ADMIN},
            Action.MANAGE_BILLING: {MembershipRole.OWNER},
            Action.ORGANIZATION_EXPORT: {MembershipRole.OWNER},
            Action.ORGANIZATION_SETTINGS: {MembershipRole.OWNER},
        }
        project_actions = {
            Action.VIEW_PROJECT,
            Action.LAUNCH_JOB,
            Action.APPROVE,
            Action.MANAGE_PROJECT,
            Action.MANAGE_PROJECT_ACCESS,
            Action.CREATE_EXTERNAL_SHARE,
        }
        for action, allowed_roles in expected.items():
            for role, user in actors.items():
                with self.subTest(action=action, role=role):
                    if action in project_actions:
                        with self.assertRaises(PermissionDenied):
                            require_organization_action(organization=self.organization, user=user, action=action)
                        authorize = lambda: require_project_action(project=self.open_project, user=user, action=action)
                    else:
                        authorize = lambda: require_organization_action(
                            organization=self.organization,
                            user=user,
                            action=action,
                        )
                    if role in allowed_roles:
                        authorize()
                    else:
                        with self.assertRaises(PermissionDenied):
                            authorize()

        for role, user in actors.items():
            with self.subTest(restricted_role=role):
                if role in {MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.MEMBER}:
                    require_project_action(project=self.restricted_project, user=user, action=Action.VIEW_PROJECT)
                else:
                    with self.assertRaises(PermissionDenied):
                        require_project_action(project=self.restricted_project, user=user, action=Action.VIEW_PROJECT)
        with self.assertRaises(PermissionDenied):
            require_organization_action(
                organization=self.organization,
                user=self.staff,
                action=Action.MANAGE_MEMBERS,
            )
        with self.assertRaises(PermissionDenied):
            require_project_action(project=self.open_project, user=self.owner, action=Action.MANAGE_BILLING)

    def test_organization_authority_uses_one_fresh_query_and_denies_cached_revocations(self):
        original = OrganizationMembership.objects.get(organization=self.organization, user=self.owner)
        with self.assertNumQueries(1):
            membership = require_organization_action(
                organization=self.organization, user=self.owner, action=Action.MANAGE_MEMBERS,
            )
        self.assertEqual((membership.pk, membership.role), (original.pk, MembershipRole.OWNER))
        deleted_user = self.create_user("deleted-authority@example.com")
        OrganizationMembership.objects.create(
            organization=self.organization, user=deleted_user, role=MembershipRole.ADMIN,
        )
        for loss in ("inactive", "deleted-user", "membership", "role", "suspended", "closed",
                     "cached-inactive", "anonymous", "unsaved-user", "unsaved-organization", "foreign"):
            with self.subTest(loss=loss), transaction.atomic():
                user, organization = self.owner, self.organization
                if loss == "inactive":
                    User.objects.filter(pk=user.pk).update(is_active=False)
                elif loss == "deleted-user":
                    user = deleted_user
                    OrganizationMembership.objects.filter(organization=organization, user=user).delete()
                    User.objects.filter(pk=user.pk).delete()
                elif loss == "membership":
                    OrganizationMembership.objects.filter(pk=original.pk).delete()
                elif loss == "role":
                    OrganizationMembership.objects.filter(pk=original.pk).update(role=MembershipRole.VIEWER)
                elif loss == "suspended":
                    Organization.objects.filter(pk=organization.pk).update(is_suspended=True)
                elif loss == "closed":
                    Organization.objects.filter(pk=organization.pk).update(is_suspended=True, closed_at=timezone.now())
                elif loss == "cached-inactive":
                    user = User(pk=user.pk, is_active=False)
                elif loss == "anonymous":
                    user = AnonymousUser()
                elif loss == "unsaved-user":
                    user = User()
                elif loss == "unsaved-organization":
                    organization = Organization()
                else:
                    organization = self.other_organization
                with self.assertRaises(PermissionDenied):
                    require_organization_action(organization=organization, user=user, action=Action.MANAGE_MEMBERS)
                transaction.set_rollback(True)

    def test_admin_project_scope_does_not_grant_organization_or_sibling_access(self):
        owner = self.create_user("project-owner@example.com")
        organization = create_organization(user=owner, name="Admin project organization")
        admin = self.create_user("project-admin@example.com")
        OrganizationMembership.objects.create(
            organization=organization,
            user=admin,
            role=MembershipRole.ADMIN,
        )
        client = self.client_for(admin)
        created = self.request(
            client,
            "post",
            f"/api/organizations/{organization.pk}/projects/",
            {
                "name": "Admin restricted",
                "canonical_origin": "https://admin.example.com",
                "access_restricted": True,
            },
        )
        self.assertEqual(created.status_code, 201, created.content)
        project = Project.objects.get(pk=created.json()["project"]["id"])
        sibling = Project.objects.create(
            organization=organization,
            name="Legacy restricted sibling",
            canonical_origin="https://sibling.example.com",
            access_restricted=True,
        )
        self.assertTrue(Project.objects.for_user(admin).filter(pk=project.pk).exists())
        self.assertEqual(
            self.request(
                client,
                "patch",
                f"/api/organizations/{organization.pk}/projects/{project.pk}/",
                {"name": "Admin updated"},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.request(
                client,
                "patch",
                f"/api/organizations/{organization.pk}/",
                {"name": "Not allowed"},
            ).status_code,
            403,
        )
        self.assertEqual(
            client.get(
                f"/api/organizations/{organization.pk}/projects/{sibling.pk}/",
                secure=True,
            ).status_code,
            404,
        )

    def test_invitation_requires_matching_verified_identity_and_acceptance_is_idempotent(self):
        invited = self.create_user("invited@example.com")
        invited.product_language = "tr"
        invited.save(update_fields=["product_language"])
        owner = self.client_for(self.owner)
        path = f"/api/organizations/{self.organization.pk}/team/"
        no_csrf = self.request(
            owner,
            "post",
            path,
            {"email": invited.email, "role": MembershipRole.MEMBER},
            csrf=False,
        )
        self.assertEqual(no_csrf.status_code, 403)
        with override_settings(DEBUG=True):
            created = self.request(
                owner,
                "post",
                path,
                {
                    "email": " Invited@Example.com ",
                    "role": MembershipRole.MEMBER,
                    "project_ids": [self.restricted_project.pk],
                },
            )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["delivery"], "sent")
        invitation = OrganizationInvitation.objects.get(pk=created.json()["invitation"]["id"])
        self.assertEqual(invitation.email, invited.email)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Kuruluş daveti (Türkçe taslak)", mail.outbox[0].subject)
        self.assertIn(self.organization.name, mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, [invited.email])
        token = mail.outbox[0].body.rsplit("#", 1)[1]
        self.assertNotEqual(invitation.token_digest, token)
        self.assertNotIn(token, json.dumps(created.json()))
        self.assertNotIn(token, json.dumps(list(AuditEvent.objects.values("details", "request_id")), default=str))

        wrong_account = self.client_for(self.outsider)
        wrong = self.request(wrong_account, "post", "/api/invitations/accept/", {"token": token})
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(wrong.json()["errors"][0]["code"], "wrong_identity")
        self.assertFalse(OrganizationMembership.objects.filter(organization=self.organization, user=invited).exists())

        OrganizationMembership.objects.filter(organization=self.organization, user=self.other_member).delete()
        invitee = self.client_for(invited)
        accepted = self.request(invitee, "post", "/api/invitations/accept/", {"token": token})
        replay = self.request(invitee, "post", "/api/invitations/accept/", {"token": token})
        self.assertEqual(accepted.status_code, 200, accepted.content)
        self.assertTrue(accepted.json()["accepted"])
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertFalse(replay.json()["accepted"])
        membership = OrganizationMembership.objects.get(organization=self.organization, user=invited)
        self.assertEqual(membership.role, MembershipRole.MEMBER)
        invited.refresh_from_db()
        self.assertIsNone(invited.registration_origin)
        self.assertTrue(membership.project_memberships.filter(project=self.restricted_project).exists())
        self.assertEqual(
            AuditEvent.objects.filter(
                invitation=invitation,
                event_type=AuditEventType.INVITATION_ACCEPTED,
            ).count(),
            1,
        )

    def test_reissue_after_failed_delivery_replaces_digest_and_preserves_scoped_grants(self):
        invited = self.create_user("retry-invite@example.com")
        owner = self.client_for(self.owner)
        with patch("tenancy.api.send_mail", side_effect=OSError("fixture relay down")):
            created = self.request(owner, "post", f"/api/organizations/{self.organization.pk}/team/", {
                "email": invited.email, "role": MembershipRole.VIEWER,
                "project_ids": [self.restricted_project.pk],
            })
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["delivery"], "failed")
        old = OrganizationInvitation.objects.get(pk=created.json()["invitation"]["id"])
        url = f"/api/organizations/{self.organization.pk}/team/invitations/{old.pk}/"
        self.assertEqual(self.request(owner, "post", url, {}, csrf=False).status_code, 403)
        self.assertEqual(self.request(self.client_for(self.outsider), "post", url, {}).status_code, 404)
        self.assertEqual(self.request(owner, "post", url, {"role": "owner"}).status_code, 400)
        old.refresh_from_db()
        self.assertEqual(old.state, InvitationState.PENDING)
        reissued = self.request(owner, "post", url, {})
        self.assertEqual(reissued.status_code, 201, reissued.content)
        self.assertEqual(reissued.json()["delivery"], "sent")
        new = OrganizationInvitation.objects.get(pk=reissued.json()["invitation"]["id"])
        old.refresh_from_db()
        self.assertEqual(old.state, InvitationState.REVOKED)
        self.assertNotEqual(old.token_digest, new.token_digest)
        self.assertEqual(list(new.project_grants.values_list("project_id", flat=True)), [self.restricted_project.pk])
        self.assertEqual(new.role, MembershipRole.VIEWER)
        self.assertEqual(self.request(owner, "post", url, {}).status_code, 409)
        token = mail.outbox[-1].body.rsplit("#", 1)[1]
        self.assertNotIn(token, json.dumps(reissued.json()))
        self.assertNotIn(token, json.dumps(list(AuditEvent.objects.values("details")), default=str))
        OrganizationMembership.objects.filter(organization=self.organization, user=self.other_member).delete()
        self.assertEqual(self.request(self.client_for(invited), "post", "/api/invitations/accept/", {"token": token}).status_code, 200)

    def test_reissue_rolls_back_if_actor_loses_project_scope(self):
        invitation, _ = create_invitation(
            organization=self.organization, actor=self.owner, email="denied-invite@example.com",
            role=MembershipRole.VIEWER, project_ids=[self.restricted_project.pk],
        )
        # A current team manager may not silently reissue restricted grants outside their current scope.
        admin = self.create_user("admin-invite@example.com")
        OrganizationMembership.objects.create(organization=self.organization, user=admin, role=MembershipRole.ADMIN)
        url = f"/api/organizations/{self.organization.pk}/team/invitations/{invitation.pk}/"
        result = self.request(self.client_for(admin), "post", url, {})
        self.assertEqual(result.status_code, 403)
        invitation.refresh_from_db()
        self.assertEqual(invitation.state, InvitationState.PENDING)

    def test_expired_and_revoked_invitations_have_stable_terminal_states(self):
        invited = self.create_user("terminal@example.com")
        invitation, token = create_invitation(
            organization=self.organization,
            actor=self.owner,
            email=invited.email,
            role=MembershipRole.VIEWER,
            project_ids=[],
        )
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        invitation.save(update_fields=["expires_at"])
        owner = self.client_for(self.owner)
        pending = owner.get(f"/api/organizations/{self.organization.pk}/team/", secure=True)
        self.assertNotIn(invitation.pk, {item["id"] for item in pending.json()["invitations"]})
        cannot_revoke = self.request(
            owner,
            "delete",
            f"/api/organizations/{self.organization.pk}/team/invitations/{invitation.pk}/",
        )
        self.assertEqual(cannot_revoke.status_code, 409)
        invitation.refresh_from_db()
        self.assertEqual(invitation.state, InvitationState.EXPIRED)
        invitee = self.client_for(invited)
        expired = self.request(invitee, "post", "/api/invitations/accept/", {"token": token})
        self.assertEqual(expired.status_code, 410)
        self.assertEqual(expired.json()["errors"][0]["code"], "expired")
        invitation.refresh_from_db()
        self.assertEqual(invitation.state, InvitationState.EXPIRED)
        self.assertTrue(AuditEvent.objects.filter(
            invitation=invitation,
            event_type=AuditEventType.INVITATION_EXPIRED,
        ).exists())
        expired_replay = self.request(invitee, "post", "/api/invitations/accept/", {"token": token})
        self.assertEqual(expired_replay.status_code, 410)
        self.assertEqual(expired_replay.json()["errors"][0]["code"], "expired")

        replacement, replacement_token = create_invitation(
            organization=self.organization,
            actor=self.owner,
            email=invited.email,
            role=MembershipRole.VIEWER,
            project_ids=[],
        )
        revoked = self.request(
            owner,
            "delete",
            f"/api/organizations/{self.organization.pk}/team/invitations/{replacement.pk}/",
        )
        self.assertEqual(revoked.status_code, 204)
        denied = self.request(invitee, "post", "/api/invitations/accept/", {"token": replacement_token})
        self.assertEqual(denied.status_code, 410)
        self.assertEqual(denied.json()["errors"][0]["code"], "revoked")

    def test_admin_cannot_escalate_roles_or_manage_privileged_members(self):
        admin = self.create_user("limited-admin@example.com")
        admin_record = OrganizationMembership.objects.create(
            organization=self.organization,
            user=admin,
            role=MembershipRole.ADMIN,
        )
        client = self.client_for(admin)
        team_path = f"/api/organizations/{self.organization.pk}/team/"
        denied_invite = self.request(
            client,
            "post",
            team_path,
            {"email": "new-admin@example.com", "role": MembershipRole.ADMIN},
        )
        self.assertEqual(denied_invite.status_code, 403)
        denied_promotion = self.request(
            client,
            "patch",
            f"{team_path}members/{self.member_record.pk}/",
            {"role": MembershipRole.ADMIN},
        )
        self.assertEqual(denied_promotion.status_code, 403)
        scoped_change = self.request(
            client,
            "patch",
            f"{team_path}members/{self.member_record.pk}/",
            {"role": MembershipRole.VIEWER, "project_ids": []},
        )
        self.assertEqual(scoped_change.status_code, 200, scoped_change.content)
        self.assertEqual(scoped_change.json()["member"]["project_ids"], [])
        self.assertTrue(self.member_record.project_memberships.filter(project=self.restricted_project).exists())
        scoped_team = client.get(team_path, secure=True)
        member_payload = next(item for item in scoped_team.json()["members"] if item["id"] == self.member_record.pk)
        self.assertEqual(member_payload["project_ids"], [])

        owner = self.client_for(self.owner)
        promoted = self.request(
            owner,
            "patch",
            f"{team_path}members/{self.member_record.pk}/",
            {"role": MembershipRole.ADMIN, "project_ids": [self.restricted_project.pk]},
        )
        self.assertEqual(promoted.status_code, 200, promoted.content)
        self.member_record.refresh_from_db()
        self.assertEqual(self.member_record.role, MembershipRole.ADMIN)
        self.assertEqual(
            self.request(
                client,
                "delete",
                f"{team_path}members/{self.member_record.pk}/",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.request(owner, "delete", f"{team_path}members/{admin_record.pk}/").status_code,
            204,
        )

        self.assertEqual(
            self.request(
                owner,
                "post",
                team_path,
                {"email": "new-owner@example.com", "role": MembershipRole.OWNER},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.request(
                owner,
                "patch",
                f"{team_path}members/{OrganizationMembership.objects.get(organization=self.organization, user=self.other_member).pk}/",
                {"role": MembershipRole.OWNER},
            ).status_code,
            403,
        )

    def test_membership_revocation_invalidates_the_same_session_without_affecting_other_tenants(self):
        member_organization = create_organization(user=self.member, name="Member owned")
        member_client = self.client_for(self.member)
        owner = self.client_for(self.owner)
        removed = self.request(
            owner,
            "delete",
            f"/api/organizations/{self.organization.pk}/team/members/{self.member_record.pk}/",
        )
        self.assertEqual(removed.status_code, 204)
        organizations = member_client.get("/api/organizations/", secure=True).json()["organizations"]
        self.assertEqual([item["id"] for item in organizations], [member_organization.pk])
        self.assertEqual(
            member_client.get(
                f"/api/organizations/{self.organization.pk}/projects/{self.open_project.pk}/",
                secure=True,
            ).status_code,
            404,
        )
        owner_record = OrganizationMembership.objects.get(organization=self.organization, user=self.owner)
        self.assertEqual(
            self.request(
                owner,
                "delete",
                f"/api/organizations/{self.organization.pk}/team/members/{owner_record.pk}/",
            ).status_code,
            403,
        )

    def test_accepted_invitation_replay_after_membership_removal_stays_revoked(self):
        invited = self.create_user("removed-invitee@example.com")
        invitation, token = create_invitation(
            organization=self.organization,
            actor=self.owner,
            email=invited.email,
            role=MembershipRole.MEMBER,
            project_ids=[],
        )
        OrganizationMembership.objects.filter(organization=self.organization, user=self.other_member).delete()
        accept_invitation(user=invited, token=token)
        membership = OrganizationMembership.objects.get(organization=self.organization, user=invited)
        owner = self.client_for(self.owner)
        self.assertEqual(
            self.request(
                owner,
                "delete",
                f"/api/organizations/{self.organization.pk}/team/members/{membership.pk}/",
            ).status_code,
            204,
        )
        invitee = self.client_for(invited)
        replay = self.request(invitee, "post", "/api/invitations/accept/", {"token": token})
        self.assertEqual(replay.status_code, 410)
        self.assertEqual(replay.json()["errors"][0]["code"], "revoked")
        self.assertFalse(OrganizationMembership.objects.filter(organization=self.organization, user=invited).exists())
        self.assertEqual(AuditEvent.objects.filter(
            invitation=invitation,
            event_type=AuditEventType.INVITATION_ACCEPTED,
        ).count(), 1)

    def test_team_api_is_scoped_bounded_and_private(self):
        owner = self.client_for(self.owner)
        response = owner.get(f"/api/organizations/{self.organization.pk}/team/", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual({item["email"] for item in response.json()["members"]}, {
            self.owner.email,
            self.member.email,
            self.other_member.email,
        })
        outsider = self.client_for(self.outsider)
        self.assertEqual(
            outsider.get(f"/api/organizations/{self.organization.pk}/team/", secure=True).status_code,
            404,
        )
        staff = self.client_for(self.staff)
        self.assertEqual(
            staff.get(f"/api/organizations/{self.organization.pk}/team/", secure=True).status_code,
            404,
        )
        viewer = self.client_for(self.other_member)
        self.assertEqual(
            self.request(
                viewer,
                "delete",
                f"/api/organizations/{self.organization.pk}/team/members/{self.member_record.pk}/",
            ).status_code,
            404,
        )

    def test_invalid_roles_are_validation_errors_and_database_rejects_noncanonical_invitation_email(self):
        owner = self.client_for(self.owner)
        invalid_invitation = self.request(
            owner,
            "post",
            f"/api/organizations/{self.organization.pk}/team/",
            {"email": "new@example.com", "role": "super-owner"},
        )
        self.assertEqual(invalid_invitation.status_code, 400)
        invalid_membership = self.request(
            owner,
            "patch",
            f"/api/organizations/{self.organization.pk}/team/members/{self.member_record.pk}/",
            {"role": "super-owner"},
        )
        self.assertEqual(invalid_membership.status_code, 400)
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizationInvitation.objects.bulk_create([
                OrganizationInvitation(
                    organization=self.organization,
                    email="MixedCase@example.com",
                    role=MembershipRole.MEMBER,
                    inviter=self.owner,
                    token_digest="a" * 64,
                    expires_at=timezone.now() + timedelta(days=1),
                ),
            ])

    def test_invitation_rate_limit_fails_before_mutation_or_delivery(self):
        owner = self.client_for(self.owner)
        before_events = AuditEvent.objects.count()
        before_messages = len(mail.outbox)
        with patch("tenancy.api.ratelimit.consume", return_value=False):
            response = self.request(
                owner,
                "post",
                f"/api/organizations/{self.organization.pk}/team/",
                {"email": "limited@example.com", "role": MembershipRole.MEMBER},
            )
        self.assertEqual(response.status_code, 429)
        self.assertFalse(OrganizationInvitation.objects.filter(email="limited@example.com").exists())
        self.assertEqual(AuditEvent.objects.count(), before_events)
        self.assertEqual(len(mail.outbox), before_messages)

    def test_team_mutation_rate_limit_fails_before_changes(self):
        owner = self.client_for(self.owner)
        invitation, _ = create_invitation(
            organization=self.organization,
            actor=self.owner,
            email="revoke-limited@example.com",
            role=MembershipRole.MEMBER,
            project_ids=[],
        )
        before_events = AuditEvent.objects.count()
        with patch("tenancy.api.ratelimit.consume", return_value=False):
            member_response = self.request(
                owner,
                "patch",
                f"/api/organizations/{self.organization.pk}/team/members/{self.member_record.pk}/",
                {"role": MembershipRole.VIEWER},
            )
            invitation_response = self.request(
                owner,
                "delete",
                f"/api/organizations/{self.organization.pk}/team/invitations/{invitation.pk}/",
            )
        self.assertEqual(member_response.status_code, 429)
        self.assertEqual(invitation_response.status_code, 429)
        self.member_record.refresh_from_db()
        invitation.refresh_from_db()
        self.assertEqual(self.member_record.role, MembershipRole.MEMBER)
        self.assertEqual(invitation.state, InvitationState.PENDING)
        self.assertEqual(AuditEvent.objects.count(), before_events)

    def test_transfer_requires_both_users_to_reauthenticate_and_explicit_target_acceptance(self):
        trial_id = self.organization.trial.pk
        trial_end = self.organization.trial.ends_at
        owner = self.client_for(self.owner)
        target = self.client_for(self.member)
        path = f"/api/organizations/{self.organization.pk}/ownership/"
        denied = self.request(owner, "post", path, {"member_id": self.member_record.pk})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.request(owner, "post", "/_allauth/browser/v1/auth/reauthenticate", {"password": self.password}).status_code, 200)
        proposed = self.request(owner, "post", path, {"member_id": self.member_record.pk})
        self.assertEqual(proposed.status_code, 201, proposed.content)
        transfer_id = proposed.json()["transfer"]["id"]
        accept_path = f"{path}{transfer_id}/accept/"
        self.assertEqual(self.request(target, "post", accept_path, {}).status_code, 403)
        self.assertEqual(self.request(target, "post", "/_allauth/browser/v1/auth/reauthenticate", {"password": self.password}).status_code, 200)
        self.assertEqual(self.request(target, "post", accept_path, {}).status_code, 200)
        self.assertEqual(self.request(target, "post", accept_path, {}).status_code, 403)
        self.member_record.refresh_from_db()
        self.assertEqual(self.member_record.role, MembershipRole.OWNER)
        self.assertEqual(OrganizationMembership.objects.get(organization=self.organization, user=self.owner).role, MembershipRole.ADMIN)
        self.assertTrue(Project.objects.for_user(self.owner).filter(pk=self.restricted_project.pk).exists())
        self.assertEqual(OwnershipTransfer.objects.get(pk=transfer_id).state, OwnershipTransfer.State.ACCEPTED)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.OWNERSHIP_ACCEPTED).count(), 1)
        self.organization.trial.refresh_from_db()
        self.assertEqual(self.organization.trial.pk, trial_id)
        self.assertEqual(self.organization.trial.ends_at, trial_end)
        self.assertEqual(OrganizationTrial.objects.filter(organization=self.organization).count(), 1)

    def test_last_owner_cannot_leave_demote_remove_or_be_suspended(self):
        owner_record = OrganizationMembership.objects.get(organization=self.organization, user=self.owner)
        admin = self.client_for(self.staff)
        with self.assertRaisesRegex(ValidationError, "last active owner"):
            set_user_suspension(user=self.owner, actor=self.staff, suspended=True, reason="Investigation")
        owner = self.client_for(self.owner)
        self.assertEqual(self.request(owner, "post", "/_allauth/browser/v1/auth/reauthenticate", {"password": self.password}).status_code, 200)
        member_path = f"/api/organizations/{self.organization.pk}/team/members/{owner_record.pk}/"
        self.assertEqual(self.request(owner, "delete", member_path).status_code, 409)
        self.assertEqual(self.request(owner, "patch", member_path, {"role": "admin"}).status_code, 400)
        self.assertEqual(self.request(owner, "post", f"/api/organizations/{self.organization.pk}/leave/", {}).status_code, 409)
        self.assertTrue(OrganizationMembership.objects.filter(pk=owner_record.pk, role=MembershipRole.OWNER).exists())
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.MEMBERSHIP_LEFT).exists())

    def test_recipient_can_decline_and_owner_can_restart_a_transfer(self):
        owner = self.client_for(self.owner)
        target = self.client_for(self.member)
        outsider = self.client_for(self.outsider)
        path = f"/api/organizations/{self.organization.pk}/ownership/"
        self.assertEqual(self.request(owner, "post", "/_allauth/browser/v1/auth/reauthenticate", {"password": self.password}).status_code, 200)
        proposed = self.request(owner, "post", path, {"member_id": self.member_record.pk})
        self.assertEqual(proposed.status_code, 201)
        transfer_id = proposed.json()["transfer"]["id"]
        cancel_path = f"{path}{transfer_id}/"
        self.assertEqual(self.request(outsider, "delete", cancel_path).status_code, 404)
        self.assertEqual(self.request(target, "delete", cancel_path).status_code, 403)
        self.assertEqual(self.request(target, "post", "/_allauth/browser/v1/auth/reauthenticate", {"password": self.password}).status_code, 200)
        self.assertEqual(self.request(target, "delete", cancel_path).status_code, 204)
        self.assertEqual(self.request(target, "delete", cancel_path).status_code, 403)
        self.assertEqual(OrganizationMembership.objects.get(pk=self.member_record.pk).role, MembershipRole.MEMBER)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.OWNERSHIP_CANCELLED).count(), 1)
        self.assertEqual(self.request(owner, "post", path, {"member_id": self.member_record.pk}).status_code, 201)

    def test_suspension_blocks_existing_sessions_without_deleting_other_members_data(self):
        member = self.client_for(self.member)
        staff = self.staff
        suspended = set_organization_suspension(
            organization=self.organization, actor=staff, suspended=True, reason="Support hold", request_id="test-req",
        )
        self.assertTrue(suspended.is_suspended)
        self.assertFalse(Project.objects.for_user(self.member).exists())
        self.assertEqual(member.get(f"/api/organizations/{self.organization.pk}/team/", secure=True).status_code, 404)
        self.assertEqual(member.get("/api/organizations/", secure=True).json()["organizations"][0]["is_suspended"], True)
        with self.assertRaises(PermissionDenied):
            require_organization_action(organization=self.organization, user=self.owner, action=Action.MANAGE_MEMBERS)
        set_organization_suspension(organization=self.organization, actor=staff, suspended=False, reason="Resolved")
        set_user_suspension(user=self.member, actor=staff, suspended=True, reason="Account hold")
        self.assertEqual(member.get("/api/organizations/", secure=True).status_code, 401)
        self.assertFalse(UserSession.objects.filter(user=self.member).exists())
        set_user_suspension(user=self.member, actor=staff, suspended=False, reason="Resolved")
        self.assertEqual(member.get("/api/organizations/", secure=True).status_code, 401)
        self.assertTrue(OrganizationMembership.objects.filter(organization=self.organization, user=self.member).exists())
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.ORGANIZATION_SUSPENDED).count(), 2)
        self.assertTrue(AuditEvent.objects.filter(event_type=AuditEventType.USER_SUSPENDED, subject_user=self.member).exists())

    def test_suspension_pauses_invitation_without_revoking_it(self):
        invited = self.create_user("paused-invitation@example.com")
        invitation, token = create_invitation(
            organization=self.organization, actor=self.owner, email=invited.email,
            role=MembershipRole.VIEWER, project_ids=[],
        )
        client = self.client_for(invited)
        set_organization_suspension(organization=self.organization, actor=self.staff, suspended=True, reason="Hold")
        response = self.request(client, "post", "/api/invitations/accept/", {"token": token})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["errors"][0]["code"], "suspended")
        invitation.refresh_from_db()
        self.assertEqual(invitation.state, InvitationState.PENDING)
        set_organization_suspension(organization=self.organization, actor=self.staff, suspended=False, reason="Resolved")
        OrganizationMembership.objects.filter(organization=self.organization, user=self.other_member).delete()
        self.assertEqual(self.request(client, "post", "/api/invitations/accept/", {"token": token}).status_code, 200)

    def test_platform_suspension_requires_staff_permission_reason_and_owner_safety(self):
        staff = self.client_for(self.staff)
        member = self.client_for(self.member)
        org_path = f"/api/platform/organizations/{self.organization.pk}/suspension/"
        user_path = f"/api/platform/users/{self.owner.pk}/suspension/"
        self.assertEqual(self.request(member, "post", org_path, {"suspended": True, "reason": "hold"}).status_code, 403)
        self.assertEqual(self.request(staff, "post", org_path, {"suspended": True, "reason": " "}).status_code, 400)
        self.assertEqual(self.request(staff, "post", user_path, {"suspended": True, "reason": "hold"}).status_code, 409)
        self.assertEqual(self.request(staff, "post", org_path, {"suspended": True, "reason": "support hold"}).status_code, 200)
        self.assertEqual(self.request(staff, "post", org_path, {"suspended": True, "reason": "same hold"}).status_code, 200)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.ORGANIZATION_SUSPENDED).count(), 1)
        self.assertEqual(self.request(staff, "post", org_path, {"suspended": False, "reason": "resolved"}).status_code, 200)

        password_only_staff = self.client_for(self.staff)
        with override_settings(STAFF_MFA_REQUIRED=True):
            unenrolled = self.request(password_only_staff, "post", org_path, {"suspended": True, "reason": "hold"})
            self.assertEqual(unenrolled.status_code, 403)
            self.assertEqual(unenrolled.json()["errors"][0]["code"], "mfa_required")
            Authenticator.objects.create(user=self.staff, type=Authenticator.Type.TOTP, data={"secret": "test-only"})
            password_only = self.request(password_only_staff, "post", org_path, {"suspended": True, "reason": "hold"})
            self.assertEqual(password_only.status_code, 403)
            self.assertEqual(password_only.json()["errors"][0]["code"], "mfa_authentication_required")

    def test_platform_trial_approval_is_permission_scoped_audited_and_atomic(self):
        pending = create_organization(user=self.owner, name="Pending trial approval")
        path = f"/api/platform/organizations/{pending.pk}/trial/approve/"
        member = self.client_for(self.member)
        staff = self.client_for(self.staff)
        limited_staff = self.client_for(self.create_user("trial-support@example.com", is_staff=True))

        self.assertEqual(self.request(member, "post", path, {"reason": "Approved"}).status_code, 403)
        self.assertEqual(self.request(limited_staff, "post", path, {"reason": "Approved"}).status_code, 403)
        with override_settings(STAFF_MFA_REQUIRED=True):
            denied = self.request(staff, "post", path, {"reason": "Approved"})
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(denied.json()["errors"][0]["code"], "mfa_required")
        correction_request = staff_trial_request(self.staff, staff)
        self.assertEqual(self.request(staff, "post", path, {"reason": " "}).status_code, 400)
        self.assertEqual(self.request(staff, "post", path, {"reason": "x" * 251}).status_code, 400)

        with patch("tenancy.services._audit", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                approve_organization_trial(
                    organization=pending,
                    actor=self.staff,
                    reason="Approved after review",
                    request=correction_request,
                )
        pending.trial.refresh_from_db()
        self.assertEqual(pending.trial.state, TrialState.PENDING_REVIEW)
        self.assertIsNone(pending.trial.started_at)

        response = self.request(staff, "post", path, {"reason": " Approved after review "})
        self.assertEqual(response.status_code, 200)
        pending.trial.refresh_from_db()
        self.assertEqual(pending.trial.state, TrialState.ACTIVE)
        self.assertEqual(pending.trial.ends_at - pending.trial.started_at, timedelta(days=30))
        self.assertIsNone(pending.trial.automatic_eligibility_id)
        event = AuditEvent.objects.get(organization=pending, event_type=AuditEventType.TRIAL_APPROVED)
        self.assertEqual(event.actor, self.staff)
        self.assertEqual(event.details["before"], {"state": TrialState.PENDING_REVIEW, "started_at": None, "ends_at": None})
        self.assertEqual(event.details["reason"], "Approved after review")
        self.assertEqual(self.request(staff, "post", path, {"reason": "Repeat"}).status_code, 409)
        self.assertEqual(AuditEvent.objects.filter(organization=pending, event_type=AuditEventType.TRIAL_APPROVED).count(), 1)

    def test_trial_approval_rechecks_actor_offer_and_trial_presence(self):
        pending = create_organization(user=self.owner, name="Reviewed trial approval")
        permission = Permission.objects.get(codename="change_organizationtrial", content_type__app_label="tenancy")
        actor = self.create_user("stale-trial-support@example.com", is_staff=True)
        actor.user_permissions.add(permission)
        self.assertTrue(actor.has_perm("tenancy.change_organizationtrial"))
        User.objects.get(pk=actor.pk).user_permissions.remove(permission)
        with self.assertRaises(PermissionDenied):
            approve_organization_trial(organization=pending, actor=actor, reason="Approved", request=staff_trial_request(actor))

        accepted = {
            "offer_version": "agency-launch-v1",
            "project_limit": 1,
            "member_limit": 3,
            "unit_limit": 40,
        }
        for field, value in (
            ("offer_version", "legacy-offer"),
            ("project_limit", 2),
            ("member_limit", 4),
            ("unit_limit", 41),
        ):
            with self.subTest(field=field):
                OrganizationTrial.objects.filter(organization=pending).update(**(accepted | {field: value}))
                with self.assertRaises(ValidationError):
                    approve_organization_trial(organization=pending, actor=self.staff, reason="Approved", request=staff_trial_request(self.staff))
                self.assertFalse(AuditEvent.objects.filter(
                    organization=pending,
                    event_type=AuditEventType.TRIAL_APPROVED,
                ).exists())

        missing = Organization.objects.create(name="Organization without trial")
        response = self.request(
            self.trial_client(),
            "post",
            f"/api/platform/organizations/{missing.pk}/trial/approve/",
            {"reason": "Approved"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(AuditEvent.objects.filter(organization=missing).exists())

    def test_platform_trial_extension_is_bounded_audited_and_atomic(self):
        trial = self.organization.trial
        started_at = timezone.now() - timedelta(days=31)
        original_end = started_at + timedelta(days=30)
        OrganizationTrial.objects.filter(pk=trial.pk).update(
            state=TrialState.READ_ONLY,
            started_at=started_at,
            ends_at=original_end,
        )
        path = f"/api/platform/organizations/{self.organization.pk}/trial/extend/"
        member = self.client_for(self.member)
        staff = self.client_for(self.staff)
        correction_request = staff_trial_request(self.staff, staff)

        self.assertEqual(self.request(member, "post", path, {"reason": "Support correction"}).status_code, 403)
        self.assertEqual(self.request(staff, "post", path, {"reason": " "}).status_code, 400)
        with patch("tenancy.services._audit", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                extend_organization_trial(
                    organization=self.organization,
                    actor=self.staff,
                    reason="Support correction",
                    request=correction_request,
                )
        trial.refresh_from_db()
        self.assertEqual(trial.state, TrialState.READ_ONLY)
        self.assertEqual(trial.ends_at, original_end)

        response = self.request(staff, "post", path, {"reason": " Support correction "})
        self.assertEqual(response.status_code, 200)
        trial.refresh_from_db()
        self.assertEqual(trial.state, TrialState.ACTIVE)
        self.assertEqual(trial.started_at, started_at)
        self.assertEqual(trial.ends_at, started_at + timedelta(days=37))
        self.assertEqual(response.json()["trial"]["ends_at"], trial.ends_at.isoformat())
        event = AuditEvent.objects.get(organization=self.organization, event_type=AuditEventType.TRIAL_EXTENDED)
        self.assertEqual(event.actor, self.staff)
        self.assertEqual(event.details["before"], {"state": TrialState.READ_ONLY, "ends_at": original_end.isoformat()})
        self.assertEqual(event.details["reason"], "Support correction")
        self.assertEqual(event.details["extension_days"], 7)
        self.assertEqual(self.request(staff, "post", path, {"reason": "Repeat"}).status_code, 409)

    def test_trial_extension_rechecks_actor_policy_suspension_and_deadline(self):
        permission = Permission.objects.get(codename="change_organizationtrial", content_type__app_label="tenancy")
        actor = self.create_user("stale-extension-support@example.com", is_staff=True)
        actor.user_permissions.add(permission)
        User.objects.get(pk=actor.pk).user_permissions.remove(permission)
        with self.assertRaises(PermissionDenied):
            extend_organization_trial(organization=self.organization, actor=actor, reason="Correction", request=staff_trial_request(actor))

        accepted = {
            "offer_version": "agency-launch-v1",
            "project_limit": 1,
            "member_limit": 3,
            "unit_limit": 40,
            "state": TrialState.ACTIVE,
            "started_at": timezone.now(),
        }
        for field, value in (
            ("offer_version", "legacy-offer"),
            ("project_limit", 2),
            ("member_limit", 4),
            ("unit_limit", 41),
            ("state", TrialState.SUSPENDED),
        ):
            with self.subTest(field=field):
                started_at = accepted["started_at"]
                OrganizationTrial.objects.filter(organization=self.organization).update(
                    **(accepted | {field: value, "ends_at": started_at + timedelta(days=30)})
                )
                with self.assertRaises(ValidationError):
                    extend_organization_trial(
                        organization=self.organization,
                        actor=self.staff,
                        reason="Correction",
                        request=staff_trial_request(self.staff),
                    )

        too_old = timezone.now() - timedelta(days=38)
        OrganizationTrial.objects.filter(organization=self.organization).update(
            **(accepted | {"started_at": too_old, "ends_at": too_old + timedelta(days=30)})
        )
        with self.assertRaises(ValidationError):
            extend_organization_trial(organization=self.organization, actor=self.staff, reason="Too late", request=staff_trial_request(self.staff))

        OrganizationTrial.objects.filter(organization=self.organization).update(
            **(accepted | {"started_at": accepted["started_at"], "ends_at": accepted["started_at"] + timedelta(days=30)})
        )
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True)
        with self.assertRaises(ValidationError):
            extend_organization_trial(organization=self.organization, actor=self.staff, reason="Suspended", request=staff_trial_request(self.staff))
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.TRIAL_EXTENDED).exists())

    def test_subscription_identity_blocks_trial_extension_without_mutating_history(self):
        subscription = PaddleSubscription.objects.create(
            organization=self.organization,
            environment=PaddleEnvironment.SANDBOX,
            customer_id="ctm_" + "a" * 26,
            subscription_id="sub_" + "b" * 26,
            status=PaddleStatus.CANCELED,
        )
        trial = self.organization.trial
        original_end = trial.ends_at
        response = self.request(
            self.trial_client(), "post",
            f"/api/platform/organizations/{self.organization.pk}/trial/extend/", {"reason": "Correction"},
        )
        self.assertEqual(response.status_code, 409)
        trial.refresh_from_db()
        self.assertEqual(trial.ends_at, original_end)
        self.assertFalse(AuditEvent.objects.filter(
            organization=self.organization, event_type=AuditEventType.TRIAL_EXTENDED,
        ).exists())
        self.assertEqual(subscription.organization_id, self.organization.pk)

        with self.assertRaises(IntegrityError), transaction.atomic():
            PaddleSubscription.objects.create(
                organization=self.other_organization,
                environment=subscription.environment,
                customer_id=subscription.customer_id,
                subscription_id="sub_" + "c" * 26,
                status=PaddleStatus.ACTIVE,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaddleSubscription.objects.create(
                organization=self.other_organization,
                environment=subscription.environment,
                customer_id="ctm_" + "d" * 26,
                subscription_id=subscription.subscription_id,
                status=PaddleStatus.ACTIVE,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaddleSubscription.objects.filter(pk=subscription.pk).update(status="paid")
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaddleSubscription.objects.filter(pk=subscription.pk).update(environment="staging")

        # A different organization is unaffected by the linked subscription.
        extended = extend_organization_trial(
            organization=self.other_organization, actor=self.staff, reason="Correction", request=staff_trial_request(self.staff),
        )
        self.assertEqual(extended.ends_at, extended.started_at + timedelta(days=37))

    def test_linked_subscription_cannot_start_a_pending_trial(self):
        pending = create_organization(user=self.owner, name="Pending with subscription")
        self.assertEqual(pending.trial.state, TrialState.PENDING_REVIEW)
        PaddleSubscription.objects.create(
            organization=pending, environment=PaddleEnvironment.SANDBOX,
            customer_id="ctm_" + "e" * 26, subscription_id="sub_" + "f" * 26,
            status=PaddleStatus.PAST_DUE,
        )
        response = self.request(
            self.trial_client(), "post",
            f"/api/platform/organizations/{pending.pk}/trial/approve/", {"reason": "Correction"},
        )
        self.assertEqual(response.status_code, 409)
        pending.trial.refresh_from_db()
        self.assertIsNone(pending.trial.started_at)
        self.assertFalse(AuditEvent.objects.filter(organization=pending, event_type=AuditEventType.TRIAL_APPROVED).exists())
        self.assertEqual(self.other_organization.trial.state, TrialState.ACTIVE)

    def test_trial_extension_restores_expired_without_resetting_limits_or_usage(self):
        started_at = timezone.now() - timedelta(days=31)
        original_end = started_at + timedelta(days=30)
        OrganizationTrial.objects.filter(organization=self.organization).update(
            state=TrialState.EXPIRED,
            started_at=started_at,
            ends_at=original_end,
        )
        job = JobRun.objects.create(
            organization=self.organization,
            project=self.open_project,
            actor=self.owner,
            handler="diagnostic_probe",
            method_version="trial-extension-test",
            input_snapshot={"sample": "trial-extension"},
        )
        reservation = UsageReservation.objects.create(
            job=job,
            organization=self.organization,
            project=self.open_project,
            provider="synthetic",
            period_start=timezone.localdate().replace(day=1),
            reserved_units=6,
            actual_units=4,
            state=UsageReservation.State.SETTLED,
            settled_at=timezone.now(),
        )

        trial = extend_organization_trial(
            organization=self.organization,
            actor=self.staff,
            reason="Restore remaining support extension",
            request=staff_trial_request(self.staff),
        )

        self.assertEqual(trial.state, TrialState.ACTIVE)
        self.assertEqual(trial.started_at, started_at)
        self.assertEqual(trial.ends_at, started_at + timedelta(days=37))
        self.assertEqual((trial.project_limit, trial.member_limit, trial.unit_limit), (1, 3, 40))
        reservation.refresh_from_db()
        self.assertEqual((reservation.reserved_units, reservation.actual_units, reservation.state), (6, 4, UsageReservation.State.SETTLED))
        payload = self.client_for(self.owner).get(
            f"/api/organizations/{self.organization.pk}/", secure=True,
        ).json()["organization"]["trial"]
        self.assertEqual((payload["settled_units"], payload["reserved_units"]), (4, 0))

    def test_unattached_user_suspension_is_audited_and_rolls_back_on_audit_failure(self):
        unattached = self.create_user("unattached@example.com")
        with patch("tenancy.services._audit", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                set_user_suspension(user=unattached, actor=self.staff, suspended=True, reason="Support hold")
        unattached.refresh_from_db()
        self.assertTrue(unattached.is_active)
        set_user_suspension(user=unattached, actor=self.staff, suspended=True, reason="Support hold")
        event = AuditEvent.objects.get(subject_user=unattached, event_type=AuditEventType.USER_SUSPENDED)
        self.assertIsNone(event.organization_id)
        self.assertEqual(event.details, {"before": True, "after": False, "reason": "Support hold"})

    def test_transfer_rollback_and_wrong_tenant_proposal_leave_state_unchanged(self):
        owner = self.client_for(self.owner)
        self.assertEqual(self.request(owner, "post", "/_allauth/browser/v1/auth/reauthenticate", {"password": self.password}).status_code, 200)
        with patch("tenancy.services._audit", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                self.request(owner, "post", f"/api/organizations/{self.organization.pk}/ownership/", {"member_id": self.member_record.pk})
        self.assertFalse(OwnershipTransfer.objects.filter(organization=self.organization).exists())
        wrong_member = OrganizationMembership.objects.get(organization=self.other_organization, user=self.outsider)
        self.assertEqual(self.request(owner, "post", f"/api/organizations/{self.organization.pk}/ownership/", {"member_id": wrong_member.pk}).status_code, 404)
        self.assertEqual(self.request(owner, "post", f"/api/organizations/{self.organization.pk}/ownership/", {"member_id": True}).status_code, 400)

    def test_staff_admin_inspection_is_permission_scoped_and_never_edits_owner_or_displays_secrets(self):
        invitation, _ = create_invitation(
            organization=self.organization, actor=self.owner, email="admin-invite@example.com",
            role=MembershipRole.VIEWER, project_ids=[],
        )
        customer = self.client_for(self.owner)
        organization_url = f"/admin/tenancy/organization/{self.organization.pk}/change/"
        self.assertEqual(customer.get(organization_url, secure=True).status_code, 302)

        limited = self.create_user("limited-staff@example.com", is_staff=True)
        limited.user_permissions.add(Permission.objects.get(codename="view_organization", content_type__app_label="tenancy"))
        limited_client = self.client_for(limited)
        self.assertEqual(limited_client.get(organization_url, secure=True).status_code, 200)
        self.assertEqual(limited_client.get(f"/admin/tenancy/project/{self.open_project.pk}/change/", secure=True).status_code, 403)
        self.assertEqual(self.request(limited_client, "post", organization_url, {"is_suspended": True}).status_code, 403)

        staff = self.client_for(self.staff)
        self.assertEqual(staff.get(organization_url, secure=True).status_code, 200)
        self.assertEqual(self.request(staff, "post", organization_url, {"is_suspended": True}).status_code, 403)
        self.organization.refresh_from_db()
        self.assertFalse(self.organization.is_suspended)
        user_view = staff.get(f"/admin/accounts/user/{self.owner.pk}/change/", secure=True)
        self.assertEqual(user_view.status_code, 200)
        self.assertNotIn(self.owner.password, user_view.content.decode())
        invitation_view = staff.get(f"/admin/tenancy/organizationinvitation/{invitation.pk}/change/", secure=True)
        self.assertEqual(invitation_view.status_code, 200)
        self.assertNotIn(invitation.token_digest, invitation_view.content.decode())


class TrialAllowanceTests(TestCase):
    unavailable_cases = (
        "missing", "pending", "expired", "read_only", "suspended", "elapsed",
        "drifted_offer", "drifted_project_limit", "drifted_member_limit", "drifted_unit_limit",
        "shortened", "day_31", "unaudited_extension", "day_38",
    )

    def setUp(self):
        self.password = f"A-{secrets.token_urlsafe(24)}"

    def create_organization(self, suffix):
        owner = User.objects.create_user(email=f"allowance-{suffix}@example.com", password=self.password)
        EmailAddress.objects.create(user=owner, email=owner.email, verified=True, primary=True)
        return owner, create_organization(user=owner, name=f"Allowance {suffix}")

    def create_user(self, suffix):
        user = User.objects.create_user(email=f"allowance-{suffix}@example.net", password=self.password)
        EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        return user

    def unavailable_organization(self, prefix, case):
        owner, organization = self.create_organization(f"{prefix}-{case}")
        trial = organization.trial
        if case == "missing":
            trial.delete()
        elif case == "pending":
            organization = create_organization(user=owner, name=f"Pending {prefix}")
        elif case in {"expired", "read_only", "suspended"}:
            OrganizationTrial.objects.filter(pk=trial.pk).update(state=case)
        elif case == "elapsed":
            start = timezone.now() - timedelta(days=31)
            OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=start, ends_at=start + timedelta(days=30))
        elif case.startswith("drifted_"):
            field = case.removeprefix("drifted_")
            OrganizationTrial.objects.filter(pk=trial.pk).update(**{
                "offer": {"offer_version": "drifted-offer"},
                "project_limit": {"project_limit": 2},
                "member_limit": {"member_limit": 4},
                "unit_limit": {"unit_limit": 41},
            }[field])
        else:
            days = {"shortened": 29, "day_31": 31, "unaudited_extension": 37, "day_38": 38}[case]
            OrganizationTrial.objects.filter(pk=trial.pk).update(ends_at=trial.started_at + timedelta(days=days))
        return owner, organization

    def test_project_creation_enforces_the_exact_trial_limit(self):
        owner, organization = self.create_organization("project-limit")
        project = create_project(
            organization=organization,
            user=owner,
            name="Allowed",
            canonical_origin="https://allowed.example.com",
        )

        with self.assertRaises(TrialAllowanceError) as caught:
            create_project(
                organization=organization,
                user=owner,
                name="Denied",
                canonical_origin="https://denied.example.com",
            )

        self.assertEqual(caught.exception.code, "project_limit")
        self.assertEqual(list(Project.objects.filter(organization=organization)), [project])

        client = Client()
        client.force_login(owner)
        response = client.post(
            f"/api/organizations/{organization.pk}/projects/",
            data=json.dumps({"name": "Also denied", "canonical_origin": "https://also-denied.example.com"}),
            content_type="application/json",
            secure=True,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["errors"][0]["code"], "project_limit")
        self.assertEqual(response.json()["errors"][0]["message"], "Trial project limit reached.")

    @override_settings(PADDLE_ENVIRONMENT="sandbox")
    def test_verified_paid_project_and_member_limits_preserve_trial_and_expiry_boundaries(self):
        owner, organization = self.create_organization("paid-resources")
        create_project(organization=organization, user=owner, name="Trial project",
                       canonical_origin="https://paid-first.example.com")
        now = timezone.now()
        subscription = PaddleSubscription.objects.create(
            organization=organization, environment=PaddleEnvironment.SANDBOX,
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26,
            status=PaddleStatus.ACTIVE, verified_at=now, currency_code="USD",
            period_starts_at=now - timedelta(days=1), period_ends_at=now + timedelta(days=29),
        )
        for number in (2, 3):
            create_project(organization=organization, user=owner, name=f"Paid {number}",
                           canonical_origin=f"https://paid-{number}.example.com")
        with self.assertRaises(TrialAllowanceError) as full:
            create_project(organization=organization, user=owner, name="Fourth",
                           canonical_origin="https://paid-fourth.example.com")
        self.assertEqual(full.exception.code, "project_limit")
        for number in range(8):
            user = self.create_user(f"paid-member-{number}")
            OrganizationMembership.objects.create(organization=organization, user=user, role=MembershipRole.MEMBER)
        invited = self.create_user("paid-member-nine")
        _, token = create_invitation(organization=organization, actor=owner,
            email=invited.email, role=MembershipRole.MEMBER, project_ids=[])
        self.assertTrue(accept_invitation(user=invited, token=token)[2])
        extra = self.create_user("paid-member-ten")
        _, extra_token = create_invitation(organization=organization, actor=owner,
            email=extra.email, role=MembershipRole.MEMBER, project_ids=[])
        with self.assertRaises(InvitationError) as full_members:
            accept_invitation(user=extra, token=extra_token)
        self.assertEqual(full_members.exception.code, "member_limit")
        self.assertEqual(OrganizationMembership.objects.filter(organization=organization).count(), 10)
        PaddleSubscription.objects.filter(pk=subscription.pk).update(period_ends_at=now - timedelta(seconds=1))
        with self.assertRaises(TrialAllowanceError) as expired:
            create_project(organization=organization, user=owner, name="After expiry",
                           canonical_origin="https://paid-expired.example.com")
        self.assertEqual(expired.exception.code, "paid_unavailable")
        self.assertEqual(Project.objects.filter(organization=organization).count(), 3)

    def test_project_creation_fails_closed_for_unavailable_or_drifted_trials(self):
        for case in self.unavailable_cases:
            with self.subTest(case=case):
                owner, organization = self.unavailable_organization("project", case)

                with self.assertRaises(TrialAllowanceError) as caught:
                    create_project(
                        organization=organization,
                        user=owner,
                        name="Unavailable",
                        canonical_origin=f"https://{case.replace('_', '-')}.example.com",
                    )
                self.assertEqual(caught.exception.code, "trial_unavailable")
                self.assertFalse(Project.objects.filter(organization=organization).exists())

        owner, organization = self.create_organization("organization-suspended")
        Organization.objects.filter(pk=organization.pk).update(is_suspended=True)
        with self.assertRaises(PermissionDenied):
            create_project(
                organization=organization,
                user=owner,
                name="Suspended",
                canonical_origin="https://suspended.example.com",
            )

    def test_audited_extension_retains_project_capacity(self):
        owner, organization = self.create_organization("audited-extension")
        staff = User.objects.create_superuser(email="allowance-extension-staff@example.com", password=self.password)
        start = timezone.now() - timedelta(days=31)
        OrganizationTrial.objects.filter(organization=organization).update(
            state=TrialState.READ_ONLY,
            started_at=start,
            ends_at=start + timedelta(days=30),
        )
        extend_organization_trial(organization=organization, actor=staff, reason="Verified support correction", request=staff_trial_request(staff))

        project = create_project(
            organization=organization,
            user=owner,
            name="Extended",
            canonical_origin="https://extended.example.com",
        )

        self.assertEqual(project.organization, organization)

    def test_invitation_acceptance_enforces_membership_limit_and_removal_reopens_capacity(self):
        owner, organization = self.create_organization("member-limit")
        inactive = self.create_user("inactive")
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        OrganizationMembership.objects.create(
            organization=organization, user=inactive, role=MembershipRole.VIEWER,
        )
        first = self.create_user("first")
        second = self.create_user("second")
        first_invitation, first_token = create_invitation(
            organization=organization, actor=owner, email=first.email,
            role=MembershipRole.MEMBER, project_ids=[],
        )
        second_invitation, second_token = create_invitation(
            organization=organization, actor=owner, email=second.email,
            role=MembershipRole.MEMBER, project_ids=[],
        )

        self.assertTrue(accept_invitation(user=first, token=first_token)[2])
        with self.assertRaises(InvitationError) as caught:
            accept_invitation(user=second, token=second_token)
        self.assertEqual(caught.exception.code, "member_limit")
        second_invitation.refresh_from_db()
        self.assertEqual(second_invitation.state, InvitationState.PENDING)

        client = Client()
        client.force_login(second)
        response = client.post(
            "/api/invitations/accept/",
            data=json.dumps({"token": second_token}),
            content_type="application/json",
            secure=True,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["errors"][0]["code"], "member_limit")
        self.assertEqual(response.json()["errors"][0]["message"], "Trial member limit reached.")

        remove_membership(
            membership=OrganizationMembership.objects.get(organization=organization, user=first),
            actor=owner,
        )
        self.assertTrue(accept_invitation(user=second, token=second_token)[2])
        self.assertFalse(accept_invitation(user=second, token=second_token)[2])
        self.assertEqual(OrganizationMembership.objects.filter(organization=organization).count(), 3)
        self.assertEqual(AuditEvent.objects.filter(
            invitation__in=[first_invitation, second_invitation],
            event_type=AuditEventType.INVITATION_ACCEPTED,
        ).count(), 2)

    def test_invitation_acceptance_fails_closed_for_unavailable_or_drifted_trials(self):
        cases = ("missing", "pending", "expired", "read_only", "suspended", "elapsed",
                 "drifted_member_limit", "unaudited_extension")
        for case in cases:
            with self.subTest(case=case):
                owner, organization = self.unavailable_organization("member", case)
                invited = self.create_user(f"{case}-invited")
                invitation, token = create_invitation(
                    organization=organization, actor=owner, email=invited.email,
                    role=MembershipRole.MEMBER, project_ids=[],
                )

                with self.assertRaises(InvitationError) as caught:
                    accept_invitation(user=invited, token=token)

                self.assertEqual(caught.exception.code, "trial_unavailable")
                invitation.refresh_from_db()
                self.assertEqual(invitation.state, InvitationState.PENDING)
                self.assertFalse(OrganizationMembership.objects.filter(
                    organization=organization, user=invited,
                ).exists())

    def test_pending_invitation_cannot_grant_project_access_to_an_existing_member_after_expiry(self):
        owner, organization = self.create_organization("existing-member-expiry")
        project = create_project(
            organization=organization,
            user=owner,
            name="Restricted",
            canonical_origin="https://existing-member.example.com",
            access_restricted=True,
        )
        invited = self.create_user("existing-member")
        invitation, token = create_invitation(
            organization=organization, actor=owner, email=invited.email,
            role=MembershipRole.MEMBER, project_ids=[project.pk],
        )
        membership = OrganizationMembership.objects.create(
            organization=organization, user=invited, role=MembershipRole.MEMBER,
        )
        start = timezone.now() - timedelta(days=31)
        OrganizationTrial.objects.filter(organization=organization).update(
            started_at=start, ends_at=start + timedelta(days=30),
        )

        with self.assertRaises(InvitationError) as caught:
            accept_invitation(user=invited, token=token)

        self.assertEqual(caught.exception.code, "trial_unavailable")
        invitation.refresh_from_db()
        self.assertEqual(invitation.state, InvitationState.PENDING)
        self.assertFalse(ProjectMembership.objects.filter(
            project=project, organization_membership=membership,
        ).exists())


class ProjectConfigurationRaceTests(TransactionTestCase):
    reset_sequences = True

    def test_concurrent_first_save_accepts_one_revision(self):
        user = User.objects.create_user(email="configuration-race@example.com", password=f"A-{secrets.token_urlsafe(24)}")
        EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        organization = create_organization(user=user, name="Configuration race")
        project = Project.objects.create(
            organization=organization,
            name="Configuration project",
            canonical_origin="https://configuration-race.example",
        )
        barrier = Barrier(2)

        def save(country):
            close_old_connections()
            try:
                thread_user = User.objects.get(pk=user.pk)
                thread_project = Project.objects.get(pk=project.pk)
                barrier.wait(timeout=5)
                try:
                    update_project_configuration(
                        project=thread_project,
                        user=thread_user,
                        expected_revision=0,
                        changes={"target_country": country},
                    )
                    return "saved"
                except ConfigurationConflict:
                    return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(save, ["First", "Second"]))
        self.assertCountEqual(results, ["saved", "conflict"])
        configuration = ProjectConfiguration.objects.get(project=project)
        self.assertEqual(configuration.revision, 1)
        self.assertIn(configuration.target_country, {"First", "Second"})


class DomainAliasRaceTests(TransactionTestCase):
    reset_sequences = True

    def test_concurrent_duplicate_alias_has_one_winner(self):
        organization = Organization.objects.create(name="Race organization")
        first = Project.objects.create(
            organization=organization,
            name="First",
            canonical_origin="https://first.example.com",
        )
        second = Project.objects.create(
            organization=organization,
            name="Second",
            canonical_origin="https://second.example.com",
        )
        barrier = Barrier(2)

        def insert(project_id):
            close_old_connections()
            try:
                project = Project.objects.get(pk=project_id)
                organization = Organization.objects.get(pk=project.organization_id)
                barrier.wait(timeout=5)
                try:
                    with transaction.atomic():
                        DomainAlias.objects.create(
                            organization=organization,
                            project=project,
                            origin="https://shared.example.com",
                        )
                    return "created"
                except (IntegrityError, ValidationError):
                    return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(insert, [first.pk, second.pk]))
        self.assertCountEqual(results, ["created", "conflict"])
        self.assertEqual(DomainAlias.objects.filter(origin="https://shared.example.com").count(), 1)

    def test_service_level_canonical_alias_race_has_one_winner(self):
        password = f"A-{secrets.token_urlsafe(24)}"
        owner = User.objects.create_user(email="race-owner@example.com", password=password)
        EmailAddress.objects.create(user=owner, email=owner.email, verified=True, primary=True)
        organization = create_organization(user=owner, name="Service race")
        project = Project.objects.create(
            organization=organization,
            name="Existing",
            canonical_origin="https://existing.example.com",
        )
        second_project = Project.objects.create(
            organization=organization,
            name="Second",
            canonical_origin="https://second.example.com",
        )
        barrier = Barrier(2)

        def insert(kind):
            close_old_connections()
            try:
                thread_owner = User.objects.get(pk=owner.pk)
                thread_organization = Organization.objects.get(pk=organization.pk)
                barrier.wait(timeout=5)
                try:
                    if kind == "canonical":
                        update_project(
                            project=Project.objects.get(pk=project.pk),
                            user=thread_owner,
                            canonical_origin="https://contended.example.com",
                        )
                    else:
                        update_project(
                            project=Project.objects.get(pk=second_project.pk),
                            user=thread_owner,
                            aliases=["https://contended.example.com"],
                        )
                    return "created"
                except (IntegrityError, ValidationError):
                    return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(insert, ["canonical", "alias"]))
        self.assertCountEqual(results, ["created", "conflict"])
        configured = Project.objects.filter(
            organization=organization,
            canonical_origin="https://contended.example.com",
        ).count() + DomainAlias.objects.filter(
            organization=organization,
            origin="https://contended.example.com",
        ).count()
        self.assertEqual(configured, 1)


class OrganizationTrialRaceTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.password = f"A-{secrets.token_urlsafe(24)}"
        self.user = User.objects.create_user(email="trial-race@example.com", password=self.password)
        EmailAddress.objects.create(user=self.user, email=self.user.email, verified=True, primary=True)

    def test_concurrent_organization_creation_grants_one_automatic_trial(self):
        barrier = Barrier(2)

        def create(index):
            close_old_connections()
            try:
                user = User.objects.get(pk=self.user.pk)
                barrier.wait(timeout=5)
                organization = create_organization(user=user, name=f"Concurrent {index}")
                return organization.trial.state
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            states = list(executor.map(create, range(2)))

        self.assertCountEqual(states, [TrialState.ACTIVE, TrialState.PENDING_REVIEW])
        self.assertEqual(AutomaticTrialEligibility.objects.filter(user=self.user).count(), 1)
        self.assertEqual(OrganizationTrial.objects.filter(organization__name__startswith="Concurrent").count(), 2)
        self.assertEqual(
            AuditEvent.objects.filter(
                event_type__in=[AuditEventType.TRIAL_GRANTED, AuditEventType.TRIAL_REVIEW_REQUIRED],
                actor=self.user,
            ).count(),
            2,
        )


class TrialApprovalRaceTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        cache.clear()
        self.password = f"A-{secrets.token_urlsafe(24)}"
        self.owner = User.objects.create_user(email="approval-race-owner@example.com", password=self.password)
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        create_organization(user=self.owner, name="Automatic trial")
        self.pending = create_organization(user=self.owner, name="Pending approval")
        self.staff = User.objects.create_superuser(email="approval-race-staff@example.com", password=self.password)
        self.requests = [staff_trial_request(self.staff) for _ in range(2)]

    def test_concurrent_approval_starts_pending_trial_once(self):
        barrier = Barrier(2)

        def approve(index):
            close_old_connections()
            try:
                organization = Organization.objects.get(pk=self.pending.pk)
                actor = User.objects.get(pk=self.staff.pk)
                barrier.wait(timeout=5)
                try:
                    approve_organization_trial(
                        organization=organization,
                        actor=actor,
                        reason=f"Approved {index}",
                        request=self.requests[index],
                    )
                    return "approved"
                except ValidationError:
                    return "already_approved"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(approve, range(2)))

        self.assertCountEqual(results, ["approved", "already_approved"])
        self.pending.trial.refresh_from_db()
        self.assertEqual(self.pending.trial.state, TrialState.ACTIVE)
        self.assertEqual(self.pending.trial.ends_at - self.pending.trial.started_at, timedelta(days=30))
        self.assertEqual(
            AuditEvent.objects.filter(
                organization=self.pending,
                event_type=AuditEventType.TRIAL_APPROVED,
            ).count(),
            1,
        )


class TrialExtensionRaceTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.password = f"A-{secrets.token_urlsafe(24)}"
        self.owner = User.objects.create_user(email="extension-race-owner@example.com", password=self.password)
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        self.organization = create_organization(user=self.owner, name="Extension race")
        self.staff = User.objects.create_superuser(email="extension-race-staff@example.com", password=self.password)
        self.requests = [staff_trial_request(self.staff) for _ in range(2)]

    def test_concurrent_extension_changes_end_once(self):
        original_end = self.organization.trial.ends_at
        barrier = Barrier(2)

        def extend(index):
            close_old_connections()
            try:
                organization = Organization.objects.get(pk=self.organization.pk)
                actor = User.objects.get(pk=self.staff.pk)
                barrier.wait(timeout=5)
                try:
                    extend_organization_trial(
                        organization=organization,
                        actor=actor,
                        reason=f"Correction {index}",
                        request=self.requests[index],
                    )
                    return "extended"
                except ValidationError:
                    return "already_extended"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(extend, range(2)))

        self.assertCountEqual(results, ["extended", "already_extended"])
        self.organization.trial.refresh_from_db()
        self.assertEqual(self.organization.trial.ends_at, original_end + timedelta(days=7))
        self.assertEqual(
            AuditEvent.objects.filter(
                organization=self.organization,
                event_type=AuditEventType.TRIAL_EXTENDED,
            ).count(),
            1,
        )


class InvitationRaceTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        cache.clear()
        self.password = f"A-{secrets.token_urlsafe(24)}"
        self.owner = User.objects.create_user(email="invite-race-owner@example.com", password=self.password)
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        self.invited = User.objects.create_user(email="invite-race-user@example.com", password=self.password)
        EmailAddress.objects.create(user=self.invited, email=self.invited.email, verified=True, primary=True)
        self.organization = create_organization(user=self.owner, name="Invitation race")

    @patch("tenancy.services.did_recently_authenticate", return_value=True)
    def test_invitation_authenticated_before_personal_closure_cannot_join_after_closure_commits(self, _reauth):
        from threading import Event
        from accounts.closure import close_personal_access
        from django.db import transaction
        from django.test import RequestFactory
        _, token = create_invitation(organization=self.organization, actor=self.owner,
            email=self.invited.email, role=MembershipRole.MEMBER, project_ids=[])
        started = Event()
        request = RequestFactory().post("/api/account/close/")
        request.user = self.invited

        def accept_stale_actor():
            close_old_connections()
            try:
                started.set()
                try:
                    accept_invitation(user=self.invited, token=token)
                    return "joined"
                except InvitationError as error:
                    return error.code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with patch("accounts.closure.end_sessions"), transaction.atomic():
                close_personal_access(actor=self.invited, request=request)
                result = executor.submit(accept_stale_actor)
                self.assertTrue(started.wait(timeout=5))
            self.assertEqual(result.result(timeout=10), "invalid")
        self.assertFalse(OrganizationMembership.objects.filter(user=self.invited).exists())
        self.assertFalse(AuditEvent.objects.filter(actor=self.invited,
                         event_type=AuditEventType.INVITATION_ACCEPTED).exists())

    def test_concurrent_acceptance_creates_one_membership_and_one_audit_event(self):
        trial_id = self.organization.trial.id
        trial_ends_at = self.organization.trial.ends_at
        eligibility_id = self.organization.trial.automatic_eligibility_id
        invitation, token = create_invitation(
            organization=self.organization,
            actor=self.owner,
            email=self.invited.email,
            role=MembershipRole.MEMBER,
            project_ids=[],
        )
        barrier = Barrier(2)

        def accept(_):
            close_old_connections()
            try:
                user = User.objects.get(pk=self.invited.pk)
                barrier.wait(timeout=5)
                try:
                    return accept_invitation(user=user, token=token)[2]
                except InvitationError as error:
                    return error.code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(accept, range(2)))
        self.assertCountEqual(results, [True, False])
        self.assertEqual(
            OrganizationMembership.objects.filter(organization=self.organization, user=self.invited).count(),
            1,
        )
        self.assertEqual(
            AuditEvent.objects.filter(
                invitation=invitation,
                event_type=AuditEventType.INVITATION_ACCEPTED,
            ).count(),
            1,
        )
        self.organization.trial.refresh_from_db()
        self.assertEqual(
            (
                self.organization.trial.id,
                self.organization.trial.ends_at,
                self.organization.trial.automatic_eligibility_id,
            ),
            (trial_id, trial_ends_at, eligibility_id),
        )
        self.assertFalse(AutomaticTrialEligibility.objects.filter(user=self.invited).exists())

    def test_concurrent_invitations_cannot_take_the_same_final_seat(self):
        seat_holder = User.objects.create_user(email="seat-holder@example.com", password=self.password)
        OrganizationMembership.objects.create(
            organization=self.organization, user=seat_holder, role=MembershipRole.VIEWER,
        )
        other = User.objects.create_user(email="second-invite-race@example.com", password=self.password)
        EmailAddress.objects.create(user=other, email=other.email, verified=True, primary=True)
        invitations = [
            create_invitation(
                organization=self.organization,
                actor=self.owner,
                email=user.email,
                role=MembershipRole.MEMBER,
                project_ids=[],
            )
            for user in (self.invited, other)
        ]
        barrier = Barrier(2)

        def accept(index):
            close_old_connections()
            try:
                user = User.objects.get(pk=(self.invited.pk, other.pk)[index])
                barrier.wait(timeout=5)
                try:
                    return accept_invitation(user=user, token=invitations[index][1])[2]
                except InvitationError as error:
                    return error.code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(accept, range(2)))

        self.assertCountEqual(results, [True, "member_limit"])
        self.assertEqual(OrganizationMembership.objects.filter(organization=self.organization).count(), 3)
        self.assertCountEqual(
            OrganizationInvitation.objects.filter(
                pk__in=[invitation.pk for invitation, _ in invitations],
            ).values_list("state", flat=True),
            [InvitationState.ACCEPTED, InvitationState.PENDING],
        )
        self.assertEqual(AuditEvent.objects.filter(
            invitation_id__in=[invitation.pk for invitation, _ in invitations],
            event_type=AuditEventType.INVITATION_ACCEPTED,
        ).count(), 1)

    def test_acceptance_serializes_with_inviter_demotion(self):
        admin = User.objects.create_user(email="race-admin@example.com", password=self.password)
        EmailAddress.objects.create(user=admin, email=admin.email, verified=True, primary=True)
        admin_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=admin,
            role=MembershipRole.ADMIN,
        )
        invitation, token = create_invitation(
            organization=self.organization,
            actor=admin,
            email=self.invited.email,
            role=MembershipRole.MEMBER,
            project_ids=[],
        )
        barrier = Barrier(2)

        def accept(_):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    return accept_invitation(user=User.objects.get(pk=self.invited.pk), token=token)[2]
                except InvitationError as error:
                    return error.code
            finally:
                close_old_connections()

        def demote(_):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                from .services import update_membership

                update_membership(
                    membership=OrganizationMembership.objects.get(pk=admin_membership.pk),
                    actor=User.objects.get(pk=self.owner.pk),
                    role=MembershipRole.MEMBER,
                )
                return "demoted"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            accept_result, demote_result = list(executor.map(lambda call: call(None), [accept, demote]))
        self.assertEqual(demote_result, "demoted")
        invitation.refresh_from_db()
        if accept_result is True:
            self.assertEqual(invitation.state, InvitationState.ACCEPTED)
            self.assertTrue(OrganizationMembership.objects.filter(
                organization=self.organization,
                user=self.invited,
            ).exists())
        else:
            self.assertEqual(accept_result, "revoked")
            self.assertEqual(invitation.state, InvitationState.REVOKED)
            self.assertFalse(OrganizationMembership.objects.filter(
                organization=self.organization,
                user=self.invited,
            ).exists())
        self.assertEqual(
            AuditEvent.objects.filter(
                invitation=invitation,
                event_type=AuditEventType.INVITATION_ACCEPTED,
            ).count(),
            1 if accept_result is True else 0,
        )


class OwnershipRaceTests(TransactionTestCase):
    def test_concurrent_owner_leaves_cannot_remove_last_active_owner(self):
        users = [User.objects.create_user(email=f"owner-race-{index}@example.com", password="test-pass") for index in range(2)]
        organization = Organization.objects.create(name="Owner race")
        for user in users:
            OrganizationMembership.objects.create(organization=organization, user=user, role=MembershipRole.OWNER)
        barrier = Barrier(2)

        def leave(user_id):
            close_old_connections()
            try:
                user = User.objects.get(pk=user_id)
                barrier.wait(timeout=5)
                try:
                    leave_organization(
                        organization=Organization.objects.get(pk=organization.pk), user=user,
                        request=SimpleNamespace(user=user),
                    )
                    return "left"
                except ValidationError:
                    return "last owner"
            finally:
                close_old_connections()

        with patch("tenancy.services.did_recently_authenticate", return_value=True):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(leave, [user.pk for user in users]))
        self.assertCountEqual(results, ["left", "last owner"])
        self.assertEqual(OrganizationMembership.objects.filter(organization=organization, role=MembershipRole.OWNER).count(), 1)
        self.assertEqual(AuditEvent.objects.filter(organization=organization, event_type=AuditEventType.MEMBERSHIP_LEFT).count(), 1)

    def test_concurrent_demotion_and_removal_preserve_an_active_owner(self):
        users = [User.objects.create_user(email=f"owner-mixed-{index}@example.com", password="test-pass") for index in range(2)]
        organization = Organization.objects.create(name="Owner mixed race")
        records = [OrganizationMembership.objects.create(organization=organization, user=user, role=MembershipRole.OWNER)
                   for user in users]
        barrier = Barrier(2)

        def mutate(index):
            close_old_connections()
            try:
                user = User.objects.get(pk=users[index].pk)
                membership = OrganizationMembership.objects.get(pk=records[index].pk)
                barrier.wait(timeout=5)
                try:
                    if index == 0:
                        update_membership(membership=membership, actor=user, role=MembershipRole.ADMIN,
                                          request=SimpleNamespace(user=user))
                    else:
                        remove_membership(membership=membership, actor=user, request=SimpleNamespace(user=user))
                    return "changed"
                except ValidationError:
                    return "last owner"
            finally:
                close_old_connections()

        with patch("tenancy.services.did_recently_authenticate", return_value=True):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(mutate, range(2)))
        self.assertCountEqual(results, ["changed", "last owner"])
        self.assertEqual(OrganizationMembership.objects.filter(organization=organization, role=MembershipRole.OWNER).count(), 1)
