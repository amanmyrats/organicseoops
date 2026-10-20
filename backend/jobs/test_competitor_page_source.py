from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tenancy.models import DomainAlias, Organization, OrganizationMembership, OrganizationTrial, Project, ProjectConfiguration
from . import competitor_page_source as page, competitor_source as root, competitor_collection as collection
from . import test_competitor_source as fixtures
from .competitor_fetch import collect_competitor_metadata, collect_competitor_schema, collect_competitor_links
from .models import CrawlRun, JobRun, UsageReservation


class CompetitorPageSourceTests(TestCase):
    setUp = fixtures.CompetitorSourceTests.setUp

    def read(self, *, actor=None, **changes):
        return page.current_competitor_page_source(project=self.project, actor=actor or self.owner,
            data={"origin": fixtures.COMPETITOR, "url": fixtures.COMPETITOR + "/selected/article", "collection_permission": True, **changes})

    def test_genuine_exact_original_url_current_binding_original_actor_privacy_fresh_objects_no_write_or_io(self):
        with patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")), patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No fetch")), CaptureQueriesContext(connection) as queries:
            result = self.read()
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(result["method_version"], page.METHOD)
        self.assertEqual(result["url"], fixtures.COMPETITOR + "/selected/article")
        self.assertEqual(result["origin"], fixtures.COMPETITOR)
        self.assertEqual(result["scope_kind"], page.SCOPE)
        self.assertEqual(result["interpretation"], page.INTERPRETATION)
        self.assertEqual(result["configuration_updated_at"], self.configuration.updated_at.isoformat())
        self.assertEqual(result["actor_id"], self.owner.pk)
        old = root.current_competitor_source(project=self.project, actor=self.owner, data={"origin": fixtures.COMPETITOR, "collection_permission": True})
        self.assertNotEqual(result["source_sha256"], old["source_sha256"])
        self.assertNotEqual(self.read(url=fixtures.COMPETITOR + "/other")["source_sha256"], result["source_sha256"])
        self.assertNotEqual(self.read(actor=self.admin)["source_sha256"], result["source_sha256"])
        result["url"] = "changed"; self.assertEqual(self.read()["url"], fixtures.COMPETITOR + "/selected/article")
        for value in ("Private customer prose", "second.example.invalid", self.owner.email): self.assertNotIn(value, str(result))
        self.assertFalse(JobRun.objects.exists()); self.assertFalse(CrawlRun.objects.exists()); self.assertFalse(UsageReservation.objects.exists())
        self.assertFalse(self.project.domain_aliases.exists())

    def test_selected_original_uri_is_frozen_before_caller_mutation_during_projection(self):
        data = {"origin": fixtures.COMPETITOR, "url": fixtures.COMPETITOR + "/selected/article", "collection_permission": True}
        expected = self.read(); original_hash = page.sha256
        def changed(content):
            result = original_hash(content)
            data.update(url="https://foreign.example.invalid/unselected", origin="https://foreign.example.invalid", collection_permission=False)
            return result
        with patch.object(page, "sha256", side_effect=changed):
            result = page.current_competitor_page_source(project=self.project, actor=self.owner, data=data)
        self.assertEqual(result, expected)
        with self.assertRaises(ValidationError): page.current_competitor_page_source(project=self.project, actor=self.owner, data=data)

    def test_exact_fields_affirmative_permission_and_bounded_canonical_nonroot_same_origin_uri(self):
        for data in (None, [], {}, {"origin": fixtures.COMPETITOR, "collection_permission": True},
            {"origin": fixtures.COMPETITOR, "url": fixtures.COMPETITOR + "/a", "collection_permission": True, "page_limit": 20}):
            with self.subTest(data=data), self.assertRaises(ValidationError): page.current_competitor_page_source(project=self.project, actor=self.owner, data=data)
        for permission in (False, 1, "true", None):
            with self.subTest(permission=permission), self.assertRaises(ValidationError): self.read(collection_permission=permission)
        for url in (True, None, "", fixtures.COMPETITOR, fixtures.COMPETITOR + "/", fixtures.COMPETITOR + "/a?", fixtures.COMPETITOR + "/a#",
            fixtures.COMPETITOR + "/a?secret=x", fixtures.COMPETITOR + "/%0a", fixtures.COMPETITOR + "/back\\slash", fixtures.COMPETITOR + "/has space",
            "https://user:secret@competitor.example.invalid/a", "https://competitor.example.invalid:443/a", "https://competitor.example.invalid:8443/a",
            "http://competitor.example.invalid/a", "https://sub.competitor.example.invalid/a", "https://second.example.invalid/a", "file:///private",
            fixtures.COMPETITOR.upper() + "/a", fixtures.COMPETITOR + "/" + "x" * 1024):
            with self.subTest(url=url), self.assertRaises(ValidationError): self.read(url=url)
        boundary = fixtures.COMPETITOR + "/" + "x" * (1024 - len(fixtures.COMPETITOR) - 1)
        self.assertEqual(self.read(url=boundary)["url"], boundary)
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=["http://competitor.example.invalid"])
        self.assertEqual(self.read(origin="http://competitor.example.invalid", url="http://competitor.example.invalid/article")["url"], "http://competitor.example.invalid/article")

    def test_original_current_manager_restricted_foreign_own_alias_demo_and_stale_cached_configuration(self):
        with self.assertRaises(PermissionDenied): self.read(actor=self.foreign)
        OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
        with self.assertRaises(PermissionDenied): self.read(actor=self.admin)
        OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="admin")
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        with self.assertRaises(PermissionDenied): self.read(actor=self.admin)
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        with self.assertRaises(PermissionDenied): self.read()
        EmailAddress.objects.filter(user=self.owner).update(verified=True)
        self.assertEqual(self.project.configuration.competitor_origins[0], fixtures.COMPETITOR)
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=["https://second.example.invalid"])
        with self.assertRaises(PermissionDenied): self.read()
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[fixtures.COMPETITOR], source_choice="synthetic_demo")
        with self.assertRaises(ValidationError): self.read()
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[fixtures.COMPETITOR, "https://owned.example.invalid", "https://alias.example.invalid"], source_choice="skip")
        DomainAlias.objects.create(organization=self.organization, project=self.project, origin="https://alias.example.invalid")
        for origin in ("https://owned.example.invalid", "https://alias.example.invalid"):
            with self.subTest(origin=origin), self.assertRaises(PermissionDenied): self.read(origin=origin, url=origin + "/page")

    def test_complete_hidden_current_metadata_and_authority_are_reread_after_page_projection(self):
        original_hash = page.sha256
        for change in (lambda: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[fixtures.COMPETITOR, "https://different.example.invalid"]),
            lambda: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(updated_at=timezone.now()),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin"),
            lambda: EmailAddress.objects.filter(user=self.owner).update(verified=False),
            lambda: DomainAlias.objects.create(organization=self.organization, project=self.project, origin="https://another-alias.example.invalid")):
            def changed(data):
                result = original_hash(data); change(); return result
            with self.subTest(change=change), transaction.atomic():
                with patch.object(page, "sha256", side_effect=changed), self.assertRaises(PermissionDenied): self.read()
                transaction.set_rollback(True)

    def test_retained_source_is_not_commercial_network_or_old_root_family_authority(self):
        binding = self.read()
        for producer in (collect_competitor_metadata, collect_competitor_schema, collect_competitor_links):
            with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No selected page fetch")), self.assertRaises(PermissionDenied):
                producer(project=self.project, actor=self.owner, binding=binding, before_request=lambda: None)
        data = {"origin": fixtures.COMPETITOR, "collection_permission": True, "use_permission": True, "storage_permission": True}
        for handler in (collection.HANDLER, "collect_competitor_schema_root", "collect_competitor_links_root"):
            method = collection._collection_contract(handler)[0]
            job = JobRun(project=self.project, organization=self.organization, actor=self.owner, handler=handler, method_version=method,
                input_snapshot=data, config_snapshot={"method": method, "binding": binding, "use_permission": True, "storage_permission": True})
            with self.subTest(handler=handler), self.assertRaises(PermissionDenied): collection.validate_job(job, current=True)
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31), ends_at=now-timedelta(days=1))
        self.assertEqual(self.read(), binding)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=121), ends_at=now-timedelta(days=91))
        with self.assertRaises(PermissionDenied): self.read()
        self.assertFalse(JobRun.objects.exists()); self.assertFalse(UsageReservation.objects.exists())
