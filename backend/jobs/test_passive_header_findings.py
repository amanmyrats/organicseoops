from tenancy.customer_artifact_barrier import project_artifact_barrier
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import io
import json
from threading import Barrier
from unittest.mock import patch
from zipfile import ZipFile

from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import Client, RequestFactory, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, Project, ProjectOriginVerification
from . import passive_header_collection as collector
from . import passive_header_findings as findings
from . import test_passive_header_collection as fixtures
from .models import Finding, JobCancellation, JobRun, JobStep, Opportunity, ProjectReportSnapshot, Recommendation, UsageReservation
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class PassiveHeaderFindingTests(TransactionTestCase):
    setUp = fixtures.PassiveHeaderCollectionTests.setUp
    verified = fixtures.PassiveHeaderCollectionTests.verified
    queue = fixtures.PassiveHeaderCollectionTests.queue
    transport = fixtures.PassiveHeaderCollectionTests.transport

    def collected(self, key="header-findings", wire=None):
        job = self.queue(key)
        self.assertTrue(collector.execute_passive_header_collection(job.pk, fetcher=self.transport(wire=wire)))
        job.refresh_from_db()
        return job

    def record(self, job, **changes):
        return findings.record_header_findings(**{**dict(project=self.project, actor=self.owner, job_id=job.pk), **changes})

    def read(self, job, **changes):
        return findings.current_header_findings(**{**dict(project=self.project, actor=self.owner, job_id=job.pk), **changes})

    def test_genuine_original_materialization_is_idempotent_bounded_private_and_not_prioritization(self):
        job = self.collected()
        with patch("socket.create_connection", side_effect=AssertionError("No network")):
            rows = self.record(job)
            self.assertEqual([row.pk for row in self.record(job)], [row.pk for row in rows])
            with CaptureQueriesContext(connection) as queries:
                report = self.read(job)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(len(rows), 7)
        self.assertEqual(len(report["findings"]), len(rows))
        self.assertTrue(report["source_current"])
        for row in rows:
            self.assertEqual(row.source_passive_header_id, job.pk)
            self.assertTrue(all(getattr(row, field) is None for field in
                ("source_metric_id", "source_api_page_id", "source_diagnostics_id", "source_indexation_id", "source_performance_id")))
            self.assertEqual(row.evidence["observed_at"], job.output["observed_at"])
            self.assertEqual(row.evidence["status"], job.output["status"])
            self.assertEqual(row.evidence["collection_sha256"], job.output["derived_sha256"])
            self.assertEqual(row.evidence["binding"], job.config_snapshot["binding"])
            self.assertLessEqual(len(json.dumps(row.evidence, separators=(",", ":")).encode()), 4096)
            self.assertGreaterEqual(row.detected_at, collector._date(row.evidence["observed_at"]))
        for private in (self.challenge, self.owner.email, "nonce-private", "secret", "private body"):
            self.assertNotIn(private, json.dumps(report))
        self.assertEqual((Opportunity.objects.count(), Recommendation.objects.count()), (0, 0))
        original = deepcopy(report)
        report["findings"][0]["evidence"]["fact"]["state"] = "changed"
        self.assertEqual(self.read(job), original)
        # Another current admin reads the original source; no actor rewriting.
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(self.read(job, actor=self.member), original)
        self.assertEqual([row.pk for row in self.record(job, actor=self.member)], [row.pk for row in rows])

    def test_empty_facts_remain_no_materialization_not_secure_and_maximum_url_recipes_fit(self):
        from .passive_header_candidates import SECURITY_HEADERS
        wire = b"HTTP/1.1 200 OK\r\n" + b"".join(name.encode() + b": present\r\n" for name in SECURITY_HEADERS) + b"\r\n"
        job = self.collected(wire=wire)
        self.assertEqual(self.record(job), [])
        self.assertEqual(self.read(job)["findings"], [])
        self.assertFalse(Finding.objects.exists())
        binding = deepcopy(job.config_snapshot["binding"])
        binding["url"] = binding["origin"] + "/" + "x" * (1024 - len(binding["origin"]) - 1)
        observation = {key: value for key, value in job.output.items() if key not in {"artifact_id", "derived_sha256"}}
        observation["url"] = binding["url"]
        observation["evidence"]["headers"]["content-security-policy"] = "absent"
        with self.assertNumQueries(0):
            recipes = findings.header_finding_values(job_id=job.pk, binding=binding, observation=observation)
        self.assertEqual(len(recipes), 1)
        self.assertLessEqual(len(collector._encode(recipes[0]["evidence"])), 4096)

    def test_immutable_model_exact_source_fact_identity_and_sql_one_source_constraints(self):
        job = self.collected()
        row = self.record(job)[0]
        with self.assertRaises(ValidationError): row.save()
        with transaction.atomic(), self.assertRaises(IntegrityError) as caught:
            Finding.objects.filter(pk=row.pk).update(source_passive_header=None)
        self.assertIn("jobs_finding_one_source", str(caught.exception))
        with transaction.atomic(), self.assertRaises(IntegrityError) as caught:
            Finding.objects.filter(pk=row.pk).update(source_diagnostics_id=999999)
        self.assertIn("jobs_finding_one_source", str(caught.exception))
        recipe = {key: getattr(row, key) for key in findings.FIELDS}
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other.example.invalid")
        for change in ({"project": other}, {"fingerprint": "a" * 64}, {"detector": "invented"},
            {"confidence": "high"}, {"evidence": {**row.evidence, "status": True}},
            {"evidence": {**row.evidence, "raw_headers": "private"}}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                Finding(**{**dict(project=self.project, actor=self.owner), **recipe, **change}).full_clean()
        cookie = next(row for row in self.record(job) if "flag" in row.evidence["fact"])
        bad = {key: getattr(cookie, key) for key in findings.FIELDS}
        bad["evidence"] = {**cookie.evidence, "fact": {**cookie.evidence["fact"], "count": True}}
        with self.assertRaises(ValidationError): Finding(project=self.project, actor=self.owner, **bad).full_clean()
        with self.assertRaises(ValidationError):
            Opportunity.objects.create(project=self.project, finding=row, actor=self.owner, review_reason="Not supported")
        with transaction.atomic():
            JobRun.objects.filter(pk=job.pk).update(handler="collect_passive_redirects")
            with self.assertRaises(ValidationError): Finding(project=self.project, actor=self.owner, **recipe).full_clean()
            transaction.set_rollback(True)

    def test_current_authority_scope_cancellation_and_expiry_deny_without_writes(self):
        job = self.collected()
        for actor in (self.member, self.outsider):
            with self.assertRaises(PermissionDenied): self.record(job, actor=actor)
        for value in (True, 0, -1, 2**53, "1"):
            with self.assertRaises(ValidationError): self.record(job, job_id=value)
        changes = (
            lambda: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="revoked", revoked_at=timezone.now()),
            lambda: JobCancellation.objects.create(job=job, requested_by=self.owner),
            lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True),
            lambda: OrganizationTrial.objects.filter(organization=self.organization).update(
                started_at=timezone.now() - timedelta(days=31), ends_at=timezone.now() - timedelta(days=1)))
        for change in changes:
            with transaction.atomic():
                change()
                with self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)): self.record(job)
                self.assertFalse(Finding.objects.exists())
                transaction.set_rollback(True)

    def test_post_insert_source_row_actor_commercial_and_cancel_loss_roll_back_complete_set(self):
        job = self.collected()
        save = Finding.save
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        changes = (
            lambda row: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
            lambda row: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(updated_at=timezone.now()),
            lambda row: JobStep.objects.filter(job=job).update(created_at=timezone.now()),
            lambda row: UsageReservation.objects.filter(job=job).update(period_start=timezone.now().date() - timedelta(days=1)),
            lambda row: JobCancellation.objects.create(job=job, requested_by=self.owner),
            lambda row: OrganizationTrial.objects.filter(organization=self.organization).update(
                started_at=timezone.now() - timedelta(days=31), ends_at=timezone.now() - timedelta(days=1)),
            lambda row: Finding.objects.filter(pk=row.pk).update(detected_at=timezone.now() + timedelta(days=1)),
            lambda row: Finding.objects.filter(pk=row.pk).update(actor=self.member),
            lambda row: Finding.objects.filter(pk=row.pk).update(evidence={**row.evidence, "status": True}))
        for change in changes:
            altered = False
            def save_changed(row, *args, **kwargs):
                nonlocal altered
                result = save(row, *args, **kwargs)
                if not altered:
                    altered = True; change(row)
                return result
            with self.subTest(change=change), patch.object(Finding, "save", autospec=True, side_effect=save_changed):
                with self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)): self.record(job)
            self.assertTrue(altered)
            self.assertFalse(Finding.objects.exists())
        ends = timezone.now() + timedelta(seconds=5)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends - timedelta(days=30), ends_at=ends)
        inserted = False
        def insert_expiring(row, *args, **kwargs):
            nonlocal inserted
            result = save(row, *args, **kwargs); inserted = True; return result
        with patch("jobs.usage.timezone.now", side_effect=lambda: ends if inserted else ends - timedelta(seconds=1)), patch.object(
            Finding, "save", autospec=True, side_effect=insert_expiring), self.assertRaises(UsageLimitError): self.record(job)
        self.assertFalse(Finding.objects.exists())

    def test_private_current_read_final_rows_and_materializer_authority_are_fenced(self):
        job = self.collected()
        rows = self.record(job)
        original = self.read(job)
        validate = findings._validate_rows
        calls = 0
        def validate_then_change(*args):
            nonlocal calls
            validate(*args); calls += 1
            if calls == 2: Finding.objects.filter(pk=rows[0].pk).update(actor=self.member)
        with transaction.atomic():
            with patch.object(findings, "_validate_rows", side_effect=validate_then_change), self.assertRaises(PermissionDenied): self.read(job)
            transaction.set_rollback(True)
        self.assertEqual(self.read(job), original)
        with transaction.atomic():
            Finding.objects.filter(pk=rows[0].pk).delete()
            with self.assertRaises(ValidationError): self.read(job)
            with self.assertRaises(ValidationError): self.record(job)
            transaction.set_rollback(True)
        # A different materializer losing management authority is independent of original source owner/caller.
        Finding.objects.filter(pk__in=[row.pk for row in rows]).update(actor=self.member)
        with self.assertRaises(PermissionDenied): self.read(job)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(len(self.read(job)["findings"]), len(rows))

    def test_complete_row_validation_checks_each_distinct_materializer_once_per_pass(self):
        job = self.collected(); rows = self.record(job)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        Finding.objects.filter(pk=rows[-1].pk).update(actor=self.member)
        observation = {key: value for key, value in job.output.items() if key not in {"artifact_id", "derived_sha256"}}
        recipes = findings.header_finding_values(job_id=job.pk, binding=job.config_snapshot["binding"], observation=observation)
        with patch.object(collector, "_read_source", wraps=collector._read_source) as authority:
            findings._validate_rows(findings._rows(self.project, job.pk), recipes, self.project, job.pk)
        self.assertEqual([call.args[2].pk for call in authority.call_args_list], [self.owner.pk, self.member.pk])
        # A later pass must not reuse the earlier authorization result.
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer")
        with self.assertRaises(PermissionDenied):
            findings._validate_rows(findings._rows(self.project, job.pk), recipes, self.project, job.pk)

    def test_ordinary_list_first_audit_reports_shares_weekly_admin_and_intent_cannot_consume(self):
        from .findings import review_finding
        from .intent_mapping import current_query_findings
        from .reporting import _render_report, create_project_report, read_project_report
        from .report_shares import create_report_share
        from .weekly_summary import _original_rows
        from tenancy.artifacts import save_project_artifact
        job = self.collected()
        rows = self.record(job)
        owner = Client(); owner.force_login(self.owner)
        path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/"
        listed = owner.get(path + "findings/").json()
        self.assertEqual((listed["findings"], listed["has_more"]), ([], False))
        first_audit = owner.get(path + "first-audit/").json()
        self.assertEqual(first_audit["candidates"], [])
        self.assertFalse(first_audit["candidates_truncated"])
        with self.assertRaises(ValidationError): current_query_findings(self.project, [rows[0].pk])
        with self.assertRaises(ValidationError):
            review_finding(project=self.project, actor=self.owner, finding_id=rows[0].pk, expected_revision=0,
                priority="low", estimated_effort="unknown", business_relevance="unknown", reason="No passive review contract")
        for fmt in ("json", "csv"):
            with self.assertRaises(PermissionDenied): _render_report(self.project, rows, [], [], fmt)
            with self.assertRaises(PermissionDenied):
                create_project_report(project=self.project, actor=self.owner, request_key="denied-passive-report",
                    content_format=fmt, finding_ids=[rows[0].pk], action_review_ids=[], outcome_ids=[])
        # Explicit corrupt report fixture: delivery must deny even if a stored body's integrity matches.
        data = b'{"private_passive_evidence":"must not deliver"}'
        with project_artifact_barrier(self.project.organization_id, shared=True):
            key = save_project_artifact(project=self.project, content=data, content_type="application/json")
        snapshot = ProjectReportSnapshot.objects.create(project=self.project, created_by=self.owner,
            request_key="corrupt-passive-report", content_format="json", artifact_key=key,
            content_sha256=sha256(data).hexdigest(), size_bytes=len(data), finding_ids=[rows[0].pk],
            action_review_ids=[], outcome_ids=[])
        with self.assertRaises(PermissionDenied): read_project_report(project=self.project, actor=self.owner, snapshot=snapshot)
        with self.assertRaises(PermissionDenied): _original_rows(snapshot)
        with self.assertRaises(PermissionDenied):
            create_report_share(project=self.project, actor=self.owner, report_id=snapshot.pk, request_key="denied-passive-share",
                recipient_email="reader@example.invalid", expires_hours=1, acknowledge_link_access=True)
        self.assertEqual(owner.get(path + f"reports/{snapshot.pk}/download/").status_code, 404)
        request = RequestFactory().get("/admin/"); request.user = self.owner
        self.assertFalse(admin.site._registry[Finding].get_queryset(request).filter(pk__in=[row.pk for row in rows]).exists())
        self.assertFalse(Recommendation.objects.exists())

    def test_two_sessions_materialize_one_original_complete_set(self):
        job = self.collected()
        barrier = Barrier(2)
        def record_once():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return [row.pk for row in self.record(job)]
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: record_once(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(Finding.objects.filter(source_passive_header=job).count(), len(results[0]))

    def test_customer_retained_export_and_child_first_scoped_erasure(self):
        from tenancy.customer_export import complete_bounded_customer_archive, project_customer_rows
        from tenancy.customer_inventory import CUSTOMER, require_complete_ownership_map
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import _customer_deletion_order, delete_customer_database_records, prepare_customer_data_deletion, sweep_customer_artifact_versions
        from tenancy.services import create_organization, create_project, revoke_origin_verification
        job = self.collected()
        rows = self.record(job)
        require_complete_ownership_map()
        order = [model._meta.label for model, _lookup in _customer_deletion_order()]
        self.assertLess(order.index("jobs.Finding"), order.index("jobs.JobRun"))
        stored = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="a" * 32)
        self.assertTrue(capture_reserved_customer_snapshot(stored.pk))
        original_part, _metadata = private_snapshot_part(organization=self.organization, actor=self.owner,
            snapshot_id=stored.pk, position=0)
        revoke_origin_verification(verification=self.verification, user=self.owner)
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=40), ends_at=now - timedelta(days=10))
        with self.assertRaises((PermissionDenied, UsageLimitError)): self.read(job)
        exported = project_customer_rows(organization=self.organization, actor=self.owner,
            model_label="jobs.Finding", after_id=0, through_id=rows[-1].pk)
        self.assertEqual(len(exported["rows"]), len(rows))
        self.assertIn("historical_response_fact_not_current", exported["rows"][0]["scope"])
        with ZipFile(io.BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            retained = json.loads(archive.read("records/jobs/Finding.json"))
            self.assertEqual({row["source_passive_header_id"] for row in retained}, {job.pk})
        self.assertEqual(private_snapshot_part(organization=self.organization, actor=self.owner,
            snapshot_id=stored.pk, position=0)[0], original_part)
        sequential = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner,
            request_key="b" * 32, format="source-parts-v2")
        for _ in range(len(CUSTOMER) * 2 + 10):
            sequential.refresh_from_db()
            if sequential.state != sequential.State.PREPARING: break
            self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
        sequential.refresh_from_db(); self.assertEqual(sequential.state, sequential.State.READY)
        part = sequential.parts.get(source__model="jobs.Finding")
        data, _metadata = private_snapshot_part(organization=self.organization, actor=self.owner,
            snapshot_id=sequential.pk, position=part.position)
        with ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(len(json.loads(archive.read("data"))), len(rows))
        other_org = create_organization(user=self.outsider, name="Other retained organization")
        other = create_project(organization=other_org, user=self.outsider, name="Other retained scope",
            canonical_origin="https://extra.example.invalid")
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): project_customer_rows(organization=self.organization, actor=self.owner,
            model_label="jobs.Finding", after_id=0, through_id=rows[-1].pk)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(Finding.objects.exists())
        self.assertFalse(JobRun.objects.filter(pk=job.pk).exists())
        self.assertTrue(Project.objects.filter(pk=other.pk, organization=other_org).exists())
