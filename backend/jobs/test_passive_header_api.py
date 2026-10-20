import json
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TransactionTestCase, override_settings
from django.db import transaction
from django.utils import timezone
from tenancy.models import OrganizationMembership, OrganizationTrial, ProjectOriginVerification, Project
from tenancy.services import create_organization, create_project

from . import passive_header_api as api
from . import passive_header_collection as collection
from . import test_passive_header_collection as fixtures
from .models import JobCancellation, JobRun


@override_settings(DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "passive-header-api"}})
class PassiveHeaderApiTests(TransactionTestCase):
    verified = fixtures.PassiveHeaderCollectionTests.verified
    transport = fixtures.PassiveHeaderCollectionTests.transport
    revoke = fixtures.PassiveHeaderCollectionTests.revoke

    def setUp(self):
        # Reuse genuine original verification and fully stub outgoing Celery dispatch.
        fixtures.PassiveHeaderCollectionTests.setUp(self)
        self.client = Client(enforce_csrf_checks=True); self.client.force_login(self.owner)
        self.client.get("/_allauth/browser/v1/auth/session", secure=True)
        self.csrf = self.client.cookies["csrftoken"].value
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/passive-headers/"

    def post(self, suffix="", data=None, **headers):
        return self.client.post(self.base + suffix, data=json.dumps(self.data if data is None else data),
            content_type="application/json", secure=True, HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/", **headers)

    def command(self, key="header-api-request"):
        preview = self.post("selection/")
        self.assertEqual(preview.status_code, 200, preview.content)
        return {**self.data, "idempotency_key": key, "selection_digest": preview.json()["selection_digest"]}

    def test_actual_preview_explicit_queue_own_lookup_private_readback_and_cancel_without_site_requests(self):
        with override_settings(STORAGES=fixtures.TEST_STORAGES), patch("socket.create_connection", side_effect=AssertionError("No egress")):
            command = self.command()
            self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
            missing = self.client.get(self.base + "?idempotency_key=header-api-request", secure=True)
            self.assertEqual(missing.json()["jobs"], [])
            response = self.post(data=command); self.assertEqual(response.status_code, 202, response.content)
            job_id = response.json()["job"]["id"]
            self.assertEqual(self.post(data=command).json()["job"]["id"], job_id)
            self.assertEqual(self.client.get(self.base + "?idempotency_key=header-api-request", secure=True).json()["jobs"][0]["id"], job_id)
            self.assertTrue(collection.execute_passive_header_collection(job_id, fetcher=self.transport()))
            detail = self.client.get(self.base + f"{job_id}/", secure=True)
            self.assertEqual(detail.status_code, 200, detail.content)
            self.assertEqual(detail.json()["evidence"]["collection"]["evidence"]["cookies"]["observed_fields"], 2)
            self.assertNotIn(b"nonce-private", detail.content); self.assertNotIn(b"secret", detail.content)
            self.assertIn("no-store", detail["Cache-Control"]); self.assertEqual(detail["X-Robots-Tag"], "noindex, nofollow")
            pending = self.post(data=self.command("header-api-cancel")).json()["job"]["id"]
            self.assertEqual(self.post(f"{pending}/", {}).status_code, 202)
            self.assertEqual(JobRun.objects.get(pk=pending).status, "cancelled")

    def test_csrf_roles_strict_fields_stale_selection_and_independent_read_limits(self):
        command = self.command()
        without_csrf = self.client.post(self.base, json.dumps(command), content_type="application/json", secure=True)
        self.assertEqual(without_csrf.status_code, 403)
        for changes in ({"raw_headers": "private"}, {"collection_permission": 1}, {"selection_digest": "a" * 64},
                        {"url": self.project.canonical_origin + "/another"}):
            self.assertIn(self.post(data={**command, **changes}).status_code, (403, 409))
        self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
        self.assertEqual(self.client.get(self.base + "?actor_id=1", secure=True).status_code, 409)
        self.assertEqual(self.client.put(self.base, "", HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_REFERER="https://testserver/", secure=True).status_code, 405)
        self.assertEqual(Client().get(self.base, secure=True).status_code, 401)
        cache.clear()
        with override_settings(ACCOUNT_RATE_LIMITS={"passive_header_read": "1/m/user"}):
            self.assertEqual(self.client.get(self.base, secure=True).status_code, 200)
            self.assertEqual(self.client.get(self.base, secure=True).status_code, 429)
            self.assertEqual(self.post("selection/").status_code, 200)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.base, secure=True).status_code, 403)

    def test_post_serialization_authority_loss_rolls_back_queue_or_withholds_private_evidence(self):
        command = self.command()
        original = api._response
        def changed(data, *args, **kwargs):
            response = original(data, *args, **kwargs)
            if "job" in data: self.revoke()
            return response
        with patch.object(api, "_response", changed):
            response = self.post(data=command)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
        # Source mutation and queue/dispatch callbacks rolled back together.
        queued = self.post(data=command); self.assertEqual(queued.status_code, 202)
        job_id = queued.json()["job"]["id"]
        with override_settings(STORAGES=fixtures.TEST_STORAGES):
            collection.execute_passive_header_collection(job_id, fetcher=self.transport())
            with patch.object(api, "_response", changed): response = self.client.get(self.base + f"{job_id}/", secure=True)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"cookies", response.content)

    def test_shared_ip_and_each_command_budget_are_independent(self):
        command = self.command()
        job_id = self.post(data=command).json()["job"]["id"]
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        other = Client(enforce_csrf_checks=True); other.force_login(self.member)
        cache.clear()
        limits = {action: "1/m/ip" for action in ("passive_header_read", "passive_header_selection",
            "passive_header_request", "passive_header_cancel")}
        with override_settings(ACCOUNT_RATE_LIMITS=limits):
            self.assertEqual(self.client.get(self.base, secure=True).status_code, 200)
            self.assertEqual(other.get(self.base, secure=True).status_code, 429)
            self.assertEqual(self.post("selection/").status_code, 200)
            self.assertEqual(self.post("selection/").status_code, 429)
            self.assertEqual(self.post(data=command).status_code, 202)
            self.assertEqual(self.post(data=command).status_code, 429)
            self.assertEqual(self.post(f"{job_id}/", {}).status_code, 202)
            self.assertEqual(self.post(f"{job_id}/", {}).status_code, 429)

    def test_foreign_scope_other_actor_key_and_strict_json_never_authorize_a_command(self):
        command = self.command()
        job_id = self.post(data=command).json()["job"]["id"]
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        other = Client(); other.force_login(self.member)
        self.assertEqual(other.get(self.base + "?idempotency_key=header-api-request", secure=True).json()["jobs"], [])
        foreign = create_organization(user=self.outsider, name="Foreign")
        foreign_project = create_project(organization=foreign, user=self.outsider, name="Other", canonical_origin="https://other.example.invalid")
        for org_id, project_id in ((foreign.pk, self.project.pk), (self.organization.pk, foreign_project.pk)):
            path = f"/api/organizations/{org_id}/projects/{project_id}/passive-headers/"
            self.assertEqual(self.client.get(path, secure=True).status_code, 404)
        # Synthetic second project isolates nested-ID denial without changing commercial policy.
        own_other = Project.objects.create(organization=self.organization, name="Second", canonical_origin="https://second.example.invalid")
        path = f"/api/organizations/{self.organization.pk}/projects/{own_other.pk}/passive-headers/{job_id}/"
        self.assertEqual(self.client.get(path, secure=True).status_code, 403)
        for body in ('{"url":"x","url":"y"}', '{', '[]', 'null', '{"url":NaN}', json.dumps({**command, "actor_id": self.owner.pk}), " " * 2049):
            response = self.client.post(self.base, body, content_type="application/json", secure=True,
                HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/")
            self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(self.post("?idempotency_key=posted", command).status_code, 400)
        for query in ("?idempotency_key=header-api-request&idempotency_key=header-api-request", "?extra=x"):
            self.assertEqual(self.client.get(self.base + query, secure=True).status_code, 409)
        self.assertEqual(JobRun.objects.filter(handler=collection.HANDLER).count(), 1)

    def test_serialized_hidden_job_cancellation_source_and_natural_expiry_are_fenced(self):
        command = self.command()
        job_id = self.post(data=command).json()["job"]["id"]
        original = api._response
        def expire():
            start = timezone.now() - timedelta(days=31)
            OrganizationTrial.objects.filter(organization=self.organization).update(started_at=start, ends_at=start + timedelta(days=30))
        for mutate in (lambda: JobRun.objects.filter(pk=job_id).update(config_snapshot={}),
            lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner),
            lambda: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64), expire):
            with self.subTest(mutate=mutate), transaction.atomic():
                def changed(data, *args, **kwargs):
                    response = original(data, *args, **kwargs)
                    if "job" in data: mutate()
                    return response
                with patch.object(api, "_response", changed): response = self.post(data=command)
                self.assertEqual(response.status_code, 403, response.content)
                transaction.set_rollback(True)
        for mutate in (lambda: JobRun.objects.filter(pk=job_id).update(config_snapshot={}),
            lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner)):
            with transaction.atomic():
                def changed_history(data, *args, **kwargs):
                    response = original(data, *args, **kwargs)
                    if "jobs" in data: mutate()
                    return response
                with patch.object(api, "_response", changed_history): response = self.client.get(self.base, secure=True)
                self.assertEqual(response.status_code, 403)
                transaction.set_rollback(True)
        with override_settings(STORAGES=fixtures.TEST_STORAGES):
            collection.execute_passive_header_collection(job_id, fetcher=self.transport())
            with patch.object(api, "_response", lambda data, *args, **kwargs:
                (original(data, *args, **kwargs), expire() if "evidence" in data else None)[0]):
                response = self.client.get(self.base + f"{job_id}/", secure=True)
            self.assertEqual(response.status_code, 403); self.assertNotIn(b"cookies", response.content)
