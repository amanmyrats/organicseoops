from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tenancy.models import DomainAlias, Organization, OrganizationMembership, OrganizationTrial, Project, ProjectConfiguration, ProjectMembership
from tenancy.services import create_organization, create_project, update_project_configuration
from . import competitor_source as source
from .crawling import CrawlScope, FetchDenied
from .models import CrawlRun, JobRun, UsageReservation


COMPETITOR = "https://competitor.example.invalid"


class CompetitorSourceTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("competitor-owner@example.invalid")
        self.admin = users.create_user("competitor-admin@example.invalid")
        self.foreign = users.create_user("competitor-foreign@example.invalid")
        for actor in (self.owner, self.admin, self.foreign):
            EmailAddress.objects.create(user=actor, email=actor.email, primary=True, verified=True)
        self.organization = create_organization(user=self.owner, name="Private competitor source")
        self.project = create_project(organization=self.organization, user=self.owner, name="Owned project",
            canonical_origin="https://owned.example.invalid")
        self.membership = OrganizationMembership.objects.create(organization=self.organization, user=self.admin, role="admin")
        self.configuration = update_project_configuration(project=self.project, user=self.owner, expected_revision=0,
            changes={"competitor_origins": [COMPETITOR, "https://second.example.invalid"], "audience": "Private customer prose"})

    def read(self, *, actor=None, project=None, **changes):
        return source.current_competitor_source(project=project or self.project, actor=actor or self.owner,
            data={"origin": COMPETITOR, "collection_permission": True, **changes})

    def test_genuine_saved_approval_read_only_private_single_host_not_alias_or_ownership_proof(self):
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")), CaptureQueriesContext(connection) as queries:
            result = self.read()
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(set(result), {"method_version", "organization_id", "project_id", "actor_id", "origin", "hostname",
            "scope_kind", "collection_permission", "configuration_revision", "configuration_updated_at", "source_sha256", "interpretation"})
        self.assertEqual((result["method_version"], result["origin"], result["hostname"], result["configuration_revision"]),
            (source.METHOD, COMPETITOR, "competitor.example.invalid", 1))
        self.assertEqual(result["configuration_updated_at"], self.configuration.updated_at.isoformat())
        self.assertRegex(result["source_sha256"], "^[a-f0-9]{64}$")
        self.assertIn("not_ownership_approval_time_network_commercial_or_observation_authority", result["interpretation"])
        self.assertNotIn("Private customer prose", str(result)); self.assertNotIn("second.example.invalid", str(result)); self.assertNotIn(self.owner.email, str(result))
        self.assertEqual(self.read(), result); self.assertFalse(self.project.domain_aliases.exists())
        self.assertFalse(JobRun.objects.exists()); self.assertFalse(CrawlRun.objects.exists()); self.assertFalse(UsageReservation.objects.exists())
        scope = CrawlScope.for_project(self.project, competitor_origin=result["origin"])
        self.assertEqual(scope.kind, "competitor"); self.assertEqual(scope.hosts, frozenset({result["hostname"]}))
        for url in (COMPETITOR + "/a", "http://competitor.example.invalid/a"):
            self.assertEqual(scope.validate_url(url), url)
        for url in (self.project.canonical_origin, "https://second.example.invalid", "https://sub.competitor.example.invalid", COMPETITOR + ":8443"):
            with self.assertRaises(FetchDenied): scope.validate_url(url)

    def test_exact_input_canonical_current_selection_ports_and_real_affirmative_permission(self):
        invalid = [None, [], {}, {"origin": COMPETITOR}, {"origin": COMPETITOR, "collection_permission": True, "actor_id": self.owner.pk}]
        invalid.extend({"origin": value, "collection_permission": True} for value in (True, 1, [], "", COMPETITOR + "/", COMPETITOR.upper(),
            COMPETITOR + ":443", COMPETITOR + ":8443", COMPETITOR + "?", COMPETITOR + "#", COMPETITOR + "/path",
            "file:///private", "https://user:password@competitor.example.invalid", " https://competitor.example.invalid", "https://competitor.example.invalid\\", "x" * 241))
        invalid.extend({"origin": COMPETITOR, "collection_permission": value} for value in (False, 1, "true", None))
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValidationError):
                source.current_competitor_source(project=self.project, actor=self.owner, data=data)
        with self.assertRaises(PermissionDenied): self.read(origin="https://unlisted.example.invalid")
        config = update_project_configuration(project=self.project, user=self.owner, expected_revision=1,
            changes={"competitor_origins": ["http://competitor.example.invalid"]})
        self.assertEqual(self.read(origin="http://competitor.example.invalid")["configuration_revision"], config.revision)

    def test_current_verified_manager_restricted_grants_foreign_org_lifecycle_and_actual_identity(self):
        self.assertEqual(self.read(actor=self.admin)["actor_id"], self.admin.pk)
        for role in ("member", "viewer"):
            OrganizationMembership.objects.filter(pk=self.membership.pk).update(role=role)
            with self.assertRaises(PermissionDenied): self.read(actor=self.admin)
        OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="admin")
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        with self.assertRaises(PermissionDenied): self.read(actor=self.admin)
        grant = ProjectMembership.objects.create(project=self.project, organization_membership=self.membership)
        self.assertEqual(self.read(actor=self.admin)["actor_id"], self.admin.pk); grant.delete()
        with self.assertRaises(PermissionDenied): self.read(actor=self.admin)
        with self.assertRaises(PermissionDenied): self.read(actor=self.foreign)
        other = create_organization(user=self.foreign, name="Foreign organization")
        stale = Project(pk=self.project.pk, organization=other, canonical_origin=self.project.canonical_origin)
        with self.assertRaises(PermissionDenied): self.read(project=stale)
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        with self.assertRaises(PermissionDenied): self.read()
        EmailAddress.objects.filter(user=self.owner).update(verified=True)
        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied): self.read()
        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=True)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True)
        with self.assertRaises(PermissionDenied): self.read()
        Organization.objects.filter(pk=self.organization.pk).update(closed_at=timezone.now())
        with self.assertRaises(PermissionDenied): self.read()

    def test_stale_python_config_never_retains_removed_approval_and_demo_own_hosts_are_not_competitors(self):
        self.assertEqual(self.project.configuration.competitor_origins, [COMPETITOR, "https://second.example.invalid"])
        old = self.read()
        update_project_configuration(project=self.project, user=self.owner, expected_revision=1,
            changes={"competitor_origins": ["https://second.example.invalid"]})
        with self.assertRaises(PermissionDenied): self.read()
        update_project_configuration(project=self.project, user=self.owner, expected_revision=2, changes={"competitor_origins": [COMPETITOR]})
        self.assertNotEqual(self.read()["source_sha256"], old["source_sha256"])
        update_project_configuration(project=self.project, user=self.owner, expected_revision=3, changes={"source_choice": "synthetic_demo"})
        with self.assertRaises(ValidationError): self.read()
        update_project_configuration(project=self.project, user=self.owner, expected_revision=4,
            changes={"source_choice": "skip", "competitor_origins": [COMPETITOR, "http://owned.example.invalid", "https://alias.example.invalid"]})
        DomainAlias.objects.create(organization=self.organization, project=self.project, origin="http://alias.example.invalid")
        for origin in ("http://owned.example.invalid", "https://alias.example.invalid"):
            with self.assertRaises(PermissionDenied): self.read(origin=origin)
        self.assertEqual(self.read()["origin"], COMPETITOR)

    def test_full_hidden_source_metadata_and_current_authority_are_rechecked_after_projection(self):
        real_hash = source.sha256
        changes = (
            lambda: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[COMPETITOR, "https://different.example.invalid"]),
            lambda: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(updated_at=timezone.now()),
            lambda: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2),
            lambda: Project.objects.filter(pk=self.project.pk).update(access_restricted=True),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(created_at=self.organization.created_at - timedelta(days=1)),
            lambda: DomainAlias.objects.create(organization=self.organization, project=self.project, origin="https://new-alias.example.invalid"),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
            lambda: EmailAddress.objects.filter(user=self.owner).update(verified=False),
        )
        for change in changes:
            def during_projection(data):
                result = real_hash(data); change(); return result
            with self.subTest(change=change), transaction.atomic():
                with patch.object(source, "sha256", side_effect=during_projection), self.assertRaises(PermissionDenied): self.read()
                transaction.set_rollback(True)

    def test_missing_or_malformed_original_configuration_dates_shape_and_unknown_selection_fail_closed(self):
        for changes in ({"competitor_origins": {}}, {"competitor_origins": [True]}, {"competitor_origins": [COMPETITOR, COMPETITOR]},
            {"competitor_origins": [COMPETITOR + ":8443"]}, {"revision": 0}, {"created_at": timezone.now() + timedelta(days=1)},
            {"updated_at": self.project.created_at - timedelta(days=1)}):
            with self.subTest(changes=changes), transaction.atomic():
                ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(**changes)
                with self.assertRaises(ValidationError): self.read()
                transaction.set_rollback(True)
        self.configuration.delete()
        with self.assertRaises(PermissionDenied): self.read()

    def test_retained_read_after_trial_expiry_is_not_a_costly_collection_allowance_or_network_operation(self):
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=31), ends_at=now - timedelta(days=1))
        self.assertEqual(self.read()["origin"], COMPETITOR)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): self.read()
        self.assertFalse(JobRun.objects.exists()); self.assertFalse(UsageReservation.objects.exists())
