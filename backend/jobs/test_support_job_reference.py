from datetime import timedelta
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, Project
from . import support_job_reference as reference, tests as fixtures
from .models import JobRun, JobStatus
from .services import run_diagnostic, transition
from .usage import settle_usage


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES)
class SupportJobReferenceTests(TestCase):
    setUp = fixtures.JobFoundationTests.setUp
    queue = fixtures.JobFoundationTests.queue

    def inspect(self, job_id, **changes):
        return reference.retained_project_job_reference(**{**dict(project=self.project, actor=self.owner, job_id=job_id), **changes})

    def test_genuine_reference_minimizes_private_fields_and_never_writes_or_dispatches(self):
        job = run_diagnostic(self.queue())
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        # Privacy-only poison, not evidence of a source/provider/incident.
        private = "private-customer-secret-key"
        JobRun.objects.filter(pk=job.pk).update(error_category=private, dispatch_error=private,
            input_snapshot={"private": private}, config_snapshot={"secret": private}, output={"body": private})
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.services.dispatch_pending", side_effect=AssertionError("dispatch")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")):
            result = self.inspect(job.pk)
        self.assertEqual(result["job"], {"id": job.pk, "status": "succeeded", "created_at": job.created_at.isoformat(),
                                        "updated_at": job.updated_at.isoformat()})
        self.assertEqual(result["method_version"], reference.METHOD)
        self.assertEqual(result["state"], "retained_job_reference")
        for value in (private, self.owner.email, self.project.canonical_origin, "actor_id", "handler", "error_category", "output"):
            self.assertNotIn(value, json.dumps(result))
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries))
        self.assertFalse(any(field in q["sql"] for q in queries for field in (
            "input_snapshot", "config_snapshot", '"output"', "error_category", "dispatch_error", "jobs_artifact", "jobs_sourcecitation")))

    def test_genuine_statuses_missing_scope_and_permitted_retained_reader_not_original_actor(self):
        job = self.queue()
        for status in (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.WAITING_PROVIDER, JobStatus.FAILED):
            if status != job.status: job = transition(job, status)
            self.assertEqual(self.inspect(job.pk)["job"]["status"], status)
        settle_usage(job=job, actual_units=0)
        partial = run_diagnostic(self.queue(partial=True))
        self.assertEqual(self.inspect(partial.pk)["job"]["status"], "partially_succeeded")
        settle_usage(job=partial, actual_units=0)
        cancelled = transition(self.queue(), JobStatus.CANCELLED)
        self.assertEqual(self.inspect(cancelled.pk)["job"]["status"], "cancelled")
        self.assertEqual(self.inspect(job.pk, project=self.other_project, actor=self.outsider)["job"], None)
        missing = self.inspect(job.pk + 99999)
        self.assertEqual((missing["state"], missing["job"]), ("unavailable_no_retained_project_job", None))
        with self.assertRaises(PermissionDenied): self.inspect(job.pk, project=self.other_project)
        viewer = get_user_model().objects.create_user("support-viewer@example.invalid")
        OrganizationMembership.objects.create(organization=self.organization, user=viewer, role="viewer")
        retained = self.inspect(job.pk, actor=viewer)
        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
        trial = OrganizationTrial.objects.get(organization=self.organization)
        OrganizationTrial.objects.filter(pk=trial.pk).update(ends_at=trial.started_at + timedelta(microseconds=1))
        with override_settings(DEBUG=False):
            self.assertEqual(self.inspect(job.pk, actor=viewer), retained)
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        with self.assertRaises(PermissionDenied): self.inspect(job.pk, actor=viewer)

    def test_current_initial_final_reader_and_original_record_loss_denies(self):
        job = self.queue(); original = reference._row
        for change, error in ((lambda: OrganizationMembership.objects.filter(user=self.owner, organization=self.organization).delete(), PermissionDenied),
                (lambda: get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False), PermissionDenied),
                (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), PermissionDenied),
                (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now()), PermissionDenied),
                (lambda: JobRun.objects.filter(pk=job.pk).update(status="cancelled"), ValidationError),
                (lambda: JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now()), ValidationError),
                (lambda: JobRun.objects.filter(pk=job.pk).update(organization_id=self.other_org.pk), ValidationError)):
            with transaction.atomic():
                def mutate(row, assessed):
                    result = original(row, assessed); change(); return result
                with patch("jobs.support_job_reference._row", side_effect=mutate), self.assertRaises(error): self.inspect(job.pk)
                transaction.set_rollback(True)
        OrganizationMembership.objects.filter(user=self.owner, organization=self.organization).delete()
        with patch("jobs.support_job_reference._row", side_effect=AssertionError("source before reader")), self.assertRaises(PermissionDenied):
            self.inspect(job.pk)

    def test_exact_safe_identity_and_explicit_date_corruption_fail_closed(self):
        job = self.queue()
        for identity in (True, "1", 0, -1, 1.1, 2**53, None):
            with self.assertRaises(ValidationError): self.inspect(identity)
        for fields in ({"updated_at": job.created_at - timedelta(microseconds=1)},
                       {"created_at": timezone.now() + timedelta(seconds=1)}, {"updated_at": timezone.now() + timedelta(seconds=1)}):
            with transaction.atomic():
                JobRun.objects.filter(pk=job.pk).update(**fields)
                with self.assertRaises(ValidationError): self.inspect(job.pk)
                transaction.set_rollback(True)
        row = JobRun.objects.values("id", "status", "created_at", "updated_at").get(pk=job.pk)
        for fields in ({"id": True}, {"status": "private provider error"}, {"created_at": job.created_at.replace(tzinfo=None)}):
            with self.assertRaises(ValidationError): reference._row({**row, **fields}, timezone.now())
