from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
import json
import os
from threading import Barrier
from unittest.mock import patch
from zipfile import ZipFile

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from providers.adapters import ProviderResponse
from providers.models import AIModel, AIProviderAccount
from providers.services import revoke_provider_account
from tenancy.models import MembershipRole, Organization, OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import test_visibility_collection as fixtures
from .models import JobRun, JobSchedule, JobStatus, JobStep
from .recovery import reconcile_stuck_visibility_samples
from .services import cancel_job, dispatch_pending, queue_job
from .visibility_collection import execute_visibility_sample, queue_visibility_sample
from .visibility_schedule import (create_visibility_schedule, run_due_visibility_schedules, schedule_denial,
                                  set_visibility_schedule_enabled)


@override_settings(STORAGES=TEST_STORAGES, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class VisibilityScheduleTests(TransactionTestCase):
    fixture_project = fixtures.VisibilityCollectionTests.fixture_project

    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        fixtures.fixture(self)
        self.created = timezone.now()
        self.options = {"project": self.project, "actor": self.owner, "sample": self.sample_data,
            "interval_minutes": 1440, "max_occurrences": 2, "lifetime_days": 7, "total_max_cost_usd": "0.02",
            "acknowledge_repeat_data_use": True, "idempotency_key": "repeat-fixture-1"}

    def create(self, **changes):
        with patch("jobs.visibility_schedule.timezone.now", return_value=self.created):
            return create_visibility_schedule(**{**self.options, **changes})

    def enable(self, schedule, **changes):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key"}), patch("jobs.visibility_schedule.timezone.now", return_value=self.created):
            return set_visibility_schedule_enabled(**{**dict(project=self.project, actor=self.owner, schedule_id=schedule.pk,
                enabled=True, acknowledge_repeat_data_use=True), **changes})

    def due(self, now):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key"}), patch("jobs.visibility_schedule.timezone.now", return_value=now), patch("jobs.services.dispatch_pending"):
            return run_due_visibility_schedules(now=now)

    def execute(self, job, now, request=None):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key"}), patch("jobs.visibility_schedule.timezone.now", return_value=now):
            return execute_visibility_sample(job.pk, request=request or (lambda **_: ProviderResponse(
                " Exact synthetic repeat answer <script>text</script> ", None, (), "req_fixture", "resp_fixture", 3, 2)))

    def test_paused_first_frozen_explicit_enable_and_total_bounds(self):
        schedule = self.create()
        self.assertFalse(schedule.enabled)
        self.assertEqual(self.create().pk, schedule.pk)
        self.assertFalse(schedule.input_snapshot["selection"]["visibility"]["policy"]["automatic_schedule"])
        self.assertEqual(self.due(self.created + timedelta(days=1)), 0)
        for changes in ({"interval_minutes": 1439}, {"max_occurrences": True}, {"max_occurrences": 31},
            {"lifetime_days": 31}, {"total_max_cost_usd": "0.019"}, {"acknowledge_repeat_data_use": False},
            {"actor": self.other}, {"sample": {**self.sample_data, "prompt_set_id": self.prompt_set.pk + 9999}}):
            with self.subTest(changes=changes), self.assertRaises((PermissionDenied, ValidationError)):
                self.create(**changes)
        with self.assertRaises(ValidationError): self.create(idempotency_key="repeat-other-key")
        with self.assertRaises(ValidationError): self.enable(schedule, acknowledge_repeat_data_use=False)
        schedule = self.enable(schedule)
        first_due = schedule.next_run_at
        self.assertEqual(self.enable(schedule).next_run_at, first_due)
        schedule.input_snapshot["policy"]["max_occurrences"] = 3
        with self.assertRaises(ValidationError): schedule.save()
        OrganizationMembership.objects.create(organization=self.project.organization, user=self.other, role=MembershipRole.MEMBER)
        with self.assertRaises(PermissionDenied): self.enable(schedule, actor=self.other)

    def test_missed_collapse_shared_manual_cooldown_exhaustion_and_once_only_usage(self):
        schedule = self.enable(self.create())
        now = self.created + timedelta(days=3, seconds=1)
        self.assertEqual(self.due(now), 1)
        self.assertEqual(self.due(now), 0)
        schedule.refresh_from_db()
        self.assertEqual((schedule.runs.count(), schedule.skipped_occurrences), (1, 2))
        first = schedule.runs.get()
        with patch("jobs.tasks.execute_visibility_sample_task.apply_async") as send, patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key"}):
            self.assertTrue(dispatch_pending(first.pk))
            self.assertEqual(send.call_args.kwargs["queue"], "ai")
        self.execute(first, now)
        first.refresh_from_db(); self.assertEqual((first.status, first.usage.actual_units), ("succeeded", 1))
        with patch("jobs.visibility_schedule.timezone.now", return_value=now), patch("jobs.services.dispatch_pending"), self.assertRaises(ValidationError):
            queue_visibility_sample(project=self.project, actor=self.owner, data=self.sample_data, idempotency_key="manual-during-cooldown")
        second_at = now + timedelta(days=1)
        self.assertEqual(self.due(second_at), 1)
        second = schedule.runs.order_by("-pk").first()
        self.assertEqual(self.due(second_at + timedelta(days=1)), 0)
        schedule.refresh_from_db(); self.assertTrue(schedule.enabled)  # Final pending occurrence is not canceled by exhaustion.
        self.execute(second, second_at)
        schedule.refresh_from_db(); self.assertEqual((schedule.enabled, schedule.last_error_category), (False, "repeat_exhausted"))
        self.assertFalse(self.execute(second, second_at, lambda **_: self.fail("paid replay")))
        self.assertEqual(sum(job.usage.actual_units for job in schedule.runs.all()), 2)
        with self.assertRaises(ValidationError): self.enable(schedule)

    def test_manual_attempt_skips_repeat_slot_and_pause_does_not_renew(self):
        schedule = self.enable(self.create())
        now = self.created + timedelta(hours=23)
        with patch("jobs.visibility_schedule.timezone.now", return_value=now), patch("jobs.services.dispatch_pending"):
            job = queue_visibility_sample(project=self.project, actor=self.owner, data=self.sample_data, idempotency_key="manual-first")
        self.execute(job, now)
        self.assertEqual(self.due(self.created + timedelta(days=1)), 0)
        schedule.refresh_from_db(); self.assertEqual((schedule.last_error_category, schedule.skipped_occurrences), ("sample_repeat_cooldown", 1))
        paused = self.enable(schedule, enabled=False, acknowledge_repeat_data_use=False)
        deadline = paused.input_snapshot["expires_at"]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key"}), patch("jobs.visibility_schedule.timezone.now", return_value=self.created + timedelta(days=6)):
            with self.assertRaises(ValidationError):
                set_visibility_schedule_enabled(project=self.project, actor=self.owner, schedule_id=paused.pk, enabled=True,
                                                acknowledge_repeat_data_use=True)
        paused.refresh_from_db(); self.assertEqual(paused.input_snapshot["expires_at"], deadline)

    def test_unknown_recovery_pause_and_no_replay(self):
        schedule = self.enable(self.create())
        now = self.created + timedelta(days=1)
        self.assertEqual(self.due(now), 1)
        job = schedule.runs.get()
        JobRun.objects.filter(pk=job.pk).update(status=JobStatus.RUNNING, updated_at=now - timedelta(minutes=3))
        JobStep.objects.create(job=job, sequence=1, name="Request selected model", status="running")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key"}), patch("jobs.visibility_schedule.timezone.now", return_value=now):
            self.assertEqual(reconcile_stuck_visibility_samples(), 1)
        job.refresh_from_db(); schedule.refresh_from_db()
        self.assertEqual((job.usage.actual_units, job.ai_usage_record.status, schedule.enabled), (1, "unknown", False))
        self.assertEqual(self.due(now + timedelta(days=1)), 0)
        self.assertFalse(self.execute(job, now, lambda **_: self.fail("unknown replay")))

    def test_current_source_role_key_model_commercial_and_fixed_expiry_pause(self):
        for reason in ("source", "role", "key", "model", "commercial", "expiry"):
            with self.subTest(reason=reason), transaction_rollback():
                schedule = self.enable(self.create())
                now = self.created + timedelta(days=1)
                if reason == "source": ProjectConfiguration.objects.filter(project=self.project).update(seed_topics=[])
                if reason == "role": OrganizationMembership.objects.filter(user=self.owner, organization=self.project.organization).update(role=MembershipRole.MEMBER)
                if reason == "key": revoke_provider_account(actor=self.operator, account=self.account)
                if reason == "model": AIModel.objects.filter(pk=self.model.pk).update(enabled=False)
                if reason == "commercial": OrganizationTrial.objects.filter(organization=self.project.organization).update(ends_at=self.created)
                if reason == "expiry": now = self.created + timedelta(days=7)
                self.assertEqual(self.due(now), 0)
                schedule.refresh_from_db(); self.assertFalse(schedule.enabled)
                self.assertFalse(schedule.runs.exists())

    def test_pause_dispatch_inflight_loss_and_cancel_keep_actual_usage(self):
        schedule = self.enable(self.create())
        now = self.created + timedelta(days=1)
        self.due(now); job = schedule.runs.get()
        self.enable(schedule, enabled=False, acknowledge_repeat_data_use=False)
        with patch("jobs.tasks.execute_visibility_sample_task.apply_async") as send:
            self.assertFalse(dispatch_pending(job.pk)); send.assert_not_called()
        job.refresh_from_db(); self.assertEqual((job.status, job.usage.actual_units), ("cancelled", 0))
        schedule = self.enable(schedule)
        later = now + timedelta(days=1)
        self.due(later); second = schedule.runs.order_by("-pk").first()
        def request(**_):
            cancel_job(job=second, actor=self.owner)
            return ProviderResponse("Private after cancel", None, (), "req_fixture", "resp_fixture", 2, 1)
        self.execute(second, later, request)
        second.refresh_from_db(); schedule.refresh_from_db()
        self.assertEqual((second.status, second.usage.actual_units, second.output["collection_eligible"], schedule.enabled), ("cancelled", 1, False, False))

    def test_direct_foreign_unlinked_and_changed_selection_reject_before_dispatch(self):
        schedule = self.enable(self.create())
        now = self.created + timedelta(days=1)
        with patch("jobs.visibility_schedule.timezone.now", return_value=now), patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key"}):
            for changes in ({"actor": self.other}, {"scheduled_for": now - timedelta(seconds=1)},
                {"config_snapshot": {}}, {"input_snapshot": {**self.sample_data, "max_output_tokens": 99}}):
                with self.subTest(changes=changes), self.assertRaises((PermissionDenied, ValidationError)):
                    queue_job(**{**dict(project=self.project, actor=self.owner, handler="sample_ai_visibility",
                        input_snapshot=self.sample_data, config_snapshot=schedule.input_snapshot["selection"],
                        schedule=schedule, scheduled_for=schedule.next_run_at, idempotency_key="direct-invalid"), **changes})
        self.assertFalse(JobRun.objects.exists())

    def test_schedule_and_answers_export_closure_and_deletion(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        schedule = self.enable(self.create())
        now = self.created + timedelta(days=1); self.due(now)
        self.execute(schedule.runs.get(), now)
        archive = complete_bounded_customer_archive(organization=self.project.organization, actor=self.owner)
        with ZipFile(BytesIO(archive)) as zipped:
            rows = json.loads(zipped.read("records/jobs/JobSchedule.json"))
        self.assertEqual(rows[0]["input_snapshot"]["policy"]["method"], "visibility-repeat-schedule-v1")
        Organization.objects.filter(pk=self.project.organization_id).update(is_suspended=True, closed_at=timezone.now())
        self.assertEqual(self.due(now + timedelta(days=1)), 0)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.project.organization))
        delete_customer_database_records(run=run)
        self.assertFalse(JobSchedule.objects.filter(pk=schedule.pk).exists())

    def test_private_api_csrf_scoped_request_lookup_roles_strict_json_and_commands(self):
        path = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/visibility-schedules/"
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.get(path).status_code, 401)
        browser.force_login(self.other); self.assertEqual(browser.get(path).status_code, 404)
        browser.force_login(self.owner)
        data = {key: value for key, value in self.options.items() if key not in {"project", "actor"}}
        self.assertEqual(browser.post(path, json.dumps(data), content_type="application/json").status_code, 403)
        browser.get("/_allauth/browser/v1/auth/session", secure=True)
        headers = {"secure": True, "HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value, "HTTP_REFERER": "https://testserver/"}
        def post(body, target=path):
            return browser.post(target, json.dumps(body), content_type="application/json", **headers)
        result = post(data)
        self.assertEqual(result.status_code, 201, result.content)
        row = result.json()["schedule"]
        self.assertFalse(row["enabled"]); self.assertEqual(row["queued_occurrences"], 0)
        self.assertEqual(post(data).json()["schedule"]["id"], row["id"])
        self.assertEqual(browser.get(path, {"request_key": data["idempotency_key"]}).json()["lookup"], "found")
        self.assertEqual(browser.get(path, {"request_key": "repeat-unknown"}).json()["lookup"], "not_found")
        self.assertEqual(browser.get(path, {"request_key": "x"}).status_code, 400)
        self.assertEqual(browser.get(path)["Cache-Control"], "private, no-store")
        detail = path + str(row["id"]) + "/"
        self.assertEqual(post({"enabled": True, "acknowledge_repeat_data_use": False}, detail).status_code, 409)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key"}):
            self.assertTrue(post({"enabled": True, "acknowledge_repeat_data_use": True}, detail).json()["schedule"]["enabled"])
        self.assertFalse(post({"enabled": False, "acknowledge_repeat_data_use": False}, detail).json()["schedule"]["enabled"])
        for body in ('{"enabled":false,"enabled":true,"acknowledge_repeat_data_use":true}',
                     '{"enabled":NaN,"acknowledge_repeat_data_use":true}', ' ' * 8193):
            self.assertEqual(browser.post(detail, body, content_type="application/json", **headers).status_code, 409)
        OrganizationMembership.objects.create(organization=self.project.organization, user=self.other, role=MembershipRole.VIEWER)
        browser.force_login(self.other); browser.get("/_allauth/browser/v1/auth/session", secure=True)
        headers["HTTP_X_CSRFTOKEN"] = browser.cookies["csrftoken"].value
        self.assertEqual(browser.get(detail).status_code, 200)
        self.assertEqual(post(data).status_code, 403)
        self.assertEqual(browser.get(path + "999999/").status_code, 404)

    def test_repeat_policy_separates_manual_history_and_rate_denominators(self):
        from .visibility_entities import sample_rates
        from .visibility_history import observation_history
        schedule = self.enable(self.create(max_occurrences=1))
        now = self.created + timedelta(days=1)
        self.due(now); scheduled = schedule.runs.get(); self.execute(scheduled, now)
        later = now + timedelta(hours=25)
        with patch("jobs.visibility_schedule.timezone.now", return_value=later), patch("jobs.services.dispatch_pending"):
            manual = queue_visibility_sample(project=self.project, actor=self.owner, data=self.sample_data, idempotency_key="manual-later")
        self.execute(manual, later)
        history = observation_history(project=self.project, actor=self.owner)
        self.assertEqual(len(history["comparison_groups"]), 2)
        self.assertEqual(history["observations"][1]["schedule_id"], schedule.pk)
        groups = sample_rates(project=self.project, actor=self.owner, prompt_set_id=self.prompt_set.pk)["groups"]
        self.assertEqual(len(groups), 2)
        self.assertEqual({group["repeat_policy"]["method"] if group["repeat_policy"] else "manual" for group in groups},
                         {"manual", "visibility-repeat-schedule-v1"})

    @override_settings(DEBUG=False)
    def test_production_beat_uses_explicit_repeat_path_not_debug_diagnostic(self):
        from .tasks import schedule_due_task
        schedule = self.enable(self.create())
        now = self.created + timedelta(days=1)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key"}), patch("jobs.visibility_schedule.timezone.now", return_value=now), patch("jobs.services.dispatch_pending"):
            self.assertEqual(schedule_due_task(), 1)
        self.assertEqual(schedule.runs.count(), 1)
        self.assertFalse(JobRun.objects.filter(handler="diagnostic_probe").exists())

    def test_missing_key_price_rotation_and_inflight_role_loss_pause(self):
        schedule = self.create()
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with self.assertRaises(ValidationError):
                set_visibility_schedule_enabled(project=self.project, actor=self.owner, schedule_id=schedule.pk,
                    enabled=True, acknowledge_repeat_data_use=True)
        schedule = self.enable(schedule); now = self.created + timedelta(days=1)
        self.due(now); job = schedule.runs.get()
        def request(**_):
            OrganizationMembership.objects.filter(user=self.owner, organization=self.project.organization).update(role=MembershipRole.MEMBER)
            return ProviderResponse("Exact private answer after creator demotion", None, (), "req_fixture", "resp_fixture", 3, 2)
        self.execute(job, now, request)
        job.refresh_from_db(); schedule.refresh_from_db()
        self.assertEqual((job.status, job.usage.actual_units, job.output["collection_eligible"], schedule.enabled), ("cancelled", 1, False, False))
        OrganizationMembership.objects.filter(user=self.owner, organization=self.project.organization).update(role=MembershipRole.OWNER)
        AIModel.objects.filter(pk=self.model.pk).update(input_price_usd_per_million="0.126")
        with self.assertRaises(ValidationError): self.enable(schedule)


# Savepoint rollback isolates destructive predicate variants without extra customer fixtures.
from contextlib import contextmanager
from django.db import transaction

@contextmanager
def transaction_rollback():
    with transaction.atomic():
        try:
            yield
        finally:
            transaction.set_rollback(True)


@override_settings(STORAGES=TEST_STORAGES)
class VisibilityScheduleConcurrencyTests(TransactionTestCase):
    fixture_project = fixtures.VisibilityCollectionTests.fixture_project

    def setUp(self):
        fixtures.fixture(self)

    def test_duplicate_due_selectors_create_one_reserved_occurrence(self):
        schedule = create_visibility_schedule(project=self.project, actor=self.owner, sample=self.sample_data,
            interval_minutes=1440, max_occurrences=2, lifetime_days=7, total_max_cost_usd="0.02",
            acknowledge_repeat_data_use=True, idempotency_key="repeat-race")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key"}):
            schedule = set_visibility_schedule_enabled(project=self.project, actor=self.owner, schedule_id=schedule.pk,
                enabled=True, acknowledge_repeat_data_use=True)
        now = schedule.next_run_at + timedelta(seconds=1)
        barrier = Barrier(2)
        def due():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return run_due_visibility_schedules(now=now)
            finally:
                close_old_connections()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key"}), patch("jobs.visibility_schedule.timezone.now", return_value=now), patch("jobs.services.dispatch_pending"), ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(due) for _ in range(2)]
            self.assertEqual(sorted(item.result(timeout=40) for item in results), [0, 1])
        self.assertEqual(schedule.runs.count(), 1)
        self.assertEqual(schedule.runs.get().usage.reserved_units, 1)
