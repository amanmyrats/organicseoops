from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, reset_queries, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, OrganizationTrial, Project, ProjectMembership, ProjectOriginVerification
from . import passive_finding_review_source as source
from . import passive_header_collection as lifecycle
from . import test_passive_header_findings as header_fixtures
from . import test_passive_resource_findings as resource_fixtures
from . import test_passive_tls_findings as tls_fixtures
from . import test_passive_redirect_findings as redirect_fixtures
from . import test_passive_redirect_chain_persistence as chain_fixtures
from .models import Finding, JobCancellation, JobRun, JobStep, Opportunity, Recommendation, UsageReservation
from .usage import UsageLimitError


class ReviewSourceChecks:
    def review_source(self, job, finding, **changes):
        return self.source(**{**dict(project=self.project, actor=self.owner, job_id=job.pk, finding_id=finding.pk), **changes})

    def test_ineligible_scope_family_status_or_caller_denied_before_original_metadata_read(self):
        job = self.collected(); finding = self.record(job)[0]
        family, candidate = {
            "collect_passive_headers": ("headers", source.headers.source.current_header_candidates),
            "collect_passive_resources": ("resources", source.resources.source.current_resource_candidates),
            "collect_passive_tls": ("tls", source.tls.source.current_tls_candidates),
            "collect_passive_redirects": ("redirects", source.redirects.source.current_redirect_candidates),
            "collect_passive_redirect_chain": ("redirect-chain", source.chains.source.current_redirect_chain_candidates),
        }[job.handler]
        foreign = Project.objects.create(organization=self.organization, name="Other review scope", canonical_origin="https://foreign.example.invalid")
        client = Client(); client.force_login(self.owner)
        for loss in ("project", "family", "failed", "missing", "caller"):
            with transaction.atomic():
                if loss == "caller": OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
                elif loss != "missing": JobRun.objects.filter(pk=job.pk).update(**{
                    "project": {"project_id": foreign.pk}, "family": {"handler": "collect_passive_http_redirects"}, "failed": {"status": "failed"},
                }[loss])
                job_id = 2**53 - 1 if loss == "missing" else job.pk
                base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/passive-{family}/{job_id}/"
                direct = {
                    "candidate": lambda: candidate(project=self.project, actor=self.owner, job_id=job_id),
                    "current": lambda: self.read(job, job_id=job_id),
                    "record": lambda: self.record(job, job_id=job_id),
                    "review": lambda: self.source(project=self.project, actor=self.owner, job_id=job_id, finding_id=finding.pk),
                }
                for name, read in direct.items():
                    with self.subTest(loss=loss, consumer=name), patch.object(lifecycle, "_read_metadata", wraps=lifecycle._read_metadata) as metadata:
                        with self.assertRaises(PermissionDenied): read()
                        metadata.assert_not_called()
                for name, read in {
                    "candidate-api": lambda: client.get(base + "candidates/", secure=True),
                    "finding-get": lambda: client.get(base + "findings/", secure=True),
                    "finding-post": lambda: client.post(base + "findings/", json.dumps({"candidate_digest": "b" * 64}), content_type="application/json", secure=True),
                }.items():
                    cache.clear()
                    with self.subTest(loss=loss, consumer=name), patch.object(lifecycle, "_read_metadata", wraps=lifecycle._read_metadata) as metadata:
                        response = read(); self.assertEqual(response.status_code, 403, response.content)
                        metadata.assert_not_called()
                transaction.set_rollback(True)

    def test_successful_observation_without_materialized_fact_is_not_reviewable(self):
        job = self.collected()
        with patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No I/O for absent fact")):
            with self.assertRaises(PermissionDenied):
                self.source(project=self.project, actor=self.owner, job_id=job.pk, finding_id=2**53 - 1)
        self.assertFalse(Finding.objects.exists()); self.assertFalse(Opportunity.objects.exists())

    def test_genuine_exact_fact_stable_digest_read_only_fresh_private_and_not_human_review(self):
        job = self.collected(); rows = self.record(job); selected = rows[0]
        counts = (Finding.objects.count(), JobRun.objects.count(), UsageReservation.objects.count())
        reset_queries()  # Keep the read-only SQL assertion complete after the genuine producer/materializer.
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            with CaptureQueriesContext(connection) as queries: result = self.review_source(job, selected)
            self.assertEqual(self.review_source(job, selected), result)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(set(result), {"method_version", "organization_id", "project_id", "job_id", "source_current",
            "finding", "source_sha256", "interpretation"})
        self.assertEqual((result["method_version"], result["interpretation"]), (source.METHOD, source.INTERPRETATION))
        self.assertEqual(result["finding"], self.read(job)["findings"][0])
        self.assertEqual(result["finding"]["evidence"]["observed_at"], job.output["observed_at"])
        self.assertRegex(result["source_sha256"], r"^[0-9a-f]{64}$")
        original = deepcopy(result); result["finding"]["evidence"]["binding"]["observations"].append("invented")
        self.assertEqual(self.review_source(job, selected), original)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(self.review_source(job, selected, actor=self.member), original)
        self.assertEqual((Finding.objects.count(), JobRun.objects.count(), UsageReservation.objects.count()), counts)
        self.assertEqual((Opportunity.objects.count(), Recommendation.objects.count()), (0, 0))
        for private in (self.challenge, self.owner.email, "nonce-private", "secret=value", "raw_body", "target_url"):
            self.assertNotIn(private, json.dumps(original))
        if len(rows) > 1:
            self.assertNotEqual(self.review_source(job, rows[1])["source_sha256"], original["source_sha256"])

    def test_invalid_absent_foreign_job_project_and_wrong_family_selection_before_private_io(self):
        job = self.collected(); selected = self.record(job)[0]
        other = self.collected("different-original"); foreign = self.record(other)[0]
        project = Project.objects.create(organization=self.organization, name="Other scope", canonical_origin="https://other.example.invalid")
        with patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No I/O for invalid selection")):
            for key in ("job_id", "finding_id"):
                for value in (True, 0, -1, 2**53, "7"):
                    with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                        self.review_source(job, selected, **{key: value})
            for changes in ({"job_id": other.pk}, {"finding_id": foreign.pk}, {"finding_id": 2**53 - 1}, {"project": project}):
                with self.subTest(changes=changes), self.assertRaises(PermissionDenied): self.review_source(job, selected, **changes)
            for entrypoint in (source.current_header_review_source, source.current_resource_review_source,
                source.current_tls_review_source, source.current_redirect_review_source, source.current_redirect_chain_review_source):
                if entrypoint is not self.source:
                    with self.assertRaises(PermissionDenied):
                        entrypoint(project=self.project, actor=self.owner, job_id=job.pk, finding_id=selected.pk)
        for actor in (self.member, self.outsider):
            with self.assertRaises(PermissionDenied): self.review_source(job, selected, actor=actor)

    def test_projection_and_private_io_full_original_rows_authority_cancel_and_natural_expiry_fenced(self):
        job = self.collected(); selected = self.record(job)[0]
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        mutations = (
            lambda: Finding.objects.filter(pk=selected.pk).update(detected_at=timezone.now()),
            lambda: Finding.objects.filter(pk=selected.pk).update(actor=self.member),
            lambda: Finding.objects.filter(pk=selected.pk).delete(),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer"),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
            lambda: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(updated_at=timezone.now()),
            lambda: JobStep.objects.filter(job=job).update(created_at=timezone.now()),
            lambda: UsageReservation.objects.filter(job=job).update(period_start=timezone.now().date() - timedelta(days=1)),
            lambda: JobCancellation.objects.create(job=job, requested_by=self.owner),
            lambda: OrganizationTrial.objects.filter(organization=self.organization).update(
                started_at=timezone.now() - timedelta(days=31), ends_at=timezone.now() - timedelta(days=1)))
        for boundary in ("projection", "private_io"):
            for mutate in mutations:
                changed = False
                original = source.deepcopy if boundary == "projection" else lifecycle.read_project_artifact
                def project_then_change(*args, **kwargs):
                    nonlocal changed
                    result = original(*args, **kwargs)
                    if not changed: changed = True; mutate()
                    return result
                target, attribute = (source, "deepcopy") if boundary == "projection" else (lifecycle, "read_project_artifact")
                with self.subTest(boundary=boundary, mutation=mutate), transaction.atomic():
                    with patch.object(target, attribute, side_effect=project_then_change):
                        with self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                            self.review_source(job, selected, actor=self.member)
                    self.assertTrue(changed); transaction.set_rollback(True)
        ends = timezone.now() + timedelta(seconds=5)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends - timedelta(days=30), ends_at=ends)
        projected = False
        def slow_projection(value):
            nonlocal projected
            result = deepcopy(value); projected = True; return result
        with patch.object(source, "deepcopy", side_effect=slow_projection), patch("jobs.usage.timezone.now",
            side_effect=lambda: ends if projected else ends - timedelta(microseconds=1)):
            with self.assertRaises(UsageLimitError): self.review_source(job, selected)
        self.assertTrue(projected)

    def test_hidden_valid_row_change_binds_new_digest_and_independent_restricted_materializer(self):
        job = self.collected(); rows = self.record(job); selected = rows[0]
        original = self.review_source(job, selected)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        Finding.objects.filter(pk=rows[-1].pk).update(actor=self.member)
        changed = self.review_source(job, selected)
        self.assertNotEqual(changed["source_sha256"], original["source_sha256"])
        self.assertEqual(changed["finding"], original["finding"])
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True); self.project.refresh_from_db()
        with self.assertRaises(PermissionDenied): self.review_source(job, selected)
        # Changing restriction invalidates the original binding; collect a genuine new restricted source.
        restricted = self.collected("restricted-review-source"); restricted_rows = self.record(restricted)
        restricted_selected = restricted_rows[0]
        Finding.objects.filter(pk=restricted_rows[-1].pk).update(actor=self.member)
        with self.assertRaises(PermissionDenied): self.review_source(restricted, restricted_selected)
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        allowed = self.review_source(restricted, restricted_selected)
        self.assertEqual(self.review_source(restricted, restricted_selected, actor=self.member), allowed)
        ProjectMembership.objects.filter(project=self.project, organization_membership=membership).delete()
        with self.assertRaises(PermissionDenied): self.review_source(restricted, restricted_selected)

    def test_authority_after_last_metadata_or_rows_including_independent_materializer_and_natural_expiry(self):
        job = self.collected(); selected = self.record(job)[0]
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        OrganizationMembership.objects.create(organization=self.organization, user=self.outsider, role="admin")
        Finding.objects.filter(pk=selected.pk).update(actor=self.outsider)
        self.review_source(job, selected, actor=self.member)
        service, read_name = {
            "collect_passive_headers": (source.headers, "current_header_findings"),
            "collect_passive_resources": (source.resources, "current_resource_findings"),
            "collect_passive_tls": (source.tls, "current_tls_findings"),
            "collect_passive_redirects": (source.redirects, "current_redirect_findings"),
            "collect_passive_redirect_chain": (source.chains, "current_redirect_chain_findings"),
        }[job.handler]
        read = getattr(service, read_name)
        ends = timezone.now() + timedelta(seconds=5)
        now = timezone.now
        mutations = {
            "original_actor": lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
            "independent_caller": lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer"),
            "independent_materializer": lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.outsider).update(role="viewer"),
            "origin": lambda: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(updated_at=now()),
            "cancel": lambda: JobCancellation.objects.create(job=job, requested_by=self.owner),
            "natural_expiry": lambda: None,
        }
        for boundary in ("metadata", "rows"):
            for name, mutate in mutations.items():
                with self.subTest(boundary=boundary, loss=name), transaction.atomic():
                    if name == "natural_expiry":
                        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends-timedelta(days=30), ends_at=ends)
                    completed = 0; lost = False
                    def complete_read(**kwargs):
                        nonlocal completed
                        result = read(**kwargs); completed += 1; return result
                    target, attribute = (service.source, "_metadata") if boundary == "metadata" else (service, "_rows")
                    original = getattr(target, attribute)
                    def last_pin(*args, **kwargs):
                        nonlocal lost
                        result = original(*args, **kwargs)
                        if completed == 2 and not lost:
                            mutate(); lost = True
                        return result
                    with patch.object(service, read_name, side_effect=complete_read), patch.object(target, attribute, side_effect=last_pin), \
                         patch("jobs.usage.timezone.now", side_effect=lambda: (ends if lost else ends-timedelta(microseconds=1)) if name == "natural_expiry" else now()):
                        with self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                            self.review_source(job, selected, actor=self.member)
                    self.assertTrue(lost); transaction.set_rollback(True)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}))
