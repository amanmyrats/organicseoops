import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.core.cache import cache
from django.db import transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, OrganizationTrial, Project, ProjectConfiguration
from . import competitor_api as api
from . import competitor_collection as collection
from . import test_competitor_collection as fixtures
from .models import Artifact, JobCancellation, JobRun, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "competitor-root-api"}})
class CompetitorApiTests(TransactionTestCase):
    transport = fixtures.CompetitorCollectionTests.transport
    fetcher = fixtures.CompetitorCollectionTests.fetcher
    revoke = fixtures.CompetitorCollectionTests.revoke

    def setUp(self):
        fixtures.CompetitorCollectionTests.setUp(self)
        cache.clear()
        self.client = Client(enforce_csrf_checks=True); self.client.force_login(self.owner)
        self.client.get("/_allauth/browser/v1/auth/session", secure=True)
        self.csrf = self.client.cookies["csrftoken"].value
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/competitor-roots/"

    def post(self, suffix="", data=None):
        return self.client.post(self.base + suffix, json.dumps(self.data if data is None else data), content_type="application/json",
            secure=True, HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/")

    def command(self, key="competitor-api-request"):
        preview = self.post("selection/")
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(api._digest(preview.json()["selection"]), preview.json()["selection_digest"])
        return {**self.data, "idempotency_key": key, "selection_digest": preview.json()["selection_digest"]}

    def test_genuine_preview_queue_own_lookup_private_detail_independent_admin_and_cancel(self):
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")):
            command = self.command()
            self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
            self.assertEqual(self.client.get(self.base + "?idempotency_key=competitor-api-request", secure=True).json()["jobs"], [])
            queued = self.post(data=command)
            self.assertEqual(queued.status_code, 202, queued.content)
            job_id = queued.json()["job"]["id"]
            self.assertEqual(self.post(data=command).json()["job"]["id"], job_id)
            lookup = self.client.get(self.base + "?idempotency_key=competitor-api-request", secure=True)
            self.assertEqual(lookup.json()["jobs"][0]["id"], job_id)
            self.assertTrue(collection.execute_competitor_collection(job_id, fetcher=self.fetcher()))
            detail = self.client.get(self.base + f"{job_id}/", secure=True)
            self.assertEqual(detail.status_code, 200, detail.content)
            self.assertEqual(detail.json()["evidence"]["collection"]["evidence"]["metadata"]["title"], "Public fixture")
            self.assertNotIn(b"private-contact", detail.content); self.assertNotIn(b"secret", detail.content)
            self.assertIn("no-store", detail["Cache-Control"]); self.assertEqual(detail["X-Robots-Tag"], "noindex, nofollow")
            other = Client(); other.force_login(self.admin)
            self.assertEqual(other.get(self.base + f"{job_id}/", secure=True).json()["evidence"], detail.json()["evidence"])
            self.assertEqual(other.get(self.base + "?idempotency_key=competitor-api-request", secure=True).json()["jobs"], [])
            pending = self.post(data=self.command("competitor-api-cancel")).json()["job"]["id"]
            self.assertEqual(self.post(f"{pending}/", {}).status_code, 202)
            self.assertEqual(JobRun.objects.get(pk=pending).status, "cancelled")

    def test_strict_csrf_rights_json_query_own_scope_and_stale_digest_deny_without_job(self):
        command = self.command()
        self.assertEqual(self.client.post(self.base, json.dumps(command), content_type="application/json", secure=True).status_code, 403)
        for changes in ({"raw_html": "private"}, {"collection_permission": 1}, {"storage_permission": False},
            {"use_permission": "true"}, {"selection_digest": "a" * 64}, {"origin": "https://second.example.invalid"}):
            self.assertIn(self.post(data={**command, **changes}).status_code, (403, 409))
        self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
        for body in ('{"origin":"x","origin":"y"}', '{', '[]', 'null', '{"origin":NaN}', " " * 2049):
            cache.clear()  # This fixture checks parsing; independent command budgets have their own case.
            response = self.client.post(self.base, body, content_type="application/json", secure=True,
                HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/")
            self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(self.post("?idempotency_key=posted", command).status_code, 400)
        for query in ("?extra=x", "?idempotency_key=a&idempotency_key=a"):
            self.assertEqual(self.client.get(self.base + query, secure=True).status_code, 409)
        self.assertEqual(self.client.get(self.base + "selection/", secure=True).status_code, 405)
        self.assertEqual(Client().get(self.base, secure=True).status_code, 401)
        self.client.force_login(self.foreign)
        self.assertEqual(self.client.get(self.base, secure=True).status_code, 404)
        self.client.force_login(self.admin)
        OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
        self.assertEqual(self.client.get(self.base, secure=True).status_code, 403)

    def test_all_four_maintained_command_budgets_are_independent_and_shared_ip_scoped(self):
        command = self.command()
        job_id = self.post(data=command).json()["job"]["id"]
        other = Client(); other.force_login(self.admin)
        cache.clear()
        limits = {action: "1/h/ip" for action in ("competitor_root_read", "competitor_root_selection", "competitor_root_request", "competitor_root_cancel")}
        with override_settings(ACCOUNT_RATE_LIMITS=limits):
            self.assertEqual(self.client.get(self.base, secure=True).status_code, 200)
            self.assertEqual(other.get(self.base, secure=True).status_code, 429)
            self.assertEqual(self.post("selection/").status_code, 200)
            self.assertEqual(self.post("selection/").status_code, 429)
            self.assertEqual(self.post(data=command).status_code, 202)
            self.assertEqual(self.post(data=command).status_code, 429)
            self.assertEqual(self.post(f"{job_id}/", {}).status_code, 202)
            self.assertEqual(self.post(f"{job_id}/", {}).status_code, 429)

    def test_post_serialization_queue_loss_rolls_back_rows_usage_and_dispatch_callbacks(self):
        command = self.command()
        original = api._response
        for mutate in (self.revoke,
            lambda: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2),
            lambda: EmailAddress.objects.filter(user=self.owner).update(verified=False)):
            def changed(data, *args, **kwargs):
                response = original(data, *args, **kwargs)
                if "job" in data: mutate()
                return response
            with patch.object(api, "_response", changed), patch("jobs.tasks.execute_competitor_collection_task.apply_async") as dispatch:
                response = self.post(data=command)
            self.assertEqual(response.status_code, 403, response.content)
            self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
            self.assertFalse(UsageReservation.objects.filter(provider=collection.PROVIDER).exists()); dispatch.assert_not_called()

    def test_preview_and_same_key_queue_final_original_source_cancel_and_natural_expiry(self):
        original = api._response
        for mutate in (self.revoke,
            lambda: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)):
            def changed_preview(data, *args, **kwargs):
                response = original(data, *args, **kwargs)
                if "selection" in data: mutate()
                return response
            with patch.object(api, "_response", changed_preview): response = self.post("selection/")
            self.assertEqual(response.status_code, 403)
        command = self.command()
        job_id = self.post(data=command).json()["job"]["id"]
        deadline = timezone.now() + timedelta(seconds=20)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=deadline - timedelta(days=30), ends_at=deadline)
        for boundary in ("source", "cancel", "expiry"):
            with transaction.atomic():
                now = [timezone.now()]
                def changed_queue(data, *args, **kwargs):
                    response = original(data, *args, **kwargs)
                    if "job" in data:
                        if boundary == "source": JobRun.objects.filter(pk=job_id).update(config_snapshot={})
                        elif boundary == "cancel": JobCancellation.objects.create(job_id=job_id, requested_by=self.owner)
                        else: now[0] = deadline
                    return response
                with patch("jobs.usage.timezone.now", side_effect=lambda: now[0]), patch.object(api, "_response", changed_queue):
                    response = self.post(data=command)
                self.assertIn(response.status_code, (403, 409), response.content)
                transaction.set_rollback(True)

    def test_post_serialization_private_full_source_caller_rows_cancel_and_expiry_are_fenced(self):
        command = self.command()
        job_id = self.post(data=command).json()["job"]["id"]
        collection.execute_competitor_collection(job_id, fetcher=self.fetcher())
        original = api._response
        def expire():
            now = timezone.now()
            OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=31), ends_at=now - timedelta(days=1))
        for mutate in (self.revoke,
            lambda: ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[]),
            lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner),
            lambda: Artifact.objects.filter(job_id=job_id).update(created_at=timezone.now() + timedelta(days=1)), expire):
            with transaction.atomic():
                def changed(data, *args, **kwargs):
                    response = original(data, *args, **kwargs)
                    if "evidence" in data: mutate()
                    return response
                with patch.object(api, "_response", changed): response = self.client.get(self.base + f"{job_id}/", secure=True)
                self.assertIn(response.status_code, (403, 409), response.content)
                self.assertNotIn(b"Public fixture", response.content)
                transaction.set_rollback(True)
        self.client.force_login(self.admin)
        with transaction.atomic():
            def changed_caller(data, *args, **kwargs):
                response = original(data, *args, **kwargs)
                if "evidence" in data: OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="owner")
                return response
            with patch.object(api, "_response", changed_caller): response = self.client.get(self.base + f"{job_id}/", secure=True)
            self.assertEqual(response.status_code, 403); transaction.set_rollback(True)

    def test_status_history_retained_expiry_no_current_evidence_and_final_hidden_status_drift(self):
        command = self.command()
        job_id = self.post(data=command).json()["job"]["id"]
        collection.execute_competitor_collection(job_id, fetcher=self.fetcher())
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=31), ends_at=now - timedelta(days=1))
        self.assertEqual(self.client.get(self.base, secure=True).status_code, 200)
        self.assertEqual(self.client.get(self.base + f"{job_id}/", secure=True).status_code, 403)
        self.assertEqual(self.post("selection/").status_code, 403)
        original = api._response
        for mutate in (lambda: JobRun.objects.filter(pk=job_id).update(config_snapshot={}),
            lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner)):
            with transaction.atomic():
                def changed(data, *args, **kwargs):
                    response = original(data, *args, **kwargs)
                    if "jobs" in data: mutate()
                    return response
                with patch.object(api, "_response", changed): response = self.client.get(self.base, secure=True)
                self.assertEqual(response.status_code, 403); transaction.set_rollback(True)
        other_project = Project.objects.create(organization=self.organization, name="Other scope", canonical_origin="https://other.example.invalid")
        path = f"/api/organizations/{self.organization.pk}/projects/{other_project.pk}/competitor-roots/{job_id}/"
        self.assertEqual(self.client.get(path, secure=True).status_code, 403)

    def test_natural_expiry_during_final_caller_check_withholds_private_response(self):
        command = self.command()
        job_id = self.post(data=command).json()["job"]["id"]
        collection.execute_competitor_collection(job_id, fetcher=self.fetcher())
        deadline = timezone.now() + timedelta(seconds=20)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=deadline - timedelta(days=30), ends_at=deadline)
        now, checks = [timezone.now()], [0]
        original = api._current
        def expire_after_current(*args):
            original(*args)
            checks[0] += 1
            if checks[0] == 2: now[0] = deadline
        with patch("jobs.usage.timezone.now", side_effect=lambda: now[0]), patch.object(api, "_current", side_effect=expire_after_current):
            response = self.client.get(self.base + f"{job_id}/", secure=True)
        self.assertEqual(response.status_code, 403); self.assertNotIn(b"Public fixture", response.content)
