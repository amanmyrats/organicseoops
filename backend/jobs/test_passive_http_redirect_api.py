import json
from unittest.mock import patch

from django.core.cache import cache
from django.db import transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, Project, ProjectOriginVerification
from . import passive_header_api as api
from . import passive_http_redirect_collection as collection
from . import test_passive_http_redirect_collection as fixtures
from . import test_passive_redirect_api as api_fixtures
from .models import JobCancellation, JobRun


@override_settings(DEBUG=True, SECURE_SSL_REDIRECT=False, STORAGES=TEST_STORAGES,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "passive-http-redirect-api"}})
class PassiveHTTPRedirectApiTests(TransactionTestCase):
    verified = fixtures.PassiveHTTPRedirectCollectionTests.verified
    transport = fixtures.PassiveHTTPRedirectCollectionTests.transport
    WIRE = fixtures.PassiveHTTPRedirectCollectionTests.WIRE
    post = api_fixtures.PassiveRedirectApiTests.post

    def setUp(self):
        fixtures.PassiveHTTPRedirectCollectionTests.setUp(self)
        self.client = Client(enforce_csrf_checks=True); self.client.force_login(self.owner)
        self.client.get("/_allauth/browser/v1/auth/session", secure=True)
        self.csrf = self.client.cookies["csrftoken"].value
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/passive-http-redirects/"

    def command(self, key="http-redirect-api-request"):
        preview = self.post("selection/"); self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(preview.json()["selection"]["method"], collection.METHOD)
        self.assertEqual(preview.json()["selection"]["binding"]["observations"], ["http_response_location"])
        return {**self.data, "idempotency_key": key, "selection_digest": preview.json()["selection_digest"]}

    def collected(self):
        command = self.command(); response = self.post(data=command); self.assertEqual(response.status_code, 202, response.content)
        job_id = response.json()["job"]["id"]
        self.assertTrue(collection.execute_passive_http_redirect_collection(job_id, fetcher=self.transport(wire=self.WIRE)))
        return job_id, command

    def test_genuine_preview_queue_own_key_current_private_plaintext_detail_nullable_syntax_and_cancel(self):
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")):
            command = self.command(); self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
            queued = self.post(data=command); self.assertEqual(queued.status_code, 202, queued.content); job_id = queued.json()["job"]["id"]
            self.assertEqual(self.post(data=command).json()["job"]["id"], job_id)
            self.assertEqual(self.client.get(self.base + "?idempotency_key=" + command["idempotency_key"], secure=True).json()["jobs"][0]["id"], job_id)
            self.assertTrue(collection.execute_passive_http_redirect_collection(job_id, fetcher=self.transport(wire=self.WIRE)))
            detail = self.client.get(self.base + f"{job_id}/", secure=True); self.assertEqual(detail.status_code, 200, detail.content)
            result = detail.json()["evidence"]["collection"]; location = result["evidence"]["response_location"]
            self.assertEqual((result["method"], location["target_scheme"], location["same_origin"], location["same_hostname_default_https"]),
                ("passive-http-redirect-evidence-v1", "https", False, True))
            self.assertEqual(result["observed_at"], result["evidence"]["observed_at"])
            self.assertIn("not_authenticated_identity_observed_https_followed_upgrade", result["interpretation"])
            for private in (b"secret=value", b"private body", b"raw_location", self.challenge.encode()): self.assertNotIn(private, detail.content)
            lexical = self.post(data=self.command("http-redirect-lexical")).json()["job"]["id"]
            collection.execute_passive_http_redirect_collection(lexical, fetcher=self.transport(wire=b"HTTP/1.1 200 OK\r\nLocation: javascript:private\r\n\r\n"))
            values = self.client.get(self.base + f"{lexical}/", secure=True).json()["evidence"]["collection"]["evidence"]["response_location"]
            self.assertEqual((values["target_scheme"], values["same_origin"], values["same_hostname_default_https"]), (None, None, None))
            pending = self.post(data=self.command("http-redirect-cancel")).json()["job"]["id"]
            ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64)
            self.assertEqual(self.post(f"{pending}/", {}).status_code, 202)
            self.assertEqual(JobRun.objects.get(pk=pending).status, "cancelled")

    def test_exact_fields_csrf_permission_role_family_tenant_own_key_and_fixed_methods(self):
        command = self.command()
        for changes in ({"collection_permission": 1}, {"observations": ["response_location"]}, {"url": self.https_origin + "/public"},
            {"handler": collection.HANDLER}, {"selection_digest": "a" * 64}):
            self.assertIn(self.post(data={**command, **changes}).status_code, (403, 409))
        for family in ("passive-headers", "passive-tls", "passive-resources", "passive-redirects"):
            self.assertEqual(self.post(data=command, base=self.base.replace("passive-http-redirects", family)).status_code, 409)
        self.assertEqual(self.client.post(self.base, json.dumps(command), content_type="application/json", secure=True).status_code, 403)
        self.assertEqual(Client().get(self.base, secure=True).status_code, 401)
        self.assertEqual(self.client.get(self.base + "selection/", secure=True).status_code, 405)
        self.assertEqual(self.post("?handler=collect_passive_redirects", command).status_code, 400)
        cache.clear()
        for body in ('{"url":"x","url":"y"}', '{', '[]', 'null', '{"url":NaN}', " " * 2049):
            self.assertEqual(self.client.post(self.base, body, content_type="application/json", secure=True,
                HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/").status_code, 409)
        self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
        cache.clear()
        job_id = self.post(data=command).json()["job"]["id"]
        for family in ("passive-headers", "passive-tls", "passive-resources", "passive-redirects"):
            self.assertEqual(self.client.get(self.base.replace("passive-http-redirects", family) + f"{job_id}/", secure=True).status_code, 403)
        other = Project.objects.create(organization=self.organization, name="Other scope", canonical_origin="http://other.example.invalid")
        self.assertEqual(self.client.get(self.base.replace(f"projects/{self.project.pk}/", f"projects/{other.pk}/") + f"{job_id}/", secure=True).status_code, 403)
        self.client.force_login(self.member); self.assertEqual(self.client.get(self.base, secure=True).status_code, 403)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(self.client.get(self.base + "?idempotency_key=" + command["idempotency_key"], secure=True).json()["jobs"], [])

    def test_four_independent_maintained_http_ip_budgets_and_original_family_reads(self):
        command = self.command(); job_id = self.post(data=command).json()["job"]["id"]; cache.clear()
        with override_settings(ACCOUNT_RATE_LIMITS={f"passive_http_redirect_{action}": "1/m/ip" for action in ("read", "selection", "request", "cancel")}):
            self.assertEqual(self.client.get(self.base, secure=True).status_code, 200); self.assertEqual(self.client.get(self.base, secure=True).status_code, 429)
            for family in ("passive-headers", "passive-tls", "passive-resources", "passive-redirects"):
                self.assertEqual(self.client.get(self.base.replace("passive-http-redirects", family), secure=True).status_code, 200)
            self.assertEqual(self.post("selection/").status_code, 200); self.assertEqual(self.post("selection/").status_code, 429)
            self.assertEqual(self.post(data=command).status_code, 202); self.assertEqual(self.post(data=command).status_code, 429)
            self.assertEqual(self.post(f"{job_id}/", {}).status_code, 202); self.assertEqual(self.post(f"{job_id}/", {}).status_code, 429)

    def test_serialization_queue_rollback_and_current_private_original_metadata_authority_cancel(self):
        command = self.command(); response = api._response
        def changed(data, *args, **kwargs):
            value = response(data, *args, **kwargs)
            if "job" in data: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64)
            return value
        with patch.object(api, "_response", changed): self.assertEqual(self.post(data=command).status_code, 403)
        self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
        job_id, _ = self.collected()
        for mutate in (lambda: ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="b" * 64),
            lambda: JobRun.objects.filter(pk=job_id).update(config_snapshot={}),
            lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member")):
            with transaction.atomic():
                def changed(data, *args, **kwargs):
                    value = response(data, *args, **kwargs)
                    if "evidence" in data: mutate()
                    return value
                with patch.object(api, "_response", changed): result = self.client.get(self.base + f"{job_id}/", secure=True)
                self.assertIn(result.status_code, (403, 409)); self.assertNotIn(b"response_location", result.content)
                transaction.set_rollback(True)

    def test_natural_expiry_after_final_metadata_or_final_role_read_withholds_private_delivery(self):
        job_id, _ = self.collected()
        for attribute, last in (("_metadata", 2), ("_current", 2)):
            original = getattr(api, attribute); now = [timezone.now()]; end = self.organization.trial.ends_at; calls = 0
            def slow(*args, **kwargs):
                nonlocal calls
                value = original(*args, **kwargs); calls += 1
                if calls == last: now[0] = end
                return value
            with patch.object(api, attribute, slow), patch("jobs.usage.timezone.now", side_effect=lambda: now[0]):
                result = self.client.get(self.base + f"{job_id}/", secure=True)
            self.assertEqual(result.status_code, 403); self.assertNotIn(b"response_location", result.content)
            self.assertEqual(calls, last)
