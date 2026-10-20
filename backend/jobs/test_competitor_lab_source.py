from datetime import timedelta
from hashlib import sha256
import json
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tenancy.models import DomainAlias, Organization, OrganizationMembership, OrganizationTrial, Project, ProjectConfiguration, ProjectMembership
from . import competitor_lab_source as source, competitor_page_source as page, competitor_collection as collection
from . import test_competitor_source as fixtures
from .models import CrawlRun, JobRun, PerformanceObservationSnapshot, UsageReservation
from .performance import parse_pagespeed_lab
from .test_competitor_lab import CompetitorLabTests


class CompetitorLabSourceTests(TestCase):
    setUp = fixtures.CompetitorSourceTests.setUp

    def data(self, **changes):
        return {"origin": fixtures.COMPETITOR, "url": fixtures.COMPETITOR + "/selected/article", "collection_permission": True,
            "provider_processing_permission": True, "strategy": "mobile", **changes}

    def read(self, *, actor=None, project=None, **changes):
        return source.current_competitor_lab_source(project=project or self.project, actor=actor or self.owner, data=self.data(**changes))

    def test_actual_current_original_page_device_processing_digest_privacy_fresh_copy_no_write_key_or_io(self):
        with (patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")), patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No fetch")),
            patch("providers.performance_key.google_performance_key", side_effect=AssertionError("No credential decryption")), CaptureQueriesContext(connection) as queries):
            result = self.read()
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(set(result), {"method_version", "provider", "page_source", "strategy", "provider_processing_permission", "interpretation", "source_sha256"})
        self.assertEqual((result["method_version"], result["provider"], result["strategy"], result["provider_processing_permission"]),
            (source.METHOD, source.PROVIDER, "mobile", True))
        original = page.current_competitor_page_source(project=self.project, actor=self.owner,
            data={key: self.data()[key] for key in ("origin", "url", "collection_permission")})
        self.assertEqual(result["page_source"], original)
        payload = {key: value for key, value in result.items() if key != "source_sha256"}
        content = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
        self.assertEqual(result["source_sha256"], sha256(content).hexdigest()); self.assertLessEqual(len(content), source.MAX_RESULT_BYTES)
        self.assertNotEqual(self.read(strategy="desktop")["source_sha256"], result["source_sha256"])
        self.assertNotEqual(self.read(actor=self.admin)["source_sha256"], result["source_sha256"])
        self.assertNotEqual(self.read(url=fixtures.COMPETITOR+"/other")["source_sha256"], result["source_sha256"])
        result["page_source"]["url"] = "changed"; self.assertEqual(self.read()["page_source"], original)
        for private in ("Private customer prose", "second.example.invalid", self.owner.email, "api_key", "encrypted_secret", "observed_at", "legal_permission_verified"):
            self.assertNotIn(private, json.dumps(result))
        self.assertFalse(JobRun.objects.exists()); self.assertFalse(CrawlRun.objects.exists()); self.assertFalse(UsageReservation.objects.exists())
        self.assertFalse(PerformanceObservationSnapshot.objects.exists()); self.assertFalse(self.project.domain_aliases.exists())

    def test_exact_fields_affirmative_separate_flags_device_and_original_nonroot_uri_before_current_source(self):
        invalid = [None, [], {}, {key: value for key, value in self.data().items() if key != "provider_processing_permission"},
            self.data(api_key="private"), self.data(actor_id=self.owner.pk), self.data(lab_job_id=1)]
        for key in ("collection_permission", "provider_processing_permission"):
            invalid += [self.data(**{key: value}) for value in (False, 1, "true", None)]
        invalid += [self.data(strategy=value) for value in (None, [], True, "tablet", "MOBILE")]
        invalid += [self.data(url=value) for value in (fixtures.COMPETITOR+"/", fixtures.COMPETITOR+"/a?", fixtures.COMPETITOR+"/a#",
            fixtures.COMPETITOR+"/a?secret=x", "http://competitor.example.invalid/a", "https://sub.competitor.example.invalid/a", fixtures.COMPETITOR+":443/a")]
        for data in invalid:
            with self.subTest(data=data), patch.object(source, "current_competitor_page_source", side_effect=AssertionError("Invalid input before source read")), self.assertRaises(ValidationError):
                source.current_competitor_lab_source(project=self.project, actor=self.owner, data=data)
        with self.assertRaises(PermissionDenied): self.read(origin="https://unselected.example.invalid", url="https://unselected.example.invalid/a")

    def test_real_foreign_verified_manager_restricted_grants_alias_demo_and_stale_objects_are_checked(self):
        with self.assertRaises(PermissionDenied): self.read(actor=self.foreign)
        other = fixtures.create_organization(user=self.foreign, name="Foreign")
        fake = Project(pk=self.project.pk, organization=other, canonical_origin=self.project.canonical_origin)
        with self.assertRaises(PermissionDenied): self.read(project=fake)
        OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
        with self.assertRaises(PermissionDenied): self.read(actor=self.admin)
        OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="admin")
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        with self.assertRaises(PermissionDenied): self.read(actor=self.admin)
        grant = ProjectMembership.objects.create(project=self.project, organization_membership=self.membership)
        self.assertEqual(self.read(actor=self.admin)["page_source"]["actor_id"], self.admin.pk); grant.delete()
        Project.objects.filter(pk=self.project.pk).update(access_restricted=False)
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        with self.assertRaises(PermissionDenied): self.read()
        EmailAddress.objects.filter(user=self.owner).update(verified=True)
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(source_choice="synthetic_demo")
        with self.assertRaises(ValidationError): self.read()
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(source_choice="skip", competitor_origins=[fixtures.COMPETITOR,"https://owned.example.invalid","https://alias.example.invalid"])
        DomainAlias.objects.create(organization=self.organization, project=self.project, origin="https://alias.example.invalid")
        for origin in ("https://owned.example.invalid", "https://alias.example.invalid"):
            with self.assertRaises(PermissionDenied): self.read(origin=origin, url=origin+"/page")
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[])
        with self.assertRaises((PermissionDenied, ValidationError)): self.read()

    def test_original_input_is_frozen_before_caller_mutation_during_digest_projection(self):
        data = self.data(); expected = self.read(); original = source.sha256
        def changed(content):
            result = original(content)
            data.update(strategy="tablet", provider_processing_permission=False, url="https://unselected.example.invalid/page")
            return result
        with patch.object(source, "sha256", side_effect=changed):
            self.assertEqual(source.current_competitor_lab_source(project=self.project, actor=self.owner, data=data), expected)
        with self.assertRaises(ValidationError): source.current_competitor_lab_source(project=self.project, actor=self.owner, data=data)

    def test_last_original_projection_rereads_full_hidden_actor_configuration_grants_and_lifecycle(self):
        original = source.sha256
        for change in (lambda: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[fixtures.COMPETITOR,"https://changed.example.invalid"]),
            lambda: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(updated_at=timezone.now()),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="admin"),
            lambda: EmailAddress.objects.filter(user=self.owner).update(verified=False),
            lambda: DomainAlias.objects.create(organization=self.organization, project=self.project, origin="https://new-alias.example.invalid")):
            with self.subTest(change=change), transaction.atomic():
                def changed(content):
                    result = original(content); change(); return result
                with patch.object(source, "sha256", side_effect=changed), self.assertRaises(PermissionDenied): self.read()
                transaction.set_rollback(True)

    def test_source_is_not_commercial_owned_performance_or_old_capture_snapshot_authority(self):
        binding = self.read()
        for handler in collection.COMPETITOR_HANDLERS:
            method = collection._collection_contract(handler)[0]
            data = {"origin": fixtures.COMPETITOR, "collection_permission": True, "use_permission": True, "storage_permission": True}
            if "page" in handler: data["url"] = fixtures.COMPETITOR+"/selected/article"
            job = JobRun(project=self.project, organization=self.organization, actor=self.owner, handler=handler, method_version=method,
                input_snapshot=data, config_snapshot={"method":method,"binding":binding,"use_permission":True,"storage_permission":True})
            with self.subTest(handler=handler), self.assertRaises((PermissionDenied, ValidationError)): collection.validate_job(job, current=True)
        with self.assertRaises(ValidationError): parse_pagespeed_lab(project=self.project,requested_url=binding["page_source"]["url"],strategy="mobile",payload=CompetitorLabTests().payload(url=binding["page_source"]["url"]))
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31),ends_at=now-timedelta(days=1))
        self.assertEqual(self.read(),binding)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=121),ends_at=now-timedelta(days=91))
        with self.assertRaises(PermissionDenied): self.read()
        self.assertFalse(JobRun.objects.exists()); self.assertFalse(UsageReservation.objects.exists())
