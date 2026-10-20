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
from . import passive_header_candidate_source as source
from . import passive_header_collection as collector
from . import test_passive_header_collection as fixtures
from .models import Artifact, JobCancellation, JobRun, JobStep, SourceCitation, UsageReservation
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}))
class CurrentHeaderCandidateTests(TransactionTestCase):
    setUp = fixtures.PassiveHeaderCollectionTests.setUp
    verified = fixtures.PassiveHeaderCollectionTests.verified
    queue = fixtures.PassiveHeaderCollectionTests.queue
    transport = fixtures.PassiveHeaderCollectionTests.transport

    def collected(self):
        job = self.queue()
        self.assertTrue(collector.execute_passive_header_collection(job.pk, fetcher=self.transport()))
        job.refresh_from_db()
        return job

    def read(self, job, **changes):
        return source.current_header_candidates(**{**dict(project=self.project, actor=self.owner, job_id=job.pk), **changes})

    def test_genuine_original_read_only_private_source_preserves_dates_binding_and_fresh_ownership(self):
        job = self.collected()
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            report = self.read(job)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual((report["job_id"], report["source_current"]), (job.pk, True))
        self.assertEqual(report["binding"], job.config_snapshot["binding"])
        self.assertEqual(report["collection"], collector.read_passive_header_observation(
            project=self.project, actor=self.owner, job_id=job.pk)["collection"])
        original = deepcopy(report)
        report["collection"]["evidence"]["headers"]["server"] = "present_nonempty"
        report["binding"]["observations"].append("raw")
        self.assertEqual(self.read(job), original)
        for private in (self.challenge, self.verification.challenge_digest, self.owner.email, "nonce-private", "secret", "private body"):
            self.assertNotIn(private, json.dumps(original))

    def test_current_caller_and_original_actor_are_independent_and_ordinary_read_does_not_authorize_candidates(self):
        job = self.collected()
        for actor in (self.member, self.outsider):
            with self.assertRaises(PermissionDenied): self.read(job, actor=actor)
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)
        membership.role = "admin"; membership.save(update_fields=["role"])
        self.assertEqual(self.read(job, actor=self.member)["binding"]["actor_id"], self.owner.pk)
        # Changing project restriction also changes the original source pin: collect a new original binding.
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        self.project.refresh_from_db()
        restricted = self.queue("restricted")
        self.assertTrue(collector.execute_passive_header_collection(restricted.pk, fetcher=self.transport()))
        with self.assertRaises(PermissionDenied): self.read(restricted, actor=self.member)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(self.read(restricted, actor=self.member)["job_id"], restricted.pk)
        evaluator = source.response_header_candidates
        def demote_caller(*args, **kwargs):
            report = evaluator(*args, **kwargs)
            OrganizationMembership.objects.filter(pk=membership.pk).update(role="viewer")
            return report
        with transaction.atomic():
            with patch.object(source, "response_header_candidates", side_effect=demote_caller), self.assertRaises(PermissionDenied):
                self.read(restricted, actor=self.member)
            transaction.set_rollback(True)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member")
        with self.assertRaises(PermissionDenied): self.read(restricted, actor=self.member)

    def test_invalid_nested_scope_other_family_failed_cancelled_or_corrupt_originals_fail_closed(self):
        job = self.collected()
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other.example.invalid")
        with self.assertRaises(PermissionDenied): self.read(job, project=other)
        for job_id in (True, 0, -1, 2**53, "1"):
            with self.assertRaises(ValidationError): self.read(job, job_id=job_id)
        for changes in ({"handler": "collect_passive_redirects"}, {"status": "failed"}, {"status": "cancelled"},
            {"output": {}}):
            with transaction.atomic():
                JobRun.objects.filter(pk=job.pk).update(**changes)
                with self.assertRaises((PermissionDenied, ValidationError)): self.read(job)
                transaction.set_rollback(True)
        with transaction.atomic():
            JobCancellation.objects.create(job=job, requested_by=self.owner)
            with self.assertRaises(PermissionDenied): self.read(job)
            transaction.set_rollback(True)

    def test_full_metadata_and_caller_source_commercial_loss_during_io_or_projection_are_withheld(self):
        job = self.collected()
        initial = self.read(job)
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
        evaluator = source.response_header_candidates
        for boundary in ("io", "projection"):
            for change in changes:
                with self.subTest(boundary=boundary, change=change), transaction.atomic():
                    def read_changed(**kwargs):
                        body = read_project_artifact(**kwargs); change(); return body
                    def evaluate_changed(*args, **kwargs):
                        report = evaluator(*args, **kwargs); change(); return report
                    context = patch.object(collector, "read_project_artifact", side_effect=read_changed) if boundary == "io" else patch.object(
                        source, "response_header_candidates", side_effect=evaluate_changed)
                    with context, self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)): self.read(job)
                    transaction.set_rollback(True)
        self.assertEqual(self.read(job), initial)
        # Natural deadline during projection, with no edited source/expiry metadata.
        ends = timezone.now() + timedelta(seconds=5)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends - timedelta(days=30), ends_at=ends)
        finished = False
        def evaluate_expiring(*args, **kwargs):
            nonlocal finished
            result = evaluator(*args, **kwargs); finished = True; return result
        with patch("jobs.usage.timezone.now", side_effect=lambda: ends if finished else ends - timedelta(seconds=1)), patch.object(
            source, "response_header_candidates", side_effect=evaluate_expiring), self.assertRaises(UsageLimitError): self.read(job)
        self.assertTrue(finished)
