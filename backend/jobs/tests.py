from tenancy.customer_artifact_barrier import project_artifact_barrier
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import save_project_artifact
from tenancy.models import (
    AuditEvent, AuditEventType, MembershipRole, Organization, OrganizationMembership,
    OrganizationTrial, PaddleEnvironment, PaddleStatus, PaddleSubscription, Project, TrialState,
)
from tenancy.services import create_organization, create_project
from allauth.account.models import EmailAddress

from .models import Artifact, JobCancellation, JobRun, JobSchedule, JobStatus, JobStep, SourceCitation, UsageReservation
from .services import cancel_job, create_job, execute_job, queue_job, reconcile_dispatch, run_diagnostic, transition
from .usage import UsageLimitError, reconcile_usage, reserve_usage, settle_usage, usage_denial
from .schedules import create_schedule, run_due_schedules, set_schedule_enabled
from .recovery import reconcile_stuck_jobs


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES)
class JobFoundationTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.tasks.execute_job_task.apply_async", return_value=None)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        user_model = get_user_model()
        self.owner = user_model.objects.create_user("job-owner@example.com", password="test-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        self.outsider = user_model.objects.create_user("job-outsider@example.com", password="test-password")
        EmailAddress.objects.create(user=self.outsider, email=self.outsider.email, verified=True, primary=True)
        self.organization = create_organization(user=self.owner, name="Job organization")
        self.other_org = create_organization(user=self.outsider, name="Other organization")
        self.project = create_project(organization=self.organization, user=self.owner,
                                      name="Job site", canonical_origin="https://jobs.example.com")
        self.other_project = create_project(organization=self.other_org, user=self.outsider,
                                            name="Other site", canonical_origin="https://other-jobs.example.com")

    def queue(self, *, partial=False):
        job = create_job(project=self.project, actor=self.owner, handler="diagnostic_probe",
                         input_snapshot={"sample": "safe diagnostic", "simulate_partial": partial})
        reserve_usage(job=job, provider="diagnostic", units=0)
        return job

    def test_diagnostic_handler_persists_progress_and_distinguishes_partial_from_failure(self):
        completed = run_diagnostic(self.queue())
        self.assertEqual(completed.status, JobStatus.SUCCEEDED)
        self.assertEqual(completed.output["sample_length"], len("safe diagnostic"))
        self.assertEqual(list(completed.steps.values_list("status", "progress_percent")),
                         [("succeeded", 50), ("succeeded", 100)])

        partial = run_diagnostic(self.queue(partial=True))
        self.assertEqual(partial.status, JobStatus.PARTIALLY_SUCCEEDED)
        self.assertEqual(partial.steps.filter(status="failed", error_category="synthetic_partial").count(), 1)
        self.assertTrue(partial.output["partial"])
        self.assertEqual(partial.project_id, self.project.pk)
        self.assertEqual(partial.organization_id, self.organization.pk)

    def test_transition_matrix_rejects_illegal_moves_and_revoked_actors(self):
        job = self.queue()
        with self.assertRaises(ValidationError):
            transition(job, JobStatus.SUCCEEDED)
        job.status = JobStatus.SUCCEEDED
        with self.assertRaises(ValidationError):
            job.save(update_fields=["status"])
        job.refresh_from_db()
        self.assertEqual(transition(job, JobStatus.RUNNING).status, JobStatus.RUNNING)
        self.assertEqual(transition(job, JobStatus.WAITING_PROVIDER).status, JobStatus.WAITING_PROVIDER)
        self.assertEqual(transition(job, JobStatus.RUNNING).status, JobStatus.RUNNING)
        self.assertEqual(transition(job, JobStatus.FAILED).status, JobStatus.FAILED)
        with self.assertRaises(ValidationError):
            transition(job, JobStatus.RUNNING)
        self.assertEqual(JobRun.objects.get(pk=job.pk).status, JobStatus.FAILED)

        waiting = self.queue()
        self.organization.is_suspended = True
        self.organization.save(update_fields=["is_suspended"])
        with self.assertRaises(PermissionDenied):
            transition(waiting, JobStatus.RUNNING)
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, JobStatus.QUEUED)

    def test_job_input_and_actor_scope_are_validated_before_any_work(self):
        for invalid in ([], {"sample": "valid", "simulate_partial": "no"},
                        {"sample": "x" * 33000, "simulate_partial": False},
                        {"sample": "valid", "simulate_partial": False, "unknown": 1}):
            with self.subTest(value=type(invalid).__name__), self.assertRaises(ValidationError):
                create_job(project=self.project, actor=self.owner, handler="diagnostic_probe", input_snapshot=invalid)
        with self.assertRaises(PermissionDenied):
            create_job(project=self.project, actor=self.outsider, handler="diagnostic_probe",
                       input_snapshot={"sample": "x", "simulate_partial": False})
        with self.assertRaises(ValidationError):
            JobRun(organization=self.organization, project=self.other_project, actor=self.owner,
                   handler="diagnostic_probe", method_version="v1").save()
        with self.assertRaises(ValidationError):
            JobRun(organization=self.organization, project=self.project, actor=self.outsider,
                   handler="diagnostic_probe", method_version="v1").save()
        self.assertFalse(JobRun.objects.exists())

    def test_artifact_citation_and_schedule_reject_cross_tenant_links(self):
        job = run_diagnostic(self.queue())
        other_job = create_job(project=self.other_project, actor=self.outsider,
                               handler="diagnostic_probe",
                               input_snapshot={"sample": "other", "simulate_partial": False})
        reserve_usage(job=other_job, provider="diagnostic", units=0)
        other = run_diagnostic(other_job)
        with project_artifact_barrier(self.project.organization_id, shared=True):
            key = save_project_artifact(project=self.project, content=b'{"ok":true}', content_type="application/json")
        artifact = Artifact.objects.create(job=job, project=self.project, key=key,
                                           content_type="application/json", size_bytes=11)
        self.assertEqual(artifact.key, key)
        with self.assertRaises(ValidationError):
            Artifact(job=other, project=self.project, key=key, content_type="application/json", size_bytes=11).save()
        with self.assertRaises(ValidationError):
            Artifact(job=job, project=self.project, key="organizations/1/projects/1/../not-safe.json",
                     content_type="application/json", size_bytes=11).save()
        citation = SourceCitation.objects.create(job=job, step=job.steps.first(), source_title="Internal diagnostic",
                                                 observed_at=timezone.now())
        self.assertEqual(citation.job_id, job.pk)
        with self.assertRaises(ValidationError):
            SourceCitation(job=other, step=job.steps.first(), source_title="Wrong job",
                           observed_at=timezone.now()).save()
        with self.assertRaises(ValidationError):
            JobSchedule(organization=self.organization, project=self.other_project, actor=self.owner,
                        handler="diagnostic_probe").save()
        with self.assertRaises(ValidationError):
            JobRun(organization=self.organization, project=self.project, actor=self.owner,
                   handler="diagnostic_probe", method_version="diagnostic-v1", retry_of=other).save()
        with self.assertRaises(ValidationError):
            JobSchedule(organization=self.organization, project=self.project, actor=self.outsider,
                        handler="diagnostic_probe").save()
        schedule = JobSchedule.objects.create(organization=self.organization, project=self.project,
                                              actor=self.owner, handler="diagnostic_probe")
        self.assertFalse(schedule.enabled)
        with self.assertRaises(IntegrityError), transaction.atomic():
            JobSchedule.objects.filter(pk=schedule.pk).update(enabled=True)

    def test_job_api_scopes_create_read_cancel_and_retry_with_csrf(self):
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        self.assertEqual(owner.get("/_allauth/browser/v1/auth/session", secure=True).status_code, 200)
        csrf = owner.cookies["csrftoken"].value
        base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/jobs/"
        data = {"handler": "diagnostic_probe", "input": {"sample": "demo", "simulate_partial": False},
                "idempotency_key": "diagnostic-1"}

        def post(client, path, body, token=csrf):
            return client.post(path, data=json.dumps(body), content_type="application/json", secure=True,
                               HTTP_X_CSRFTOKEN=token, HTTP_REFERER="https://testserver/")

        self.assertEqual(post(owner, base, data, token="").status_code, 403)
        with patch("jobs.tasks.execute_job_task.apply_async") as send:
            response = post(owner, base, data)
        self.assertEqual(response.status_code, 202, response.content)
        send.assert_called_once()  # The owning request has committed.
        job_id = response.json()["job"]["id"]
        self.assertEqual(post(owner, base, data).json()["job"]["id"], job_id)
        admitted = AuditEvent.objects.get(event_type=AuditEventType.JOB_QUEUED,
                                          details__job_id=job_id)
        self.assertEqual((admitted.organization_id, admitted.project_id, admitted.actor_id),
                         (self.organization.pk, self.project.pk, self.owner.pk))
        self.assertEqual(admitted.details, {"job_id": job_id, "retry_of": None})
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(owner.get(base, secure=True).json()["jobs"][0]["id"], job_id)

        viewer = get_user_model().objects.create_user("job-viewer@example.com", password="test-password")
        OrganizationMembership.objects.create(organization=self.organization, user=viewer, role=MembershipRole.VIEWER)
        viewer_client = Client(enforce_csrf_checks=True)
        viewer_client.force_login(viewer)
        viewer_client.get("/_allauth/browser/v1/auth/session", secure=True)
        viewer_csrf = viewer_client.cookies["csrftoken"].value
        self.assertEqual(viewer_client.get(f"{base}{job_id}/", secure=True).status_code, 200)
        self.assertEqual(post(viewer_client, base, data, viewer_csrf).status_code, 403)
        self.assertEqual(post(viewer_client, f"{base}{job_id}/cancel/", {}, viewer_csrf).status_code, 403)
        self.assertEqual(owner.get(f"/api/organizations/{self.other_org.pk}/projects/{self.other_project.pk}/jobs/{job_id}/", secure=True).status_code, 404)

        cancelled = post(owner, f"{base}{job_id}/cancel/", {})
        self.assertEqual(cancelled.status_code, 200)
        self.assertTrue(cancelled.json()["cancelled"])
        self.assertFalse(post(owner, f"{base}{job_id}/cancel/", {}).json()["cancelled"])
        cancelled_event = AuditEvent.objects.get(event_type=AuditEventType.JOB_CANCEL_REQUESTED,
                                                 details__job_id=job_id)
        self.assertEqual((cancelled_event.organization_id, cancelled_event.project_id, cancelled_event.actor_id),
                         (self.organization.pk, self.project.pk, self.owner.pk))
        self.assertEqual(cancelled_event.details, {"job_id": job_id})
        retried = post(owner, f"{base}{job_id}/retry/", {"idempotency_key": "diagnostic-retry"})
        self.assertEqual(retried.status_code, 202)
        new_id = retried.json()["job"]["id"]
        self.assertNotEqual(new_id, job_id)
        self.assertEqual(retried.json()["job"]["retry_of"], job_id)
        self.assertEqual(post(owner, f"{base}{job_id}/retry/", {"idempotency_key": "diagnostic-retry"}).json()["job"]["id"], new_id)
        self.assertEqual(AuditEvent.objects.get(event_type=AuditEventType.JOB_QUEUED,
            details__job_id=new_id).details, {"job_id": new_id, "retry_of": job_id})
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.JOB_QUEUED).count(), 2)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.JOB_CANCEL_REQUESTED).count(), 1)
        self.assertEqual(post(owner, f"{base}{new_id}/retry/", {"idempotency_key": "not-terminal"}).status_code, 409)
        done = run_diagnostic(JobRun.objects.get(pk=new_id))
        details = owner.get(f"{base}{done.pk}/", secure=True).json()["job"]
        self.assertEqual(details["status"], "succeeded")
        self.assertEqual([step["progress_percent"] for step in details["steps"]], [50, 100])
        self.assertEqual(details["estimate"], {"diagnostic_units_max": 0})
        with override_settings(DEBUG=False):
            self.assertEqual(owner.get(base, secure=True).status_code, 404)
        self.project.access_restricted = True
        self.project.save(update_fields=["access_restricted"])
        self.assertEqual(viewer_client.get(base, secure=True).status_code, 404)
        self.assertEqual(owner.get(base, secure=True).status_code, 200)
        self.assertEqual(Client().get(base, secure=True).status_code, 401)

    def test_job_api_preserves_trial_denial_codes(self):
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        owner.get("/_allauth/browser/v1/auth/session", secure=True)
        path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/jobs/"
        data = {
            "handler": "diagnostic_probe",
            "input": {"sample": "demo", "simulate_partial": False},
            "idempotency_key": "trial-denial",
        }
        headers = {
            "content_type": "application/json",
            "secure": True,
            "HTTP_X_CSRFTOKEN": owner.cookies["csrftoken"].value,
            "HTTP_REFERER": "https://testserver/",
        }
        for category, status in (("trial_unavailable", 403), ("trial_units_exhausted", 429)):
            with self.subTest(category=category), patch(
                "jobs.api.queue_job",
                side_effect=UsageLimitError("denied", category=category),
            ):
                response = owner.post(path, data=json.dumps(data), **headers)
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["errors"][0]["code"], category)


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES)
class DispatchTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user("dispatch-owner@example.com", password="test-password")
        EmailAddress.objects.create(user=self.actor, email=self.actor.email, verified=True, primary=True)
        self.organization = create_organization(user=self.actor, name="Dispatch organization")
        self.project = create_project(organization=self.organization, user=self.actor,
                                      name="Dispatch site", canonical_origin="https://dispatch.example.com")
        self.payload = {"sample": "small", "simulate_partial": False}

    def enqueue(self, key="safe-key"):
        return queue_job(project=self.project, actor=self.actor, handler="diagnostic_probe",
                         input_snapshot=self.payload, idempotency_key=key)

    def test_dispatch_follows_commit_and_broker_failure_remains_recoverable(self):
        with patch("jobs.tasks.execute_job_task.apply_async") as send:
            with self.assertRaisesRegex(RuntimeError, "rollback"), transaction.atomic():
                self.enqueue("rolled-back")
                self.assertEqual(send.call_count, 0)
                raise RuntimeError("rollback")
            self.assertFalse(JobRun.objects.filter(idempotency_key="rolled-back").exists())
            self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.JOB_QUEUED).exists())
            self.enqueue()
            self.assertEqual(send.call_count, 1)
            self.assertEqual(send.call_args.kwargs["queue"], "default")
        job = JobRun.objects.get(idempotency_key="safe-key")
        self.assertIsNotNone(job.dispatched_at)
        self.assertEqual(job.dispatch_error, "")

        from kombu.exceptions import OperationalError
        with patch("jobs.tasks.execute_job_task.apply_async", side_effect=OperationalError("untrusted secret")):
            failed = self.enqueue("broker-down")
        failed.refresh_from_db()
        self.assertIsNone(failed.dispatched_at)
        self.assertEqual(failed.dispatch_error, "broker_unavailable")
        self.assertNotIn("secret", str(list(JobRun.objects.values("dispatch_error", "error_category"))))
        with patch("jobs.tasks.execute_job_task.apply_async") as send:
            self.assertEqual(reconcile_dispatch(), 1)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(reconcile_dispatch(), 0)
        failed.refresh_from_db()
        self.assertIsNotNone(failed.dispatched_at)

    def test_duplicate_delivery_and_stale_redelivery_have_one_persisted_result(self):
        with patch("jobs.tasks.execute_job_task.apply_async") as send:
            job = self.enqueue()
            JobRun.objects.filter(pk=job.pk).update(dispatched_at=timezone.now() - timedelta(minutes=2))
            self.assertEqual(reconcile_dispatch(stale_seconds=60), 1)
            self.assertEqual(send.call_count, 2)
        self.assertTrue(execute_job(job.pk))
        self.assertFalse(execute_job(job.pk))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertEqual(job.steps.count(), 2)
        self.assertEqual(reconcile_dispatch(), 0)
        self.assertEqual(job.usage.state, UsageReservation.State.RELEASED)

    def test_revocation_and_handler_failure_are_terminal_without_raw_errors(self):
        with patch("jobs.tasks.execute_job_task.apply_async"):
            revoked = self.enqueue("revoked")
            other = self.enqueue("unexpected")
        self.organization.is_suspended = True
        self.organization.save(update_fields=["is_suspended"])
        self.assertTrue(execute_job(revoked.pk))
        revoked.refresh_from_db()
        self.assertEqual((revoked.status, revoked.error_category), (JobStatus.CANCELLED, "actor_revoked"))
        self.assertEqual(revoked.usage.state, UsageReservation.State.RELEASED)
        self.organization.is_suspended = False
        self.organization.save(update_fields=["is_suspended"])
        with patch("jobs.services.run_diagnostic", side_effect=RuntimeError("private credential")):
            self.assertTrue(execute_job(other.pk))
        other.refresh_from_db()
        self.assertEqual((other.status, other.error_category), (JobStatus.FAILED, "handler_failed"))
        self.assertEqual(other.steps.count(), 0)
        self.assertNotIn("credential", str(other.output))
        self.assertEqual(other.usage.state, UsageReservation.State.RELEASED)

    def test_concurrent_same_key_returns_one_job_and_one_publish(self):
        barrier = Barrier(2)

        def enqueue(_):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                project = Project.objects.get(pk=self.project.pk)
                barrier.wait(timeout=5)
                return queue_job(project=project, actor=actor, handler="diagnostic_probe",
                                 input_snapshot=self.payload, idempotency_key="concurrent").pk
            finally:
                close_old_connections()

        with patch("jobs.tasks.execute_job_task.apply_async") as send:
            with ThreadPoolExecutor(max_workers=2) as pool:
                ids = list(pool.map(enqueue, range(2)))
        self.assertEqual(ids, [ids[0], ids[0]])
        self.assertEqual(send.call_count, 1)
        self.assertEqual(JobRun.objects.filter(idempotency_key="concurrent").count(), 1)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.JOB_QUEUED,
                                                  details__job_id=ids[0]).count(), 1)

    def test_job_audit_storage_failure_rolls_back_admission_and_cancellation(self):
        create_audit = AuditEvent.objects.create

        def invalid_audit(**fields):
            return create_audit(**{**fields, "event_type": None})

        with patch("jobs.tasks.execute_job_task.apply_async") as send:
            with patch("jobs.services.AuditEvent.objects.create", side_effect=invalid_audit):
                with self.assertRaises(IntegrityError):
                    self.enqueue("audit-failed")
            send.assert_not_called()
            self.assertFalse(JobRun.objects.filter(idempotency_key="audit-failed").exists())
            self.assertFalse(UsageReservation.objects.exists())
            job = self.enqueue("cancel-audit-failed")
        with patch("jobs.services.AuditEvent.objects.create", side_effect=invalid_audit):
            with self.assertRaises(IntegrityError):
                cancel_job(job=job, actor=self.actor)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertEqual(job.usage.state, UsageReservation.State.RESERVED)
        self.assertFalse(JobCancellation.objects.filter(job=job).exists())
        self.assertFalse(AuditEvent.objects.filter(event_type=AuditEventType.JOB_CANCEL_REQUESTED).exists())

    def test_idempotent_repeat_reuses_same_job_but_rejects_changed_inputs_or_actor(self):
        with patch("jobs.tasks.execute_job_task.apply_async") as send:
            first = self.enqueue("stable")
            self.assertEqual(self.enqueue("stable").pk, first.pk)
            self.assertEqual(send.call_count, 1)
            with self.assertRaises(ValidationError):
                queue_job(project=self.project, actor=self.actor, handler="diagnostic_probe",
                          input_snapshot={"sample": "different", "simulate_partial": False},
                          idempotency_key="stable")
            with self.assertRaises(ValidationError):
                self.enqueue("../unsafe")
        self.assertEqual(JobRun.objects.filter(idempotency_key="stable").count(), 1)

    def test_crash_mid_step_rolls_back_and_stale_dispatch_recovers_on_restart(self):
        with patch("jobs.tasks.execute_job_task.apply_async"):
            job = self.enqueue("crash-check")
        create_step = JobStep.objects.create
        calls = 0

        def interrupted_step(**fields):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise SystemExit("simulated worker loss")
            return create_step(**fields)

        with patch("jobs.services.JobStep.objects.create", side_effect=interrupted_step):
            with self.assertRaises(SystemExit):
                execute_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertFalse(job.steps.exists())
        JobRun.objects.filter(pk=job.pk).update(dispatched_at=timezone.now() - timedelta(minutes=2))
        with patch("jobs.tasks.execute_job_task.apply_async") as send:
            self.assertEqual(reconcile_dispatch(stale_seconds=60), 1)
            self.assertEqual(send.call_count, 1)
        self.assertTrue(execute_job(job.pk))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertEqual(job.steps.count(), 2)

    def test_cancellation_request_reaches_running_worker_between_stages(self):
        paused = Event()
        resume = Event()
        create_step = JobStep.objects.create
        with patch("jobs.tasks.execute_job_task.apply_async"):
            job = self.enqueue("cancel-mid-stage")

        def pause_after_first(**fields):
            step = create_step(**fields)
            if fields["sequence"] == 1:
                paused.set()
                if not resume.wait(timeout=10):
                    raise RuntimeError("Cancellation never reached the worker")
            return step

        def worker():
            close_old_connections()
            try:
                return execute_job(job.pk)
            finally:
                close_old_connections()

        with patch("jobs.services.JobStep.objects.create", side_effect=pause_after_first):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(worker)
                try:
                    self.assertTrue(paused.wait(timeout=10))
                    client = Client(enforce_csrf_checks=True)
                    client.force_login(self.actor)
                    client.get("/_allauth/browser/v1/auth/session", secure=True)
                    response = client.post(
                        f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/jobs/{job.pk}/cancel/",
                        data="{}", content_type="application/json", secure=True,
                        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
                        HTTP_REFERER="https://testserver/",
                    )
                    self.assertEqual(response.status_code, 202, response.content)
                    self.assertTrue(response.json()["cancel_requested"])
                    self.assertFalse(response.json()["cancelled"])
                finally:
                    resume.set()
                self.assertTrue(future.result(timeout=10))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertEqual(list(job.steps.values_list("sequence", flat=True)), [1])
        self.assertEqual(job.output["cancelled_after_step"], 1)
        self.assertEqual(job.usage.state, UsageReservation.State.RELEASED)


