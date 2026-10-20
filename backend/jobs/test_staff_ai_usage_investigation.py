import json
import os
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.mfa.models import Authenticator
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from providers.adapters import ProviderRequestError, ProviderResponse
from providers.models import AIModel
from providers.services import create_provider_account, revoke_provider_account
from tenancy.models import AuditEvent, AuditEventType, Organization, OrganizationTrial
from tenancy.services import create_organization, create_project
from . import staff_ai_usage_investigation as staff, test_ai_text as fixtures
from .ai_text import execute_ai_text
from .ai_usage import record_ai_attempt
from .models import AIUsageRecord, JobRun, JobStep
from .recovery import reconcile_stuck_ai_text


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES)
class StaffAIUsageInvestigationTests(TestCase):
    queue = fixtures.AITextJobTests.queue

    def setUp(self):
        fixtures.AITextJobTests.setUp(self)
        self.staff = get_user_model().objects.create_user("ai-staff@example.invalid", password="fixture-password", is_staff=True)
        self.staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="jobs",
            codename__in=["view_jobrun", "view_aiusagerecord"]))
        self.client.force_login(self.staff)
        Authenticator.objects.create(user=self.staff, type=Authenticator.Type.TOTP, data={"secret": "unused-fixture"})
        session = self.client.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa", "at": timezone.now().timestamp()}]; session.save()
        self.request = RequestFactory().post("/admin/jobs/jobrun/scoped/")
        self.request.user, self.request.session = self.staff, self.client.session
        other_owner = get_user_model().objects.create_user("other-ai-owner@example.invalid", password="fixture-password")
        EmailAddress.objects.create(user=other_owner, email=other_owner.email, primary=True, verified=True)
        self.other_org = create_organization(user=other_owner, name="Other fixture organization")
        self.other_project = create_project(organization=self.other_org, user=other_owner,
            name="Other fixture project", canonical_origin="https://other-fixture.example.invalid")
        self.job = self.queue()
        self.execute(self.job)

    def execute(self, job, request=None):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-secret"}):
            self.assertTrue(execute_ai_text(job.pk, request=request or (lambda **_: ProviderResponse(
                "Private result", None, (), "req_safe", "resp_safe", 12, 5))))

    def inspect(self, **changes):
        return staff.inspect_staff_ai_usage(**{**dict(request=self.request, organization_id=self.organization.pk,
            project_id=self.project.pk, job_id=self.job.pk, reason="investigation"), **changes})

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_AI_USAGE_INSPECTED)

    def test_genuine_success_refusal_missing_tokens_and_original_estimate_not_current_price(self):
        observation = self.inspect()["observation"]
        self.assertEqual(len(observation), 8)
        self.assertEqual((observation["status"], observation["input_tokens"], observation["output_tokens"],
            observation["estimated_cost_usd"], observation["reported_cost_usd"]), ("completed", 12, 5, "0.000014", None))
        AIModel.objects.filter(pk=self.model.pk).update(input_price_usd_per_million=Decimal("9.0000"))
        self.assertEqual(self.inspect()["observation"], observation)
        AIModel.objects.filter(pk=self.model.pk).update(input_price_usd_per_million=Decimal("0.1250"))
        refused = self.queue(idempotency_key="refusal")
        def refusal(**_): raise ProviderRequestError("refused", request_id="req_safe", input_tokens=10, output_tokens=1)
        self.execute(refused, refusal)
        failed = self.inspect(job_id=refused.pk)["observation"]
        self.assertEqual((failed["status"], failed["input_tokens"], failed["output_tokens"], failed["reported_cost_usd"]), ("failed", 10, 1, None))
        missing = self.queue(idempotency_key="missing-tokens")
        self.execute(missing, lambda **_: ProviderResponse("Private result", None, (), "req_safe", "resp_safe", None, None))
        result = self.inspect(job_id=missing.pk)["observation"]
        self.assertEqual((result["input_tokens"], result["output_tokens"], result["estimated_cost_usd"], result["reported_cost_usd"]), (None, None, None, None))
        for event in self.events():
            self.assertEqual((event.organization_id, event.project_id, event.actor_id), (self.organization.pk, self.project.pk, self.staff.pk))
            self.assertEqual(set(event.details), {"job_id", "reason", "state"})

    def test_genuine_unknown_revocation_and_explicit_pending_reported_value_semantics(self):
        missing = self.queue(idempotency_key="no-attempt")
        self.assertIsNone(self.inspect(job_id=missing.pk)["observation"])
        self.assertEqual(self.inspect(job_id=missing.pk)["state"], "unavailable_no_retained_ai_observation")
        # Explicit producer-based pending fixture; no actual provider request is made.
        JobRun.objects.filter(pk=missing.pk).update(status="running", created_at=timezone.now() - timedelta(minutes=4),
            updated_at=timezone.now() - timedelta(minutes=3))
        missing.refresh_from_db()
        step = JobStep.objects.create(job=missing, sequence=1, name="Fixture pending request", status="running", output={"state": "attempted"})
        record_ai_attempt(job=missing, step=step)
        pending = self.inspect(job_id=missing.pk)["observation"]
        self.assertEqual((pending["status"], pending["finished_at"], pending["estimated_cost_usd"]), ("attempted", None, None))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dummy-secret"}): self.assertEqual(reconcile_stuck_ai_text(), 1)
        self.assertEqual(self.inspect(job_id=missing.pk)["observation"]["status"], "unknown")
        revoked = self.queue(idempotency_key="revoked")
        def revocation(**_):
            revoke_provider_account(actor=self.operator, account=self.account)
            return ProviderResponse("Private discarded result", None, (), "req_safe", "resp_safe", 3, 2)
        self.execute(revoked, revocation)
        result = self.inspect(job_id=revoked.pk)
        self.assertEqual((result["job"]["status"], result["observation"]["status"]), ("cancelled", "completed"))
        # Explicit synthetic reported-value/zero fixture; current producers never populate reported USD.
        AIUsageRecord.objects.filter(job=self.job).update(reported_cost_usd=Decimal("0.000000"), input_tokens=0)
        self.assertEqual((self.inspect()["observation"]["reported_cost_usd"], self.inspect()["observation"]["input_tokens"]), ("0.000000", 0))

    def test_scalar_privacy_only_audit_write_no_provider_settings_or_work_network(self):
        poison = "private-secret-customer-marker"
        JobRun.objects.filter(pk=self.job.pk).update(input_snapshot={"private": poison}, config_snapshot={"private": poison}, output={"body": poison}, error_category=poison)
        JobStep.objects.filter(job=self.job).update(name=poison, output={"body": poison}, error_category=poison)
        AIUsageRecord.objects.filter(job=self.job).update(error_category=poison, provider_request_id=poison, provider_response_id=poison)
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.services.dispatch_pending", side_effect=AssertionError("dispatch")), \
                patch("jobs.usage.settle_usage", side_effect=AssertionError("settle")):
            result = self.inspect()
        for value in (poison, self.owner.email, self.project.canonical_origin, '"account_id"', '"model_id"', '"provider_id"'):
            self.assertNotIn(value, json.dumps(result)); self.assertNotIn(value, json.dumps(self.events().get().details))
        self.assertFalse(any(field in query["sql"] for query in queries for field in (
            "input_snapshot", "config_snapshot", '"output"', "error_category", "provider_request_id", "provider_response_id",
            "secret_reference", "encrypted_secret", "price_usd", '"name"', '"label"', "jobs_usagereservation")))
        writes = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(len(writes), 1); self.assertIn("tenancy_auditevent", writes[0])

    def test_separate_permissions_scope_initial_final_session_hidden_source_loss_audit_rollback(self):
        for changes in ({"organization_id": self.other_org.pk}, {"project_id": self.other_project.pk}, {"job_id": self.job.pk + 99999}):
            with self.assertRaises(PermissionDenied): self.inspect(**changes)
        for changes in ({"job_id": True}, {"organization_id": 0}, {"project_id": 2**53}, {"reason": "private free text"}):
            with self.assertRaises(ValidationError): self.inspect(**changes)
        permission = Permission.objects.get(content_type__app_label="jobs", codename="view_aiusagerecord")
        self.staff.user_permissions.remove(permission)
        with patch("jobs.staff_ai_usage_investigation._projection", side_effect=AssertionError("source before permission")), self.assertRaises(PermissionDenied): self.inspect()
        self.staff.user_permissions.add(permission)
        alternate = create_provider_account(actor=self.operator, provider=self.provider, label="Other fixture account", secret_reference="env:OPENAI_API_KEY")
        create = AuditEvent.objects.create
        for mutate, error in ((lambda: self.staff.user_permissions.clear(), PermissionDenied),
                (lambda: Session.objects.filter(session_key=self.request.session.session_key).delete(), PermissionDenied),
                (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), PermissionDenied),
                (lambda: AIUsageRecord.objects.filter(job=self.job).update(organization_id=self.other_org.pk), ValidationError),
                (lambda: AIUsageRecord.objects.filter(job=self.job).update(account_id=alternate.pk), ValidationError),
                (lambda: AIUsageRecord.objects.filter(job=self.job).update(input_tokens=13), ValidationError)):
            self.request.session = self.client.session
            def changed(**kwargs):
                result = create(**kwargs); mutate(); return result
            with patch("jobs.staff_ai_usage_investigation.AuditEvent.objects.create", side_effect=changed), self.assertRaises(error): self.inspect()
            self.assertFalse(self.events().exists())
        self.request.session = self.client.session
        with patch("jobs.staff_ai_usage_investigation.AuditEvent.objects.create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.inspect()
        self.assertFalse(self.events().exists())

    def test_original_binding_numeric_date_currency_corruption_and_selection_reread(self):
        row = AIUsageRecord.objects.filter(job=self.job).values(*staff.FIELDS).get()
        job = JobRun.objects.filter(pk=self.job.pk).values(*staff.AI_JOB_FIELDS).get()
        for fields in ({"status": "private error"}, {"input_tokens": True}, {"output_tokens": 100_000_001}, {"duration_ms": 120_001},
                {"operation_version": "other"}, {"step__job_id": self.job.pk + 1}, {"step__sequence": 2},
                {"model__provider_id": self.provider.pk + 1}, {"account__provider_id": self.provider.pk + 1},
                {"account__organization_id": self.other_org.pk}, {"organization_id": self.other_org.pk},
                {"attempted_at": job["created_at"] - timedelta(microseconds=1)}, {"attempted_at": row["attempted_at"].replace(tzinfo=None)},
                {"finished_at": None}, {"finished_at": row["attempted_at"] - timedelta(microseconds=1)},
                {"finished_at": timezone.now() + timedelta(seconds=1)}, {"estimated_cost_usd": Decimal("-0.000001")},
                {"reported_cost_usd": Decimal("NaN")}, {"reported_cost_usd": Decimal("1000000")}, {"reported_cost_usd": Decimal("0.0000001")}):
            with self.assertRaises(ValidationError): staff._observation({**row, **fields}, job, timezone.now())
        original = staff._observation
        def changed(row, job, assessed):
            result = original(row, job, assessed)
            AIUsageRecord.objects.filter(pk=row["id"]).update(input_tokens=13)
            return result
        with patch("jobs.staff_ai_usage_investigation._observation", side_effect=changed), self.assertRaises(ValidationError): self.inspect()
        self.assertFalse(self.events().exists())

    def test_retained_observation_independent_of_current_costly_access_closed_expired_scope_denies(self):
        now = timezone.now()
        trial = OrganizationTrial.objects.get(organization=self.organization)
        OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=now - timedelta(days=31), ends_at=now - timedelta(days=1))
        self.assertEqual(self.inspect()["observation"]["status"], "completed")
        with transaction.atomic():
            Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
            with self.assertRaises(PermissionDenied): self.inspect()
            transaction.set_rollback(True)
        OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): self.inspect()
