from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import io
import json
from threading import Barrier
from unittest.mock import patch
from zipfile import ZipFile

from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, reset_queries, transaction
from django.db.models.deletion import ProtectedError
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, OrganizationTrial, Project, ProjectMembership, ProjectOriginVerification
from . import passive_header_collection as lifecycle
from . import passive_redirect_chain_collection as collector
from . import passive_redirect_chain_findings as findings
from . import test_passive_header_findings as header_checks
from . import test_passive_redirect_chain_collection as fixtures
from . import test_passive_redirect_chain_transport as transport_fixtures
from .models import Finding, JobCancellation, JobRun, JobStep, Opportunity, Recommendation, UsageReservation
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class PassiveRedirectChainFindingTests(TransactionTestCase):
    verified = fixtures.PassiveRedirectChainCollectionTests.verified
    queue = fixtures.PassiveRedirectChainCollectionTests.queue

    def setUp(self):
        fixtures.PassiveRedirectChainCollectionTests.setUp(self)
        self.data = {**self.data, "url": self.https + "/public", "target_urls": [self.http + "/public"]}

    def collected(self, key="chain-facts", *, loop=True, max_redirects=5, fields=None):
        job = self.queue(key)
        case = transport_fixtures.PassiveRedirectChainTransportTests(); self.addCleanup(case.doCleanups)
        urls = [self.data["url"], *self.data["target_urls"]]
        wires = [f"HTTP/1.1 301 Moved\r\nLocation: {url}\r\nSet-Cookie: private=secret\r\n\r\nprivate body".encode() for url in urls[1:]]
        wires.append(f"HTTP/1.1 302 Found\r\nLocation: {urls[0]}\r\n\r\n".encode() if loop else b"HTTP/1.1 200 OK\r\n\r\n")
        if fields is not None: wires = [b"HTTP/1.1 301 Moved\r\n" + fields + b"\r\n"]
        fetcher, self.connections, self.responses, *_ = case.transport(*wires, max_redirects=max_redirects)
        fetcher.scope = fixtures.CrawlScope(frozenset({"security.example.com", "www.security.example.com"}))
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")):
            self.assertTrue(collector.execute_passive_redirect_chain_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); return job

    def record(self, job, **changes):
        return findings.record_redirect_chain_findings(**{**dict(project=self.project, actor=self.owner, job_id=job.pk), **changes})

    def read(self, job, **changes):
        return findings.current_redirect_chain_findings(**{**dict(project=self.project, actor=self.owner, job_id=job.pk), **changes})

    test_ordinary_list_first_audit_reports_shares_weekly_admin_and_intent_cannot_consume = header_checks.PassiveHeaderFindingTests.test_ordinary_list_first_audit_reports_shares_weekly_admin_and_intent_cannot_consume

    def test_genuine_complete_two_fact_idempotent_private_read_only_independent_caller(self):
        job = self.collected(); counts = (JobRun.objects.count(), UsageReservation.objects.count())
        self.assertEqual(self.read(job)["state"], "no_retained_materialized_findings")
        rows = self.record(job); self.assertEqual(len(rows), 2)
        original = self.read(job)
        with patch("socket.create_connection", side_effect=AssertionError("No network")):
            self.assertEqual([row.pk for row in self.record(job)], [row.pk for row in rows])
            reset_queries()  # Capture the whole read-only query set after genuine production/materialization.
            with CaptureQueriesContext(connection) as queries: self.assertEqual(self.read(job), original)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual({row.source_passive_redirect_chain_id for row in rows}, {job.pk})
        self.assertEqual({row.actor_id for row in rows}, {self.owner.pk})
        for row in rows:
            self.assertEqual(row.subject, self.data["url"])
            self.assertEqual(row.evidence["binding"]["actor_id"], self.owner.pk)
            self.assertEqual(row.evidence["collection_sha256"], job.output["derived_sha256"])
            self.assertEqual(row.evidence["last_observed_at"], job.output["last_observed_at"])
            self.assertLessEqual(len(lifecycle._encode(row.evidence)), 4096)
        original_copy = deepcopy(original); original["findings"][0]["evidence"]["captures"].clear()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(self.read(job, actor=self.member), original_copy)
        self.assertEqual([row.pk for row in self.record(job, actor=self.member)], [row.pk for row in rows])
        self.assertEqual((JobRun.objects.count(), UsageReservation.objects.count()), counts)
        self.assertEqual((Opportunity.objects.count(), Recommendation.objects.count()), (0, 0))
        for private in (self.challenge, self.owner.email, "raw_location", "private", "secret=value", "target_urls"):
            self.assertNotIn(private, json.dumps(original_copy))
        for conn, response in zip(self.connections, self.responses): conn.request.assert_called_once(); response.read.assert_not_called()

    def test_native_empty_unknown_terminal_maximum_paths_and_budget_facts(self):
        for key, fields in (("absent", b""), ("ambiguous", b"Location: /one\r\nLocation: /two\r\n"),
            ("outside", b"Location: https://foreign.invalid/private\r\n"), ("unknown", b"Location: javascript:private\r\n")):
            job = self.collected(key, fields=fields)
            self.assertEqual(self.record(job), []); self.assertEqual(self.read(job)["findings"], [])
        self.data = {**self.data, "url": self.http + "/terminal", "target_urls": []}
        terminal = self.collected("terminal", loop=False); self.assertEqual(self.record(terminal), [])
        urls = [(self.https if index % 2 == 0 else self.http) + f"/page-{index}-" for index in range(6)]
        urls = [prefix + "x" * (1024 - len(prefix)) for prefix in urls]
        self.data = {**self.data, "url": urls[0], "target_urls": urls[1:]}
        maximum = self.collected("maximum"); rows = self.record(maximum)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(len(row.evidence["captures"]), 6); self.assertEqual(row.evidence["availability"]["selected_urls"], 6)
            self.assertLessEqual(len(lifecycle._encode(row.evidence)), 4096)
        budget = self.collected("budget", max_redirects=1); rows = self.record(budget)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row.evidence["availability"]["observed_hops"] for row in rows}, {2})
        self.assertIn("redirect_limit", [row.evidence["fact"].get("state") for row in rows])

    def test_genuine_model_immutable_full_original_identity_sql_one_source_and_priority_action_denial(self):
        from .action_review import _opportunity_source
        job = self.collected(); row = self.record(job)[0]
        with self.assertRaises(ValidationError): row.save()
        with self.assertRaises(ProtectedError): job.delete()
        for field in ("source_metric", "source_api_page", "source_diagnostics", "source_indexation", "source_performance",
            "source_passive_header", "source_passive_resource", "source_passive_tls", "source_passive_redirect"):
            with transaction.atomic(), self.assertRaises(IntegrityError) as caught:
                Finding.objects.filter(pk=row.pk).update(**{field + "_id": job.pk})
            self.assertIn("jobs_finding_one_source", str(caught.exception))
        with transaction.atomic(), self.assertRaises(IntegrityError) as caught:
            Finding.objects.filter(pk=row.pk).update(source_passive_redirect_chain=None)
        self.assertIn("jobs_finding_one_source", str(caught.exception))
        recipe = {key: getattr(row, key) for key in findings.FIELDS}
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://foreign.example.invalid")
        for change in ({"project": other}, {"fingerprint": "a" * 64}, {"detector": "invented"}, {"confidence": "high"},
            {"subject": self.http}, {"evidence": {**row.evidence, "binding_sha256": "b" * 64}},
            {"evidence": {**row.evidence, "raw_location": "private"}}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                Finding(**{**dict(project=self.project, actor=self.owner), **recipe, **change}).full_clean()
        for change in ({"handler": "collect_passive_redirects"}, {"status": "failed"}, {"output": {}}):
            with transaction.atomic():
                JobRun.objects.filter(pk=job.pk).update(**change)
                with self.assertRaises(ValidationError): Finding(project=self.project, actor=self.owner, **recipe).full_clean()
                transaction.set_rollback(True)
        with self.assertRaises(ValidationError): Opportunity.objects.create(project=self.project, finding=row, actor=self.owner, review_reason="Denied")
        opportunity = Opportunity.objects.bulk_create([Opportunity(project=self.project, finding=row, actor=self.owner, review_reason="Corrupt fixture")])[0]
        with self.assertRaises(ValidationError): Recommendation.objects.create(project=self.project, opportunity=opportunity, actor=self.owner, revision=1, draft="Denied")
        recommendation = Recommendation.objects.bulk_create([Recommendation(project=self.project, opportunity=opportunity, actor=self.owner, revision=1, draft="Corrupt fixture")])[0]
        with self.assertRaises(ValidationError): _opportunity_source(self.project, self.owner, opportunity.pk, "update", "")
        request = header_checks.RequestFactory().get("/admin/"); request.user = self.owner
        self.assertFalse(admin.site._registry[Opportunity].get_queryset(request).filter(pk=opportunity.pk).exists())
        self.assertFalse(admin.site._registry[Recommendation].get_queryset(request).filter(pk=recommendation.pk).exists())

    def test_scope_family_role_restrictions_deny_before_private_metadata_and_original_actor_remains_required(self):
        job = self.collected()
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://foreign.example.invalid")
        for operation in (self.read, self.record):
            with patch.object(lifecycle, "_read_metadata", side_effect=AssertionError("No premature private pin")):
                for changes in ({"actor": self.member}, {"actor": self.outsider}, {"project": other}, {"job_id": job.pk + 1000}):
                    with self.assertRaises(PermissionDenied): operation(job, **changes)
            for field, values in (("handler", set(lifecycle.PASSIVE_HANDLERS) - {collector.HANDLER}), ("status", ("queued", "running", "failed", "cancelled"))):
                for value in values:
                    with transaction.atomic():
                        JobRun.objects.filter(pk=job.pk).update(**{field: value})
                        with patch.object(lifecycle, "_read_metadata", side_effect=AssertionError("No premature private pin")), self.assertRaises(PermissionDenied): operation(job)
                        transaction.set_rollback(True)
            for value in (True, 0, -1, 2**53, "1"):
                with self.assertRaises(ValidationError): operation(job, job_id=value)
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)
        OrganizationMembership.objects.filter(pk=membership.pk).update(role="admin")
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True); self.project.refresh_from_db()
        job = self.collected("restricted-original")
        with self.assertRaises(PermissionDenied): self.record(job, actor=self.member)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(len(self.record(job, actor=self.member)), 2)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member")
        with self.assertRaises(PermissionDenied): self.read(job, actor=self.member)

    def test_post_insert_source_metadata_actor_cancel_commercial_and_full_intended_rows_roll_back(self):
        job = self.collected(); save = Finding.save
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        changes = [lambda row: JobStep.objects.filter(job=job).update(created_at=timezone.now()),
            lambda row: JobCancellation.objects.create(job=job, requested_by=self.owner),
            lambda row: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
            lambda row: OrganizationTrial.objects.filter(organization=self.organization).update(started_at=timezone.now()-timedelta(days=31), ends_at=timezone.now()-timedelta(days=1)),
            lambda row: Finding.objects.filter(pk=row.pk).update(detected_at=timezone.now()),
            lambda row: Finding.objects.filter(pk=row.pk).update(actor=self.member),
            lambda row: Finding.objects.filter(pk=row.pk).update(evidence={**row.evidence, "raw_location": "private"})]
        for verification in (self.http_verification, self.https_verification):
            changes.append(lambda row, pk=verification.pk: ProjectOriginVerification.objects.filter(pk=pk).update(updated_at=timezone.now()))
        for change in changes:
            changed = False
            def save_changed(row, *args, **kwargs):
                nonlocal changed
                result = save(row, *args, **kwargs)
                if not changed: changed = True; change(row)
                return result
            with self.subTest(change=change), patch.object(Finding, "save", autospec=True, side_effect=save_changed), self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                self.record(job)
            self.assertTrue(changed); self.assertFalse(Finding.objects.exists())

    def test_complete_partial_corrupt_over_ceiling_and_late_row_materializer_loss_withhold(self):
        job = self.collected(); rows = self.record(job); original = self.read(job)
        for change in (lambda: Finding.objects.filter(pk=rows[-1].pk).delete(),
            lambda: Finding.objects.filter(pk=rows[0].pk).update(evidence={}),
            lambda: Finding.objects.bulk_create([Finding(project=self.project, actor=self.owner, source_passive_redirect_chain=job,
                detector="invented", method_version=findings.METHOD, subject=self.data["url"], fingerprint="a" * 64, evidence={})])):
            with transaction.atomic():
                change()
                for operation in (self.read, self.record):
                    with self.assertRaises(ValidationError): operation(job)
                transaction.set_rollback(True)
        validate = findings._validate_rows; calls = 0
        def late_row(*args):
            nonlocal calls
            validate(*args); calls += 1
            if calls == 2: Finding.objects.filter(pk=rows[0].pk).update(actor=self.member)
        with transaction.atomic():
            with patch.object(findings, "_validate_rows", side_effect=late_row), self.assertRaises(PermissionDenied): self.read(job)
            transaction.set_rollback(True)
        Finding.objects.filter(pk=rows[-1].pk).update(actor=self.member)
        with self.assertRaises(PermissionDenied): self.read(job)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(self.read(job), original)

    def test_final_metadata_and_rows_every_origin_unvisited_caller_materializer_cancel_and_natural_expiry(self):
        unvisited = self.verified("https://www.security.example.com")
        self.data["target_urls"].append(unvisited.origin + "/unvisited")
        job = self.queue("unvisited")
        fetcher = fixtures.PassiveRedirectChainCollectionTests.transport(self, {**self.data, "target_urls": self.data["target_urls"][:1]})[0]
        self.assertTrue(collector.execute_passive_redirect_chain_collection(job.pk, fetcher=fetcher)); job.refresh_from_db()
        self.assertEqual(len(self.record(job)), 1)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        Finding.objects.filter(source_passive_redirect_chain=job).update(actor=self.member)
        original = self.read(job); final_rows = findings._rows; end = self.organization.trial.ends_at
        changes = [lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer"),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
            lambda: JobCancellation.objects.create(job=job, requested_by=self.owner)]
        for verification in (self.http_verification, self.https_verification, unvisited):
            changes.append(lambda pk=verification.pk: ProjectOriginVerification.objects.filter(pk=pk).update(updated_at=timezone.now()))
        for boundary in ("metadata", "rows"):
            for change in [*changes, None]:
                calls = 0; finished = False
                metadata = findings.source._metadata
                def changed_read(*args, **kwargs):
                    nonlocal calls, finished
                    result = (metadata if boundary == "metadata" else final_rows)(*args, **kwargs); calls += 1
                    # Each current report has three metadata reads; outer final metadata is eighth.
                    if calls == (8 if boundary == "metadata" else 2):
                        finished = True
                        if change is not None: change()
                    return result
                with self.subTest(boundary=boundary, change=change), transaction.atomic():
                    target = patch.object(findings.source, "_metadata", side_effect=changed_read) if boundary == "metadata" else patch.object(findings, "_rows", side_effect=changed_read)
                    with target, patch("jobs.usage.timezone.now", side_effect=lambda: end if finished and change is None else end - timedelta(seconds=1)), self.assertRaises((PermissionDenied, UsageLimitError)):
                        self.read(job)
                    self.assertTrue(finished); transaction.set_rollback(True)
        self.assertEqual(self.read(job), original)

    def test_two_postgresql_sessions_materialize_one_complete_original_set(self):
        job = self.collected(); barrier = Barrier(2)
        def once():
            close_old_connections()
            try:
                barrier.wait(timeout=10); return [row.pk for row in self.record(job)]
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _: once(), range(2)))
        self.assertEqual(results[0], results[1]); self.assertEqual(Finding.objects.filter(source_passive_redirect_chain=job).count(), 2)

    def test_private_bytes_lost_after_recipe_projection_and_late_independent_caller_withhold(self):
        from tenancy.artifacts import read_project_artifact
        job = self.collected(); self.record(job); original = self.read(job)
        recipe = findings.redirect_chain_finding_values; projected = False
        def project(**kwargs):
            nonlocal projected
            result = recipe(**kwargs); projected = True; return result
        def bytes_after_projection(**kwargs): return b"{}" if projected else read_project_artifact(**kwargs)
        for operation in (self.read, self.record):
            projected = False
            with patch.object(findings, "redirect_chain_finding_values", side_effect=project), patch.object(lifecycle,
                "read_project_artifact", side_effect=bytes_after_projection), self.assertRaises(ValidationError): operation(job)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        rows = findings._rows; calls = 0
        def rows_then_demote(*args):
            nonlocal calls
            result = rows(*args); calls += 1
            if calls == 2: OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer")
            return result
        with transaction.atomic():
            with patch.object(findings, "_rows", side_effect=rows_then_demote), self.assertRaises(PermissionDenied): self.read(job, actor=self.member)
            transaction.set_rollback(True)
        self.assertEqual(self.read(job), original)

    def test_independent_materializer_post_insert_loss_and_final_rows_natural_expiry_roll_back(self):
        job = self.collected(); membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)
        OrganizationMembership.objects.filter(pk=membership.pk).update(role="admin")
        save = Finding.save
        def save_then_demote(row, *args, **kwargs):
            result = save(row, *args, **kwargs)
            OrganizationMembership.objects.filter(pk=membership.pk).update(role="viewer")
            return result
        with patch.object(Finding, "save", autospec=True, side_effect=save_then_demote), self.assertRaises(PermissionDenied): self.record(job, actor=self.member)
        self.assertFalse(Finding.objects.exists()); self.assertEqual(OrganizationMembership.objects.get(pk=membership.pk).role, "admin")
        rows = findings._rows; calls = 0; finished = False; end = self.organization.trial.ends_at
        def final_rows(*args):
            nonlocal calls, finished
            result = rows(*args); calls += 1
            if calls == 3: finished = True
            return result
        with patch.object(findings, "_rows", side_effect=final_rows), patch("jobs.usage.timezone.now",
            side_effect=lambda: end if finished else end-timedelta(seconds=1)), self.assertRaises(UsageLimitError): self.record(job)
        self.assertTrue(finished); self.assertFalse(Finding.objects.exists())

    def test_retained_owner_bounded_stored_sequential_exports_cutoff_and_scoped_child_first_erasure(self):
        from tenancy.customer_export import complete_bounded_customer_archive, project_customer_rows
        from tenancy.customer_inventory import CUSTOMER, require_complete_ownership_map
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import _customer_deletion_order, delete_customer_database_records, prepare_customer_data_deletion, sweep_customer_artifact_versions
        from tenancy.models import Organization
        from tenancy.services import create_organization, create_project, revoke_origin_verification
        job = self.collected(); rows = self.record(job); require_complete_ownership_map()
        order = [model._meta.label for model, _lookup in _customer_deletion_order()]
        self.assertLess(order.index("jobs.Finding"), order.index("jobs.JobRun"))
        stored = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="a" * 32)
        self.assertTrue(capture_reserved_customer_snapshot(stored.pk))
        original_part, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=stored.pk, position=0)
        revoke_origin_verification(verification=self.http_verification, user=self.owner); now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=40), ends_at=now-timedelta(days=10))
        with self.assertRaises((PermissionDenied, UsageLimitError)): self.read(job)
        exported = project_customer_rows(organization=self.organization, actor=self.owner, model_label="jobs.Finding", after_id=0, through_id=rows[-1].pk)
        self.assertEqual({row["source_passive_redirect_chain_id"] for row in exported["rows"]}, {job.pk})
        self.assertTrue(all("historical_literal_chain_fact_not_current" in row["scope"] for row in exported["rows"]))
        with self.assertRaises(PermissionDenied): project_customer_rows(organization=self.organization, actor=self.outsider, model_label="jobs.Finding", after_id=0, through_id=rows[-1].pk)
        with ZipFile(io.BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            self.assertEqual({row["source_passive_redirect_chain_id"] for row in json.loads(archive.read("records/jobs/Finding.json"))}, {job.pk})
        self.assertEqual(private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=stored.pk, position=0)[0], original_part)
        sequential = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="b" * 32, format="source-parts-v2")
        for _ in range(len(CUSTOMER)*2+10):
            sequential.refresh_from_db()
            if sequential.state != sequential.State.PREPARING: break
            self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
        sequential.refresh_from_db(); self.assertEqual(sequential.state, sequential.State.READY)
        part = sequential.parts.get(source__model="jobs.Finding")
        data, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=sequential.pk, position=part.position)
        with ZipFile(io.BytesIO(data)) as archive: self.assertEqual({row["source_passive_redirect_chain_id"] for row in json.loads(archive.read("data"))}, {job.pk})
        other_org = create_organization(user=self.outsider, name="Other retained organization")
        other = create_project(organization=other_org, user=self.outsider, name="Other retained scope", canonical_origin="https://extra.example.invalid")
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=121), ends_at=now-timedelta(days=91))
        with self.assertRaises(PermissionDenied): project_customer_rows(organization=self.organization, actor=self.owner, model_label="jobs.Finding", after_id=0, through_id=rows[-1].pk)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(Finding.objects.filter(source_passive_redirect_chain_id=job.pk).exists()); self.assertFalse(JobRun.objects.filter(pk=job.pk).exists())
        self.assertTrue(Project.objects.filter(pk=other.pk, organization=other_org).exists())