@override_settings(DEBUG=True)
class UsageTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user("usage-owner@example.com", password="test-password")
        EmailAddress.objects.create(user=self.actor, email=self.actor.email, verified=True, primary=True)
        self.organization = create_organization(user=self.actor, name="Usage organization")
        self.projects = [Project.objects.create(organization=self.organization,
                                        name=f"Usage site {index}", canonical_origin=f"https://usage-{index}.example.com")
                         for index in range(3)]

    def job(self, project=None):
        return create_job(project=project or self.projects[0], actor=self.actor, handler="diagnostic_probe",
                          input_snapshot={"sample": "synthetic", "simulate_partial": False})

    def test_reservations_bound_scope_and_preserve_real_actual_usage(self):
        first = self.job()
        reserved = reserve_usage(job=first, provider="synthetic", units=25)
        self.assertEqual(reserve_usage(job=first, provider="synthetic", units=25).pk, reserved.pk)
        second = self.job()
        with self.assertRaises(UsageLimitError):
            reserve_usage(job=second, provider="synthetic", units=20)
        self.assertFalse(UsageReservation.objects.filter(job=second).exists())
        self.assertEqual(settle_usage(job=first, actual_units=10).state, UsageReservation.State.SETTLED)
        reserve_usage(job=second, provider="synthetic", units=20)
        settled = settle_usage(job=second, actual_units=27)  # Report a real over-estimate, never hide it.
        self.assertEqual(settled.actual_units, 27)
        self.assertEqual(settle_usage(job=second, actual_units=27).actual_units, 27)
        with self.assertRaises(ValidationError):
            settle_usage(job=second, actual_units=20)
        with self.assertRaises(UsageLimitError):
            reserve_usage(job=self.job(), provider="other", units=4)
        with self.assertRaises(ValidationError):
            UsageReservation(job=self.job(), organization=self.organization, project=self.projects[1],
                             provider="synthetic", period_start=timezone.now().date().replace(day=1),
                             reserved_units=1).save()

    @patch("jobs.usage._entitlement_denial", return_value="")
    def test_project_provider_and_organization_caps_are_independent(self, _entitlement_denial):
        first = self.job()
        reserve_usage(job=first, provider="engine", units=35)
        with self.assertRaises(UsageLimitError):
            reserve_usage(job=self.job(self.projects[1]), provider="engine", units=35)
        reserve_usage(job=self.job(self.projects[1]), provider="second", units=35)
        with self.assertRaises(UsageLimitError):
            reserve_usage(job=self.job(self.projects[2]), provider="third", units=35)

        zero_a, zero_b, zero_c = self.job(self.projects[2]), self.job(self.projects[2]), self.job(self.projects[2])
        reserve_usage(job=zero_a, provider="diagnostic", units=0)
        reserve_usage(job=zero_b, provider="diagnostic", units=0)
        with self.assertRaises(UsageLimitError):
            reserve_usage(job=zero_c, provider="diagnostic", units=0)
        settle_usage(job=zero_a, actual_units=0)
        reserve_usage(job=zero_c, provider="diagnostic", units=0)
        with self.assertRaises(UsageLimitError):
            reserve_usage(job=self.job(self.projects[1]), provider="diagnostic", units=0)
        settle_usage(job=zero_b, actual_units=0)
        reserve_usage(job=self.job(self.projects[1]), provider="diagnostic", units=0)

    def test_concurrent_reservation_has_one_budget_winner(self):
        ids = [self.job().pk for _ in range(2)]
        barrier = Barrier(2)

        def compete(job_id):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    reserve_usage(job=JobRun.objects.get(pk=job_id), provider="synthetic", units=25)
                    return "reserved"
                except UsageLimitError as error:
                    return error.category
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(compete, ids))
        self.assertCountEqual(results, ["reserved", "trial_units_exhausted"])
        self.assertEqual(UsageReservation.objects.filter(state=UsageReservation.State.RESERVED).count(), 1)

    @override_settings(PADDLE_ENVIRONMENT="sandbox", INTERNAL_ORG_MONTHLY_UNITS=200,
                       INTERNAL_PROJECT_MONTHLY_UNITS=200, INTERNAL_PROVIDER_MONTHLY_UNITS=200)
    def test_concurrent_paid_reservations_cannot_exceed_one_period_allowance(self):
        now = timezone.now()
        PaddleSubscription.objects.create(
            organization=self.organization, environment=PaddleEnvironment.SANDBOX,
            customer_id="ctm_" + "g" * 26, subscription_id="sub_" + "h" * 26,
            status=PaddleStatus.ACTIVE, verified_at=now, currency_code="USD",
            period_starts_at=now - timedelta(days=1), period_ends_at=now + timedelta(days=29))
        ids = [self.job(self.projects[index]).pk for index in (0, 1)]
        barrier = Barrier(2)

        def compete(job_id):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    reserve_usage(job=JobRun.objects.get(pk=job_id), provider="paid", units=60)
                    return "reserved"
                except UsageLimitError as error:
                    return error.category
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(compete, ids))
        self.assertCountEqual(results, ["reserved", "paid_units_exhausted"])
        self.assertEqual(UsageReservation.objects.filter(state=UsageReservation.State.RESERVED).count(), 1)

    def test_positive_trial_allowance_and_zero_unit_read_only_boundary(self):
        first = self.job()
        reserve_usage(job=first, provider="synthetic", units=25)
        settle_usage(job=first, actual_units=10)
        second = self.job()
        reserve_usage(job=second, provider="synthetic", units=30)
        with self.assertRaises(UsageLimitError) as exhausted:
            reserve_usage(job=self.job(), provider="synthetic", units=1)
        self.assertEqual(exhausted.exception.category, "trial_units_exhausted")

        trial = self.organization.trial
        OrganizationTrial.objects.filter(pk=trial.pk).update(
            started_at=timezone.now() - timedelta(days=31),
            ends_at=timezone.now() - timedelta(days=1),
        )
        with self.assertRaises(UsageLimitError) as unavailable:
            reserve_usage(job=self.job(), provider="synthetic", units=1)
        self.assertEqual(unavailable.exception.category, "trial_unavailable")
        reserve_usage(job=self.job(), provider="diagnostic", units=0)

        for state in (TrialState.PENDING_REVIEW, TrialState.READ_ONLY, TrialState.SUSPENDED):
            pending = state == TrialState.PENDING_REVIEW
            OrganizationTrial.objects.filter(organization=self.organization).update(
                state=state,
                automatic_eligibility_id=None,
                started_at=None if pending else timezone.now() - timedelta(days=1),
                ends_at=None if pending else timezone.now() + timedelta(days=29),
            )
            with self.subTest(state=state), self.assertRaises(UsageLimitError) as state_denial:
                reserve_usage(job=self.job(), provider="synthetic", units=1)
            self.assertEqual(state_denial.exception.category, "trial_unavailable")

    def test_linked_subscription_disables_trial_reservation_and_costly_stage(self):
        reserved = self.job()
        reserve_usage(job=reserved, provider="synthetic", units=1)
        PaddleSubscription.objects.create(
            organization=self.organization, environment=PaddleEnvironment.SANDBOX,
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26,
            status=PaddleStatus.ACTIVE,
        )
        self.assertEqual(usage_denial(job=reserved), "trial_unavailable")
        with self.assertRaises(UsageLimitError) as denied:
            reserve_usage(job=self.job(), provider="synthetic", units=1)
        self.assertEqual(denied.exception.category, "trial_unavailable")
        self.assertEqual(UsageReservation.objects.filter(organization=self.organization).count(), 1)
        reserve_usage(job=self.job(), provider="diagnostic", units=0)

    @override_settings(PADDLE_ENVIRONMENT="sandbox", INTERNAL_ORG_MONTHLY_UNITS=200,
                       INTERNAL_PROJECT_MONTHLY_UNITS=200, INTERNAL_PROVIDER_MONTHLY_UNITS=200)
    def test_verified_paid_period_has_one_org_allowance_and_stops_on_adverse_hold(self):
        from tenancy.models import PaddleWebhookReceipt

        now = timezone.now()
        subscription = PaddleSubscription.objects.create(
            organization=self.organization, environment=PaddleEnvironment.SANDBOX,
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26,
            status=PaddleStatus.ACTIVE, verified_at=now, currency_code="USD",
            period_starts_at=now - timedelta(hours=1), period_ends_at=now + timedelta(days=30),
        )
        first = self.job()
        reserve_usage(job=first, provider="one", units=40)
        settle_usage(job=first, actual_units=40)
        second = self.job(self.projects[1])
        reserve_usage(job=second, provider="two", units=40)
        settle_usage(job=second, actual_units=40)
        active = self.job(self.projects[2])
        reserve_usage(job=active, provider="three", units=20)
        with self.assertRaises(UsageLimitError) as exhausted:
            reserve_usage(job=self.job(), provider="four", units=1)
        self.assertEqual(exhausted.exception.category, "paid_units_exhausted")
        self.assertEqual(usage_denial(job=active), "")
        PaddleWebhookReceipt.objects.create(environment="sandbox", event_id="evt_" + "a" * 26,
            notification_id="ntf_" + "a" * 26, event_type="adjustment.updated",
            occurred_at=now, entity_id="adj_" + "a" * 26, raw_digest="a" * 64,
            subscription_id=subscription.subscription_id, customer_id=subscription.customer_id,
            state=PaddleWebhookReceipt.State.PENDING)
        self.assertEqual(usage_denial(job=active), "billing_review_hold")
        with self.assertRaises(UsageLimitError) as hold:
            reserve_usage(job=self.job(), provider="four", units=1)
        self.assertEqual(hold.exception.category, "billing_review_hold")
        reserve_usage(job=self.job(), provider="diagnostic", units=0)

    @override_settings(PADDLE_ENVIRONMENT="sandbox", INTERNAL_ORG_MONTHLY_UNITS=200,
                       INTERNAL_PROJECT_MONTHLY_UNITS=200, INTERNAL_PROVIDER_MONTHLY_UNITS=200)
    def test_paid_period_change_and_expiry_recheck_reserved_work(self):
        now = timezone.now()
        subscription = PaddleSubscription.objects.create(
            organization=self.organization, environment=PaddleEnvironment.SANDBOX,
            customer_id="ctm_" + "c" * 26, subscription_id="sub_" + "d" * 26,
            status=PaddleStatus.ACTIVE, verified_at=now, currency_code="USD",
            period_starts_at=now - timedelta(days=1), period_ends_at=now + timedelta(days=29),
        )
        job = self.job()
        reservation = reserve_usage(job=job, provider="one", units=1)
        UsageReservation.objects.filter(pk=reservation.pk).update(created_at=now - timedelta(days=2))
        self.assertEqual(usage_denial(job=job), "paid_period_changed")
        PaddleSubscription.objects.filter(pk=subscription.pk).update(period_ends_at=now - timedelta(seconds=1))
        self.assertEqual(usage_denial(job=job), "paid_unavailable")

    @override_settings(PADDLE_ENVIRONMENT="sandbox", INTERNAL_ORG_MONTHLY_UNITS=200,
                       INTERNAL_PROJECT_MONTHLY_UNITS=200, INTERNAL_PROVIDER_MONTHLY_UNITS=200)
    def test_failed_renewal_grace_reuses_prior_paid_allowance_and_expires_without_beat(self):
        now = timezone.now()
        prior_start = now - timedelta(days=15)
        subscription = PaddleSubscription.objects.create(
            organization=self.organization, environment=PaddleEnvironment.SANDBOX,
            customer_id="ctm_" + "e" * 26, subscription_id="sub_" + "f" * 26,
            status=PaddleStatus.ACTIVE, verified_at=now, currency_code="USD",
            period_starts_at=prior_start, period_ends_at=now + timedelta(days=15),
        )
        for index in (0, 1):
            job = self.job(self.projects[index])
            reserve_usage(job=job, provider=f"paid-{index}", units=40)
            settle_usage(job=job, actual_units=40)
        failure = now - timedelta(minutes=1)
        PaddleSubscription.objects.filter(pk=subscription.pk).update(
            status=PaddleStatus.PAST_DUE, verified_at=now, failed_at=failure,
            grace_usage_starts_at=prior_start,
            period_starts_at=now, period_ends_at=now + timedelta(days=30),
        )
        reserve_usage(job=self.job(self.projects[2]), provider="grace", units=20)
        with self.assertRaises(UsageLimitError) as exhausted:
            reserve_usage(job=self.job(self.projects[2]), provider="another", units=1)
        self.assertEqual(exhausted.exception.category, "paid_units_exhausted")
        PaddleSubscription.objects.filter(pk=subscription.pk).update(
            status=PaddleStatus.ACTIVE, failed_at=None, grace_usage_starts_at=prior_start)
        with self.assertRaises(UsageLimitError) as after_recovery:
            reserve_usage(job=self.job(self.projects[2]), provider="another", units=1)
        self.assertEqual(after_recovery.exception.category, "paid_units_exhausted")
        PaddleSubscription.objects.filter(pk=subscription.pk).update(
            status=PaddleStatus.PAST_DUE, failed_at=now - timedelta(days=7),
            grace_usage_starts_at=now - timedelta(days=15),
        )
        with self.assertRaises(UsageLimitError) as expired:
            reserve_usage(job=self.job(self.projects[2]), provider="another", units=1)
        self.assertEqual(expired.exception.category, "paid_unavailable")

    def test_missing_and_drifted_trials_fail_closed_without_cross_tenant_usage(self):
        legacy_user = get_user_model().objects.create_user("legacy-usage@example.com", password="test-password")
        legacy = Organization.objects.create(name="Legacy usage organization")
        OrganizationMembership.objects.create(organization=legacy, user=legacy_user, role=MembershipRole.OWNER)
        legacy_project = Project.objects.create(
            organization=legacy,
            name="Legacy usage site",
            canonical_origin="https://legacy-usage.example.com",
        )
        # D098 retained-data access now denies a legacy organization with no
        # lifecycle record before it can create/reserve even a diagnostic job.
        with self.assertRaises(PermissionDenied):
            create_job(project=legacy_project, actor=legacy_user, handler="diagnostic_probe",
                       input_snapshot={"sample": "synthetic", "simulate_partial": False})
        self.assertFalse(JobRun.objects.filter(organization=legacy).exists())
        self.assertFalse(UsageReservation.objects.filter(organization=legacy).exists())

        OrganizationTrial.objects.filter(organization=self.organization).update(offer_version="legacy-offer")
        with self.assertRaises(UsageLimitError) as drifted:
            reserve_usage(job=self.job(), provider="synthetic", units=1)
        self.assertEqual(drifted.exception.category, "trial_unavailable")
        self.assertFalse(UsageReservation.objects.filter(organization=self.organization).exists())

    def test_trial_usage_is_isolated_by_organization(self):
        other_user = get_user_model().objects.create_user("other-usage@example.com", password="test-password")
        EmailAddress.objects.create(user=other_user, email=other_user.email, verified=True, primary=True)
        other_org = create_organization(user=other_user, name="Other usage organization")
        other_project = create_project(
            organization=other_org,
            user=other_user,
            name="Other usage site",
            canonical_origin="https://other-usage.example.com",
        )
        other_job = create_job(
            project=other_project,
            actor=other_user,
            handler="diagnostic_probe",
            input_snapshot={"sample": "synthetic", "simulate_partial": False},
        )
        reserve_usage(job=other_job, provider="synthetic", units=40)
        reserve_usage(job=self.job(), provider="synthetic", units=1)
        self.assertEqual(
            UsageReservation.objects.get(job__organization=self.organization).reserved_units,
            1,
        )

    def test_trial_window_is_half_open_and_extension_keeps_consumption(self):
        trial = self.organization.trial
        start = timezone.now() - timedelta(days=31)
        end = start + timedelta(days=37)
        OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=start, ends_at=end)
        AuditEvent.objects.create(
            organization=self.organization,
            event_type=AuditEventType.TRIAL_EXTENDED,
            actor=self.actor,
        )

        before = self.job()
        reserve_usage(job=before, provider="synthetic", units=25)
        settle_usage(job=before, actual_units=25)
        previous_period = (timezone.localdate().replace(day=1) - timedelta(days=1)).replace(day=1)
        UsageReservation.objects.filter(job=before).update(
            created_at=start - timedelta(microseconds=1),
            period_start=previous_period,
        )

        inside = self.job()
        reserve_usage(job=inside, provider="synthetic", units=25)
        settle_usage(job=inside, actual_units=39)
        UsageReservation.objects.filter(job=inside).update(created_at=start)
        reserve_usage(job=self.job(), provider="synthetic", units=1)
        with self.assertRaises(UsageLimitError) as exhausted:
            reserve_usage(job=self.job(), provider="synthetic", units=1)
        self.assertEqual(exhausted.exception.category, "trial_units_exhausted")

        UsageReservation.objects.filter(state=UsageReservation.State.RESERVED).update(
            created_at=end,
            period_start=previous_period,
        )
        reserve_usage(job=self.job(), provider="synthetic", units=1)

    def test_dispatch_expiry_preserves_reason_and_releases_reservation(self):
        from .services import dispatch_pending

        job = self.job()
        reserve_usage(job=job, provider="synthetic", units=10)
        OrganizationTrial.objects.filter(organization=self.organization).update(
            state=TrialState.ACTIVE,
            started_at=timezone.now() - timedelta(days=31),
            ends_at=timezone.now() - timedelta(days=1),
        )

        with patch("jobs.tasks.execute_job_task.apply_async") as send:
            self.assertFalse(dispatch_pending(job.pk))
        job.refresh_from_db()
        self.assertEqual(send.call_count, 0)
        self.assertEqual((job.status, job.error_category), (JobStatus.CANCELLED, "trial_unavailable"))
        self.assertEqual(job.usage.state, UsageReservation.State.RELEASED)

    def test_terminal_diagnostic_reconciles_but_unknown_provider_usage_is_not_refunded(self):
        diagnostic = self.job()
        reserve_usage(job=diagnostic, provider="diagnostic", units=0)
        transition(diagnostic, JobStatus.RUNNING)
        transition(diagnostic, JobStatus.FAILED)
        self.assertEqual(reconcile_usage(), 1)
        self.assertEqual(reconcile_usage(), 0)
        self.assertEqual(diagnostic.usage.state, UsageReservation.State.RELEASED)

        unknown = self.job()
        reserve_usage(job=unknown, provider="synthetic", units=20)
        transition(unknown, JobStatus.RUNNING)
        transition(unknown, JobStatus.FAILED)
        self.assertEqual(reconcile_usage(), 0)
        self.assertEqual(unknown.usage.state, UsageReservation.State.RESERVED)
        self.assertEqual(settle_usage(job=unknown, actual_units=7).actual_units, 7)


