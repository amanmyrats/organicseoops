from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import io
import json
from threading import Barrier
from unittest.mock import patch
from zipfile import ZipFile

from allauth.account.models import EmailAddress
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectOriginVerification
from . import passive_finding_reviews as reviews
from . import test_passive_finding_review_source as fixtures
from . import test_findings as ordinary_fixtures
from .models import Finding, JobCancellation, JobRun, Opportunity, Recommendation
from .usage import UsageLimitError


class PriorityChecks:
    def decision(self, job, finding, **changes):
        inspected = self.review_source(job, finding)
        return self.record_priority(**{**dict(project=self.project, actor=self.owner, job_id=job.pk,
            finding_id=finding.pk, source_sha256=inspected["source_sha256"], expected_revision=0,
            priority="low", estimated_effort="unknown", business_relevance="unknown", reason="Review this literal dated fact"), **changes})

    def priority(self, job, finding, **changes):
        return self.read_priority(**{**dict(project=self.project, actor=self.owner, job_id=job.pk, finding_id=finding.pk), **changes})

    def test_explicit_current_judgment_immutable_corrections_exact_digest_revision_and_same_actor_replay(self):
        job = self.collected(); finding = self.record(job)[0]
        self.assertIsNone(self.priority(job, finding)["decision"])
        review = self.decision(job, finding, reason="  Review this literal dated fact  ")
        self.assertEqual(self.decision(job, finding).pk, review.pk)
        current = self.priority(job, finding)
        self.assertEqual(current["method_version"], reviews.METHOD)
        self.assertEqual(current["decision"]["priority"], "low")
        self.assertEqual(current["source"]["finding"]["evidence"], finding.evidence)
        self.assertEqual(current["reviewed_at"], review.created_at.isoformat())
        self.assertEqual(review.passive_source_sha256, current["source"]["source_sha256"])
        with self.assertRaises(ValidationError): review.save()
        for changes in ({"expected_revision": True}, {"expected_revision": 65535}, {"priority": []}, {"reason": " "},
            {"reason": "x" * 241}, {"estimated_effort": "automatic"}, {"business_relevance": "proven"}, {"priority": "high"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError): self.decision(job, finding, **changes)
        with self.assertRaises(PermissionDenied): self.decision(job, finding, source_sha256="0" * 64)
        corrected = self.decision(job, finding, expected_revision=1, priority="high")
        self.assertEqual((corrected.revision, corrected.priority), (2, "high"))
        self.assertEqual(self.decision(job, finding, expected_revision=1, priority="high").pk, corrected.pk)
        with self.assertRaises(ValidationError): self.decision(job, finding)
        self.assertEqual(Opportunity.objects.count(), 2); self.assertFalse(Recommendation.objects.exists())
        with transaction.atomic(), self.assertRaises(IntegrityError) as caught:
            Opportunity.objects.filter(pk=review.pk).update(passive_source_sha256="not-a-digest")
        self.assertIn("jobs_opportunity_passive_digest_shape", str(caught.exception))
        for actor in (self.member, self.outsider):
            with self.assertRaises(PermissionDenied): self.priority(job, finding, actor=actor)

    def test_post_insert_late_review_source_actor_materializer_commercial_cancel_loss_rolls_back(self):
        job = self.collected(); finding = self.record(job)[0]
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        original_save = Opportunity.save
        mutations = (
            lambda row: Opportunity.objects.filter(pk=row.pk).update(review_reason="Altered hidden human judgment"),
            lambda row: Opportunity.objects.filter(pk=row.pk).update(actor=self.member),
            lambda row: Finding.objects.filter(pk=finding.pk).update(detected_at=timezone.now()),
            lambda row: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
            lambda row: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(updated_at=timezone.now()),
            lambda row: JobCancellation.objects.create(job=job, requested_by=self.owner),
            lambda row: OrganizationTrial.objects.filter(organization=self.organization).update(
                started_at=timezone.now() - timedelta(days=31), ends_at=timezone.now() - timedelta(days=1)))
        for mutate in mutations:
            inserted = False
            def save_then_change(row, *args, **kwargs):
                nonlocal inserted
                result = original_save(row, *args, **kwargs); inserted = True; mutate(row); return result
            with self.subTest(mutation=mutate), patch.object(Opportunity, "save", autospec=True, side_effect=save_then_change):
                with self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)): self.decision(job, finding)
            self.assertTrue(inserted); self.assertFalse(Opportunity.objects.exists())
        ends = timezone.now() + timedelta(seconds=5)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends - timedelta(days=30), ends_at=ends)
        inserted = False
        def save_expiring(row, *args, **kwargs):
            nonlocal inserted
            result = original_save(row, *args, **kwargs); inserted = True; return result
        with patch.object(Opportunity, "save", autospec=True, side_effect=save_expiring), patch("jobs.usage.timezone.now",
            side_effect=lambda: ends if inserted else ends - timedelta(microseconds=1)):
            with self.assertRaises((UsageLimitError, ValidationError)): self.decision(job, finding)
        self.assertTrue(inserted); self.assertFalse(Opportunity.objects.exists())

    def test_final_private_read_denies_independent_reviewer_loss_and_full_latest_row_drift(self):
        job = self.collected(); finding = self.record(job)[0]
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        review = self.decision(job, finding, actor=self.member)
        current = self.priority(job, finding)
        original_reader = reviews._reader(self.family)
        mutations = (
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer"),
            lambda: Opportunity.objects.filter(pk=review.pk).update(review_reason="Changed during final private source delivery"),
            lambda: Opportunity.objects.filter(pk=review.pk).update(created_at=timezone.now()),
            lambda: Opportunity.objects.filter(pk=review.pk).delete())
        for index, mutate in enumerate(mutations):
            caller_reads = 0
            def read_then_change(**kwargs):
                nonlocal caller_reads
                result = original_reader(**kwargs)
                if kwargs["actor"].pk == self.owner.pk:
                    caller_reads += 1
                    if caller_reads == 2: mutate()
                return result
            with self.subTest(mutation=mutate), transaction.atomic():
                with patch.object(reviews, "_reader", return_value=read_then_change):
                    with self.assertRaises((PermissionDenied, ValidationError)): self.priority(job, finding)
                # Reviewer authorization follows the final source recheck; row drift stops earlier.
                self.assertEqual(caller_reads, 3 if index == 0 else 2); transaction.set_rollback(True)
        self.assertEqual(self.priority(job, finding), current)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer")
        with self.assertRaises(PermissionDenied): self.priority(job, finding)
        with self.assertRaises(PermissionDenied): self.decision(job, finding, expected_revision=1)

    def test_final_latest_read_fences_independent_authority_and_exact_expiry_for_delivery_and_writes(self):
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        OrganizationMembership.objects.create(organization=self.organization, user=self.outsider, role="admin")
        caller = type(self.owner).objects.create_user("priority-caller@example.com", password="test-password")
        EmailAddress.objects.create(user=caller, email=caller.email, verified=True, primary=True)
        OrganizationMembership.objects.create(organization=self.organization, user=caller, role="admin")
        job = self.collected(); finding = self.record(job, actor=self.outsider)[0]
        review = self.decision(job, finding, actor=self.member)
        original = self.priority(job, finding, actor=caller)
        now = timezone.now; ends = now() + timedelta(seconds=5)
        mutations = {
            "original_actor": lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
            "materializer": lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.outsider).update(role="viewer"),
            "caller": lambda: OrganizationMembership.objects.filter(organization=self.organization, user=active_actor).update(role="viewer"),
            "reviewer": lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer"),
            "origin": lambda: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(updated_at=now()),
            "cancel": lambda: JobCancellation.objects.create(job=job, requested_by=self.owner),
            "natural_expiry": lambda: None,
        }
        for operation in ("empty_read", "create", "current", "replay", "correct"):
            active_actor = self.member if operation == "replay" else caller
            for loss, mutate in mutations.items():
                if loss == "reviewer" and operation not in {"current", "replay"}: continue
                with self.subTest(operation=operation, loss=loss), transaction.atomic():
                    if operation in {"empty_read", "create"}: Opportunity.objects.filter(pk=review.pk).delete()
                    before = list(Opportunity.objects.order_by("pk").values())
                    if loss == "natural_expiry":
                        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends-timedelta(days=30), ends_at=ends)
                    calls = 0; lost = False; latest = reviews._latest
                    def last_latest(*args):
                        nonlocal calls, lost
                        result = latest(*args); calls += 1
                        if calls == 2: mutate(); lost = True
                        return result
                    with patch.object(reviews, "_latest", side_effect=last_latest), patch("jobs.usage.timezone.now",
                        side_effect=lambda: (ends if lost else ends-timedelta(microseconds=1)) if loss == "natural_expiry" else now()):
                        with self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                            if operation in {"empty_read", "current"}: self.priority(job, finding, actor=active_actor)
                            else: self.decision(job, finding, actor=active_actor, expected_revision=1 if operation == "correct" else 0,
                                priority="high" if operation == "correct" else "low")
                    self.assertTrue(lost); self.assertEqual(calls, 2)
                    if operation in {"create", "replay", "correct"}:
                        self.assertEqual(list(Opportunity.objects.order_by("pk").values()), before)
                    transaction.set_rollback(True)
        self.assertEqual(self.priority(job, finding, actor=caller), original)

    def test_two_sessions_identical_replay_and_conflicting_correction_are_serialized(self):
        job = self.collected(); finding = self.record(job)[0]; barrier = Barrier(2)
        def record_once(priority="low", revision=0):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try: return self.decision(job, finding, priority=priority, expected_revision=revision).pk
                except ValidationError: return None
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _: record_once(), range(2)))
        self.assertEqual(results[0], results[1]); self.assertIsNotNone(results[0])
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            corrections = list(pool.map(lambda value: record_once(value, 1), ("medium", "high")))
        self.assertEqual(sum(value is not None for value in corrections), 1)
        self.assertEqual(Opportunity.objects.count(), 2)

    def test_private_priority_does_not_authorize_ordinary_review_report_admin_intent_action_or_draft(self):
        from .action_review import _opportunity_source
        from .findings import review_finding
        from .intent_mapping import current_query_findings
        from .reporting import create_project_report
        job = self.collected(); finding = self.record(job)[0]; review = self.decision(job, finding)
        client = Client(); client.force_login(self.owner)
        base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/"
        self.assertEqual(client.get(base + "findings/").json()["findings"], [])
        self.assertEqual(client.get(base + "first-audit/").json()["candidates"], [])
        with self.assertRaises(ValidationError):
            review_finding(project=self.project, actor=self.owner, finding_id=finding.pk, expected_revision=1,
                priority="high", estimated_effort="small", business_relevance="high", reason="Ordinary route has no passive authority")
        with self.assertRaises(ValidationError): current_query_findings(self.project, [finding.pk])
        with self.assertRaises(ValidationError): _opportunity_source(self.project, self.owner, review.pk, "update", "")
        with self.assertRaises(ValidationError): Recommendation.objects.create(project=self.project,
            actor=self.owner, opportunity=review, revision=1, draft="No passive draft contract")
        with self.assertRaises(PermissionDenied): create_project_report(project=self.project, actor=self.owner,
            request_key="no-private-priority-in-report", content_format="json", finding_ids=[finding.pk], action_review_ids=[], outcome_ids=[])
        request = RequestFactory().get("/admin/"); request.user = self.owner
        self.assertFalse(admin.site._registry[Opportunity].get_queryset(request).filter(pk=review.pk).exists())

    def test_retained_owner_stored_sequential_human_history_cutoff_and_child_first_foreign_erasure(self):
        from tenancy.customer_export import complete_bounded_customer_archive, project_customer_rows
        from tenancy.customer_inventory import CUSTOMER, require_complete_ownership_map
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import _customer_deletion_order, delete_customer_database_records, prepare_customer_data_deletion, sweep_customer_artifact_versions
        from tenancy.services import create_organization, create_project, revoke_origin_verification
        job = self.collected(); finding = self.record(job)[0]; review = self.decision(job, finding)
        require_complete_ownership_map(); order = [model._meta.label for model, _ in _customer_deletion_order()]
        self.assertLess(order.index("jobs.Opportunity"), order.index("jobs.Finding"))
        self.assertLess(order.index("jobs.Finding"), order.index("jobs.JobRun"))
        stored = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="a" * 32)
        self.assertTrue(capture_reserved_customer_snapshot(stored.pk))
        original_part, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=stored.pk, position=0)
        revoke_origin_verification(verification=self.verification, user=self.owner)
        now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(
            started_at=now - timedelta(days=40), ends_at=now - timedelta(days=10))
        with self.assertRaises((PermissionDenied, UsageLimitError)): self.priority(job, finding)
        exported = project_customer_rows(organization=self.organization, actor=self.owner,
            model_label="jobs.Opportunity", after_id=0, through_id=review.pk)["rows"]
        self.assertEqual(exported[0]["passive_source_sha256"], review.passive_source_sha256)
        self.assertIn("historical_human_passive_priority_not_current", exported[0]["scope"])
        with ZipFile(io.BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            self.assertEqual(json.loads(archive.read("records/jobs/Opportunity.json"))[0]["id"], review.pk)
        self.assertEqual(private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=stored.pk, position=0)[0], original_part)
        sequential = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="b" * 32, format="source-parts-v2")
        for _ in range(len(CUSTOMER) * 2 + 10):
            sequential.refresh_from_db()
            if sequential.state != sequential.State.PREPARING: break
            self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
        sequential.refresh_from_db(); self.assertEqual(sequential.state, sequential.State.READY)
        part = sequential.parts.get(source__model="jobs.Opportunity")
        data, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=sequential.pk, position=part.position)
        with ZipFile(io.BytesIO(data)) as archive: self.assertEqual(json.loads(archive.read("data"))[0]["id"], review.pk)
        other_org = create_organization(user=self.outsider, name="Other retained organization")
        other = create_project(organization=other_org, user=self.outsider, name="Other retained scope", canonical_origin="https://extra.example.invalid")
        with self.assertRaises(PermissionDenied): project_customer_rows(organization=self.organization, actor=self.outsider,
            model_label="jobs.Opportunity", after_id=0, through_id=review.pk)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): project_customer_rows(organization=self.organization, actor=self.owner,
            model_label="jobs.Opportunity", after_id=0, through_id=review.pk)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(Opportunity.objects.filter(pk=review.pk).exists()); self.assertFalse(Finding.objects.filter(pk=finding.pk).exists())
        self.assertFalse(JobRun.objects.filter(pk=job.pk).exists()); self.assertTrue(other_org.projects.filter(pk=other.pk).exists())


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class HeaderPriorityTests(PriorityChecks, TransactionTestCase):
    setUp = fixtures.HeaderReviewSourceTests.setUp
    verified = fixtures.HeaderReviewSourceTests.verified
    queue = fixtures.HeaderReviewSourceTests.queue
    transport = fixtures.HeaderReviewSourceTests.transport
    collected = fixtures.HeaderReviewSourceTests.collected
    record = fixtures.HeaderReviewSourceTests.record
    review_source = fixtures.HeaderReviewSourceTests.review_source
    source = staticmethod(fixtures.HeaderReviewSourceTests.source)
    family = "header"
    record_priority = staticmethod(reviews.record_header_priority)
    read_priority = staticmethod(reviews.current_header_priority)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class ResourcePriorityTests(PriorityChecks, TransactionTestCase):
    setUp = fixtures.ResourceReviewSourceTests.setUp
    verified = fixtures.ResourceReviewSourceTests.verified
    queue = fixtures.ResourceReviewSourceTests.queue
    transport = fixtures.ResourceReviewSourceTests.transport
    collected = fixtures.ResourceReviewSourceTests.collected
    record = fixtures.ResourceReviewSourceTests.record
    review_source = fixtures.ResourceReviewSourceTests.review_source
    source = staticmethod(fixtures.ResourceReviewSourceTests.source)
    family = "resource"
    record_priority = staticmethod(reviews.record_resource_priority)
    read_priority = staticmethod(reviews.current_resource_priority)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class TLSPriorityTests(PriorityChecks, TransactionTestCase):
    setUp = fixtures.TLSReviewSourceTests.setUp
    verified = fixtures.TLSReviewSourceTests.verified
    queue = fixtures.TLSReviewSourceTests.queue
    transport = fixtures.TLSReviewSourceTests.transport
    collected = fixtures.TLSReviewSourceTests.collected
    record = fixtures.TLSReviewSourceTests.record
    review_source = fixtures.TLSReviewSourceTests.review_source
    source = staticmethod(fixtures.TLSReviewSourceTests.source)
    family = "tls"
    record_priority = staticmethod(reviews.record_tls_priority)
    read_priority = staticmethod(reviews.current_tls_priority)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class RedirectPriorityTests(PriorityChecks, TransactionTestCase):
    setUp = fixtures.RedirectReviewSourceTests.setUp
    verified = fixtures.RedirectReviewSourceTests.verified
    queue = fixtures.RedirectReviewSourceTests.queue
    transport = fixtures.RedirectReviewSourceTests.transport
    collected = fixtures.RedirectReviewSourceTests.collected
    record = fixtures.RedirectReviewSourceTests.record
    review_source = fixtures.RedirectReviewSourceTests.review_source
    source = staticmethod(fixtures.RedirectReviewSourceTests.source)
    WIRE = fixtures.RedirectReviewSourceTests.WIRE
    family = "redirect"
    record_priority = staticmethod(reviews.record_redirect_priority)
    read_priority = staticmethod(reviews.current_redirect_priority)


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class RedirectChainPriorityTests(PriorityChecks, TransactionTestCase):
    setUp = fixtures.RedirectChainReviewSourceTests.setUp
    verified = fixtures.RedirectChainReviewSourceTests.verified
    queue = fixtures.RedirectChainReviewSourceTests.queue
    collected = fixtures.RedirectChainReviewSourceTests.collected
    record = fixtures.RedirectChainReviewSourceTests.record
    review_source = fixtures.RedirectChainReviewSourceTests.review_source
    source = staticmethod(fixtures.RedirectChainReviewSourceTests.source)
    family = "redirect_chain"
    record_priority = staticmethod(reviews.record_redirect_chain_priority)
    read_priority = staticmethod(reviews.current_redirect_chain_priority)

    def test_every_original_origin_including_unvisited_and_private_bytes_after_final_latest(self):
        from . import passive_header_collection as lifecycle
        unvisited = self.verified("https://www.security.example.com")
        self.data["target_urls"].append(unvisited.origin + "/unvisited")
        job = self.collected(fields=f"Location: {self.data['url']}\r\n".encode()); finding = self.record(job)[0]
        self.assertEqual((finding.evidence["availability"]["selected_urls"], finding.evidence["availability"]["observed_hops"]), (3, 1))
        self.decision(job, finding); original = self.priority(job, finding)
        for operation in ("read", "correct"):
            for verification in (self.https_verification, self.http_verification, unvisited, None):
                with self.subTest(operation=operation, origin=None if verification is None else verification.origin), transaction.atomic():
                    before = list(Opportunity.objects.order_by("pk").values())
                    calls = 0; lost = False; latest = reviews._latest; read_bytes = lifecycle.read_project_artifact
                    def last_latest(*args):
                        nonlocal calls, lost
                        result = latest(*args); calls += 1
                        if calls == 2:
                            lost = True
                            if verification is not None:
                                ProjectOriginVerification.objects.filter(pk=verification.pk).update(updated_at=timezone.now())
                        return result
                    def late_bytes(**kwargs): return b"{}" if lost and verification is None else read_bytes(**kwargs)
                    with patch.object(reviews, "_latest", side_effect=last_latest), patch.object(lifecycle, "read_project_artifact", side_effect=late_bytes):
                        with self.assertRaises((PermissionDenied, ValidationError)):
                            if operation == "read": self.priority(job, finding)
                            else: self.decision(job, finding, expected_revision=1, priority="high")
                    self.assertTrue(lost)
                    if operation == "correct": self.assertEqual(list(Opportunity.objects.order_by("pk").values()), before)
                    transaction.set_rollback(True)
        self.assertEqual(self.priority(job, finding), original)
        for family in ("header", "resource", "tls", "redirect"):
            with self.subTest(family=family), patch.object(lifecycle, "_read_metadata", side_effect=AssertionError("No private pins for wrong family")):
                with self.assertRaises(PermissionDenied):
                    reviews._current(family=family, project=self.project, actor=self.owner, job_id=job.pk, finding_id=finding.pk)
                with self.assertRaises(PermissionDenied):
                    reviews._record(family=family, project=self.project, actor=self.owner, job_id=job.pk, finding_id=finding.pk,
                        source_sha256=original["source"]["source_sha256"], expected_revision=1, priority="high",
                        estimated_effort="unknown", business_relevance="unknown", reason="Wrong original source family")


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv"}))
class OrdinaryPriorityDigestTests(TestCase):
    setUp = ordinary_fixtures.FindingEvidenceTests.setUp

    def test_ordinary_review_stays_blank_and_cannot_claim_a_passive_digest(self):
        from .findings import record_csv_findings, review_finding
        finding = record_csv_findings(project=self.project, actor=self.owner, connection=self.connection, import_id=self.run.pk)[0][0]
        review = review_finding(project=self.project, actor=self.owner, finding_id=finding.pk, expected_revision=0,
            priority="low", estimated_effort="unknown", business_relevance="unknown", reason="Ordinary genuine source")
        self.assertEqual(review.passive_source_sha256, "")
        with self.assertRaises(ValidationError): Opportunity(project=self.project, actor=self.owner, finding=finding,
            revision=2, passive_source_sha256="a" * 64, review_reason="False passive attribution").full_clean()
