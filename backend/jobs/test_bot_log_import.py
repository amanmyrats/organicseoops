from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
import json
from unittest.mock import patch
from threading import Barrier
from zipfile import ZipFile

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from config.test_foundations import TEST_STORAGES

from tenancy.models import Organization, ProjectOriginVerification, OrganizationTrial, OrganizationMembership
from tenancy.services import create_organization, create_project
from .bot_log_import import HANDLER, execute_bot_log_import, queue_bot_log_import, source_current
from .indexation import build_indexation_evidence
from .models import CrawlRun, CrawlPageSnapshot, JobRun, JobStep, UsageReservation
from .services import _snapshot, cancel_job, dispatch_pending, queue_job, retry_job

@override_settings(STORAGES=TEST_STORAGES, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class BotLogImportTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        self.owner = get_user_model().objects.create_user("bot-log@example.invalid", password="test-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        self.org = create_organization(user=self.owner, name="Fixture logs")
        self.project = create_project(organization=self.org, user=self.owner, name="Fixture site",
                                      canonical_origin="https://log.example.invalid")
        self.verification = ProjectOriginVerification.objects.create(organization=self.org, project=self.project,
            origin=self.project.canonical_origin, challenge_digest="a" * 64, state="verified", verified_at=timezone.now())
        crawl = JobRun.objects.create(project=self.project, organization=self.org, actor=self.owner,
            handler="crawl_site", input_snapshot={"seeds": [self.project.canonical_origin + "/service"], "page_limit": 1},
            method_version="crawl-http-v1")
        crawl.status = "running"; crawl.save()
        run = CrawlRun.objects.create(project=self.project, organization=self.org, job=crawl,
            page_limit=1, pages_attempted=1, pages_observed=1, completed_at=timezone.now(), discovery={})
        CrawlPageSnapshot.objects.create(crawl_run=run, project=self.project,
            requested_url=self.project.canonical_origin + "/service", final_url=self.project.canonical_origin + "/service", status_code=200)
        crawl.status = "succeeded"; crawl.save()
        self.inventory = build_indexation_evidence(run.pk)
        self.end = timezone.now().replace(microsecond=0)
        self.start = self.end - timedelta(days=1)
        self.row = {"timestamp": (self.end - timedelta(hours=1)).isoformat(), "origin": self.project.canonical_origin,
            "target": "/service?token=private-raw-secret", "status": 404, "user_agent": "GPTBot/1.0 private-raw-secret",
            "ip": "192.0.2.98", "referrer": "private-raw-secret"}
        self.content = (json.dumps(self.row) + "\n" + json.dumps({**self.row, "target": "/private-raw-secret"})).encode()

    def queue(self, key="fixture-request", **changes):
        args = dict(project=self.project, actor=self.owner, content=self.content, origin=self.project.canonical_origin,
            window_start=self.start, window_end=self.end, inventory_id=self.inventory.pk, authorize_logfile=True,
            idempotency_key=key)
        with patch("jobs.services.dispatch_pending"):
            return queue_bot_log_import(**{**args, **changes})

    def test_minimized_staging_actual_serializer_duplicate_once_only_worker_and_private_export_deletion(self):
        job = self.queue()
        self.assertEqual(_snapshot(job.input_snapshot), job.input_snapshot)
        self.assertEqual(self.queue().pk, job.pk)
        with self.assertRaises(ValidationError): self.queue("duplicate-other-request")
        with patch("jobs.tasks.execute_bot_log_import_task.apply_async") as send:
            self.assertTrue(dispatch_pending(job.pk))
            send.assert_called_once_with(args=[job.pk], queue="default", task_id=f"job-{job.pk}", retry=False)
        self.assertTrue(execute_bot_log_import(job.pk)); self.assertFalse(execute_bot_log_import(job.pk))
        job.refresh_from_db()
        self.assertEqual((job.status, job.usage.actual_units, job.steps.count()), ("succeeded", 1, 1))
        self.assertEqual(job.output["request_candidates"]["unmatched_inventory_requests"], 1)
        self.assertEqual(job.output["request_candidates"]["redirect_or_error_requests"], 2)
        self.assertEqual(job.output["inventory_families"][0]["representative_inventory_url"], self.project.canonical_origin + "/service")
        for value in ("private-raw-secret", "192.0.2.98", "GPTBot/1.0", "referrer"):
            self.assertNotIn(value, json.dumps([job.input_snapshot, job.output, job.config_snapshot, list(job.steps.values())], default=str))
        from tenancy.customer_export import complete_bounded_customer_archive
        with ZipFile(BytesIO(complete_bounded_customer_archive(organization=self.org, actor=self.owner))) as archive:
            data = archive.read("records/jobs/JobRun.json").decode()
            self.assertIn(HANDLER, data); self.assertNotIn("private-raw-secret", data)
        changed = deepcopy(job.output); changed["raw"] = "private-raw-secret"; job.output = changed
        with self.assertRaises(ValidationError): job.save()
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        Organization.objects.filter(pk=self.org.pk).update(closed_at=timezone.now(), is_suspended=True)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.org))
        delete_customer_database_records(run=run)
        self.assertFalse(JobRun.objects.filter(pk=job.pk).exists())

    def test_direct_queue_and_model_reject_raw_extra_fields_foreign_inventory_and_unknown_path_labels(self):
        valid = self.queue()
        for mutate in (lambda data: data.update(raw="private-raw-secret"),
                       lambda data: data["summary"].update(ip="192.0.2.98"),
                       lambda data: data["summary"]["groups"][0].update(user_agent="private-raw-secret"),
                       lambda data: data["summary"]["groups"][0].update(known_url=self.project.canonical_origin + "/unowned"),
                       lambda data: data["summary"]["groups"][0].update(request_count=True)):
            data = deepcopy(valid.input_snapshot); mutate(data)
            with self.assertRaises((PermissionDenied, ValidationError)):
                queue_job(project=self.project, actor=self.owner, handler=HANDLER, input_snapshot=data,
                    config_snapshot=valid.config_snapshot, idempotency_key="bad-direct")
            with self.assertRaises((PermissionDenied, ValidationError)):
                JobRun.objects.create(project=self.project, organization=self.org, actor=self.owner, handler=HANDLER,
                    method_version=valid.method_version, input_snapshot=data, config_snapshot=valid.config_snapshot)
        with self.assertRaises(ValidationError):
            JobStep.objects.create(job=valid, sequence=1, name="raw", status="succeeded", output={"raw": "private-raw-secret"})
        with self.assertRaises(ValidationError): self.queue(authorize_logfile=False)
        with self.assertRaises(PermissionDenied): self.queue(inventory_id=self.inventory.pk + 999)
        self.assertEqual(JobRun.objects.filter(handler=HANDLER).count(), 1)

    def test_revocation_cancel_expiry_and_role_loss_release_usage_and_deny_delivery(self):
        job = self.queue()
        self.verification.state = "revoked"; self.verification.revoked_at = timezone.now(); self.verification.save()
        self.assertFalse(source_current(job)); self.assertFalse(execute_bot_log_import(job.pk))
        job.refresh_from_db(); self.assertEqual((job.status, job.usage.actual_units), ("cancelled", 0))
        with self.assertRaises(ValidationError): retry_job(job=job, actor=self.owner, idempotency_key="retry")
        self.verification.state = "verified"; self.verification.revoked_at = None; self.verification.verified_at = timezone.now(); self.verification.save()
        self.assertFalse(source_current(job))  # Same row re-verification does not revive old authority.
        cancelled = self.queue("cancel", content=self.content + b"\n")
        cancel_job(job=cancelled, actor=self.owner); self.assertFalse(execute_bot_log_import(cancelled.pk))
        expired = self.queue("expired", content=self.content + b"\n\n")
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.org).update(started_at=now-timedelta(days=31), ends_at=now-timedelta(seconds=1))
        self.assertFalse(execute_bot_log_import(expired.pk)); expired.refresh_from_db()
        self.assertEqual(expired.error_category, "trial_unavailable")
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
        with self.assertRaises(PermissionDenied): self.queue("role", content=self.content + b"\n\n\n")

    def test_private_raw_body_intake_csrf_role_scope_rate_limits_and_revoked_consumer_export(self):
        from django.core.cache import cache
        cache.clear()
        path = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/bot-logs/"
        headers = {"HTTP_X_LOG_ORIGIN": self.project.canonical_origin, "HTTP_X_LOG_INVENTORY": str(self.inventory.pk),
            "HTTP_X_LOG_START": self.start.isoformat(), "HTTP_X_LOG_END": self.end.isoformat(),
            "HTTP_X_LOG_AUTHORIZATION": "true", "HTTP_X_LOG_REQUEST": "api-fixture"}
        anonymous = Client(); self.assertEqual(anonymous.get(path).status_code, 401)
        browser = Client(enforce_csrf_checks=True); browser.force_login(self.owner)
        browser.get("/_allauth/browser/v1/auth/session")
        self.assertEqual(browser.post(path, self.content, content_type="application/x-ndjson", **headers).status_code, 403)
        headers["HTTP_X_CSRFTOKEN"] = browser.cookies["csrftoken"].value
        catalog = browser.get(path); self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog["Cache-Control"], "private, no-store")
        self.assertEqual(catalog.json()["inventories"][0]["id"], self.inventory.pk)
        with patch("jobs.services.dispatch_pending"), patch("config.artifacts.save_private_artifact") as storage:
            response = browser.post(path, self.content, content_type="application/x-ndjson", **headers)
            self.assertEqual(response.status_code, 202); storage.assert_not_called()
        job = JobRun.objects.get(pk=response.json()["job"]["id"]); execute_bot_log_import(job.pk)
        detail = browser.get(path + f"{job.pk}/")
        self.assertTrue(detail.json()["job"]["evidence"])
        self.assertNotIn("private-raw-secret", detail.content.decode())
        self.assertEqual(browser.get(path + "?before=bad").status_code, 409)
        self.assertEqual(browser.get(path + f"?before={job.pk}").json()["jobs"], [])
        for content_type, changed in (("application/json", {}), ("multipart/form-data", {}),
            ("application/x-ndjson", {"HTTP_X_LOG_AUTHORIZATION": "false"}),
            ("application/x-ndjson", {"HTTP_X_LOG_INVENTORY": str(self.inventory.pk + 1000)})):
            self.assertIn(browser.post(path, self.content, content_type=content_type,
                                       **{**headers, **changed}).status_code, (403, 409, 413))
        other = get_user_model().objects.create_user("bot-log-other@example.invalid", password="test-password")
        EmailAddress.objects.create(user=other, email=other.email, verified=True, primary=True)
        foreign_org = create_organization(user=other, name="Foreign log fixture")
        foreign_project = create_project(organization=foreign_org, user=other, name="Foreign", canonical_origin="https://foreign.example.invalid")
        foreign_path = f"/api/organizations/{foreign_org.pk}/projects/{foreign_project.pk}/bot-logs/"
        self.assertEqual(browser.get(foreign_path).status_code, 404)
        self.assertEqual(browser.post(foreign_path, self.content, content_type="application/x-ndjson", **headers).status_code, 404)
        viewer = get_user_model().objects.create_user("bot-log-viewer@example.invalid", password="test-password")
        OrganizationMembership.objects.create(organization=self.org, user=viewer, role="viewer")
        viewer_browser = Client(); viewer_browser.force_login(viewer)
        self.assertTrue(viewer_browser.get(path + f"{job.pk}/").json()["job"]["evidence"])
        self.assertEqual(viewer_browser.post(path, self.content, content_type="application/x-ndjson", **headers).status_code, 403)
        with patch("jobs.bot_log_api.ratelimit.consume", return_value=False):
            self.assertEqual(browser.post(path, self.content, content_type="application/x-ndjson", **headers).status_code, 429)
        with patch("django.core.files.uploadhandler.TemporaryFileUploadHandler.new_file", side_effect=AssertionError("raw temp upload")):
            self.assertEqual(browser.post(path, {"file": BytesIO(b"x" * (3 * 1024 * 1024))}).status_code, 413)
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            snapshot = reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner, request_key="f" * 32)
        self.assertTrue(capture_reserved_customer_snapshot(snapshot.pk))
        private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=snapshot.pk, position=0)
        self.verification.state = "revoked"; self.verification.revoked_at = timezone.now(); self.verification.save()
        with self.assertRaises(PermissionDenied):
            private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=snapshot.pk, position=0)
        self.assertIsNone(browser.get(path + f"{job.pk}/").json()["job"]["evidence"])
        from tenancy.customer_export import project_customer_rows
        rows = project_customer_rows(organization=self.org, actor=self.owner, model_label="jobs.JobRun", after_id=0, through_id=job.pk)
        record = next(row for row in rows["rows"] if row["id"] == job.pk)
        self.assertFalse(record["source_current"]); self.assertEqual(record["output"], {"state": "source_authority_unavailable"})
        self.assertEqual(JobRun.objects.filter(handler=HANDLER).count(), 1)

    def test_export_reserved_before_import_capture_cannot_deliver_after_source_revocation(self):
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            snapshot = reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner, request_key="e" * 32)
        job = self.queue(); self.assertGreater(job.created_at, snapshot.created_at)
        execute_bot_log_import(job.pk)
        self.assertTrue(capture_reserved_customer_snapshot(snapshot.pk))
        data, _digest = private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=snapshot.pk, position=0)
        with ZipFile(BytesIO(data)) as archive:
            self.assertIn(HANDLER, archive.read("records/jobs/JobRun.json").decode())
        self.verification.state = "revoked"; self.verification.revoked_at = timezone.now(); self.verification.save()
        with self.assertRaises(PermissionDenied):
            private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=snapshot.pk, position=0)


@override_settings(STORAGES=TEST_STORAGES, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class BotLogImportConcurrencyTests(TransactionTestCase):
    setUp = BotLogImportTests.setUp
    queue = BotLogImportTests.queue

    def test_two_connections_cannot_stage_one_raw_file_twice_or_reserve_twice(self):
        barrier = Barrier(2)
        def launch(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    self.queue(f"log-race-{index}")
                    return "queued"
                except ValidationError:
                    return "duplicate"
            finally:
                close_old_connections()
        with patch("jobs.services.dispatch_pending"), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(launch, index) for index in (1, 2)]
            self.assertEqual(sorted(future.result(timeout=40) for future in futures), ["duplicate", "queued"])
        self.assertEqual(JobRun.objects.filter(handler=HANDLER).count(), 1)
        self.assertEqual(UsageReservation.objects.filter(job__handler=HANDLER).count(), 1)
