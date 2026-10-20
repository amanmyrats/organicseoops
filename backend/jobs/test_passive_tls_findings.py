from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import io
from threading import Barrier
from zipfile import ZipFile
from unittest import TestCase
from unittest.mock import patch

from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from . import passive_header_collection as lifecycle
from . import passive_tls_collection as collector
from . import test_passive_tls_candidates as pure_fixtures
from . import test_passive_tls_collection as fixtures
from . import test_passive_header_findings as header_checks
from . import test_passive_tls_candidate_source as source_checks
from . import passive_tls_findings as findings
from .passive_tls_findings import CONFIDENCE, FIELDS, METHOD, tls_finding_values


class TLSFindingRecipeTests(TestCase):
    setUp = pure_fixtures.TLSReviewCandidateTests.setUp
    collection = pure_fixtures.TLSReviewCandidateTests.collection

    def test_exact_two_original_facts_compact_identity_privacy_and_fresh_ownership(self):
        observation = self.collection(datetime(2025, 1, 1, 0, 0, 0, 1, tzinfo=UTC), "TLSv1.1")
        original = deepcopy((observation, self.binding))
        rows = tls_finding_values(job_id=7, binding=self.binding, observation=observation)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(set(row), set(FIELDS))
            self.assertEqual((row["source_passive_tls_id"], row["subject"], row["method_version"], row["confidence"]),
                (7, self.binding["origin"], METHOD, CONFIDENCE))
            evidence = row["evidence"]
            self.assertEqual(evidence["source"], "passive_certificate_dates_and_negotiated_tls")
            self.assertEqual((evidence["binding"], evidence["job_id"], evidence["observed_at"]), (self.binding, 7, observation["observed_at"]))
            self.assertEqual(evidence["collection_sha256"], sha256(lifecycle._encode(observation)).hexdigest())
            self.assertEqual(evidence["availability"], {"certificate_dates": "observed", "negotiated_version": "observed"})
            self.assertEqual(row["fingerprint"], sha256(lifecycle._encode([METHOD, row["detector"], evidence])).hexdigest())
            self.assertLessEqual(len(lifecycle._encode(evidence)), 4096)
        self.assertEqual(rows[0]["evidence"]["fact"], {key: observation["evidence"]["certificate_dates"][key]
            for key in ("not_before", "not_after", "position", "remaining_microseconds")})
        self.assertEqual(rows[0]["evidence"]["fact"]["remaining_microseconds"], "-1")
        self.assertEqual(rows[1]["evidence"]["fact"], {"version": "TLSv1.1"})
        self.assertNotEqual(rows[0]["fingerprint"], rows[1]["fingerprint"])
        for private in ("raw_certificate", "serial", "OCSP", "status", "url", "source_current", "priority", "source_passive_header", "secret_bits"):
            self.assertNotIn(private, json.dumps(rows))
        rows[0]["evidence"]["binding"]["observations"].append("raw")
        rows[0]["evidence"]["fact"]["remaining_microseconds"] = "0"
        rows[0]["evidence"]["availability"]["certificate_dates"] = "unavailable"
        self.assertEqual(rows[1]["evidence"]["availability"]["certificate_dates"], "observed")
        self.assertEqual((observation, self.binding), original)
        self.assertEqual(tls_finding_values(job_id=7, binding=self.binding, observation=observation)[0]["evidence"]["fact"]["remaining_microseconds"], "-1")

    def test_inclusive_window_nullable_availability_and_cipher_label_do_not_create_false_recipes(self):
        end = datetime(2025, 1, 1, tzinfo=UTC)
        for observed in (end - timedelta(microseconds=1), end):
            self.assertEqual(tls_finding_values(job_id=7, binding=self.binding, observation=self.collection(observed)), [])
        for dates in (True, False):
            for version in (None, "TLSv1", "TLSv1.1", "TLSv1.2", "TLSv1.3"):
                observation = self.collection(version=version, dates=dates)
                observation["evidence"]["negotiated_tls"]["cipher"] = {"name": "TLSv1", "secret_bits": 256}
                rows = tls_finding_values(job_id=7, binding=self.binding, observation=observation)
                self.assertEqual(len(rows), 1 if version in {"TLSv1", "TLSv1.1"} else 0)
                if rows:
                    self.assertEqual(rows[0]["evidence"]["fact"], {"version": version})
                    self.assertEqual(rows[0]["evidence"]["availability"], {"certificate_dates": "observed" if dates else "unavailable", "negotiated_version": "observed"})

    def test_malformed_original_identity_family_dates_availability_and_parameters_fail_closed(self):
        observation = self.collection()
        for job_id in (True, 0, -1, 2**53, "7"):
            with self.assertRaises(ValidationError): tls_finding_values(job_id=job_id, binding=self.binding, observation=observation)
        for changes in ({"method_version": "passive-resource-source-v1"}, {"project_id": True}, {"collection_permission": 1},
            {"source_digest": "bad"}, {"url": self.binding["origin"] + "/"}, {"origin": "https://foreign.example.invalid"}):
            with self.assertRaises(ValidationError): tls_finding_values(job_id=7, binding={**self.binding, **changes}, observation=observation)
        mutations = (lambda row: row.update(status=200), lambda row: row.update(method="passive-resource-evidence-v1"),
            lambda row: row.update(observed_at="2025-02-30T00:00:00.000000+00:00"),
            lambda row: row["evidence"]["certificate_dates"].update(state="unavailable"),
            lambda row: row["evidence"]["certificate_dates"].update(position="before_reported_window"),
            lambda row: row["evidence"]["certificate_dates"].update(remaining_microseconds="-0"),
            lambda row: row["evidence"]["negotiated_tls"].update(version="SSLv3"),
            lambda row: row["evidence"]["negotiated_tls"]["cipher"].update(protocol="TLSv1"))
        for mutate in mutations:
            bad = deepcopy(observation); mutate(bad)
            with self.assertRaises(ValidationError): tls_finding_values(job_id=7, binding=self.binding, observation=bad)

    def test_maximum_original_origin_safe_ids_and_changed_dates_parameters_bind_distinct_identity(self):
        observation = self.collection(datetime(2025, 1, 1, 0, 0, 0, 1, tzinfo=UTC), "TLSv1")
        origin = "https://" + ".".join(["a" * 63] * 3 + ["b" * 55])
        self.binding["origin"] = origin
        for key in ("actor_id", "organization_id", "project_id", "verification_id"): self.binding[key] = 2**53 - 1
        observation["origin"] = origin; observation["evidence"]["origin"] = origin
        rows = tls_finding_values(job_id=2**53 - 1, binding=self.binding, observation=observation)
        self.assertEqual(len(rows), 2); self.assertEqual(len(rows[0]["subject"]), 255)
        self.assertTrue(all(len(lifecycle._encode(row["evidence"])) <= 4096 for row in rows))
        self.assertNotEqual(rows[0]["fingerprint"], tls_finding_values(job_id=7, binding=self.binding, observation=observation)[0]["fingerprint"])
        changed = deepcopy(observation); changed["evidence"]["negotiated_tls"]["version"] = "TLSv1.1"
        self.assertNotEqual(rows[0]["fingerprint"], tls_finding_values(job_id=2**53 - 1, binding=self.binding, observation=changed)[0]["fingerprint"])


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json"}))
class OriginalTLSFindingRecipeTests(TransactionTestCase):
    setUp = fixtures.PassiveTLSCollectionTests.setUp
    verified = fixtures.PassiveTLSCollectionTests.verified
    queue = fixtures.PassiveTLSCollectionTests.queue
    transport = fixtures.PassiveTLSCollectionTests.transport

    def test_genuine_original_private_handshake_readback_to_pure_recipe_without_io_or_persistence(self):
        from .models import Finding, JobRun, Opportunity, Recommendation, UsageReservation
        job = self.queue(); fetcher = self.transport(); self.connection.sock.version.return_value = "TLSv1.1"
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")):
            self.assertTrue(collector.execute_passive_tls_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); source = collector.read_passive_tls_observation(project=self.project, actor=self.owner, job_id=job.pk)
        original = deepcopy(source)
        with self.assertNumQueries(0), patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No I/O")), patch(
            "socket.create_connection", side_effect=AssertionError("No network")):
            rows = tls_finding_values(job_id=job.pk, binding=job.config_snapshot["binding"], observation=source["collection"])
        self.assertEqual(source, original); self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_passive_tls_id"], job.pk)
        self.assertEqual(rows[0]["evidence"]["collection_sha256"], job.output["derived_sha256"])
        self.assertEqual(rows[0]["evidence"]["observed_at"], job.output["observed_at"])
        self.assertEqual((Finding.objects.count(), Opportunity.objects.count(), Recommendation.objects.count()), (0, 0, 0))
        self.assertEqual(JobRun.objects.filter(handler=collector.HANDLER).count(), 1)
        self.assertEqual(UsageReservation.objects.filter(job=job).count(), 1)
        for private in (self.challenge, self.verification.challenge_digest, self.owner.email, "private", "protocol"):
            self.assertNotIn(private, json.dumps(rows))
        self.connection.connect.assert_called_once(); self.connection.request.assert_not_called()


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class PassiveTLSFindingTests(TransactionTestCase):
    setUp = fixtures.PassiveTLSCollectionTests.setUp
    verified = fixtures.PassiveTLSCollectionTests.verified
    queue = fixtures.PassiveTLSCollectionTests.queue
    transport = fixtures.PassiveTLSCollectionTests.transport

    def collected(self, key="tls-findings", *, version="TLSv1.1", dates="outside"):
        job = self.queue(key); fetcher = self.transport()
        self.connection.sock.version.return_value = version
        if dates == "outside":
            self.connection.sock.getpeercert.side_effect = lambda: {
                "notBefore": "Jan  1 00:00:00 2020 GMT", "notAfter": "Jan  1 00:00:00 2025 GMT"}
        elif dates == "unknown":
            self.connection.sock.getpeercert.side_effect = lambda: {}
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")):
            self.assertTrue(collector.execute_passive_tls_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db()
        return job

    def record(self, job, **changes):
        return findings.record_tls_findings(**{**dict(project=self.project, actor=self.owner, job_id=job.pk), **changes})

    def read(self, job, **changes):
        return findings.current_tls_findings(**{**dict(project=self.project, actor=self.owner, job_id=job.pk), **changes})

    # Same genuine producer-independent authority, rollback and ordinary-consumer checks.
    test_current_authority_scope_cancellation_and_expiry_deny_without_writes = header_checks.PassiveHeaderFindingTests.test_current_authority_scope_cancellation_and_expiry_deny_without_writes
    test_post_insert_source_row_actor_commercial_and_cancel_loss_roll_back_complete_set = header_checks.PassiveHeaderFindingTests.test_post_insert_source_row_actor_commercial_and_cancel_loss_roll_back_complete_set
    test_ordinary_list_first_audit_reports_shares_weekly_admin_and_intent_cannot_consume = header_checks.PassiveHeaderFindingTests.test_ordinary_list_first_audit_reports_shares_weekly_admin_and_intent_cannot_consume
    test_complete_metadata_source_commercial_cancel_and_natural_expiry_after_io_projection_withhold = source_checks.CurrentTLSCandidateTests.test_complete_metadata_source_commercial_cancel_and_natural_expiry_after_io_projection_withhold

    def test_genuine_two_original_facts_private_idempotent_read_only_without_new_work(self):
        from tenancy.models import OrganizationMembership
        from .models import Finding, JobRun, Opportunity, Recommendation, UsageReservation
        job = self.collected(); counts = (JobRun.objects.count(), UsageReservation.objects.count())
        self.assertEqual(self.read(job)["state"], "no_retained_materialized_findings")
        with patch("socket.create_connection", side_effect=AssertionError("No network")):
            rows = self.record(job); original = self.read(job)
            self.assertEqual([row.pk for row in self.record(job)], [row.pk for row in rows])
            with CaptureQueriesContext(connection) as queries: result = self.read(job)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(result, original); self.assertEqual(len(rows), 2)
        self.assertEqual([row.detector for row in rows], ["reported_certificate_date_outside_window_candidate", "negotiated_tlsv1_or_tlsv1_1_candidate"])
        for row in rows:
            self.assertEqual((row.source_passive_tls_id, row.subject), (job.pk, self.project.canonical_origin))
            self.assertTrue(all(getattr(row, field) is None for field in ("source_metric_id", "source_api_page_id",
                "source_diagnostics_id", "source_indexation_id", "source_performance_id", "source_passive_header_id", "source_passive_resource_id")))
            self.assertEqual(row.evidence["binding"], job.config_snapshot["binding"])
            self.assertEqual(row.evidence["observed_at"], job.output["observed_at"])
            self.assertEqual(row.evidence["collection_sha256"], job.output["derived_sha256"])
            self.assertLessEqual(len(lifecycle._encode(row.evidence)), 4096)
            self.assertNotIn("status", row.evidence); self.assertNotIn("url", row.evidence)
        self.assertEqual(result["state"], "current_materialized_facts")
        self.assertEqual((JobRun.objects.count(), UsageReservation.objects.count()), counts)
        self.assertEqual((Opportunity.objects.count(), Recommendation.objects.count()), (0, 0))
        result["findings"][0]["evidence"]["availability"]["certificate_dates"] = "unavailable"
        self.assertEqual(self.read(job), original)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(self.read(job, actor=self.member), original)
        self.assertEqual([row.pk for row in self.record(job, actor=self.member)], [row.pk for row in rows])
        self.assertEqual(Finding.objects.count(), 2)
        self.connection.connect.assert_called_once(); self.connection.request.assert_not_called()

    def test_independent_null_empty_and_single_fact_never_materialize_a_clean_verdict(self):
        from .models import Finding
        for key, version, dates, count in (("empty", "TLSv1.3", "within", 0), ("unknown-version", None, "within", 0),
            ("unknown-dates", "TLSv1.3", "unknown", 0), ("unknown-both", None, "unknown", 0),
            ("date-only", None, "outside", 1), ("version-only", "TLSv1", "unknown", 1)):
            job = self.collected(key, version=version, dates=dates)
            rows = self.record(job); report = self.read(job)
            self.assertEqual(len(rows), count)
            self.assertEqual(report["state"], "current_materialized_facts" if count else "no_retained_materialized_findings")
            self.assertEqual(Finding.objects.filter(source_passive_tls=job).count(), count)

    def test_immutable_same_project_exact_tls_facts_sql_one_source_and_human_denial(self):
        from tenancy.models import Project
        from .models import Finding, JobRun, Opportunity, Recommendation
        job = self.collected(); row = self.record(job)[0]
        with self.assertRaises(ValidationError): row.save()
        with self.assertRaises(ProtectedError): job.delete()
        for change in ({"source_passive_tls": None}, {"source_passive_header_id": job.pk},
            {"source_passive_resource_id": job.pk}, {"source_diagnostics_id": 999999}):
            with transaction.atomic(), self.assertRaises(IntegrityError) as caught: Finding.objects.filter(pk=row.pk).update(**change)
            self.assertIn("jobs_finding_one_source", str(caught.exception))
        recipe = {key: getattr(row, key) for key in FIELDS}
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other.example.invalid")
        for change in ({"project": other}, {"fingerprint": "a" * 64}, {"detector": "invented"}, {"confidence": "high"},
            {"subject": self.project.canonical_origin + "/"}, {"evidence": {**row.evidence, "status": 200}},
            {"evidence": {**row.evidence, "raw_certificate": "private"}},
            {"evidence": {**row.evidence, "availability": {"certificate_dates": "unavailable", "negotiated_version": "observed"}}}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                Finding(**{**dict(project=self.project, actor=self.owner), **recipe, **change}).full_clean()
        with self.assertRaises(ValidationError):
            Opportunity.objects.create(project=self.project, finding=row, actor=self.owner, review_reason="Not supported")
        opportunity = Opportunity.objects.bulk_create([Opportunity(project=self.project, finding=row, actor=self.owner, review_reason="Corrupt fixture")])[0]
        with self.assertRaises(ValidationError):
            Recommendation.objects.create(project=self.project, opportunity=opportunity, actor=self.owner, revision=1, draft="Not supported")
        recommendation = Recommendation.objects.bulk_create([Recommendation(project=self.project, opportunity=opportunity, actor=self.owner, revision=1, draft="Corrupt fixture")])[0]
        request = header_checks.RequestFactory().get("/admin/"); request.user = self.owner
        self.assertFalse(admin.site._registry[Opportunity].get_queryset(request).filter(pk=opportunity.pk).exists())
        self.assertFalse(admin.site._registry[Recommendation].get_queryset(request).filter(pk=recommendation.pk).exists())
        for change in ({"handler": "collect_passive_headers"}, {"handler": "collect_passive_resources"},
            {"handler": "collect_passive_redirects"}, {"status": "failed"}, {"output": {}}):
            with transaction.atomic():
                JobRun.objects.filter(pk=job.pk).update(**change)
                with self.assertRaises(ValidationError): Finding(project=self.project, actor=self.owner, **recipe).full_clean()
                with self.assertRaises((PermissionDenied, ValidationError)): self.read(job)
                transaction.set_rollback(True)

    def test_current_materializer_full_rows_partial_set_and_detector_ceiling_are_fenced(self):
        from tenancy.models import OrganizationMembership
        from .models import Finding
        job = self.collected(); rows = self.record(job); original = self.read(job)
        validate = findings._validate_rows; calls = 0
        def validate_then_change(*args):
            nonlocal calls
            validate(*args); calls += 1
            if calls == 2: Finding.objects.filter(pk=rows[0].pk).update(detected_at=timezone.now())
        with transaction.atomic():
            with patch.object(findings, "_validate_rows", side_effect=validate_then_change), self.assertRaises(PermissionDenied): self.read(job)
            transaction.set_rollback(True)
        self.assertEqual(self.read(job), original)
        with transaction.atomic():
            Finding.objects.filter(pk=rows[0].pk).delete()
            with self.assertRaises(ValidationError): self.read(job)
            with self.assertRaises(ValidationError): self.record(job)
            transaction.set_rollback(True)
        with transaction.atomic():
            Finding.objects.bulk_create([Finding(project=self.project, actor=self.owner, source_passive_tls=job,
                detector="invented", method_version=METHOD, subject=self.project.canonical_origin, fingerprint="a" * 64, evidence={})])
            with self.assertRaises(ValidationError): self.read(job)
            with self.assertRaises(ValidationError): self.record(job)
            transaction.set_rollback(True)
        Finding.objects.filter(pk__in=[row.pk for row in rows]).update(actor=self.member)
        with self.assertRaises(PermissionDenied): self.read(job)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(len(self.read(job)["findings"]), 2)
        Finding.objects.filter(pk__in=[row.pk for row in rows]).delete()
        self.assertEqual(self.read(job)["state"], "no_retained_materialized_findings")

    def test_independent_caller_materializer_restricted_project_and_foreign_scope(self):
        from tenancy.models import OrganizationMembership, Project, ProjectMembership
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
        rows = self.record(job); recipe = findings.tls_finding_values; calls = 0
        def recipe_then_demote(**kwargs):
            nonlocal calls
            result = recipe(**kwargs); calls += 1
            if calls == 2: OrganizationMembership.objects.filter(pk=membership.pk).update(role="viewer")
            return result
        with transaction.atomic():
            with patch.object(findings, "tls_finding_values", side_effect=recipe_then_demote), self.assertRaises(PermissionDenied):
                self.read(job, actor=self.member)
            transaction.set_rollback(True)
        self.assertEqual({row.actor_id for row in rows}, {self.owner.pk})
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True); self.project.refresh_from_db()
        restricted = self.collected("restricted")
        with self.assertRaises(PermissionDenied): self.record(restricted, actor=self.member)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(len(self.record(restricted, actor=self.member)), 2)
        ProjectMembership.objects.filter(project=self.project, organization_membership=membership).delete()
        with self.assertRaises(PermissionDenied): self.read(restricted)
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other.example.invalid")
        for operation in (self.read, self.record):
            with self.assertRaises(PermissionDenied): operation(restricted, project=other)
        with patch.object(lifecycle, "read_project_artifact", side_effect=AssertionError("No I/O for missing job")):
            with self.assertRaises(PermissionDenied): self.read(job, job_id=job.pk + 1000)

    def test_two_sessions_materialize_one_original_complete_two_fact_set(self):
        from .models import Finding
        job = self.collected(); barrier = Barrier(2)
        def record_once():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return [row.pk for row in self.record(job)]
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _: record_once(), range(2)))
        self.assertEqual(results[0], results[1]); self.assertEqual(Finding.objects.filter(source_passive_tls=job).count(), 2)

    def test_tls_retained_owner_stored_sequential_exports_and_scoped_child_first_erasure(self):
        from tenancy.customer_export import complete_bounded_customer_archive, project_customer_rows
        from tenancy.customer_inventory import CUSTOMER, require_complete_ownership_map
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import _customer_deletion_order, delete_customer_database_records, prepare_customer_data_deletion, sweep_customer_artifact_versions
        from tenancy.models import Organization, OrganizationTrial, Project
        from tenancy.services import create_organization, create_project, revoke_origin_verification
        from .models import Finding, JobRun
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
        self.assertEqual({row["source_passive_tls_id"] for row in exported["rows"]}, {job.pk})
        self.assertTrue(all("historical_literal_tls_fact_not_current" in row["scope"] for row in exported["rows"]))
        with self.assertRaises(PermissionDenied):
            project_customer_rows(organization=self.organization, actor=self.outsider, model_label="jobs.Finding", after_id=0, through_id=rows[-1].pk)
        with ZipFile(io.BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            self.assertEqual({row["source_passive_tls_id"] for row in json.loads(archive.read("records/jobs/Finding.json"))}, {job.pk})
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
            self.assertEqual({row["source_passive_tls_id"] for row in json.loads(archive.read("data"))}, {job.pk})
        other_org = create_organization(user=self.outsider, name="Other retained organization")
        other = create_project(organization=other_org, user=self.outsider, name="Other retained scope", canonical_origin="https://extra.example.invalid")
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied):
            project_customer_rows(organization=self.organization, actor=self.owner, model_label="jobs.Finding", after_id=0, through_id=rows[-1].pk)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(Finding.objects.filter(source_passive_tls_id=job.pk).exists()); self.assertFalse(JobRun.objects.filter(pk=job.pk).exists())
        self.assertTrue(Project.objects.filter(pk=other.pk, organization=other_org).exists())
