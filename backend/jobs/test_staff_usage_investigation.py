import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import AuditEvent, AuditEventType, Organization, OrganizationTrial
from . import staff_usage_investigation as staff, test_staff_job_investigation as fixtures
from .models import JobRun, UsageReservation
from .services import create_job
from .usage import reserve_usage, settle_usage


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES)
class StaffUsageInvestigationTests(TestCase):
    queue = fixtures.StaffJobInvestigationTests.queue

    def setUp(self):
        fixtures.StaffJobInvestigationTests.setUp(self)
        self.staff.user_permissions.clear()
        self.staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="jobs",
            codename__in=["view_jobrun", "view_usagereservation"]))

    def inspect(self, **changes):
        return staff.inspect_staff_usage(**{**dict(request=self.request, organization_id=self.organization.pk,
            project_id=self.project.pk, job_id=self.job.pk, reason="investigation"), **changes})

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_USAGE_INSPECTED)

    def test_genuine_reserve_settle_release_overshoot_missing_and_no_cost_or_charge_inference(self):
        self.assertEqual(self.inspect()["reservation"]["state"], "released")
        job = create_job(project=self.project, actor=self.owner, handler="diagnostic_probe",
                         input_snapshot={"sample": "safe diagnostic", "simulate_partial": False})
        missing = self.inspect(job_id=job.pk)
        self.assertEqual((missing["state"], missing["reservation"]), ("unavailable_no_retained_reservation", None))
        reserve_usage(job=job, provider="synthetic", units=1)
        reserved = self.inspect(job_id=job.pk)["reservation"]
        self.assertEqual((reserved["state"], reserved["reserved_units"], reserved["actual_units"], reserved["settled_at"]),
                         ("reserved", 1, 0, None))
        settle_usage(job=job, actual_units=2)
        settled = self.inspect(job_id=job.pk)["reservation"]
        self.assertEqual((settled["state"], settled["reserved_units"], settled["actual_units"]), ("settled", 1, 2))
        self.assertEqual(len(settled), 7)
        self.assertEqual(settled["unit_meaning"], "internal_units_not_provider_tokens_currency_or_customer_charges")
        self.assertEqual(settle_usage(job=job, actual_units=2).actual_units, 2)
        for event in self.events():
            self.assertEqual((event.organization_id, event.project_id, event.actor_id), (self.organization.pk, self.project.pk, self.staff.pk))
            self.assertEqual(set(event.details), {"job_id", "reason", "state"})

    def test_scalar_privacy_no_usage_mutation_work_network_or_ai_provider_lookup(self):
        private = "private-customer-secret-value"
        JobRun.objects.filter(pk=self.job.pk).update(output={"body": private}, input_snapshot={"secret": private}, error_category=private)
        UsageReservation.objects.filter(job=self.job).update(provider="private_provider_marker")
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.usage.reconcile_usage", side_effect=AssertionError("reconcile")), \
                patch("jobs.usage.settle_usage", side_effect=AssertionError("settle")):
            result = self.inspect()
        for poison in (private, "private_provider_marker", self.owner.email, self.project.canonical_origin, "estimated_cost", '"provider":', "error_category"):
            self.assertNotIn(poison, json.dumps(result)); self.assertNotIn(poison, json.dumps(self.events().get().details))
        self.assertFalse(any(field in query["sql"] for query in queries for field in (
            "input_snapshot", "config_snapshot", '"output"', "error_category", '"provider"', "jobs_aiusagerecord", "providers_")))
        writes = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(len(writes), 1); self.assertIn("tenancy_auditevent", writes[0])

    def test_separate_permission_scope_and_after_audit_session_scope_original_loss_roll_back(self):
        for changes in ({"organization_id": self.other_org.pk}, {"project_id": self.other_project.pk}, {"job_id": self.job.pk + 99999}):
            with self.assertRaises(PermissionDenied): self.inspect(**changes)
        for changes in ({"job_id": True}, {"organization_id": 0}, {"project_id": 2**53}, {"reason": "private free text"}):
            with self.assertRaises(ValidationError): self.inspect(**changes)
        usage_permission = Permission.objects.get(content_type__app_label="jobs", codename="view_usagereservation")
        self.staff.user_permissions.remove(usage_permission)
        with patch("jobs.staff_usage_investigation._projection", side_effect=AssertionError("source before permission")), self.assertRaises(PermissionDenied): self.inspect()
        self.staff.user_permissions.add(usage_permission)
        create = AuditEvent.objects.create
        for mutate, error in ((lambda: self.staff.user_permissions.clear(), PermissionDenied),
                (lambda: Session.objects.filter(session_key=self.request.session.session_key).delete(), PermissionDenied),
                (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), PermissionDenied),
                (lambda: UsageReservation.objects.filter(job=self.job).update(organization_id=self.other_org.pk), ValidationError),
                (lambda: UsageReservation.objects.filter(job=self.job).update(reserved_units=1), ValidationError)):
            self.request.session = self.client.session
            def changed(**kwargs):
                result = create(**kwargs); mutate(); return result
            with patch("jobs.staff_usage_investigation.AuditEvent.objects.create", side_effect=changed), self.assertRaises(error): self.inspect()
            self.assertFalse(self.events().exists())
        self.request.session = self.client.session
        with patch("jobs.staff_usage_investigation.AuditEvent.objects.create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.inspect()
        self.assertFalse(self.events().exists())

    def test_original_selection_date_period_settlement_corruption_is_unavailable(self):
        row = UsageReservation.objects.filter(job=self.job).values(*staff.FIELDS).get()
        job = JobRun.objects.filter(pk=self.job.pk).values(*staff.JOB_FIELDS).get()
        for fields in ({"state": "private error"}, {"actual_units": True}, {"reserved_units": -1},
                {"period_start": row["period_start"] + timedelta(days=1)},
                {"period_start": timezone.now().date().replace(day=1) + timedelta(days=62)},
                {"created_at": job["created_at"] - timedelta(microseconds=1)},
                {"settled_at": row["created_at"] - timedelta(microseconds=1)},
                {"settled_at": timezone.now() + timedelta(seconds=1)}, {"settled_at": None},
                {"created_at": row["created_at"].replace(tzinfo=None)}, {"actual_units": 1}, {"organization_id": self.other_org.pk}):
            with self.assertRaises(ValidationError): staff._reservation({**row, **fields}, job, timezone.now())
        original = staff._reservation
        def changed(row, job, assessed):
            result = original(row, job, assessed)
            UsageReservation.objects.filter(pk=row["id"]).update(reserved_units=1)
            return result
        with patch("jobs.staff_usage_investigation._reservation", side_effect=changed), self.assertRaises(ValidationError): self.inspect()
        self.assertFalse(self.events().exists())

    def test_retained_accounting_is_independent_of_current_costly_access_but_closed_or_expired_scope_denies(self):
        now = timezone.now()
        trial = OrganizationTrial.objects.get(organization=self.organization)
        OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=now - timedelta(days=31), ends_at=now - timedelta(days=1))
        self.assertEqual(self.inspect()["reservation"]["state"], "released")
        with transaction.atomic():
            Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
            with self.assertRaises(PermissionDenied): self.inspect()
            transaction.set_rollback(True)
        OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): self.inspect()
