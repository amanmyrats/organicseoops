from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from hashlib import sha256
import io
import json
from threading import Barrier
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from . import passive_header_collection as lifecycle
from . import passive_redirect_collection as collector
from . import test_passive_redirect_candidates as pure_fixtures
from . import test_passive_redirect_collection as fixtures
from . import test_passive_header_findings as header_checks
from . import test_passive_redirect_candidate_source as source_checks
from . import passive_redirect_findings as findings
from .models import Finding, JobRun, Opportunity, Recommendation, UsageReservation
from .passive_redirect_findings import CONFIDENCE, FIELDS, METHOD, redirect_finding_values


class RedirectFindingRecipeTests(TestCase):
    setUp = pure_fixtures.RedirectReviewCandidateTests.setUp
    collection = pure_fixtures.RedirectReviewCandidateTests.collection

    def test_exact_original_http_fact_compact_identity_privacy_and_fresh_ownership(self):
        for status in (200, 201, 300, 301, 302, 303, 304, 307, 308, 404, 599):
            observation = self.collection(status); original = deepcopy((observation, self.binding))
            rows = redirect_finding_values(job_id=7, binding=self.binding, observation=observation)
            self.assertEqual(len(rows), 1); row = rows[0]; evidence = row["evidence"]
            self.assertEqual(set(row), set(FIELDS))
            self.assertEqual((row["source_passive_redirect_id"], row["subject"], row["method_version"], row["confidence"]),
                (7, self.binding["url"], METHOD, CONFIDENCE))
            self.assertEqual(set(evidence), {"source", "job_id", "binding", "collection_sha256", "observed_at", "status",
                "availability", "fact", "coverage", "interpretation"})
            self.assertEqual(evidence["source"], "passive_first_response_location")
            self.assertEqual((evidence["binding"], evidence["job_id"], evidence["observed_at"], evidence["status"]),
                (self.binding, 7, observation["observed_at"], status))
            self.assertEqual(evidence["availability"], {"target_metadata": "observed"})
            self.assertEqual(evidence["fact"], {"response_status": status, "redirect_status": status in {301, 302, 303, 307, 308},
                "location_state": "single_classified", "target_scheme": "http", "same_origin": False})
            self.assertEqual(evidence["collection_sha256"], sha256(lifecycle._encode(observation)).hexdigest())
            self.assertEqual(row["fingerprint"], sha256(lifecycle._encode([METHOD, row["detector"], evidence])).hexdigest())
            self.assertLessEqual(len(lifecycle._encode(evidence)), 4096)
            for private in ("private.invalid", "secret=value", "raw_location", "target_url", "raw_body", "source_current", "priority", "source_passive_tls"):
                self.assertNotIn(private, json.dumps(rows))
            evidence["binding"]["observations"].append("raw"); evidence["fact"]["target_scheme"] = "https"
            evidence["availability"]["target_metadata"] = "unavailable"
            self.assertEqual((observation, self.binding), original)
            self.assertEqual(redirect_finding_values(job_id=7, binding=self.binding, observation=observation)[0]["fingerprint"], row["fingerprint"])

    def test_unknown_null_and_classified_https_empty_never_create_secure_or_false_recipes(self):
        for fields in (b"", b"Location: \t\r\n", b"Location: /one\r\nLocation: /two\r\n", b"Location: javascript:private\r\n",
            b"Location: /relative?secret=value\r\n", b"Location: https://foreign.invalid/\r\n"):
            self.assertEqual(redirect_finding_values(job_id=7, binding=self.binding, observation=self.collection(fields=fields)), [])

    def test_malformed_job_binding_family_original_date_status_classification_null_fail_closed(self):
        observation = self.collection()
        for job_id in (True, 0, -1, 2**53, "7"):
            with self.assertRaises(ValidationError): redirect_finding_values(job_id=job_id, binding=self.binding, observation=observation)
        for changes in ({"method_version": "passive-resource-source-v1"}, {"project_id": True}, {"collection_permission": 1},
            {"source_digest": "bad"}, {"url": self.binding["url"] + "/other"}, {"origin": "https://foreign.invalid"}, {"observations": ["response_headers"]}):
            with self.assertRaises(ValidationError): redirect_finding_values(job_id=7, binding={**self.binding, **changes}, observation=observation)
        mutations = (lambda row: row.update(status=True), lambda row: row.update(status="302"), lambda row: row.update(status=199),
            lambda row: row.update(method="passive-resource-evidence-v1"), lambda row: row.update(raw_location="private"),
            lambda row: row.update(observed_at="2025-02-30T00:00:00.000000+00:00"), lambda row: row["evidence"].update(observed_at=self.binding["verified_at"]),
            lambda row: row["evidence"]["response_location"].update(redirect_status=1),
            lambda row: row["evidence"]["response_location"].update(response_status=200),
            lambda row: row["evidence"]["response_location"].update(same_origin=True),
            lambda row: row["evidence"]["response_location"].update(same_origin=0),
            lambda row: row["evidence"]["response_location"].update(target_scheme=None),
            lambda row: row["evidence"]["response_location"].update(location_state="single_unclassified"))
        for mutate in mutations:
            bad = deepcopy(observation); mutate(bad)
            with self.assertRaises(ValidationError): redirect_finding_values(job_id=7, binding=self.binding, observation=bad)

    def test_safe_maximum_url_ids_bound_and_original_identity_changes(self):
        observation = self.collection(); url = self.binding["origin"] + "/" + "a" * (1023 - len(self.binding["origin"]))
        self.binding["url"] = url; observation["url"] = url
        for key in ("actor_id", "organization_id", "project_id", "verification_id"): self.binding[key] = 2**53 - 1
        row = redirect_finding_values(job_id=2**53 - 1, binding=self.binding, observation=observation)[0]
        self.assertEqual(len(row["subject"]), 1024); self.assertLessEqual(len(lifecycle._encode(row["evidence"])), 4096)
        self.assertNotEqual(row["fingerprint"], redirect_finding_values(job_id=7, binding=self.binding, observation=observation)[0]["fingerprint"])
        observed = datetime.fromisoformat(observation["observed_at"])
        changed = deepcopy(observation); changed["observed_at"] = changed["evidence"]["observed_at"] = (observed - timedelta(microseconds=1)).isoformat(timespec="microseconds")
        self.assertNotEqual(row["fingerprint"], redirect_finding_values(job_id=2**53 - 1, binding=self.binding, observation=changed)[0]["fingerprint"])
        changed = deepcopy(observation); changed["status"] = changed["evidence"]["response_location"]["response_status"] = 200
        changed["evidence"]["response_location"]["redirect_status"] = False
        self.assertNotEqual(row["fingerprint"], redirect_finding_values(job_id=2**53 - 1, binding=self.binding, observation=changed)[0]["fingerprint"])


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}))
class OriginalRedirectFindingRecipeTests(TransactionTestCase):
    setUp = fixtures.PassiveRedirectCollectionTests.setUp
    verified = fixtures.PassiveRedirectCollectionTests.verified
    queue = fixtures.PassiveRedirectCollectionTests.queue
    transport = fixtures.PassiveRedirectCollectionTests.transport
    WIRE = fixtures.PassiveRedirectCollectionTests.WIRE

    def test_genuine_original_private_first_response_readback_to_pure_recipe_without_io_or_persistence(self):
        job = self.queue(); fetcher = self.transport(wire=self.WIRE)
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")):
            self.assertTrue(collector.execute_passive_redirect_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); source = collector.read_passive_redirect_observation(project=self.project, actor=self.owner, job_id=job.pk)
        original = deepcopy(source)
        with self.assertNumQueries(0), patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No I/O")), patch(
            "socket.create_connection", side_effect=AssertionError("No network")):
            rows = redirect_finding_values(job_id=job.pk, binding=job.config_snapshot["binding"], observation=source["collection"])
        self.assertEqual(source, original); self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_passive_redirect_id"], job.pk)
        self.assertEqual(rows[0]["evidence"]["collection_sha256"], job.output["derived_sha256"])
        self.assertEqual(rows[0]["evidence"]["observed_at"], job.output["observed_at"])
        self.assertEqual((Finding.objects.count(), Opportunity.objects.count(), Recommendation.objects.count()), (0, 0, 0))
        self.assertEqual(JobRun.objects.filter(handler=collector.HANDLER).count(), 1)
        self.assertEqual(UsageReservation.objects.filter(job=job).count(), 1)
        for private in (self.challenge, self.verification.challenge_digest, self.owner.email, "private", "secret=value", "raw_location"):
            self.assertNotIn(private, json.dumps(rows))
        self.connection.request.assert_called_once()


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class PassiveRedirectFindingTests(TransactionTestCase):
    setUp = fixtures.PassiveRedirectCollectionTests.setUp
    verified = fixtures.PassiveRedirectCollectionTests.verified
    queue = fixtures.PassiveRedirectCollectionTests.queue
    transport = fixtures.PassiveRedirectCollectionTests.transport
    WIRE = fixtures.PassiveRedirectCollectionTests.WIRE
    collected = source_checks.CurrentRedirectCandidateTests.collected

    def record(self, job, **changes):
        return findings.record_redirect_findings(**{**dict(project=self.project, actor=self.owner, job_id=job.pk), **changes})

    def read(self, job, **changes):
        return findings.current_redirect_findings(**{**dict(project=self.project, actor=self.owner, job_id=job.pk), **changes})

    # Genuine producer-independent authority, rollback and ordinary-consumer checks.
    test_current_authority_scope_cancellation_and_expiry_deny_without_writes = header_checks.PassiveHeaderFindingTests.test_current_authority_scope_cancellation_and_expiry_deny_without_writes
    test_post_insert_source_row_actor_commercial_and_cancel_loss_roll_back_complete_set = header_checks.PassiveHeaderFindingTests.test_post_insert_source_row_actor_commercial_and_cancel_loss_roll_back_complete_set
    test_ordinary_list_first_audit_reports_shares_weekly_admin_and_intent_cannot_consume = header_checks.PassiveHeaderFindingTests.test_ordinary_list_first_audit_reports_shares_weekly_admin_and_intent_cannot_consume
    test_complete_original_metadata_source_commercial_cancel_and_natural_expiry_after_io_projection_withhold = source_checks.CurrentRedirectCandidateTests.test_complete_original_metadata_source_commercial_cancel_and_natural_expiry_after_io_projection_withhold

    def test_genuine_original_single_fact_private_idempotent_read_only_without_new_work(self):
        from tenancy.models import OrganizationMembership
        job = self.collected(); counts = (JobRun.objects.count(), UsageReservation.objects.count())
        self.assertEqual(self.read(job)["state"], "no_retained_materialized_findings")
        with patch("socket.create_connection", side_effect=AssertionError("No network")):
            rows = self.record(job); original = self.read(job)
            self.assertEqual([row.pk for row in self.record(job)], [row.pk for row in rows])
            with CaptureQueriesContext(connection) as queries: result = self.read(job)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(result, original); self.assertEqual(len(rows), 1); row = rows[0]
        self.assertEqual((row.source_passive_redirect_id, row.subject, row.detector),
            (job.pk, self.data["url"], "http_scheme_location_reference_candidate"))
        self.assertTrue(all(getattr(row, field) is None for field in ("source_metric_id", "source_api_page_id",
            "source_diagnostics_id", "source_indexation_id", "source_performance_id", "source_passive_header_id",
            "source_passive_resource_id", "source_passive_tls_id")))
        self.assertEqual(row.evidence["binding"], job.config_snapshot["binding"])
        self.assertEqual(row.evidence["observed_at"], job.output["observed_at"])
        self.assertEqual(row.evidence["collection_sha256"], job.output["derived_sha256"])
        self.assertEqual(row.evidence["status"], 302); self.assertTrue(row.evidence["fact"]["redirect_status"])
        self.assertLessEqual(len(lifecycle._encode(row.evidence)), 4096)
        self.assertEqual(result["state"], "current_materialized_facts")
        self.assertEqual((JobRun.objects.count(), UsageReservation.objects.count()), counts)
        self.assertEqual((Opportunity.objects.count(), Recommendation.objects.count()), (0, 0))
        result["findings"][0]["evidence"]["availability"]["target_metadata"] = "unavailable"
        self.assertEqual(self.read(job), original)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(self.read(job, actor=self.member), original)
        self.assertEqual([row.pk for row in self.record(job, actor=self.member)], [row.pk for row in rows])
        self.assertEqual(Finding.objects.count(), 1); self.assertEqual(row.actor_id, self.owner.pk)
        for private in (self.challenge, self.owner.email, "private.invalid", "secret=value", "target_url"):
            self.assertNotIn(private, json.dumps(original))
        self.connection.request.assert_called_once()

    def test_original_status_unknown_null_and_classified_https_empty_are_not_secure_verdicts(self):
        for key, fields in (("absent", b""), ("empty", b"Location: \t\r\n"),
            ("multiple", b"Location: /one\r\nLocation: /two\r\n"), ("unknown", b"Location: javascript:private\r\n"),
            ("https", b"Location: /relative\r\n")):
            job = self.collected(key, wire=b"HTTP/1.1 200 OK\r\n" + fields + b"\r\n")
            self.assertEqual(self.record(job), []); report = self.read(job)
            self.assertEqual((report["state"], report["findings"]), ("no_retained_materialized_findings", []))
            self.assertFalse(Finding.objects.filter(source_passive_redirect=job).exists())
        for status in (200, 301, 599):
            job = self.collected(f"status-{status}", wire=f"HTTP/1.1 {status} Original\r\n".encode() + b"Location: http://foreign.invalid/\r\n\r\n")
            row = self.record(job)[0]
            self.assertEqual(row.evidence["status"], status)
            self.assertIs(row.evidence["fact"]["redirect_status"], status == 301)
            self.assertEqual(row.evidence["availability"], {"target_metadata": "observed"})

    def test_immutable_same_project_exact_location_facts_sql_one_source_and_human_denial(self):
        from tenancy.models import Project
        from .action_review import _opportunity_source
        job = self.collected(); row = self.record(job)[0]
        with self.assertRaises(ValidationError): row.save()
        with self.assertRaises(ProtectedError): job.delete()
        for change in ({"source_passive_redirect": None}, {"source_passive_header_id": job.pk},
            {"source_passive_resource_id": job.pk}, {"source_passive_tls_id": job.pk}, {"source_diagnostics_id": 999999}):
            with transaction.atomic(), self.assertRaises(IntegrityError) as caught: Finding.objects.filter(pk=row.pk).update(**change)
            self.assertIn("jobs_finding_one_source", str(caught.exception))
        recipe = {key: getattr(row, key) for key in FIELDS}
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other.example.invalid")
        for change in ({"project": other}, {"fingerprint": "a" * 64}, {"detector": "invented"}, {"confidence": "high"},
            {"subject": self.project.canonical_origin}, {"evidence": {**row.evidence, "status": True}},
            {"evidence": {**row.evidence, "raw_location": "private"}},
            {"evidence": {**row.evidence, "availability": {"target_metadata": "unavailable"}}},
            {"evidence": {**row.evidence, "fact": {**row.evidence["fact"], "redirect_status": 1}}}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                Finding(**{**dict(project=self.project, actor=self.owner), **recipe, **change}).full_clean()
        with self.assertRaises(ValidationError):
            Opportunity.objects.create(project=self.project, finding=row, actor=self.owner, review_reason="Not supported")
        opportunity = Opportunity.objects.bulk_create([Opportunity(project=self.project, finding=row, actor=self.owner, review_reason="Corrupt fixture")])[0]
        with self.assertRaises(ValidationError):
            Recommendation.objects.create(project=self.project, opportunity=opportunity, actor=self.owner, revision=1, draft="Not supported")
        recommendation = Recommendation.objects.bulk_create([Recommendation(project=self.project, opportunity=opportunity, actor=self.owner, revision=1, draft="Corrupt fixture")])[0]
        with self.assertRaises(ValidationError): _opportunity_source(self.project, self.owner, opportunity.pk, "update", "")
        request = header_checks.RequestFactory().get("/admin/"); request.user = self.owner
        self.assertFalse(admin.site._registry[Opportunity].get_queryset(request).filter(pk=opportunity.pk).exists())
        self.assertFalse(admin.site._registry[Recommendation].get_queryset(request).filter(pk=recommendation.pk).exists())
        for change in ({"handler": "collect_passive_headers"}, {"handler": "collect_passive_resources"},
            {"handler": "collect_passive_tls"}, {"status": "failed"}, {"output": {}}):
            with transaction.atomic():
                JobRun.objects.filter(pk=job.pk).update(**change)
                with self.assertRaises(ValidationError): Finding(project=self.project, actor=self.owner, **recipe).full_clean()
                with self.assertRaises((PermissionDenied, ValidationError)): self.read(job)
                transaction.set_rollback(True)

    def test_current_materializer_full_final_rows_and_detector_ceiling_are_fenced(self):
        from tenancy.models import OrganizationMembership
        job = self.collected(); row = self.record(job)[0]; original = self.read(job)
        validate = findings._validate_rows
        for changes in ({"detected_at": timezone.now()}, {"actor": self.member}, {"source_passive_redirect": None, "source_passive_tls": job}):
            calls = 0
            def validate_then_change(*args):
                nonlocal calls
                validate(*args); calls += 1
                if calls == 2: Finding.objects.filter(pk=row.pk).update(**changes)
            with transaction.atomic():
                with patch.object(findings, "_validate_rows", side_effect=validate_then_change), self.assertRaises(PermissionDenied): self.read(job)
                transaction.set_rollback(True)
        self.assertEqual(self.read(job), original)
        with transaction.atomic():
            Finding.objects.bulk_create([Finding(project=self.project, actor=self.owner, source_passive_redirect=job,
                detector="invented", method_version=METHOD, subject=self.data["url"], fingerprint="a" * 64, evidence={})])
            with self.assertRaises(ValidationError): self.read(job)
            with self.assertRaises(ValidationError): self.record(job)
            transaction.set_rollback(True)
        Finding.objects.filter(pk=row.pk).update(actor=self.member)
        with self.assertRaises(PermissionDenied): self.read(job)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(len(self.read(job)["findings"]), 1)
        Finding.objects.filter(pk=row.pk).delete()
        self.assertEqual(self.read(job)["state"], "no_retained_materialized_findings")

    def test_independent_caller_materializer_restricted_project_and_foreign_scope(self):
        from tenancy.models import OrganizationMembership, Project, ProjectMembership
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
        rows = self.record(job); recipe = findings.redirect_finding_values; calls = 0
        def recipe_then_demote(**kwargs):
            nonlocal calls
            result = recipe(**kwargs); calls += 1
            if calls == 2: OrganizationMembership.objects.filter(pk=membership.pk).update(role="viewer")
            return result
        with transaction.atomic():
            with patch.object(findings, "redirect_finding_values", side_effect=recipe_then_demote), self.assertRaises(PermissionDenied):
                self.read(job, actor=self.member)
            transaction.set_rollback(True)
        self.assertEqual({row.actor_id for row in rows}, {self.owner.pk})
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True); self.project.refresh_from_db()
        restricted = self.collected("restricted-location")
        with self.assertRaises(PermissionDenied): self.record(restricted, actor=self.member)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(len(self.record(restricted, actor=self.member)), 1)
        ProjectMembership.objects.filter(project=self.project, organization_membership=membership).delete()
        with self.assertRaises(PermissionDenied): self.read(restricted)
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other.example.invalid")
        for operation in (self.read, self.record):
            with self.assertRaises(PermissionDenied): operation(restricted, project=other)
        with patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No I/O for missing job")):
            with self.assertRaises(PermissionDenied): self.read(job, job_id=job.pk + 1000)

    def test_two_sessions_materialize_one_original_single_fact_set(self):
        job = self.collected(); barrier = Barrier(2)
        def record_once():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return [row.pk for row in self.record(job)]
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _: record_once(), range(2)))
        self.assertEqual(results[0], results[1]); self.assertEqual(Finding.objects.filter(source_passive_redirect=job).count(), 1)

    def test_location_retained_owner_stored_sequential_exports_and_scoped_child_first_erasure(self):
        from tenancy.customer_export import complete_bounded_customer_archive, project_customer_rows
        from tenancy.customer_inventory import CUSTOMER, require_complete_ownership_map
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import _customer_deletion_order, delete_customer_database_records, prepare_customer_data_deletion, sweep_customer_artifact_versions
        from tenancy.models import Organization, OrganizationTrial, Project
        from tenancy.services import create_organization, create_project, revoke_origin_verification
        from .usage import UsageLimitError
        job = self.collected(); rows = self.record(job); require_complete_ownership_map()
        order = [model._meta.label for model, _lookup in _customer_deletion_order()]
        self.assertLess(order.index("jobs.Finding"), order.index("jobs.JobRun"))
        stored = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="a" * 32)
        self.assertTrue(capture_reserved_customer_snapshot(stored.pk))
        original_part, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=stored.pk, position=0)
        revoke_origin_verification(verification=self.verification, user=self.owner)
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=40), ends_at=now - timedelta(days=10))
        with self.assertRaises((PermissionDenied, UsageLimitError)): self.read(job)
        exported = project_customer_rows(organization=self.organization, actor=self.owner, model_label="jobs.Finding", after_id=0, through_id=rows[-1].pk)
        self.assertEqual({row["source_passive_redirect_id"] for row in exported["rows"]}, {job.pk})
        self.assertTrue(all("historical_literal_location_fact_not_current" in row["scope"] for row in exported["rows"]))
        with self.assertRaises(PermissionDenied):
            project_customer_rows(organization=self.organization, actor=self.outsider, model_label="jobs.Finding", after_id=0, through_id=rows[-1].pk)
        with ZipFile(io.BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            self.assertEqual({row["source_passive_redirect_id"] for row in json.loads(archive.read("records/jobs/Finding.json"))}, {job.pk})
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
            self.assertEqual({row["source_passive_redirect_id"] for row in json.loads(archive.read("data"))}, {job.pk})
        other_org = create_organization(user=self.outsider, name="Other retained organization")
        other = create_project(organization=other_org, user=self.outsider, name="Other retained scope", canonical_origin="https://extra.example.invalid")
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied):
            project_customer_rows(organization=self.organization, actor=self.owner, model_label="jobs.Finding", after_id=0, through_id=rows[-1].pk)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(Finding.objects.filter(source_passive_redirect_id=job.pk).exists()); self.assertFalse(JobRun.objects.filter(pk=job.pk).exists())
        self.assertTrue(Project.objects.filter(pk=other.pk, organization=other_org).exists())
