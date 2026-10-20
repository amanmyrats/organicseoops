from tenancy.customer_artifact_barrier import project_artifact_barrier
from datetime import timedelta
from copy import deepcopy
from hashlib import sha256
import json
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from tenancy.services import create_organization, create_project, update_project

from config.artifacts import ArtifactNotFound, read_private_artifact, save_private_artifact
from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import project_artifact_scope

from .models import Artifact, JobCancellation, JobRun, JobStatus, JobStep, PerformanceObservationSnapshot, UsageReservation
from .models import Finding, Opportunity
from .findings import record_performance_findings
from .performance_job import (METHOD, _finish, execute_performance_audit, queue_performance_audit,
                              record_performance_observation, validate_performance_selection)
from .performance_transport import PerformanceTransportError
from .recovery import reconcile_stuck_performance_jobs
from .usage import reserve_usage


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}))
class PerformanceSnapshotTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending")
        dispatch.start()
        self.addCleanup(dispatch.stop)
        self.owner = get_user_model().objects.create_user("performance-job@example.com", password="test-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        self.organization = create_organization(user=self.owner, name="Performance job")
        self.project = create_project(organization=self.organization, user=self.owner, name="Measured site",
                                      canonical_origin="https://measured.example")
        self.target = "https://measured.example/page"
        self.job = JobRun.objects.create(
            organization=self.organization, project=self.project, actor=self.owner, handler="audit_performance",
            method_version=METHOD, input_snapshot={"target": self.target, "grain": "page", "strategy": "mobile",
                                                   "sources": ["psi_lab", "crux_current"]},
        )
        reserve_usage(job=self.job, provider="performance", units=2)
        self.job.status = JobStatus.RUNNING
        self.job.save(update_fields=["status", "updated_at"])
        end = timezone.now().date() - timedelta(days=2)
        self.crux = {"record": {
            "key": {"url": self.target, "formFactor": "PHONE"},
            "collectionPeriod": {"firstDate": self.date_part(end - timedelta(days=27)),
                                 "lastDate": self.date_part(end)},
            "metrics": {"largest_contentful_paint": {"percentiles": {"p75": 2500}}},
        }}
        self.lab = {"lighthouseResult": {
            "requestedUrl": self.target, "finalUrl": self.target, "fetchTime": timezone.now().isoformat(),
            "lighthouseVersion": "12.5.0", "configSettings": {"formFactor": "mobile"},
            "categories": {"performance": {"score": .7}}, "audits": {},
        }}

    @staticmethod
    def date_part(value):
        return {"year": value.year, "month": value.month, "day": value.day}

    def test_released_reservation_does_not_rollback_terminal_denial(self):
        JobStep.objects.create(
            job=self.job,
            sequence=1,
            name="Collect performance source",
            status=JobStep.Status.RUNNING,
            output={"source": "psi_lab", "state": "attempted"},
        )
        self.job.usage.state = UsageReservation.State.RELEASED
        self.job.usage.settled_at = timezone.now()
        self.job.usage.save(update_fields=["state", "settled_at"])
        self.assertTrue(_finish(self.job.pk))
        self.job.refresh_from_db()
        self.job.usage.refresh_from_db()
        self.assertEqual((self.job.status, self.job.error_category), (JobStatus.CANCELLED, "usage_unreserved"))
        self.assertEqual((self.job.usage.state, self.job.usage.actual_units), (UsageReservation.State.RELEASED, 0))

    def test_separate_source_snapshots_preserve_unknown_field_coverage_and_replay(self):
        self.lab["loadingExperience"] = {"private_provider_field": "raw-only-fixture"}
        lab = record_performance_observation(job=self.job, source="psi_lab", response=self.lab)
        field = record_performance_observation(job=self.job, source="crux_current", response=self.crux)
        self.assertNotEqual(lab.pk, field.pk)
        self.assertEqual((lab.output["field_data"], lab.output["score_method"]),
                         ("not_used", "lighthouse_lab_score_not_field_p75"))
        self.assertEqual(field.output["metrics"][0]["grade"], "good")
        self.assertEqual(field.output["metrics"][1]["state"], "unavailable")
        self.assertEqual(lab.raw_artifact.project_id, self.project.pk)
        self.assertIn(b"raw-only-fixture", read_private_artifact(lab.raw_artifact.key))
        self.assertNotIn("raw-only-fixture", str(lab.output))
        self.assertEqual(record_performance_observation(job=self.job, source="crux_current", response=self.crux).pk,
                         field.pk)
        self.crux["record"]["metrics"]["largest_contentful_paint"]["percentiles"]["p75"] = 4001
        with self.assertRaises(ValidationError):
            record_performance_observation(job=self.job, source="crux_current", response=self.crux)
        with self.assertRaises(ValidationError):
            field.save()
        field.raw_artifact = lab.raw_artifact
        with self.assertRaises(ValidationError):
            field.full_clean()
        self.lab["loadingExperience"]["private_provider_field"] = "changed-raw-with-identical-parsed-output"
        with self.assertRaises(ValidationError):
            record_performance_observation(job=self.job, source="psi_lab", response=self.lab)
        self.assertEqual(PerformanceObservationSnapshot.objects.filter(job=self.job).count(), 2)

    def test_source_owned_lab_and_field_candidates_skip_unavailable_metrics(self):
        self.lab["lighthouseResult"]["categories"]["performance"]["score"] = .4
        self.crux["record"]["metrics"]["largest_contentful_paint"]["percentiles"]["p75"] = 4501
        lab = record_performance_observation(job=self.job, source="psi_lab", response=self.lab)
        field = record_performance_observation(job=self.job, source="crux_current", response=self.crux)
        self.assertTrue(_finish(self.job.pk))
        lab_findings, lab_truncated = record_performance_findings(project=self.project, actor=self.owner,
                                                                   observation_id=lab.pk)
        field_findings, field_truncated = record_performance_findings(project=self.project, actor=self.owner,
                                                                       observation_id=field.pk)
        self.assertFalse(lab_truncated or field_truncated)
        self.assertEqual([item.detector for item in lab_findings], ["low_lighthouse_lab_score_candidate"])
        self.assertEqual([item.detector for item in field_findings], ["poor_crux_field_lcp_candidate"])
        self.assertEqual(field_findings[0].evidence["details"]["method"], "field_p75_not_a_lab_score")
        self.assertEqual(lab_findings[0].evidence["details"]["method"], "lighthouse_lab_score_not_field_p75")
        self.assertFalse(Opportunity.objects.exists())
        self.assertEqual([item.pk for item in lab_findings], [item.pk for item in record_performance_findings(
            project=self.project, actor=self.owner, observation_id=lab.pk)[0]])
        self.assertEqual(Finding.objects.filter(project=self.project).count(), 2)

    def test_original_raw_digest_legacy_replay_shape_and_reconstruction(self):
        field = record_performance_observation(job=self.job, source="crux_current", response=self.crux)
        raw = read_private_artifact(field.raw_artifact.key)
        self.assertEqual(field.raw_sha256, sha256(raw).hexdigest())
        original_date = field.collected_at
        for value in ("", "A" * 64, "a" * 63, "g" * 64):
            with self.subTest(value=value), self.assertRaises(IntegrityError), transaction.atomic():
                PerformanceObservationSnapshot.objects.filter(pk=field.pk).update(raw_sha256=value)
        PerformanceObservationSnapshot.objects.filter(pk=field.pk).update(raw_sha256="b" * 64)
        with self.assertRaises(ValidationError):
            record_performance_observation(job=self.job, source="crux_current", response=self.crux)
        # Explicit legacy fixture: original capture cannot be reconstructed from this later read.
        PerformanceObservationSnapshot.objects.filter(pk=field.pk).update(raw_sha256=None)
        replay = record_performance_observation(job=self.job, source="crux_current", response=self.crux)
        self.assertEqual((replay.pk, replay.raw_sha256, replay.collected_at), (field.pk, None, original_date))
        reconstructed = PerformanceObservationSnapshot(**{
            item.attname: getattr(replay, item.attname) for item in replay._meta.concrete_fields})
        reconstructed.raw_sha256 = sha256(raw).hexdigest()
        with self.assertRaises(ValidationError):
            reconstructed.save()
        replay.refresh_from_db()
        self.assertIsNone(replay.raw_sha256)
        self.assertEqual(replay.collected_at, original_date)
        changed = deepcopy(self.crux)
        changed["raw_only"] = "different"
        with self.assertRaises(ValidationError):
            record_performance_observation(job=self.job, source="crux_current", response=changed)

    @override_settings(GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
    def test_real_worker_snapshot_insertion_rollback_cleans_orphan_without_digest(self):
        job = self.queue(["crux_current"], key="digest-insert-rollback")
        saved = []
        original = save_private_artifact
        def capture(**kwargs):
            key = original(**kwargs); saved.append(key); return key
        with patch("jobs.performance_job.save_private_artifact", side_effect=capture), \
                patch.object(PerformanceObservationSnapshot, "save", side_effect=ValidationError("fixture insert denial")):
            self.assertTrue(execute_performance_audit(job.pk, fetch=lambda **_: self.crux))
        self.assertEqual(len(saved), 1)
        self.assertFalse(PerformanceObservationSnapshot.objects.filter(job=job).exists())
        self.assertFalse(Artifact.objects.filter(job=job).exists())
        with self.assertRaises(ArtifactNotFound):
            read_private_artifact(saved[0])
        job.refresh_from_db()
        self.assertEqual((job.status, job.usage.actual_units), (JobStatus.FAILED, 1))

    def test_original_digest_scoped_customer_export_and_erasure(self):
        from tenancy.customer_export import project_customer_rows, _reviewed_fields
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        from tenancy.models import Organization, Project
        from tenancy.customer_inventory import require_complete_ownership_map
        field = record_performance_observation(job=self.job, source="crux_current", response=self.crux)
        other = get_user_model().objects.create_user("other-performance-export@example.invalid", password="fixture-password")
        EmailAddress.objects.create(user=other, email=other.email, verified=True, primary=True)
        other_org = create_organization(user=other, name="Other performance")
        other_project = create_project(organization=other_org, user=other, name="Other site",
                                       canonical_origin="https://other-performance.example.invalid")
        require_complete_ownership_map()
        _reviewed_fields("jobs.PerformanceObservationSnapshot")
        rows = project_customer_rows(organization=self.organization, actor=self.owner,
            model_label="jobs.PerformanceObservationSnapshot", after_id=0, through_id=field.pk)["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["raw_sha256"], field.raw_sha256)
        self.assertNotIn(field.raw_artifact.key, json.dumps(rows, cls=DjangoJSONEncoder))
        self.assertEqual(project_customer_rows(organization=other_org, actor=other,
            model_label="jobs.PerformanceObservationSnapshot", after_id=0, through_id=field.pk)["rows"], [])
        self.assertTrue(_finish(self.job.pk))
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        delete_customer_database_records(run=run)
        self.assertFalse(PerformanceObservationSnapshot.objects.filter(pk=field.pk).exists())
        self.assertTrue(Project.objects.filter(pk=other_project.pk).exists())

    def test_revocation_cancellation_and_foreign_response_never_add_evidence(self):
        invalid = {**self.crux, "record": {**self.crux["record"], "key": {
            "url": "https://other.example/page", "formFactor": "PHONE"}}}
        with self.assertRaises(ValidationError):
            record_performance_observation(job=self.job, source="crux_current", response=invalid)
        JobCancellation.objects.create(job=self.job, requested_by=self.owner)
        with self.assertRaises(PermissionDenied):
            record_performance_observation(job=self.job, source="psi_lab", response=self.lab)
        JobCancellation.objects.filter(job=self.job).delete()
        update_project(project=self.project, user=self.owner, canonical_origin="https://new-site.example")
        with self.assertRaises(ValidationError):
            record_performance_observation(job=self.job, source="psi_lab", response=self.lab)
        self.assertFalse(PerformanceObservationSnapshot.objects.exists())

    def test_rejects_malformed_or_incompatible_selection_without_work(self):
        valid = self.job.input_snapshot
        for change in ({"sources": ["psi_lab", "psi_lab"]}, {"grain": "origin"},
                       {"sources": ["crux_current", "wrong"]}, {"target": [self.target]},
                       {"strategy": []}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                validate_performance_selection({**valid, **change})

    def test_oversize_response_and_orphan_staging_do_not_leave_private_source_payload(self):
        self.lab["provider_extension"] = "x" * (2 * 1024 * 1024 + 1)
        with self.assertRaises(ValidationError):
            record_performance_observation(job=self.job, source="psi_lab", response=self.lab)
        self.assertFalse(PerformanceObservationSnapshot.objects.exists())
        scope = f"{project_artifact_scope(self.project)}/jobs/{self.job.pk}"
        with project_artifact_barrier(self.project.organization_id, shared=True):
            orphan = save_private_artifact(scope=scope, content=b'{"uncommitted":true}',
                                           content_type="application/json", key_stem="f" * 32)
        JobStep.objects.create(job=self.job, sequence=1, name="Collect performance source",
                               status=JobStep.Status.RUNNING, output={"source": "psi_lab", "state": "attempted"})
        self.assertTrue(_finish(self.job.pk, error="handler_failed"))
        with self.assertRaises(ArtifactNotFound):
            read_private_artifact(orphan)
        self.job.refresh_from_db()
        self.assertEqual(self.job.usage.actual_units, 1)

    def queue(self, sources, *, key="performance-fixture"):
        with patch("jobs.services.dispatch_pending"):
            return queue_performance_audit(project=self.project, actor=self.owner, target=self.target,
                grain="page", strategy="mobile", sources=sources, idempotency_key=key)

    @override_settings(GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
    def test_audit_job_keeps_lab_and_field_sources_distinct_and_settles_attempts(self):
        job = self.queue(["psi_lab", "crux_current", "crux_history"])
        self.assertEqual(job.usage.reserved_units, 3)
        current = deepcopy(self.crux)
        current["record"]["metrics"].update({
            "interaction_to_next_paint": {"percentiles": {"p75": 200}},
            "cumulative_layout_shift": {"percentiles": {"p75": "0.10"}},
            "experimental_time_to_first_byte": {"percentiles": {"p75": 800}},
        })
        history = deepcopy(current)
        record = history["record"]
        record["collectionPeriods"] = [record.pop("collectionPeriod")]
        record["metrics"] = {name: {"percentilesTimeseries": {"p75s": [value["percentiles"]["p75"]]}}
                             for name, value in record["metrics"].items()}
        observed = []
        def fetch(*, kind, api_key, **kwargs):
            self.assertEqual(api_key, "fixture_key_with_32_placeholder_chars")
            observed.append(kind)
            return {"psi_lab": self.lab, "crux_current": current, "crux_history": history}[kind]
        self.assertTrue(execute_performance_audit(job.pk, fetch=fetch))
        job.refresh_from_db()
        self.assertEqual(observed, ["psi_lab", "crux_current", "crux_history"])
        self.assertEqual((job.status, job.usage.actual_units, job.output["sources_recorded"]), (JobStatus.SUCCEEDED, 3, 3))
        self.assertEqual((job.output["lab"], job.output["field"]), ("observed", "observed"))
        self.assertFalse(execute_performance_audit(job.pk, fetch=fetch))
        self.assertEqual(PerformanceObservationSnapshot.objects.filter(job=job).count(), 3)
        for snapshot in PerformanceObservationSnapshot.objects.filter(job=job).select_related("raw_artifact"):
            payload = {"psi_lab": self.lab, "crux_current": current, "crux_history": history}[snapshot.source]
            raw = json.dumps(payload, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
            self.assertEqual(read_private_artifact(snapshot.raw_artifact.key), raw)
            self.assertEqual(snapshot.raw_sha256, sha256(raw).hexdigest())

    @override_settings(GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
    def test_quota_stops_later_requests_and_preserves_lab(self):
        job = self.queue(["psi_lab", "crux_history", "crux_current"], key="partial-performance")
        observed = []
        def fetch(*, kind, **kwargs):
            observed.append(kind)
            if kind == "crux_history":
                raise PerformanceTransportError("quota_limited", retryable=True)
            return self.lab
        self.assertTrue(execute_performance_audit(job.pk, fetch=fetch))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.usage.actual_units),
                         (JobStatus.PARTIALLY_SUCCEEDED, "quota_limited", 2))
        self.assertEqual(observed, ["psi_lab", "crux_history"])
        self.assertEqual((job.output["lab"], job.output["field"]), ("observed", "unavailable"))
        self.assertEqual(PerformanceObservationSnapshot.objects.filter(job=job).count(), 1)

    @override_settings(GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
    def test_missing_field_data_is_unavailable_not_passing(self):
        job = self.queue(["psi_lab", "crux_current"], key="missing-field")
        def fetch(*, kind, **kwargs):
            if kind == "crux_current":
                raise PerformanceTransportError("field_data_unavailable")
            return self.lab
        self.assertTrue(execute_performance_audit(job.pk, fetch=fetch))
        job.refresh_from_db()
        self.assertEqual((job.status, job.output["field"], job.usage.actual_units),
                         (JobStatus.PARTIALLY_SUCCEEDED, "unavailable", 2))

    @override_settings(GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
    def test_partial_crux_metrics_keep_unknown_coverage_even_on_http_success(self):
        job = self.queue(["crux_current"], key="partial-field-metrics")
        self.assertTrue(execute_performance_audit(job.pk, fetch=lambda **kwargs: self.crux))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.output["coverage"]),
                         (JobStatus.PARTIALLY_SUCCEEDED, "partial_coverage", "partial"))
        snapshot = PerformanceObservationSnapshot.objects.get(job=job)
        self.assertEqual([item["state"] for item in snapshot.output["metrics"]],
                         ["observed", "unavailable", "unavailable", "unavailable"])

    @override_settings(GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
    def test_worker_loss_does_not_refetch_uncertain_source_and_recovery_republishes_once(self):
        job = self.queue(["psi_lab", "crux_current"], key="lost-performance")
        def lost(**kwargs):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            execute_performance_audit(job.pk, fetch=lost)
        JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=4))
        with patch("jobs.tasks.execute_performance_task.apply_async") as dispatch:
            self.assertEqual(reconcile_stuck_performance_jobs(), 1)
            dispatch.assert_called_once_with(args=[job.pk], queue="audit", task_id=f"job-{job.pk}", retry=False)
        observed = []
        def fetch(*, kind, **kwargs):
            observed.append(kind)
            return self.crux
        self.assertTrue(execute_performance_audit(job.pk, fetch=fetch))
        job.refresh_from_db()
        self.assertEqual(observed, ["crux_current"])
        self.assertEqual((job.status, job.usage.actual_units, job.output["sources_recorded"]),
                         (JobStatus.PARTIALLY_SUCCEEDED, 2, 1))

    @override_settings(GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
    def test_revoked_project_during_provider_request_cannot_commit_result(self):
        original_origin = self.project.canonical_origin
        job = self.queue(["psi_lab"], key="scope-loss-performance")
        def fetch(**kwargs):
            update_project(project=self.project, user=self.owner, canonical_origin="https://changed.example")
            return self.lab
        self.assertTrue(execute_performance_audit(job.pk, fetch=fetch))
        job.refresh_from_db()
        self.assertEqual((job.status, job.usage.actual_units), (JobStatus.CANCELLED, 1))
        self.assertFalse(PerformanceObservationSnapshot.objects.filter(job=job).exists())
        from functools import partial
        from .performance_transport import google_performance_request
        from .test_performance_transport import FakeConnection, FakeResponse
        for phase in ("unchanged", "dns", "tls"):
            with self.subTest(phase=phase):
                update_project(project=self.project, user=self.owner, canonical_origin=original_origin)
                self.project.refresh_from_db()
                delayed = self.queue(["psi_lab"], key=f"performance-origin-loss-{phase}")
                connection = FakeConnection(FakeResponse(json.dumps(self.lab).encode()))
                def revoke():
                    update_project(project=self.project, user=self.owner, canonical_origin="https://changed.example")
                def resolver(*_args):
                    if phase == "dns":
                        revoke()
                    return ["93.184.216.34"]
                def factory(*_args):
                    self.assertNotEqual(phase, "dns", "DNS source loss must stop before connecting")
                    connection.connect = revoke if phase == "tls" else lambda: None
                    return connection
                self.assertTrue(execute_performance_audit(delayed.pk, fetch=partial(google_performance_request,
                    resolver=resolver, connection_factory=factory)))
                delayed.refresh_from_db()
                self.assertEqual((delayed.status, delayed.error_category),
                    (JobStatus.SUCCEEDED, "") if phase == "unchanged" else (JobStatus.CANCELLED, "scope_revoked"))
                self.assertEqual(delayed.usage.actual_units, 1)
                self.assertEqual(len(connection.requests), 1 if phase == "unchanged" else 0)
                self.assertEqual(PerformanceObservationSnapshot.objects.filter(job=delayed).exists(), phase == "unchanged")

    @override_settings(GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
    def test_current_actor_or_credential_loss_cannot_capture_original_digest(self):
        from providers.models import OrganizationPerformanceKey
        for loss in ("actor", "credential"):
            with self.subTest(loss=loss):
                job = self.queue(["crux_current"], key=f"digest-{loss}-loss")
                def fetch(**_kwargs):
                    if loss == "actor":
                        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
                    else:
                        OrganizationPerformanceKey.objects.create(organization=self.organization,
                            state="revoked", encrypted_secret="", rotated_at=timezone.now())
                    return self.crux
                self.assertTrue(execute_performance_audit(job.pk, fetch=fetch))
                job.refresh_from_db()
                self.assertEqual((job.status, job.usage.actual_units), (JobStatus.CANCELLED, 1))
                self.assertFalse(PerformanceObservationSnapshot.objects.filter(job=job).exists())
                self.assertFalse(Artifact.objects.filter(job=job).exists())
                get_user_model().objects.filter(pk=self.owner.pk).update(is_active=True)
                OrganizationPerformanceKey.objects.filter(organization=self.organization).delete()
