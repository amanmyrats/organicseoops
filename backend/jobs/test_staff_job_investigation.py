import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.mfa.models import Authenticator
from django.contrib.auth import HASH_SESSION_KEY, get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import AuditEvent, AuditEventType, Organization, OrganizationTrial, Project
from . import staff_job_investigation as staff, tests as fixtures
from .models import JobRun, JobStatus, JobStep
from .services import execute_job, run_diagnostic
from .usage import settle_usage


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES)
class StaffJobInvestigationTests(TestCase):
    queue = fixtures.JobFoundationTests.queue

    def setUp(self):
        fixtures.JobFoundationTests.setUp(self)
        self.staff = get_user_model().objects.create_user("job-staff@example.invalid", password="fixture-password", is_staff=True)
        self.permissions = Permission.objects.filter(content_type__app_label="jobs", codename__in=["view_jobrun", "view_jobstep"])
        self.staff.user_permissions.add(*self.permissions)
        self.client.force_login(self.staff)
        Authenticator.objects.create(user=self.staff, type=Authenticator.Type.TOTP, data={"secret": "unused-fixture"})
        session = self.client.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa", "at": timezone.now().timestamp()}]; session.save()
        self.request = RequestFactory().post("/admin/jobs/jobrun/scoped/")
        self.request.user, self.request.session = self.staff, self.client.session
        self.job = run_diagnostic(self.queue(partial=True))
        settle_usage(job=self.job, actual_units=0)

    def inspect(self, **changes):
        return staff.inspect_staff_job(**{**dict(request=self.request, organization_id=self.organization.pk,
            project_id=self.project.pk, job_id=self.job.pk, reason="investigation"), **changes})

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_JOB_INSPECTED)

    def test_genuine_partial_success_and_executor_failure_with_payload_free_scoped_audit(self):
        result = self.inspect()
        self.assertEqual(result["job"]["status"], "partially_succeeded")
        self.assertEqual([(row["sequence"], row["status"], row["progress_percent"]) for row in result["steps"]],
                         [(1, "succeeded", 50), (2, "failed", 100)])
        event = self.events().get()
        self.assertEqual((event.actor_id, event.organization_id, event.project_id),
                         (self.staff.pk, self.organization.pk, self.project.pk))
        self.assertEqual(event.details, {"job_id": self.job.pk, "reason": "investigation", "status": "partially_succeeded", "step_count": 2})
        failed = self.queue()
        with patch("jobs.services.run_diagnostic", side_effect=RuntimeError("fixture failure")):
            self.assertTrue(execute_job(failed.pk))
        self.assertEqual(self.inspect(job_id=failed.pk)["job"]["status"], "failed")
        self.assertEqual(self.inspect(job_id=failed.pk)["steps"], [])
        succeeded = run_diagnostic(self.queue())
        self.assertEqual(self.inspect(job_id=succeeded.pk)["job"]["status"], "succeeded")

    def test_privacy_scalar_sql_only_no_work_mutation_network_or_secret_copy(self):
        private = "private-customer-secret-value"
        JobRun.objects.filter(pk=self.job.pk).update(input_snapshot={"private": private}, output={"body": private},
            config_snapshot={"secret": private}, error_category=private, dispatch_error=private)
        JobStep.objects.filter(job=self.job).update(name=private, output={"body": private}, error_category=private)
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.services.dispatch_pending", side_effect=AssertionError("dispatch")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")):
            result = self.inspect()
        for value in (private, self.owner.email, self.project.canonical_origin, "handler", "error_category", "output", "actor_id", "provider"):
            self.assertNotIn(value, json.dumps(result))
            self.assertNotIn(value, json.dumps(self.events().get().details))
        self.assertFalse(any(field in query["sql"] for query in queries for field in (
            "input_snapshot", "config_snapshot", '"output"', "error_category", "dispatch_error", '"name"',
            "jobs_artifact", "jobs_usage", "jobs_aiusage", "jobs_sourcecitation")))
        writes = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(len(writes), 1); self.assertIn("tenancy_auditevent", writes[0])

    def test_separate_permissions_current_staff_persisted_session_totp_and_mfa_required(self):
        for permission in self.permissions:
            self.staff.user_permissions.remove(permission)
            with self.assertRaises(PermissionDenied): self.inspect()
            self.staff.user_permissions.add(permission)
        for mutate in (lambda: get_user_model().objects.filter(pk=self.staff.pk).update(is_staff=False),
                       lambda: get_user_model().objects.filter(pk=self.staff.pk).update(is_active=False),
                       lambda: get_user_model().objects.filter(pk=self.staff.pk).update(password="changed-auth-hash"),
                       lambda: Authenticator.objects.filter(user=self.staff).delete(),
                       lambda: Session.objects.filter(session_key=self.request.session.session_key).delete()):
            self.request.session = self.client.session
            with transaction.atomic():
                mutate()
                with self.assertRaises(PermissionDenied): self.inspect()
                transaction.set_rollback(True)
        self.staff.user_permissions.clear()
        self.staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="tenancy", codename__in=["view_supportrequest", "change_supportrequest"]))
        with self.assertRaises(PermissionDenied): self.inspect()
        self.staff.user_permissions.add(*self.permissions)
        session = self.client.session; session[AUTHENTICATION_METHODS_SESSION_KEY] = []; session.save()
        with self.assertRaises(PermissionDenied): self.inspect()
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa"}]; session[HASH_SESSION_KEY] = "wrong"; session.save()
        with self.assertRaises(PermissionDenied): self.inspect()
        self.assertFalse(self.events().exists())

    def test_scope_identity_reason_retention_and_current_customer_role_are_independent(self):
        for changes in ({"organization_id": self.other_org.pk}, {"project_id": self.other_project.pk}, {"job_id": self.job.pk + 99999}):
            with self.assertRaises(PermissionDenied): self.inspect(**changes)
        for key in ("organization_id", "project_id", "job_id"):
            for invalid in (True, "1", 0, -1, 1.1, 2**53, None):
                with self.assertRaises(ValidationError): self.inspect(**{key: invalid})
        for reason in ("free text", True, None):
            with self.assertRaises(ValidationError): self.inspect(reason=reason)
        # Retained investigations do not impersonate or require the original customer actor.
        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        self.assertEqual(self.inspect()["job"]["id"], self.job.pk)
        trial = OrganizationTrial.objects.get(organization=self.organization)
        for fields in ({"is_suspended": True}, {"is_suspended": True, "closed_at": timezone.now()}):
            with transaction.atomic():
                Organization.objects.filter(pk=self.organization.pk).update(**fields)
                with self.assertRaises(PermissionDenied): self.inspect()
                transaction.set_rollback(True)
        OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=timezone.now() - timedelta(days=121), ends_at=timezone.now() - timedelta(days=91))
        with self.assertRaises(PermissionDenied): self.inspect()

    def test_final_source_scope_permission_session_loss_and_audit_failure_roll_back(self):
        create = AuditEvent.objects.create
        for mutate, error in ((lambda: self.staff.user_permissions.clear(), PermissionDenied),
                (lambda: Session.objects.filter(session_key=self.request.session.session_key).delete(), PermissionDenied),
                (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), PermissionDenied),
                (lambda: JobRun.objects.filter(pk=self.job.pk).update(organization_id=self.other_org.pk), PermissionDenied),
                (lambda: JobRun.objects.filter(pk=self.job.pk).update(updated_at=timezone.now()), ValidationError),
                (lambda: JobStep.objects.filter(job=self.job, sequence=1).update(progress_percent=51), ValidationError)):
            self.request.session = self.client.session
            def changed(**kwargs):
                result = create(**kwargs); mutate(); return result
            with patch("jobs.staff_job_investigation.AuditEvent.objects.create", side_effect=changed), self.assertRaises(error): self.inspect()
            self.assertFalse(self.events().exists())
        self.request.session = self.client.session
        with patch("jobs.staff_job_investigation.AuditEvent.objects.create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.inspect()
        self.assertFalse(self.events().exists())
        # Initial permission denial precedes any source read.
        self.staff.user_permissions.clear()
        with patch("jobs.staff_job_investigation._projection", side_effect=AssertionError("source before authority")), self.assertRaises(PermissionDenied): self.inspect()

    def test_complete_bound_dates_status_validation_and_original_selection_reread(self):
        for fields in ({"created_at": timezone.now() + timedelta(seconds=1)},
                       {"updated_at": self.job.created_at - timedelta(microseconds=1)}):
            with transaction.atomic():
                JobRun.objects.filter(pk=self.job.pk).update(**fields)
                with self.assertRaises(ValidationError): self.inspect()
                transaction.set_rollback(True)
        JobStep.objects.filter(job=self.job, sequence=1).update(created_at=self.job.created_at - timedelta(microseconds=1))
        with self.assertRaises(ValidationError): self.inspect()
        JobStep.objects.filter(job=self.job, sequence=1).update(created_at=self.job.created_at)
        # Explicit synthetic cap fixture, not a claim of a real 100-stage producer.
        JobStep.objects.bulk_create([JobStep(job=self.job, sequence=seq, name="synthetic cap", status="running") for seq in range(3, 101)])
        self.assertEqual(len(self.inspect()["steps"]), 100)
        JobStep.objects.create(job=self.job, sequence=101, name="overflow", status="running")
        with self.assertRaises(ValidationError): self.inspect()
        JobStep.objects.filter(job=self.job, sequence=101).delete()
        original = staff.job_reference_row
        def changed(row, assessed):
            result = original(row, assessed)
            JobRun.objects.filter(pk=self.job.pk).update(updated_at=timezone.now())
            return result
        with patch("jobs.staff_job_investigation.job_reference_row", side_effect=changed), self.assertRaises(ValidationError): self.inspect()
