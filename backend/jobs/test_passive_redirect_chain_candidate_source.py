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
from tenancy.models import OrganizationMembership, Project, ProjectMembership, ProjectOriginVerification
from . import passive_header_collection as lifecycle
from . import passive_redirect_chain_collection as collector
from . import passive_redirect_chain_candidate_source as source
from . import test_passive_redirect_chain_collection as fixtures
from .models import Artifact, Finding, JobCancellation, JobRun, JobStep, SourceCitation, UsageReservation
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class CurrentRedirectChainCandidateTests(TransactionTestCase):
    setUp = fixtures.PassiveRedirectChainCollectionTests.setUp
    verified = fixtures.PassiveRedirectChainCollectionTests.verified
    queue = fixtures.PassiveRedirectChainCollectionTests.queue
    transport = fixtures.PassiveRedirectChainCollectionTests.transport

    def collected(self, key="chain-candidates"):
        job = self.queue(key); fetcher, self.connections, self.responses, *_ = self.transport()
        with patch("socket.create_connection", side_effect=AssertionError("No real network")):
            self.assertTrue(collector.execute_passive_redirect_chain_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); return job

    def read(self, job, **changes):
        return source.current_redirect_chain_candidates(**{**dict(project=self.project, actor=self.owner, job_id=job.pk), **changes})

    def test_genuine_original_private_read_only_fresh_independent_caller_and_before_pin_scope_denial(self):
        self.data = {**self.data, "url": self.https + "/public", "target_urls": [self.http + "/public"]}
        job = self.collected()
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            report = self.read(job)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual((report["job_id"], report["source_current"]), (job.pk, True))
        self.assertEqual(report["binding"], job.config_snapshot["binding"])
        self.assertEqual(report["collection"], collector.read_passive_redirect_chain_observation(project=self.project, actor=self.owner, job_id=job.pk)["collection"])
        self.assertEqual(report["candidates"], [{"detector": "observed_https_to_http_transition_candidate", "evidence": {"transitions": [{"from_hop": 0, "to_hop": 1}]}}])
        original = deepcopy(report); report["binding"]["target_urls"].clear(); report["candidates"][0]["evidence"]["transitions"].clear()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(self.read(job, actor=self.member), original)
        for private in (self.challenge, self.http_verification.challenge_digest, self.owner.email, "private", "secret"):
            self.assertNotIn(private, json.dumps(original))
        for handler in lifecycle.PASSIVE_HANDLERS:
            if handler == collector.HANDLER: continue
            with transaction.atomic():
                JobRun.objects.filter(pk=job.pk).update(handler=handler)
                with patch.object(lifecycle, "_read_metadata", side_effect=AssertionError("No premature full pin")), self.assertRaises(PermissionDenied): self.read(job)
                transaction.set_rollback(True)
        for status in ("queued", "running", "failed", "cancelled"):
            with transaction.atomic():
                JobRun.objects.filter(pk=job.pk).update(status=status)
                with patch.object(lifecycle, "_read_metadata", side_effect=AssertionError("No premature full pin")), self.assertRaises(PermissionDenied): self.read(job)
                transaction.set_rollback(True)
        with patch.object(lifecycle, "_read_metadata", side_effect=AssertionError("No foreign or unauthorized full pin")):
            for actor in (self.outsider,):
                with self.assertRaises(PermissionDenied): self.read(job, actor=actor)
            with self.assertRaises(PermissionDenied): self.read(job, job_id=job.pk + 1000)
            other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://foreign.example.invalid")
            with self.assertRaises(PermissionDenied): self.read(job, project=other)
        for value in (True, 0, -1, 2**53, "1"):
            with self.assertRaises(ValidationError): self.read(job, job_id=value)
        self.assertEqual(Finding.objects.count(), 0)
        for conn, response in zip(self.connections, self.responses): conn.request.assert_called_once(); response.read.assert_not_called()

    def test_restricted_independent_caller_and_original_actor_source_authority_remain_separate(self):
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)
        OrganizationMembership.objects.filter(pk=membership.pk).update(role="admin")
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True); self.project.refresh_from_db()
        job = self.collected()
        with patch.object(lifecycle, "_read_metadata", side_effect=AssertionError("No restricted premature full pin")), self.assertRaises(PermissionDenied): self.read(job, actor=self.member)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(self.read(job, actor=self.member)["binding"]["actor_id"], self.owner.pk)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member")
        with self.assertRaises(PermissionDenied): self.read(job, actor=self.member)

    def test_private_io_projection_late_all_metadata_either_origin_cancel_and_byte_loss_withhold_original(self):
        job = self.collected(); initial = self.read(job); evaluator = source.redirect_chain_review_candidates
        changes = [lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
            lambda: JobRun.objects.filter(pk=job.pk).update(idempotency_key="changed-original"),
            lambda: JobStep.objects.filter(job=job).update(created_at=timezone.now()),
            lambda: Artifact.objects.filter(job=job).update(created_at=timezone.now()),
            lambda: SourceCitation.objects.filter(job=job).update(source_title="Changed"),
            lambda: UsageReservation.objects.filter(job=job).update(period_start=timezone.now().date() - timedelta(days=1)),
            lambda: JobCancellation.objects.create(job=job, requested_by=self.owner)]
        for verification in (self.http_verification, self.https_verification):
            changes.extend((lambda pk=verification.pk: ProjectOriginVerification.objects.filter(pk=pk).update(challenge_digest="b" * 64),
                lambda pk=verification.pk: ProjectOriginVerification.objects.filter(pk=pk).update(updated_at=timezone.now())))
        for boundary in ("io", "projection"):
            for change in changes:
                with self.subTest(boundary=boundary, change=change), transaction.atomic():
                    def changed_read(**kwargs):
                        result = read_project_artifact(**kwargs); change(); return result
                    def changed_projection(*args, **kwargs):
                        result = evaluator(*args, **kwargs); change(); return result
                    context = patch.object(lifecycle, "read_project_artifact", side_effect=changed_read) if boundary == "io" else patch.object(source,
                        "redirect_chain_review_candidates", side_effect=changed_projection)
                    with context, self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)): self.read(job)
                    transaction.set_rollback(True)
        corrupted = False
        def projection(*args, **kwargs):
            nonlocal corrupted
            result = evaluator(*args, **kwargs); corrupted = True; return result
        def bytes_after_projection(**kwargs): return b"{}" if corrupted else read_project_artifact(**kwargs)
        with patch.object(source, "redirect_chain_review_candidates", side_effect=projection), patch.object(lifecycle, "read_project_artifact", side_effect=bytes_after_projection), self.assertRaises(ValidationError): self.read(job)
        self.assertEqual(self.read(job), initial)

    def test_unvisited_original_grant_and_natural_expiry_after_final_metadata_are_current_not_retained_authority(self):
        unvisited = self.verified("https://www.security.example.com")
        self.data["target_urls"].append("https://www.security.example.com/unvisited")
        job = self.queue("unvisited"); fetcher, *_ = self.transport({**self.data, "target_urls": self.data["target_urls"][:1]})
        self.assertTrue(collector.execute_passive_redirect_chain_collection(job.pk, fetcher=fetcher)); job.refresh_from_db()
        initial = self.read(job)
        self.assertEqual((initial["availability"]["selected_urls"], initial["availability"]["observed_hops"]), (3, 2))
        self.assertIn(unvisited.origin, [row["origin"] for row in initial["binding"]["origins"]])
        metadata = source._metadata; end = self.organization.trial.ends_at
        for loss in ("unvisited", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                calls = 0; finished = False
                def changed_metadata(*args, **kwargs):
                    nonlocal calls, finished
                    result = metadata(*args, **kwargs); calls += 1
                    if calls == 3:
                        finished = True
                        if loss == "unvisited": ProjectOriginVerification.objects.filter(pk=unvisited.pk).update(updated_at=timezone.now())
                    return result
                with patch.object(source, "_metadata", side_effect=changed_metadata), patch("jobs.usage.timezone.now", side_effect=lambda: end if finished and loss == "expiry" else end - timedelta(seconds=1)), self.assertRaises((PermissionDenied, UsageLimitError)): self.read(job)
                self.assertTrue(finished); transaction.set_rollback(True)
        self.assertEqual(self.read(job), initial)