@override_settings(DEBUG=True)
class ScheduleRecoveryTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user("schedule-owner@example.com", password="test-password")
        EmailAddress.objects.create(user=self.actor, email=self.actor.email, verified=True, primary=True)
        self.organization = create_organization(user=self.actor, name="Schedule organization")
        self.project = create_project(organization=self.organization, user=self.actor,
                                      name="Schedule site", canonical_origin="https://schedule.example.com")
        self.input_snapshot = {"sample": "synthetic", "simulate_partial": False}

    def schedule(self):
        return create_schedule(project=self.project, actor=self.actor, input_snapshot=self.input_snapshot,
                               interval_minutes=60)

    def test_due_run_skips_backlog_and_is_idempotent_across_schedulers(self):
        schedule = self.schedule()
        self.assertFalse(schedule.enabled)
        schedule = set_schedule_enabled(schedule=schedule, actor=self.actor, enabled=True)
        now = timezone.now()
        JobSchedule.objects.filter(pk=schedule.pk).update(next_run_at=now - timedelta(hours=3))
        barrier = Barrier(2)

        def due(_):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return run_due_schedules(now=now)
            finally:
                close_old_connections()

        with patch("jobs.tasks.execute_job_task.apply_async") as send:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(due, range(2)))
        self.assertCountEqual(results, [1, 0])
        self.assertEqual(send.call_count, 1)
        schedule.refresh_from_db()
        self.assertEqual(schedule.skipped_occurrences, 3)
        self.assertEqual(schedule.last_error_category, "")
        self.assertGreater(schedule.next_run_at, now)
        self.assertEqual(JobRun.objects.filter(schedule=schedule).count(), 1)
        self.assertEqual(UsageReservation.objects.filter(job__schedule=schedule).count(), 1)
        self.assertEqual(run_due_schedules(now=now), 0)

    def test_schedule_access_loss_pauses_and_capacity_defers_without_backlog(self):
        member = get_user_model().objects.create_user("schedule-member@example.com", password="test-password")
        membership = OrganizationMembership.objects.create(organization=self.organization, user=member, role=MembershipRole.MEMBER)
        member_schedule = create_schedule(project=self.project, actor=member, input_snapshot=self.input_snapshot,
                                          interval_minutes=60)
        set_schedule_enabled(schedule=member_schedule, actor=member, enabled=True)
        now = timezone.now()
        JobSchedule.objects.filter(pk=member_schedule.pk).update(next_run_at=now - timedelta(minutes=1))
        from tenancy.services import remove_membership
        remove_membership(membership=membership, actor=self.actor)
        self.assertEqual(run_due_schedules(now=now), 0)
        member_schedule.refresh_from_db()
        self.assertFalse(member_schedule.enabled)
        self.assertEqual(member_schedule.last_error_category, "access_revoked")
        self.assertFalse(JobRun.objects.filter(schedule=member_schedule).exists())

        owner_schedule = self.schedule()
        set_schedule_enabled(schedule=owner_schedule, actor=self.actor, enabled=True)
        JobSchedule.objects.filter(pk=owner_schedule.pk).update(next_run_at=now - timedelta(minutes=2))
        with patch("jobs.tasks.execute_job_task.apply_async"):
            for key in ("occupied-one", "occupied-two"):
                queue_job(project=self.project, actor=self.actor, handler="diagnostic_probe",
                          input_snapshot=self.input_snapshot, idempotency_key=key)
            self.assertEqual(run_due_schedules(now=now), 0)
        owner_schedule.refresh_from_db()
        self.assertTrue(owner_schedule.enabled)
        self.assertEqual(owner_schedule.last_error_category, "internal_capacity")
        self.assertGreater(owner_schedule.next_run_at, now)
        self.assertFalse(JobRun.objects.filter(schedule=owner_schedule).exists())

    def test_commercial_trial_denial_pauses_schedule(self):
        now = timezone.now()
        for category in ("trial_unavailable", "trial_units_exhausted"):
            schedule = self.schedule()
            set_schedule_enabled(schedule=schedule, actor=self.actor, enabled=True)
            JobSchedule.objects.filter(pk=schedule.pk).update(next_run_at=now - timedelta(minutes=1))
            with self.subTest(category=category), patch(
                "jobs.schedules.queue_job",
                side_effect=UsageLimitError("denied", category=category),
            ):
                self.assertEqual(run_due_schedules(now=now), 0)
            schedule.refresh_from_db()
            self.assertFalse(schedule.enabled)
            self.assertEqual(schedule.last_error_category, category)

    def test_stuck_diagnostic_is_failed_and_usage_settled_without_touching_live_lock(self):
        with patch("jobs.tasks.execute_job_task.apply_async"):
            job = queue_job(project=self.project, actor=self.actor, handler="diagnostic_probe",
                            input_snapshot=self.input_snapshot, idempotency_key="stuck-one")
        transition(job, JobStatus.RUNNING)
        JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=3))
        with transaction.atomic():
            JobRun.objects.select_for_update().get(pk=job.pk)

            def probe_lock():
                close_old_connections()
                try:
                    return reconcile_stuck_jobs()
                finally:
                    close_old_connections()

            with ThreadPoolExecutor(max_workers=1) as executor:
                self.assertEqual(executor.submit(probe_lock).result(timeout=5), 0)
        self.assertEqual(reconcile_stuck_jobs(), 1)
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.FAILED, "worker_stalled"))
        self.assertEqual(job.usage.state, UsageReservation.State.RELEASED)
        self.assertEqual(reconcile_stuck_jobs(), 0)

    def test_dispatch_rechecks_suspension_and_releases_reserved_capacity(self):
        with patch("jobs.tasks.execute_job_task.apply_async"):
            job = queue_job(project=self.project, actor=self.actor, handler="diagnostic_probe",
                            input_snapshot=self.input_snapshot, idempotency_key="suspend-before-dispatch")
        self.organization.is_suspended = True
        self.organization.save(update_fields=["is_suspended"])
        JobRun.objects.filter(pk=job.pk).update(dispatched_at=timezone.now() - timedelta(minutes=3))
        with patch("jobs.tasks.execute_job_task.apply_async") as send:
            self.assertEqual(reconcile_dispatch(), 0)
            self.assertEqual(send.call_count, 0)
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.CANCELLED, "actor_revoked"))
        self.assertEqual(job.usage.state, UsageReservation.State.RELEASED)

    def test_dispatch_stops_when_actual_usage_exceeds_reserved_internal_ceiling(self):
        diagnostic = create_job(project=self.project, actor=self.actor, handler="diagnostic_probe",
                                input_snapshot=self.input_snapshot)
        reserve_usage(job=diagnostic, provider="diagnostic", units=0)
        costly = create_job(project=self.project, actor=self.actor, handler="diagnostic_probe",
                            input_snapshot=self.input_snapshot)
        reserve_usage(job=costly, provider="synthetic", units=25)
        transition(costly, JobStatus.RUNNING)
        transition(costly, JobStatus.FAILED)
        settle_usage(job=costly, actual_units=101)
        self.assertEqual(usage_denial(job=diagnostic), "internal_capacity")
        with patch("jobs.tasks.execute_job_task.apply_async") as send:
            from .services import dispatch_pending
            self.assertFalse(dispatch_pending(diagnostic.pk))
            self.assertEqual(send.call_count, 0)
        diagnostic.refresh_from_db()
        self.assertEqual((diagnostic.status, diagnostic.error_category), (JobStatus.CANCELLED, "internal_capacity"))
        self.assertEqual(UsageReservation.objects.get(job=diagnostic).state, UsageReservation.State.RELEASED)

    def test_schedule_api_is_scoped_idempotent_and_explicitly_paused_by_default(self):
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.actor)
        owner.get("/_allauth/browser/v1/auth/session", secure=True)
        csrf = owner.cookies["csrftoken"].value
        path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/job-schedules/"

        def post(client, body, token=csrf):
            return client.post(path, data=json.dumps(body), content_type="application/json",
                               secure=True, HTTP_X_CSRFTOKEN=token, HTTP_REFERER="https://testserver/")

        body = {"input": self.input_snapshot, "interval_minutes": 60, "idempotency_key": "hourly-1"}
        self.assertEqual(post(owner, body, token="").status_code, 403)
        first = post(owner, body)
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(first.json()["schedule"]["enabled"], False)
        schedule_id = first.json()["schedule"]["id"]
        self.assertEqual(post(owner, body).json()["schedule"]["id"], schedule_id)
        self.assertEqual(post(owner, {**body, "interval_minutes": 120}).status_code, 400)
        self.assertEqual(JobSchedule.objects.filter(pk=schedule_id).count(), 1)

        viewer = get_user_model().objects.create_user("schedule-viewer@example.com", password="test-password")
        OrganizationMembership.objects.create(organization=self.organization, user=viewer, role=MembershipRole.VIEWER)
        view = Client(enforce_csrf_checks=True)
        view.force_login(viewer)
        view.get("/_allauth/browser/v1/auth/session", secure=True)
        self.assertEqual(view.get(path, secure=True).json()["schedules"][0]["id"], schedule_id)
        self.assertEqual(post(view, {**body, "idempotency_key": "viewer"}, view.cookies["csrftoken"].value).status_code, 403)

        detail = f"{path}{schedule_id}/"
        enabled = owner.patch(detail, data='{"enabled":true}', content_type="application/json", secure=True,
                              HTTP_X_CSRFTOKEN=csrf, HTTP_REFERER="https://testserver/")
        self.assertEqual(enabled.status_code, 200)
        self.assertGreater(JobSchedule.objects.get(pk=schedule_id).next_run_at, timezone.now())
        self.assertEqual(view.patch(detail, data='{"enabled":false}', content_type="application/json", secure=True,
                                    HTTP_X_CSRFTOKEN=view.cookies["csrftoken"].value,
                                    HTTP_REFERER="https://testserver/").status_code, 403)
        paused = owner.patch(detail, data='{"enabled":false}', content_type="application/json", secure=True,
                             HTTP_X_CSRFTOKEN=csrf, HTTP_REFERER="https://testserver/")
        self.assertEqual(paused.status_code, 200)
        self.assertFalse(paused.json()["schedule"]["enabled"])
        with override_settings(DEBUG=False):
            self.assertEqual(owner.get(path, secure=True).status_code, 404)

    def test_suspension_during_execution_stops_after_completed_stage(self):
        paused, resume = Event(), Event()
        create_step = JobStep.objects.create
        with patch("jobs.tasks.execute_job_task.apply_async"):
            job = queue_job(project=self.project, actor=self.actor, handler="diagnostic_probe",
                            input_snapshot=self.input_snapshot, idempotency_key="stage-suspension")

        def stop_after_first(**fields):
            step = create_step(**fields)
            if fields["sequence"] == 1:
                paused.set()
                if not resume.wait(timeout=10):
                    raise RuntimeError("Worker was not resumed")
            return step

        def worker():
            close_old_connections()
            try:
                return execute_job(job.pk)
            finally:
                close_old_connections()

        with patch("jobs.services.JobStep.objects.create", side_effect=stop_after_first):
            with ThreadPoolExecutor(max_workers=1) as pool:
                running = pool.submit(worker)
                try:
                    self.assertTrue(paused.wait(timeout=10))
                    Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True)
                finally:
                    resume.set()
                self.assertTrue(running.result(timeout=10))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.CANCELLED, "actor_revoked"))
        self.assertEqual(list(job.steps.values_list("sequence", flat=True)), [1])
        self.assertEqual(UsageReservation.objects.get(job=job).state, UsageReservation.State.RELEASED)

    def test_job_admin_denies_generic_inspection_and_mutation(self):
        private_input = {"sample": "private-fixture-only", "simulate_partial": False}
        job = create_job(project=self.project, actor=self.actor, handler="diagnostic_probe",
                         input_snapshot=private_input)
        staff = get_user_model().objects.create_superuser("job-staff@example.com", password="staff-password")
        client = Client(enforce_csrf_checks=True)
        client.force_login(staff)
        client.get("/admin/", secure=True)
        url = f"/admin/jobs/jobrun/{job.pk}/change/"
        response = client.get(url, secure=True)
        # D209 retired unreasoned generic JobRun inspection; the separately
        # permissioned/session-MFA exact-scope consumer has its own tests.
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("private-fixture-only", response.content.decode())
        self.assertEqual(client.post(url, data={"status": "succeeded"}, secure=True,
                                     HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
                                     HTTP_REFERER="https://testserver/").status_code, 403)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.QUEUED)
