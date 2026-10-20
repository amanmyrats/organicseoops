from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import read_project_artifact
from tenancy.models import OrganizationMembership, OrganizationTrial, Project, ProjectMembership, ProjectOriginVerification
from . import passive_header_collection as lifecycle
from . import passive_tls_collection as collector
from . import passive_tls_candidate_source as source
from . import test_passive_tls_collection as fixtures
from .models import Artifact, JobCancellation, JobRun, JobStep, SourceCitation, UsageReservation
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}))
class CurrentTLSCandidateTests(TransactionTestCase):
    setUp = fixtures.PassiveTLSCollectionTests.setUp
    verified = fixtures.PassiveTLSCollectionTests.verified
    queue = fixtures.PassiveTLSCollectionTests.queue
    transport = fixtures.PassiveTLSCollectionTests.transport

    def collected(self, key="tls-candidates", *, version="TLSv1.1", unknown_dates=False):
        job = self.queue(key); fetcher = self.transport()
        self.connection.sock.version.return_value = version
        if unknown_dates: self.connection.sock.getpeercert.side_effect = lambda: {}
        with patch("socket.create_connection", side_effect=AssertionError("No real network")):
            self.assertTrue(collector.execute_passive_tls_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db()
        return job

    def read(self, job, **changes):
        return source.current_tls_candidates(**{**dict(project=self.project, actor=self.owner, job_id=job.pk), **changes})

    def test_genuine_private_current_read_is_read_only_original_fresh_and_never_reconnects(self):
        job = self.collected()
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            report = self.read(job)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual((report["job_id"], report["source_current"]), (job.pk, True))
        self.assertEqual(report["binding"], job.config_snapshot["binding"])
        self.assertEqual(report["collection"], collector.read_passive_tls_observation(project=self.project, actor=self.owner, job_id=job.pk)["collection"])
        original = deepcopy(report)
        report["binding"]["observations"].append("raw"); report["candidates"][0]["evidence"]["version"] = "changed"
        self.assertEqual(self.read(job), original)
        for private in (self.challenge, self.verification.challenge_digest, self.owner.email, "private", "subject", "OCSP"):
            self.assertNotIn(private, json.dumps(original))
        self.connection.connect.assert_called_once(); self.connection.request.assert_not_called()
        with patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No I/O for missing job")):
            with self.assertRaises(PermissionDenied): self.read(job, job_id=job.pk + 1000)

    def test_independent_current_caller_original_actor_restricted_tenant_ids_and_family_fences(self):
        job = self.collected()
        for actor in (self.member, self.outsider):
            with self.assertRaises(PermissionDenied): self.read(job, actor=actor)
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)
        OrganizationMembership.objects.filter(pk=membership.pk).update(role="admin")
        self.assertEqual(self.read(job, actor=self.member)["binding"]["actor_id"], self.owner.pk)
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True); self.project.refresh_from_db()
        restricted = self.collected("restricted-tls")
        with self.assertRaises(PermissionDenied): self.read(restricted, actor=self.member)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(self.read(restricted, actor=self.member)["job_id"], restricted.pk)
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other.example.invalid")
        with self.assertRaises(PermissionDenied): self.read(restricted, project=other)
        for value in (True, 0, -1, 2**53, "1"):
            with self.assertRaises(ValidationError): self.read(restricted, job_id=value)
        for changes in ({"handler": "collect_passive_headers"}, {"handler": "collect_passive_resources"}, {"handler": "collect_passive_redirects"},
            {"status": "failed"}, {"status": "cancelled"}, {"output": {}}):
            with transaction.atomic():
                JobRun.objects.filter(pk=restricted.pk).update(**changes)
                with self.assertRaises((PermissionDenied, ValidationError)): self.read(restricted)
                transaction.set_rollback(True)
        evaluator = source.tls_review_candidates
        def demoted_caller(*args, **kwargs):
            result = evaluator(*args, **kwargs)
            OrganizationMembership.objects.filter(pk=membership.pk).update(role="viewer")
            return result
        with transaction.atomic():
            with patch.object(source, "tls_review_candidates", side_effect=demoted_caller), self.assertRaises(PermissionDenied):
                self.read(restricted, actor=self.member)
            transaction.set_rollback(True)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member")
        with self.assertRaises(PermissionDenied): self.read(restricted, actor=self.member)

    def test_independent_original_unknowns_and_eligible_empty_do_not_become_zero_or_secure(self):
        for key, version, unknown in (("empty", "TLSv1.3", False), ("unknown-version", None, False),
            ("unknown-dates", "TLSv1.3", True), ("both-unknown", None, True)):
            report = self.read(self.collected(key, version=version, unknown_dates=unknown))
            self.assertEqual(report["candidates"], [])
            self.assertEqual(report["availability"], {"certificate_dates": "unavailable" if unknown else "observed",
                "negotiated_version": "unavailable" if version is None else "observed"})
            if unknown:
                self.assertIsNone(report["collection"]["evidence"]["certificate_dates"]["remaining_microseconds"])

    def test_complete_metadata_source_commercial_cancel_and_natural_expiry_after_io_projection_withhold(self):
        job = self.collected(); initial = self.read(job)
        def expire():
            start = timezone.now() - timedelta(days=31)
            OrganizationTrial.objects.filter(organization=self.organization).update(started_at=start, ends_at=start + timedelta(days=30))
        changes = (
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
            lambda: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64),
            lambda: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(updated_at=timezone.now()),
            lambda: JobRun.objects.filter(pk=job.pk).update(idempotency_key="changed-original"),
            lambda: JobStep.objects.filter(job=job).update(created_at=timezone.now()),
            lambda: Artifact.objects.filter(job=job).update(created_at=timezone.now()),
            lambda: SourceCitation.objects.filter(job=job).update(source_title="Changed"),
            lambda: UsageReservation.objects.filter(job=job).update(period_start=timezone.now().date() - timedelta(days=1)),
            lambda: JobCancellation.objects.create(job=job, requested_by=self.owner), expire)
        evaluator = source.tls_review_candidates
        for boundary in ("io", "projection"):
            for change in changes:
                with self.subTest(boundary=boundary, change=change), transaction.atomic():
                    def changed_read(**kwargs):
                        result = read_project_artifact(**kwargs); change(); return result
                    def changed_projection(*args, **kwargs):
                        result = evaluator(*args, **kwargs); change(); return result
                    context = patch.object(lifecycle, "read_project_artifact", side_effect=changed_read) if boundary == "io" else patch.object(
                        source, "tls_review_candidates", side_effect=changed_projection)
                    with context, self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)): self.read(job)
                    transaction.set_rollback(True)
        self.assertEqual(self.read(job), initial)
        ends = timezone.now() + timedelta(seconds=5)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends - timedelta(days=30), ends_at=ends)
        finished = False
        def expiring_projection(*args, **kwargs):
            nonlocal finished
            result = evaluator(*args, **kwargs); finished = True; return result
        with patch("jobs.usage.timezone.now", side_effect=lambda: ends if finished else ends - timedelta(seconds=1)), patch.object(
            source, "tls_review_candidates", side_effect=expiring_projection), self.assertRaises(UsageLimitError): self.read(job)
        self.assertTrue(finished)
