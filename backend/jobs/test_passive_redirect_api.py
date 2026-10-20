import json
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db import transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from tenancy.models import OrganizationMembership, OrganizationTrial, Project, ProjectOriginVerification
from tenancy.services import create_organization, create_project
from config.test_foundations import TEST_STORAGES
from . import passive_header_api as api
from . import passive_redirect_collection as collection
from . import test_passive_redirect_collection as fixtures
from .models import JobCancellation, JobRun, UsageReservation


@override_settings(DEBUG=True, SECURE_SSL_REDIRECT=False, STORAGES=TEST_STORAGES,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "passive-redirect-api"}})
class PassiveRedirectApiTests(TransactionTestCase):
    verified = fixtures.PassiveRedirectCollectionTests.verified
    transport = fixtures.PassiveRedirectCollectionTests.transport
    WIRE = fixtures.PassiveRedirectCollectionTests.WIRE

    def setUp(self):
        fixtures.PassiveRedirectCollectionTests.setUp(self)
        self.client = Client(enforce_csrf_checks=True); self.client.force_login(self.owner)
        self.client.get("/_allauth/browser/v1/auth/session", secure=True)
        self.csrf = self.client.cookies["csrftoken"].value
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/passive-redirects/"

    def post(self, suffix="", data=None, base=None):
        return self.client.post((base or self.base) + suffix, json.dumps(self.data if data is None else data),
            content_type="application/json", secure=True, HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/")

    def command(self, key="redirect-api-request"):
        preview = self.post("selection/"); self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(preview.json()["selection"]["method"], collection.METHOD)
        return {**self.data, "idempotency_key": key, "selection_digest": preview.json()["selection_digest"]}

    def test_genuine_preview_queue_own_lookup_private_original_capture_null_and_cancel(self):
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")):
            command = self.command(); self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
            self.assertEqual(self.client.get(self.base + "?idempotency_key=redirect-api-request", secure=True).json()["jobs"], [])
            queued = self.post(data=command); self.assertEqual(queued.status_code, 202, queued.content)
            job_id = queued.json()["job"]["id"]
            self.assertEqual(self.post(data=command).json()["job"]["id"], job_id)
            self.assertEqual(self.client.get(self.base + "?idempotency_key=redirect-api-request", secure=True).json()["jobs"][0]["id"], job_id)
            self.assertTrue(collection.execute_passive_redirect_collection(job_id, fetcher=self.transport(wire=self.WIRE)))
            self.connection.request.assert_called_once()
            detail = self.client.get(self.base + f"{job_id}/", secure=True); self.assertEqual(detail.status_code, 200, detail.content)
            result = detail.json()["evidence"]["collection"]
            self.assertEqual(result["method"], "passive-redirect-evidence-v1")
            self.assertEqual(result["observed_at"], result["evidence"]["observed_at"])
            self.assertEqual(result["observed_at"], JobRun.objects.get(pk=job_id).citations.get().observed_at.isoformat(timespec="microseconds"))
            location = result["evidence"]["response_location"]
            self.assertEqual((location["response_status"], location["redirect_status"], location["target_scheme"], location["same_origin"]), (302, True, "http", False))
            for raw in (b"private.invalid", b"secret=value", b"raw_location", b"response_headers", self.challenge.encode()): self.assertNotIn(raw, detail.content)
            self.assertIn("no-store", detail["Cache-Control"]); self.assertEqual(detail["X-Robots-Tag"], "noindex, nofollow")
            lexical = self.post(data=self.command("redirect-api-lexical")).json()["job"]["id"]
            collection.execute_passive_redirect_collection(lexical, fetcher=self.transport(wire=b"HTTP/1.1 200 OK\r\nLocation: javascript:private\r\n\r\n"))
            location = self.client.get(self.base + f"{lexical}/", secure=True).json()["evidence"]["collection"]["evidence"]["response_location"]
            self.assertEqual((location["location_state"], location["target_scheme"], location["same_origin"]), ("single_unclassified", None, None))
            pending = self.post(data=self.command("redirect-api-cancel")).json()["job"]["id"]
            self.assertEqual(self.post(f"{pending}/", {}).status_code, 202); self.assertEqual(JobRun.objects.get(pk=pending).status, "cancelled")

    def test_strict_named_permission_digest_fixed_family_csrf_and_actor(self):
        command = self.command()
        for change in ({"collection_permission": 1}, {"observations": ["response_headers"]}, {"observations": ["static_resource_references"]},
            {"observations": ["response_location", "response_headers"]}, {"url": self.data["url"] + "?q=x"},
            {"selection_digest": "a" * 64}, {"handler": collection.HANDLER}, {"origin": self.project.canonical_origin}):
            self.assertIn(self.post(data={**command, **change}).status_code, (403, 409))
        for family in ("passive-headers", "passive-tls", "passive-resources"):
            self.assertEqual(self.post(data=command, base=self.base.replace("passive-redirects", family)).status_code, 409)
        self.assertEqual(self.client.post(self.base, json.dumps(command), content_type="application/json", secure=True).status_code, 403)
        self.assertEqual(Client().get(self.base, secure=True).status_code, 401)
        self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
        self.client.force_login(self.member); self.assertEqual(self.client.get(self.base, secure=True).status_code, 403)

    def test_four_shared_ip_budgets_independent_from_each_other_and_original_families(self):
        command = self.command(); job_id = self.post(data=command).json()["job"]["id"]
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        other = Client(); other.force_login(self.member); cache.clear()
        with override_settings(ACCOUNT_RATE_LIMITS={f"passive_redirect_{action}": "1/m/ip" for action in ("read", "selection", "request", "cancel")}):
            self.assertEqual(self.client.get(self.base, secure=True).status_code, 200); self.assertEqual(other.get(self.base, secure=True).status_code, 429)
            for family in ("passive-headers", "passive-tls", "passive-resources"):
                self.assertEqual(self.client.get(self.base.replace("passive-redirects", family), secure=True).status_code, 200)
            self.assertEqual(self.post("selection/").status_code, 200); self.assertEqual(self.post("selection/").status_code, 429)
            self.assertEqual(self.post(data=command).status_code, 202); self.assertEqual(self.post(data=command).status_code, 429)
            self.assertEqual(self.post(f"{job_id}/", {}).status_code, 202); self.assertEqual(self.post(f"{job_id}/", {}).status_code, 429)

    def test_nested_foreign_other_actor_family_lookup_and_malformed_inputs(self):
        command = self.command(); job_id = self.post(data=command).json()["job"]["id"]
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        other = Client(); other.force_login(self.member)
        self.assertEqual(other.get(self.base + "?idempotency_key=redirect-api-request", secure=True).json()["jobs"], [])
        foreign = create_organization(user=self.outsider, name="Foreign")
        project = create_project(organization=foreign, user=self.outsider, name="Other", canonical_origin="https://other.example.invalid")
        for org_id, project_id in ((foreign.pk, self.project.pk), (self.organization.pk, project.pk)):
            self.assertEqual(self.client.get(f"/api/organizations/{org_id}/projects/{project_id}/passive-redirects/", secure=True).status_code, 404)
        second = Project.objects.create(organization=self.organization, name="Synthetic", canonical_origin="https://second.example.invalid")
        self.assertEqual(self.client.get(self.base.replace(f"projects/{self.project.pk}/", f"projects/{second.pk}/") + f"{job_id}/", secure=True).status_code, 403)
        for family in ("passive-headers", "passive-tls", "passive-resources"):
            base = self.base.replace("passive-redirects", family)
            self.assertEqual(self.client.get(base + f"{job_id}/", secure=True).status_code, 403); self.assertEqual(self.post(f"{job_id}/", {}, base).status_code, 403)
        for body in ('{"url":"x","url":"y"}', '{', '[]', 'null', '{"url":NaN}', " " * 2049):
            self.assertEqual(self.client.post(self.base, body, content_type="application/json", secure=True,
                HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/").status_code, 409)
        self.assertEqual(self.post("?handler=collect_passive_headers", command).status_code, 400)
        for query in ("?idempotency_key=redirect-api-request&idempotency_key=redirect-api-request", "?handler=collect_passive_resources"):
            self.assertEqual(self.client.get(self.base + query, secure=True).status_code, 409)
        self.assertEqual(JobRun.objects.filter(handler=collection.HANDLER).count(), 1)

    def test_serialization_queue_rollback_source_usage_cancel_expiry_and_private_final_fences(self):
        command = self.command(); original = api._response
        def expire(): OrganizationTrial.objects.filter(organization=self.organization).update(ends_at=timezone.now() - timedelta(microseconds=1))
        def revoke(): ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64)
        for mutate in (revoke, expire):
            def changed(data, *args, **kwargs):
                response = original(data, *args, **kwargs)
                if "job" in data: mutate()
                return response
            with patch.object(api, "_response", changed): response = self.post(data=command)
            self.assertEqual(response.status_code, 403); self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
        job_id = self.post(data=command).json()["job"]["id"]
        for mutate in (revoke, expire, lambda: JobRun.objects.filter(pk=job_id).update(config_snapshot={}),
            lambda: UsageReservation.objects.filter(job_id=job_id).update(reserved_units=2), lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner)):
            with transaction.atomic():
                def changed(data, *args, **kwargs):
                    response = original(data, *args, **kwargs)
                    if "job" in data: mutate()
                    return response
                with patch.object(api, "_response", changed): response = self.post(data=command)
                self.assertEqual(response.status_code, 403); transaction.set_rollback(True)
        collection.execute_passive_redirect_collection(job_id, fetcher=self.transport(wire=self.WIRE))
        for mutate in (revoke, expire, lambda: UsageReservation.objects.filter(job_id=job_id).update(actual_units=0),
            lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner)):
            with transaction.atomic():
                def changed(data, *args, **kwargs):
                    response = original(data, *args, **kwargs)
                    if "evidence" in data: mutate()
                    return response
                with patch.object(api, "_response", changed): response = self.client.get(self.base + f"{job_id}/", secure=True)
                self.assertIn(response.status_code, (403, 409)); self.assertNotIn(b"response_location", response.content); transaction.set_rollback(True)

    def test_preview_history_final_hidden_loss_and_fixed_methods(self):
        original = api._response
        def changed_preview(data, *args, **kwargs):
            response = original(data, *args, **kwargs)
            if "selection" in data: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64)
            return response
        with patch.object(api, "_response", changed_preview): response = self.post("selection/")
        self.assertEqual(response.status_code, 403)
        job_id = self.post(data=self.command()).json()["job"]["id"]
        for mutate in (lambda: JobRun.objects.filter(pk=job_id).update(config_snapshot={}), lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner)):
            with transaction.atomic():
                def changed_history(data, *args, **kwargs):
                    response = original(data, *args, **kwargs)
                    if "jobs" in data: mutate()
                    return response
                with patch.object(api, "_response", changed_history): response = self.client.get(self.base, secure=True)
                self.assertEqual(response.status_code, 403); transaction.set_rollback(True)
        self.assertEqual(self.client.get(self.base + "selection/", secure=True).status_code, 405)
        self.assertEqual(self.client.put(self.base, "", secure=True, HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/").status_code, 405)
