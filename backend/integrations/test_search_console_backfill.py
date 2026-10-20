import json
from datetime import timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from jobs.models import JobRun, JobSchedule, JobStatus
from jobs.schedules import run_due_schedules, set_schedule_enabled
from jobs.usage import UsageLimitError
from tenancy.models import (MembershipRole, OrganizationMembership, OrganizationTrial,
                            PaddleSubscription, PaddleStatus, PaddleWebhookReceipt)
from tenancy.services import create_organization, create_project, update_project

from .google_tokens import GoogleTokens, SCOPE
from .models import GoogleOAuthGrant, SearchConsoleBackfill, SearchAnalyticsPageSnapshot, SyncCursor
from .search_console_backfill import advance_search_console_backfills, queue_search_console_backfill
from .search_console_sync import execute_search_console_sync
from .search_console_schedule import (create_search_console_schedule, run_due_search_console_schedules,
                                      set_search_console_schedule_enabled)
from .services import create_connection


@override_settings(GOOGLE_OAUTH_CLIENT_ID="fixture-client", GOOGLE_OAUTH_CLIENT_SECRET="fixture-secret",
                   GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),),
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                        "LOCATION": "backfill-fixtures"}})
class SearchConsoleBackfillTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("backfill-owner@example.com", password="test-password")
        self.viewer = users.create_user("backfill-viewer@example.com", password="test-password")
        self.other = users.create_user("backfill-other@example.com", password="test-password")
        for user in (self.owner, self.viewer, self.other):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        self.organization = create_organization(user=self.owner, name="Backfill org")
        OrganizationMembership.objects.create(organization=self.organization, user=self.viewer, role=MembershipRole.VIEWER)
        self.project = create_project(organization=self.organization, user=self.owner, name="Backfill site",
                                      canonical_origin="https://backfill.example")
        self.connection = create_connection(project=self.project, user=self.owner, provider="google_search_console",
            external_property_id="https://backfill.example/", capabilities=["api_sync", "query_metrics"],
            available_dimensions=["query"], source_semantics="search_console_performance",
            source_semantics_version="gsc-performance-v1", timezone="America/Los_Angeles")
        self.grant = GoogleOAuthGrant.objects.create(organization=self.organization, project=self.project,
            actor=self.owner, scope=SCOPE, verified_at=timezone.now(), encrypted_refresh_token="v1:fixture-only",
            state=GoogleOAuthGrant.State.ACTIVE, selected_property_id=self.connection.external_property_id,
            selected_site_url="https://backfill.example/")
        self.connection.credential_reference = self.grant.credential_reference
        self.connection.save()
        self.end = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=5)
        self.start = self.end - timedelta(days=2)
        self.url = (f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}"
                    f"/sources/{self.connection.pk}/backfill/")

    def queue(self, *, key="range-one", actor=None, **overrides):
        return queue_search_console_backfill(project=self.project, actor=actor or self.owner,
            connection=self.connection, grant=self.grant, start_day=self.start, end_day=self.end,
            dimension="query", idempotency_key=key, **overrides)

    def test_advances_one_day_only_after_success_and_preserves_daily_evidence(self):
        batch = self.queue()
        self.assertEqual(self.queue().pk, batch.pk)
        self.assertEqual(advance_search_console_backfills(), 1)
        batch.refresh_from_db()
        self.assertEqual((batch.next_day, batch.current_job.input_snapshot["day"]), (self.start, self.start.isoformat()))
        self.assertEqual(advance_search_console_backfills(), 0)
        requests = []
        for day in (self.start, self.start + timedelta(days=1), self.end):
            batch.refresh_from_db()
            job = batch.current_job
            def query(**_kwargs):
                requests.append(day)
                return {"responseAggregationType": "byProperty", "rows": [{
                    "keys": ["in scope"], "clicks": 1, "impressions": 2, "ctr": .5, "position": 3}]}
            self.assertTrue(execute_search_console_sync(job.pk,
                refresh=lambda **_kwargs: GoogleTokens("fixture-access", None, timezone.now() + timedelta(minutes=20)),
                verify_site=lambda **_kwargs: {"siteUrl": "https://backfill.example/", "permissionLevel": "siteOwner"},
                query=query))
            self.assertEqual(advance_search_console_backfills(), 0 if day == self.end else 1)
        batch.refresh_from_db()
        self.assertEqual((batch.status, batch.next_day, batch.error_category), (batch.Status.SUCCEEDED, self.end, ""))
        self.assertEqual(requests, [self.start, self.start + timedelta(days=1), self.end])
        self.assertEqual(SearchAnalyticsPageSnapshot.objects.filter(project=self.project).count(), 3)
        self.assertEqual(JobRun.objects.filter(project=self.project, handler="sync_search_console").count(), 3)
        self.assertEqual(advance_search_console_backfills(), 0)

    def test_failed_or_unknown_day_pauses_without_retrying_or_queuing_later_days(self):
        batch = self.queue()
        self.assertEqual(advance_search_console_backfills(), 1)
        batch.refresh_from_db()
        JobRun.objects.filter(pk=batch.current_job_id).update(status=JobStatus.RUNNING)
        JobRun.objects.filter(pk=batch.current_job_id).update(status=JobStatus.FAILED, error_category="request_outcome_unknown")
        self.assertEqual(advance_search_console_backfills(), 0)
        batch.refresh_from_db()
        self.assertEqual((batch.status, batch.error_category), (batch.Status.PAUSED, "request_outcome_unknown"))
        self.assertEqual(JobRun.objects.filter(handler="sync_search_console").count(), 1)

    def test_revoked_scope_or_actor_stops_before_next_day(self):
        batch = self.queue()
        update_project(project=self.project, user=self.owner, canonical_origin="https://moved.example")
        self.assertEqual(advance_search_console_backfills(), 0)
        batch.refresh_from_db()
        self.assertEqual((batch.status, batch.error_category), (batch.Status.PAUSED, "source_unavailable"))
        self.assertFalse(JobRun.objects.filter(handler="sync_search_console").exists())

    def test_capacity_or_partial_report_does_not_dispatch_later_days(self):
        batch = self.queue()
        with patch("integrations.search_console_backfill.queue_search_console_sync",
                   side_effect=UsageLimitError("limit", category="trial_units_exhausted")):
            self.assertEqual(advance_search_console_backfills(), 0)
        batch.refresh_from_db()
        self.assertEqual((batch.status, batch.error_category), (batch.Status.PAUSED, "trial_units_exhausted"))
        self.assertFalse(JobRun.objects.filter(handler="sync_search_console").exists())
        second = self.queue(key="after-pause")
        self.assertEqual(advance_search_console_backfills(), 1)
        second.refresh_from_db()
        JobRun.objects.filter(pk=second.current_job_id).update(status=JobStatus.PARTIALLY_SUCCEEDED,
                                                                error_category="quota_limited")
        self.assertEqual(advance_search_console_backfills(), 0)
        second.refresh_from_db()
        self.assertEqual((second.status, second.error_category), (second.Status.PAUSED, "quota_limited"))
        self.assertEqual(JobRun.objects.filter(handler="sync_search_console").count(), 1)

    def test_bound_key_scope_and_owner_only_api_with_csrf_and_cancel(self):
        for start, end in ((self.end - timedelta(days=7), self.end), (self.start, self.end + timedelta(days=90))):
            with self.subTest(start=start, end=end), self.assertRaises(ValidationError):
                queue_search_console_backfill(project=self.project, actor=self.owner, connection=self.connection,
                    grant=self.grant, start_day=start, end_day=end, dimension="query", idempotency_key="outside")
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        owner.get("/_allauth/browser/v1/auth/session")
        viewer = Client(enforce_csrf_checks=True)
        viewer.force_login(self.viewer)
        viewer.get("/_allauth/browser/v1/auth/session")
        other = Client(enforce_csrf_checks=True)
        other.force_login(self.other)
        payload = {"start_day": self.start.isoformat(), "end_day": self.end.isoformat(),
                   "dimension": "query", "idempotency_key": "from-ui"}
        def post(client, path, data=payload, csrf=True):
            headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value} if csrf else {}
            return client.post(path, data=json.dumps(data), content_type="application/json", **headers)
        self.assertEqual(post(owner, self.url, csrf=False).status_code, 403)
        self.assertEqual(post(viewer, self.url).status_code, 403)
        self.assertEqual(other.get(self.url + "status/").status_code, 404)
        self.assertEqual(post(owner, self.url).status_code, 202)
        self.assertEqual(post(owner, self.url).status_code, 202)
        self.assertEqual(SearchConsoleBackfill.objects.count(), 1)
        self.assertEqual(post(owner, self.url, {**payload, "end_day": self.start.isoformat()}).status_code, 409)
        with patch("integrations.oauth_views.ratelimit.consume", return_value=True):
            self.assertEqual(post(owner, self.url, {**payload, "idempotency_key": "other-batch"}).status_code, 409)
        status = owner.get(self.url + "status/")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["backfill"]["next_day"], self.start.isoformat())
        self.assertNotIn("fixture-only", status.content.decode())
        cancel_path = self.url + f"{status.json()['backfill']['id']}/cancel/"
        self.assertEqual(post(viewer, cancel_path, {}).status_code, 403)
        self.assertEqual(post(owner, cancel_path, {}, csrf=False).status_code, 403)
        self.assertEqual(post(owner, cancel_path, {}).json()["backfill"]["status"], "paused")
        self.assertEqual(advance_search_console_backfills(), 0)

    def test_trial_missing_at_queue_never_creates_a_batch(self):
        OrganizationTrial.objects.filter(organization=self.organization).delete()
        # D098: without a trial/paid retention clock, project access itself is unavailable.
        with self.assertRaises(PermissionDenied):
            self.queue()
        self.assertFalse(SearchConsoleBackfill.objects.exists())

    @override_settings(PADDLE_ENVIRONMENT="sandbox")
    def test_verified_paid_can_create_schedule_and_backfill_but_expired_access_cannot_enable(self):
        now = timezone.now()
        subscription = PaddleSubscription.objects.create(
            organization=self.organization, environment="sandbox", customer_id="ctm_" + "a" * 26,
            subscription_id="sub_" + "b" * 26, status=PaddleStatus.ACTIVE,
            verified_at=now, currency_code="USD", period_starts_at=now - timedelta(days=1),
            period_ends_at=now + timedelta(days=29))
        schedule = create_search_console_schedule(project=self.project, actor=self.owner,
            connection=self.connection, grant=self.grant, dimension="query", idempotency_key="paid-daily")
        set_search_console_schedule_enabled(project=self.project, actor=self.owner,
            connection=self.connection, schedule_id=schedule.pk, enabled=True)
        self.assertEqual(self.queue().status, SearchConsoleBackfill.Status.RUNNING)
        PaddleSubscription.objects.filter(pk=subscription.pk).update(period_ends_at=now - timedelta(seconds=1))
        with self.assertRaises(UsageLimitError) as expired:
            self.queue(key="paid-after-expiry")
        self.assertEqual(expired.exception.category, "paid_unavailable")
        with self.assertRaises(UsageLimitError) as schedule_expired:
            set_search_console_schedule_enabled(project=self.project, actor=self.owner,
                connection=self.connection, schedule_id=schedule.pk, enabled=True)
        self.assertEqual(schedule_expired.exception.category, "paid_unavailable")

    @override_settings(PADDLE_ENVIRONMENT="sandbox")
    def test_signed_adverse_hold_pauses_due_paid_schedule_until_manual_reenable(self):
        now = timezone.now()
        subscription = PaddleSubscription.objects.create(
            organization=self.organization, environment="sandbox", customer_id="ctm_" + "c" * 26,
            subscription_id="sub_" + "d" * 26, status=PaddleStatus.ACTIVE,
            verified_at=now, currency_code="USD", period_starts_at=now - timedelta(days=1),
            period_ends_at=now + timedelta(days=29))
        schedule = create_search_console_schedule(project=self.project, actor=self.owner,
            connection=self.connection, grant=self.grant, dimension="query", idempotency_key="hold-daily")
        set_search_console_schedule_enabled(project=self.project, actor=self.owner,
            connection=self.connection, schedule_id=schedule.pk, enabled=True)
        JobSchedule.objects.filter(pk=schedule.pk).update(next_run_at=now - timedelta(hours=1))
        receipt = PaddleWebhookReceipt.objects.create(
            environment="sandbox", event_id="evt_" + "p" * 26,
            notification_id="ntf_" + "p" * 26, event_type="adjustment.updated",
            occurred_at=now, entity_id="adj_" + "p" * 26, raw_digest="b" * 64,
            subscription_id=subscription.subscription_id, customer_id=subscription.customer_id,
            state=PaddleWebhookReceipt.State.PENDING)
        self.assertEqual(run_due_search_console_schedules(now=now), 0)
        schedule.refresh_from_db()
        self.assertEqual((schedule.enabled, schedule.last_error_category), (False, "billing_review_hold"))
        self.assertFalse(JobRun.objects.filter(schedule=schedule).exists())
        PaddleWebhookReceipt.objects.filter(pk=receipt.pk).update(
            state=PaddleWebhookReceipt.State.SUCCEEDED, attempts=1,
            claimed_at=now, processed_at=now)
        self.assertEqual(run_due_search_console_schedules(now=now + timedelta(days=1)), 0)
        self.assertFalse(JobRun.objects.filter(schedule=schedule).exists())

    def test_daily_schedule_is_one_day_per_source_and_pauses_after_unknown_outcome(self):
        schedule = create_search_console_schedule(project=self.project, actor=self.owner,
            connection=self.connection, grant=self.grant, dimension="query", idempotency_key="daily")
        self.assertFalse(schedule.enabled)
        self.assertEqual(create_search_console_schedule(project=self.project, actor=self.owner,
            connection=self.connection, grant=self.grant, dimension="query", idempotency_key="daily").pk, schedule.pk)
        with self.assertRaises(ValidationError):
            create_search_console_schedule(project=self.project, actor=self.owner, connection=self.connection,
                grant=self.grant, dimension="page", idempotency_key="duplicate")
        schedule = set_search_console_schedule_enabled(project=self.project, actor=self.owner,
            connection=self.connection, schedule_id=schedule.pk, enabled=True)
        now = timezone.now()
        JobSchedule.objects.filter(pk=schedule.pk).update(next_run_at=now - timedelta(days=3))
        self.assertEqual(run_due_schedules(now=now), 0)
        with self.assertRaises(ValidationError):
            set_schedule_enabled(schedule=schedule, actor=self.owner, enabled=False)
        with patch("integrations.search_console_schedule._day", return_value=self.end):
            self.assertEqual(run_due_search_console_schedules(now=now), 1)
            self.assertEqual(run_due_search_console_schedules(now=now), 0)
        job = JobRun.objects.get(schedule=schedule)
        self.assertEqual((job.input_snapshot["day"], job.usage.reserved_units), (self.end.isoformat(), 3))
        schedule.refresh_from_db()
        self.assertEqual(schedule.skipped_occurrences, 3)
        self.assertEqual(schedule.last_error_category, "")
        JobRun.objects.filter(pk=job.pk).update(status=JobStatus.FAILED, error_category="request_outcome_unknown")
        JobSchedule.objects.filter(pk=schedule.pk).update(next_run_at=now - timedelta(minutes=1))
        self.assertEqual(run_due_search_console_schedules(now=now), 0)
        schedule.refresh_from_db()
        self.assertEqual((schedule.enabled, schedule.last_error_category), (False, "request_outcome_unknown"))
        self.assertEqual(JobRun.objects.filter(schedule=schedule).count(), 1)

    def test_schedule_rechecks_revoked_scope_and_waits_for_active_backfill(self):
        schedule = create_search_console_schedule(project=self.project, actor=self.owner,
            connection=self.connection, grant=self.grant, dimension="query", idempotency_key="daily")
        set_search_console_schedule_enabled(project=self.project, actor=self.owner,
            connection=self.connection, schedule_id=schedule.pk, enabled=True)
        self.queue()
        now = timezone.now()
        JobSchedule.objects.filter(pk=schedule.pk).update(next_run_at=now - timedelta(minutes=1))
        self.assertEqual(run_due_search_console_schedules(now=now), 0)
        schedule.refresh_from_db()
        self.assertEqual((schedule.enabled, schedule.last_error_category), (True, "source_busy"))
        self.assertFalse(JobRun.objects.filter(schedule=schedule).exists())
        SearchConsoleBackfill.objects.filter(connection=self.connection).update(status=SearchConsoleBackfill.Status.PAUSED)
        update_project(project=self.project, user=self.owner, canonical_origin="https://moved.example")
        JobSchedule.objects.filter(pk=schedule.pk).update(next_run_at=now - timedelta(minutes=1))
        self.assertEqual(run_due_search_console_schedules(now=now), 0)
        schedule.refresh_from_db()
        self.assertEqual((schedule.enabled, schedule.last_error_category), (False, "source_revoked"))

    def test_schedule_skips_same_finalized_day_and_queues_only_next_day(self):
        schedule = create_search_console_schedule(project=self.project, actor=self.owner,
            connection=self.connection, grant=self.grant, dimension="query", idempotency_key="daily")
        set_search_console_schedule_enabled(project=self.project, actor=self.owner,
            connection=self.connection, schedule_id=schedule.pk, enabled=True)
        now = timezone.now()
        JobSchedule.objects.filter(pk=schedule.pk).update(next_run_at=now - timedelta(minutes=1))
        with patch("integrations.search_console_schedule._day", return_value=self.start):
            self.assertEqual(run_due_search_console_schedules(now=now), 1)
        first = JobRun.objects.get(schedule=schedule)
        JobRun.objects.filter(pk=first.pk).update(status=JobStatus.SUCCEEDED)
        JobSchedule.objects.filter(pk=schedule.pk).update(next_run_at=now - timedelta(minutes=1))
        with patch("integrations.search_console_schedule._day", return_value=self.start):
            self.assertEqual(run_due_search_console_schedules(now=now), 0)
        later = now + timedelta(days=1)
        JobSchedule.objects.filter(pk=schedule.pk).update(next_run_at=later - timedelta(minutes=1))
        following = self.start + timedelta(days=1)
        with patch("integrations.search_console_schedule._day", return_value=following):
            self.assertEqual(run_due_search_console_schedules(now=later), 1)
        self.assertEqual(set(JobRun.objects.filter(schedule=schedule).values_list("input_snapshot__day", flat=True)),
                         {self.start.isoformat(), following.isoformat()})

    def test_backfill_waits_for_other_queued_source_work_and_schedule_respects_quota_backoff(self):
        from .search_console_sync import queue_search_console_sync
        with patch("jobs.services.dispatch_pending"):
            queued = queue_search_console_sync(project=self.project, actor=self.owner,
                connection=self.connection, grant=self.grant, day=self.end,
                dimensions=["query"], idempotency_key="prior-sync")
        batch = self.queue()
        self.assertEqual(advance_search_console_backfills(), 0)
        self.assertIsNone(SearchConsoleBackfill.objects.get(pk=batch.pk).current_job_id)
        JobRun.objects.filter(pk=queued.pk).update(status=JobStatus.FAILED, error_category="request_outcome_unknown")
        SearchConsoleBackfill.objects.filter(pk=batch.pk).update(status=SearchConsoleBackfill.Status.PAUSED)
        schedule = create_search_console_schedule(project=self.project, actor=self.owner,
            connection=self.connection, grant=self.grant, dimension="query", idempotency_key="daily")
        set_search_console_schedule_enabled(project=self.project, actor=self.owner,
            connection=self.connection, schedule_id=schedule.pk, enabled=True)
        now = timezone.now()
        retry_after = now + timedelta(hours=3)
        SyncCursor.objects.create(project=self.project, connection=self.connection,
            status=SyncCursor.Status.WAITING_PROVIDER, retry_after=retry_after,
            error_category="quota_limited", quota_state=SyncCursor.QuotaState.LIMITED)
        JobSchedule.objects.filter(pk=schedule.pk).update(next_run_at=now - timedelta(minutes=1))
        self.assertEqual(run_due_search_console_schedules(now=now), 0)
        schedule.refresh_from_db()
        self.assertTrue(schedule.enabled)
        self.assertEqual(schedule.last_error_category, "quota_limited")
        self.assertEqual(schedule.next_run_at, retry_after)

    def test_schedule_api_owner_csrf_status_and_toggle(self):
        path = self.url.replace("backfill/", "sync-schedule/")
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        owner.get("/_allauth/browser/v1/auth/session")
        viewer = Client(enforce_csrf_checks=True)
        viewer.force_login(self.viewer)
        viewer.get("/_allauth/browser/v1/auth/session")
        payload = {"dimension": "query", "idempotency_key": "daily"}
        def post(client, url, value, csrf=True):
            headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value} if csrf else {}
            return client.post(url, data=json.dumps(value), content_type="application/json", **headers)
        self.assertEqual(post(owner, path, payload, csrf=False).status_code, 403)
        self.assertEqual(post(viewer, path, payload).status_code, 403)
        response = post(owner, path, payload)
        self.assertEqual(response.status_code, 201)
        schedule_id = response.json()["schedule"]["id"]
        self.assertFalse(response.json()["schedule"]["enabled"])
        self.assertEqual(owner.get(path + "status/").json()["schedule"]["id"], schedule_id)
        self.assertEqual(viewer.get(path + "status/").status_code, 403)
        toggle = path + f"{schedule_id}/toggle/"
        self.assertEqual(post(owner, toggle, {"enabled": True}, csrf=False).status_code, 403)
        self.assertTrue(post(owner, toggle, {"enabled": True}).json()["schedule"]["enabled"])
        self.assertFalse(post(owner, toggle, {"enabled": False}).json()["schedule"]["enabled"])