class HeaderReviewSourceTests(ReviewSourceChecks, TransactionTestCase):
    setUp = header_fixtures.PassiveHeaderFindingTests.setUp
    verified = header_fixtures.PassiveHeaderFindingTests.verified
    queue = header_fixtures.PassiveHeaderFindingTests.queue
    transport = header_fixtures.PassiveHeaderFindingTests.transport
    collected = header_fixtures.PassiveHeaderFindingTests.collected
    record = header_fixtures.PassiveHeaderFindingTests.record
    read = header_fixtures.PassiveHeaderFindingTests.read
    source = staticmethod(source.current_header_review_source)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}))
class ResourceReviewSourceTests(ReviewSourceChecks, TransactionTestCase):
    setUp = resource_fixtures.PassiveResourceFindingTests.setUp
    verified = resource_fixtures.PassiveResourceFindingTests.verified
    queue = resource_fixtures.PassiveResourceFindingTests.queue
    transport = resource_fixtures.PassiveResourceFindingTests.transport
    collected = resource_fixtures.PassiveResourceFindingTests.collected
    record = resource_fixtures.PassiveResourceFindingTests.record
    read = resource_fixtures.PassiveResourceFindingTests.read
    source = staticmethod(source.current_resource_review_source)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}))
class TLSReviewSourceTests(ReviewSourceChecks, TransactionTestCase):
    setUp = tls_fixtures.PassiveTLSFindingTests.setUp
    verified = tls_fixtures.PassiveTLSFindingTests.verified
    queue = tls_fixtures.PassiveTLSFindingTests.queue
    transport = tls_fixtures.PassiveTLSFindingTests.transport
    collected = tls_fixtures.PassiveTLSFindingTests.collected
    record = tls_fixtures.PassiveTLSFindingTests.record
    read = tls_fixtures.PassiveTLSFindingTests.read
    source = staticmethod(source.current_tls_review_source)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}))
