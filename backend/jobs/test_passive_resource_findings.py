from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
import io
import json
from threading import Barrier
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from . import passive_header_collection as lifecycle
from . import passive_resource_collection as collector
from . import test_passive_resource_candidates as pure_fixtures
from . import test_passive_resource_collection as fixtures
from . import test_passive_header_findings as header_checks
from . import passive_resource_findings as findings
from .passive_resource_findings import CONFIDENCE, FIELDS, METHOD, resource_finding_values


class ResourceFindingRecipeTests(TestCase):
    setUp = pure_fixtures.StaticResourceCandidateTests.setUp
    observation = pure_fixtures.StaticResourceCandidateTests.observation

    def test_compact_full_original_fact_identity_privacy_and_fresh_ownership(self):
        observation = self.observation(b'<img src="http://private.invalid/?secret=value"><iframe src="relative"></iframe>')
        original = deepcopy((observation, self.binding))
        recipes = resource_finding_values(job_id=7, binding=self.binding, observation=observation)
        self.assertEqual(len(recipes), 1)
        row = recipes[0]; self.assertEqual(set(row), set(FIELDS))
        self.assertEqual((row["source_passive_resource_id"], row["method_version"], row["confidence"]), (7, METHOD, CONFIDENCE))
        evidence = row["evidence"]
        self.assertEqual(evidence, {"source": "passive_static_resource_references", "job_id": 7, "binding": self.binding,
            "collection_sha256": sha256(lifecycle._encode(observation)).hexdigest(), "observed_at": observation["observed_at"], "status": 200,
            "fact": {"counts": {"inspected_attributes": 2, "http_absolute": 1, "https_absolute": 0, "unclassified": 1},
                "selected_attributes": observation["evidence"]["resource_references"]["selected_attributes"],
                "excluded": observation["evidence"]["resource_references"]["excluded"]},
            "coverage": "selected_literal_static_resource_attributes_only",
            "interpretation": "dated_literal_http_reference_candidate_not_browser_requests_mixed_content_policy_severity_or_whole_page_security"})
        self.assertEqual(row["fingerprint"], sha256(lifecycle._encode([METHOD, row["detector"], evidence])).hexdigest())
        self.assertEqual(row["subject"], self.binding["url"])
        for private in ("private.invalid", "secret=value", "raw_body", "resource_urls", "source_passive_header"):
            self.assertNotIn(private, json.dumps(recipes))
        evidence["fact"]["counts"]["http_absolute"] = 99; evidence["binding"]["observations"].append("raw")
        self.assertEqual((observation, self.binding), original)
        self.assertEqual(resource_finding_values(job_id=7, binding=self.binding, observation=observation)[0]["evidence"]["fact"]["counts"]["http_absolute"], 1)

    def test_observed_empty_unclassified_and_unavailable_create_no_recipe_or_clean_verdict(self):
        for body in (b"", b'<img src="https://private.invalid/">', b'<img src="relative">', b'<img src="x" src="y">', b"\x00",
            b'<img src="http://private.invalid/">' * 1001):
            observation = self.observation(body); original = deepcopy(observation)
            self.assertEqual(resource_finding_values(job_id=7, binding=self.binding, observation=observation), [])
            self.assertEqual(observation, original)

    def test_exact_original_identity_family_shapes_dates_and_counts_are_validated(self):
        observation = self.observation(b'<img src="http://private.invalid/">')
        for job_id in (True, 0, -1, 2**53, "7"):
            with self.subTest(job_id=job_id), self.assertRaises(ValidationError):
                resource_finding_values(job_id=job_id, binding=self.binding, observation=observation)
        for change in ({"method_version": "passive-header-source-v1"}, {"method_version": "passive-tls-source-v1"},
            {"project_id": True}, {"collection_permission": 1}, {"source_digest": "bad"}, {"raw": "private"}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                resource_finding_values(job_id=7, binding={**self.binding, **change}, observation=observation)
        for change in ({"method": "passive-header-collection-v1"}, {"status": True}, {"status": 302}, {"raw_body": "private"},
            {"observed_at": "2026-02-30T00:00:00.000000+00:00"}, {"observed_at": self.binding["verified_at"]}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                resource_finding_values(job_id=7, binding=self.binding, observation={**observation, **change})
        for change in ({"http_absolute": True}, {"http_absolute": "1"}, {"http_absolute": 1001}, {"inspected_attributes": 0}, {"http_absolute": None}):
            bad = deepcopy(observation); bad["evidence"]["resource_references"]["counts"].update(change)
            with self.subTest(change=change), self.assertRaises(ValidationError):
                resource_finding_values(job_id=7, binding=self.binding, observation=bad)

    def test_maximum_original_url_counts_and_job_identity_fit_private_bound(self):
        self.binding["url"] = self.binding["origin"] + "/" + "x" * (1024 - len(self.binding["origin"]) - 1)
        observation = self.observation(b'<img src="http://private.invalid/">' * 1000)
        row = resource_finding_values(job_id=2**53 - 1, binding=self.binding, observation=observation)[0]
        self.assertEqual(row["evidence"]["fact"]["counts"]["http_absolute"], 1000)
        self.assertLessEqual(len(lifecycle._encode(row["evidence"])), 4096)
        other = resource_finding_values(job_id=7, binding=self.binding, observation=observation)[0]
        self.assertNotEqual(other["fingerprint"], row["fingerprint"])


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}))
class OriginalResourceFindingRecipeTests(TransactionTestCase):
    setUp = fixtures.PassiveResourceCollectionTests.setUp
    verified = fixtures.PassiveResourceCollectionTests.verified
    queue = fixtures.PassiveResourceCollectionTests.queue
    transport = fixtures.PassiveResourceCollectionTests.transport

    def test_genuine_original_resource_private_readback_to_pure_recipe_without_persistence_or_collection(self):
        from .models import Finding, JobRun, Opportunity, Recommendation, UsageReservation
        job = self.queue()
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")):
            self.assertTrue(collector.execute_passive_resource_collection(job.pk, fetcher=self.transport()))
        job.refresh_from_db(); source = collector.read_passive_resource_observation(project=self.project, actor=self.owner, job_id=job.pk)
        original = deepcopy(source)
        with self.assertNumQueries(0), patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No I/O")), patch(
            "socket.create_connection", side_effect=AssertionError("No network")):
            recipes = resource_finding_values(job_id=job.pk, binding=job.config_snapshot["binding"], observation=source["collection"])
        self.assertEqual(source, original); self.assertEqual(len(recipes), 1)
        row = recipes[0]
        self.assertEqual(row["source_passive_resource_id"], job.pk)
        self.assertEqual(row["evidence"]["collection_sha256"], job.output["derived_sha256"])
        self.assertEqual(row["evidence"]["observed_at"], job.output["observed_at"])
        self.assertEqual(row["evidence"]["binding"], job.config_snapshot["binding"])
        self.assertFalse(Finding.objects.exists()); self.assertFalse(Opportunity.objects.exists()); self.assertFalse(Recommendation.objects.exists())
        self.assertEqual(JobRun.objects.filter(handler=collector.HANDLER).count(), 1)
        self.assertEqual(UsageReservation.objects.filter(job=job).count(), 1)
        for private in (self.challenge, self.owner.email, "private.invalid", "secret"):
            self.assertNotIn(private, json.dumps(recipes))
        self.connection.request.assert_called_once()


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class PassiveResourceFindingTests(TransactionTestCase):
    setUp = fixtures.PassiveResourceCollectionTests.setUp
    verified = fixtures.PassiveResourceCollectionTests.verified
    queue = fixtures.PassiveResourceCollectionTests.queue
    transport = fixtures.PassiveResourceCollectionTests.transport

    def collected(self, key="resource-findings", body=None):
        job = self.queue(key)
        self.assertTrue(collector.execute_passive_resource_collection(job.pk, fetcher=self.transport(body=body)))
        job.refresh_from_db()
        return job

    def record(self, job, **changes):
        return findings.record_resource_findings(**{**dict(project=self.project, actor=self.owner, job_id=job.pk), **changes})

    def read(self, job, **changes):
        return findings.current_resource_findings(**{**dict(project=self.project, actor=self.owner, job_id=job.pk), **changes})

    # Exercise the same genuine producer-independent authorization/rollback/ordinary consumer contracts for resources.
    test_current_authority_scope_cancellation_and_expiry_deny_without_writes = header_checks.PassiveHeaderFindingTests.test_current_authority_scope_cancellation_and_expiry_deny_without_writes
    test_post_insert_source_row_actor_commercial_and_cancel_loss_roll_back_complete_set = header_checks.PassiveHeaderFindingTests.test_post_insert_source_row_actor_commercial_and_cancel_loss_roll_back_complete_set
    test_ordinary_list_first_audit_reports_shares_weekly_admin_and_intent_cannot_consume = header_checks.PassiveHeaderFindingTests.test_ordinary_list_first_audit_reports_shares_weekly_admin_and_intent_cannot_consume

    def test_genuine_single_original_materialization_is_private_idempotent_read_only_without_new_work(self):
        from tenancy.models import OrganizationMembership
        from .models import Finding, JobRun, Opportunity, Recommendation, UsageReservation
        job = self.collected(); counts = (JobRun.objects.count(), UsageReservation.objects.count())
        with patch("socket.create_connection", side_effect=AssertionError("No network")):
            rows = self.record(job); original = self.read(job)
            self.assertEqual([row.pk for row in self.record(job)], [row.pk for row in rows])
            with CaptureQueriesContext(connection) as queries: result = self.read(job)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(result, original); self.assertEqual(len(rows), 1); row = rows[0]
        self.assertEqual(row.source_passive_resource_id, job.pk); self.assertIsNone(row.source_passive_header_id)
        self.assertEqual(row.evidence["binding"], job.config_snapshot["binding"])
        self.assertEqual(row.evidence["observed_at"], job.output["observed_at"])
        self.assertEqual(row.evidence["collection_sha256"], job.output["derived_sha256"])
        self.assertEqual(result["state"], "current_materialized_facts")
        self.assertEqual((JobRun.objects.count(), UsageReservation.objects.count()), counts)
        self.assertEqual((Opportunity.objects.count(), Recommendation.objects.count()), (0, 0))
        result["findings"][0]["evidence"]["fact"]["counts"]["http_absolute"] = 999
        self.assertEqual(self.read(job), original)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(self.read(job, actor=self.member), original)
        self.assertEqual([row.pk for row in self.record(job, actor=self.member)], [row.pk for row in rows])
        self.connection.request.assert_called_once()

    def test_observed_empty_and_lexically_unavailable_do_not_materialize_a_clean_verdict(self):
        from .models import Finding
        for key, body in (("empty", b""), ("unclassified", b'<img src="relative">'), ("unavailable", b'<img src="x" src="y">')):
            job = self.collected(key, body=body)
            self.assertEqual(self.record(job), [])
            self.assertEqual(self.read(job)["state"], "no_retained_materialized_findings")
            self.assertFalse(Finding.objects.exists())

    def test_immutable_same_project_exact_resource_fact_and_sql_one_source_and_human_review_denial(self):
        from tenancy.models import Project
        from .models import Finding, JobRun, Opportunity, Recommendation
        job = self.collected(); row = self.record(job)[0]
        with self.assertRaises(ValidationError): row.save()
        for change in ({"source_passive_resource": None}, {"source_passive_header_id": job.pk}, {"source_diagnostics_id": 999999}):
            with transaction.atomic(), self.assertRaises(IntegrityError) as caught: Finding.objects.filter(pk=row.pk).update(**change)
            self.assertIn("jobs_finding_one_source", str(caught.exception))
        recipe = {key: getattr(row, key) for key in FIELDS}
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other.example.invalid")
        for change in ({"project": other}, {"fingerprint": "a" * 64}, {"detector": "invented"}, {"confidence": "high"},
            {"evidence": {**row.evidence, "status": True}}, {"evidence": {**row.evidence, "raw_body": "private"}}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                Finding(**{**dict(project=self.project, actor=self.owner), **recipe, **change}).full_clean()
        with self.assertRaises(ValidationError):
            Opportunity.objects.create(project=self.project, finding=row, actor=self.owner, review_reason="Not supported")
        opportunity = Opportunity.objects.bulk_create([Opportunity(project=self.project, finding=row, actor=self.owner, review_reason="Corrupt fixture")])[0]
        with self.assertRaises(ValidationError):
            Recommendation.objects.create(project=self.project, opportunity=opportunity, actor=self.owner, revision=1, draft="Not supported")
        for handler in ("collect_passive_headers", "collect_passive_tls", "collect_passive_redirects"):
            with transaction.atomic():
                JobRun.objects.filter(pk=job.pk).update(handler=handler)
                with self.assertRaises(ValidationError): Finding(project=self.project, actor=self.owner, **recipe).full_clean()
                with self.assertRaises((ValidationError, PermissionDenied)): self.read(job)
                transaction.set_rollback(True)

    def test_current_materializer_and_full_row_late_read_fences_keep_absent_set_honest(self):
        from tenancy.models import OrganizationMembership
        from .models import Finding
        job = self.collected(); row = self.record(job)[0]; original = self.read(job)
        validate = findings._validate_rows; calls = 0
        def validate_then_change(*args):
            nonlocal calls
            validate(*args); calls += 1
            if calls == 2: Finding.objects.filter(pk=row.pk).update(detected_at=timezone.now())
        with transaction.atomic():
            with patch.object(findings, "_validate_rows", side_effect=validate_then_change), self.assertRaises(PermissionDenied): self.read(job)
            transaction.set_rollback(True)
        self.assertEqual(self.read(job), original)
        Finding.objects.filter(pk=row.pk).update(actor=self.member)
        with self.assertRaises(PermissionDenied): self.read(job)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(len(self.read(job)["findings"]), 1)
        Finding.objects.filter(pk=row.pk).delete()
        self.assertEqual(self.read(job)["state"], "no_retained_materialized_findings")

    def test_two_sessions_materialize_one_original_single_fact(self):
        from .models import Finding
        job = self.collected(); barrier = Barrier(2)
        def record_once():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return [row.pk for row in self.record(job)]
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _: record_once(), range(2)))
        self.assertEqual(results[0], results[1]); self.assertEqual(Finding.objects.filter(source_passive_resource=job).count(), 1)

    def test_late_independent_caller_loss_during_write_or_current_read_is_not_original_owner_authority(self):
        from tenancy.models import OrganizationMembership
        from .models import Finding
        job = self.collected(); membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)
        OrganizationMembership.objects.filter(pk=membership.pk).update(role="admin")
        save = Finding.save
        def save_then_demote(row, *args, **kwargs):
            result = save(row, *args, **kwargs)
            OrganizationMembership.objects.filter(pk=membership.pk).update(role="viewer")
            return result
        with patch.object(Finding, "save", autospec=True, side_effect=save_then_demote), self.assertRaises(PermissionDenied):
            self.record(job, actor=self.member)
        self.assertFalse(Finding.objects.exists()); self.assertEqual(OrganizationMembership.objects.get(pk=membership.pk).role, "admin")
        row = self.record(job)[0]; recipe = findings.resource_finding_values; calls = 0
        def recipe_then_demote(**kwargs):
            nonlocal calls
            result = recipe(**kwargs); calls += 1
            if calls == 2: OrganizationMembership.objects.filter(pk=membership.pk).update(role="viewer")
            return result
        with transaction.atomic():
            with patch.object(findings, "resource_finding_values", side_effect=recipe_then_demote), self.assertRaises(PermissionDenied):
                self.read(job, actor=self.member)
            transaction.set_rollback(True)
        self.assertEqual(Finding.objects.get(pk=row.pk).actor_id, self.owner.pk)

    def test_resource_retained_owner_stored_sequential_exports_and_scoped_child_first_erasure(self):
        from tenancy.customer_export import complete_bounded_customer_archive, project_customer_rows
        from tenancy.customer_inventory import CUSTOMER, require_complete_ownership_map
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import _customer_deletion_order, delete_customer_database_records, prepare_customer_data_deletion, sweep_customer_artifact_versions
        from tenancy.models import Organization, OrganizationTrial, Project
        from tenancy.services import create_organization, create_project, revoke_origin_verification
        from .models import Finding, JobRun
        from .usage import UsageLimitError
        job = self.collected(); row = self.record(job)[0]; require_complete_ownership_map()
        order = [model._meta.label for model, _lookup in _customer_deletion_order()]
        self.assertLess(order.index("jobs.Finding"), order.index("jobs.JobRun"))
        stored = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="a" * 32)
        self.assertTrue(capture_reserved_customer_snapshot(stored.pk))
        original_part, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=stored.pk, position=0)
        revoke_origin_verification(verification=self.verification, user=self.owner)
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=40), ends_at=now - timedelta(days=10))
        with self.assertRaises((PermissionDenied, UsageLimitError)): self.read(job)
        exported = project_customer_rows(organization=self.organization, actor=self.owner, model_label="jobs.Finding", after_id=0, through_id=row.pk)
        self.assertEqual(exported["rows"][0]["source_passive_resource_id"], job.pk)
        self.assertIn("historical_literal_resource_fact_not_current", exported["rows"][0]["scope"])
        with ZipFile(io.BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            self.assertEqual(json.loads(archive.read("records/jobs/Finding.json"))[0]["source_passive_resource_id"], job.pk)
        self.assertEqual(private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=stored.pk, position=0)[0], original_part)
        sequential = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="b" * 32, format="source-parts-v2")
        for _ in range(len(CUSTOMER) * 2 + 10):
            sequential.refresh_from_db()
            if sequential.state != sequential.State.PREPARING: break
            self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
        sequential.refresh_from_db(); self.assertEqual(sequential.state, sequential.State.READY)
        part = sequential.parts.get(source__model="jobs.Finding")
        data, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=sequential.pk, position=part.position)
        with ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(json.loads(archive.read("data"))[0]["source_passive_resource_id"], job.pk)
        other_org = create_organization(user=self.outsider, name="Other retained organization")
        other = create_project(organization=other_org, user=self.outsider, name="Other retained scope", canonical_origin="https://extra.example.invalid")
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied):
            project_customer_rows(organization=self.organization, actor=self.owner, model_label="jobs.Finding", after_id=0, through_id=row.pk)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(Finding.objects.filter(pk=row.pk).exists()); self.assertFalse(JobRun.objects.filter(pk=job.pk).exists())
        self.assertTrue(Project.objects.filter(pk=other.pk, organization=other_org).exists())