class RedirectReviewSourceTests(ReviewSourceChecks, TransactionTestCase):
    setUp = redirect_fixtures.PassiveRedirectFindingTests.setUp
    verified = redirect_fixtures.PassiveRedirectFindingTests.verified
    queue = redirect_fixtures.PassiveRedirectFindingTests.queue
    transport = redirect_fixtures.PassiveRedirectFindingTests.transport
    collected = redirect_fixtures.PassiveRedirectFindingTests.collected
    record = redirect_fixtures.PassiveRedirectFindingTests.record
    read = redirect_fixtures.PassiveRedirectFindingTests.read
    WIRE = redirect_fixtures.PassiveRedirectFindingTests.WIRE
    source = staticmethod(source.current_redirect_review_source)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}))
class RedirectChainReviewSourceTests(ReviewSourceChecks, TransactionTestCase):
    def setUp(self):
        chain_fixtures.PassiveRedirectChainFindingTests.setUp(self)
        self.verification = self.https_verification
    verified = chain_fixtures.PassiveRedirectChainFindingTests.verified
    queue = chain_fixtures.PassiveRedirectChainFindingTests.queue
    collected = chain_fixtures.PassiveRedirectChainFindingTests.collected
    record = chain_fixtures.PassiveRedirectChainFindingTests.record
    read = chain_fixtures.PassiveRedirectChainFindingTests.read
    source = staticmethod(source.current_redirect_chain_review_source)

    def test_every_original_origin_including_unvisited_and_late_private_bytes_without_priority_authority(self):
        from . import passive_finding_reviews as reviews
        unvisited = self.verified("https://www.security.example.com")
        self.data["target_urls"].append(unvisited.origin+"/unvisited")
        job = self.collected(fields=f"Location: {self.data['url']}\r\n".encode()); finding = self.record(job)[0]
        self.assertEqual((finding.evidence["availability"]["selected_urls"], finding.evidence["availability"]["observed_hops"]), (3, 1))
        original = self.review_source(job, finding)
        for verification in (self.https_verification, self.http_verification, unvisited):
            with self.subTest(origin=verification.origin), transaction.atomic():
                changed = False
                def projected(value):
                    nonlocal changed
                    result = deepcopy(value)
                    if not changed:
                        changed = True
                        ProjectOriginVerification.objects.filter(pk=verification.pk).update(updated_at=timezone.now())
                    return result
                with patch.object(source, "deepcopy", side_effect=projected), self.assertRaises((PermissionDenied, ValidationError)):
                    self.review_source(job, finding)
                self.assertTrue(changed); transaction.set_rollback(True)
        projected = False; read_bytes = lifecycle.read_project_artifact
        def after_projection(value):
            nonlocal projected
            result = deepcopy(value); projected = True; return result
        def changed_bytes(**kwargs): return b"{}" if projected else read_bytes(**kwargs)
        with patch.object(source, "deepcopy", side_effect=after_projection), patch.object(lifecycle, "read_project_artifact", side_effect=changed_bytes), \
             self.assertRaises(ValidationError): self.review_source(job, finding)
        self.assertEqual(self.review_source(job, finding), original)
        with self.assertRaises(ValidationError): reviews._reader("http_redirect")
        with self.assertRaises(ValidationError): Opportunity.objects.create(project=self.project, actor=self.owner, finding=finding,
            review_reason="Source inspection without a bound digest is not a decision contract")
        self.assertFalse(Opportunity.objects.exists()); self.assertFalse(Recommendation.objects.exists())
