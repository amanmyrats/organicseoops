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
from . import passive_tls_collection as collection
from . import test_passive_tls_collection as fixtures
from .models import JobCancellation, JobRun, UsageReservation


@override_settings(DEBUG=True, SECURE_SSL_REDIRECT=False, STORAGES=TEST_STORAGES,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "passive-tls-api"}})
class PassiveTLSApiTests(TransactionTestCase):
    verified = fixtures.PassiveTLSCollectionTests.verified
    transport = fixtures.PassiveTLSCollectionTests.transport

    def setUp(self):
        fixtures.PassiveTLSCollectionTests.setUp(self)
        self.client = Client(enforce_csrf_checks=True); self.client.force_login(self.owner)
        self.client.get("/_allauth/browser/v1/auth/session", secure=True)
        self.csrf = self.client.cookies["csrftoken"].value
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/passive-tls/"

    def post(self, suffix="", data=None):
        return self.client.post(self.base + suffix, json.dumps(self.data if data is None else data),
            content_type="application/json", secure=True, HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/")

    def command(self, key="tls-api-request"):
        preview = self.post("selection/"); self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(preview.json()["selection"]["method"], collection.METHOD)
        return {**self.data, "idempotency_key": key, "selection_digest": preview.json()["selection_digest"]}

    def test_genuine_preview_queue_own_lookup_private_original_tls_and_cancel_no_http(self):
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")):
            command = self.command()
            self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
            self.assertEqual(self.client.get(self.base + "?idempotency_key=tls-api-request", secure=True).json()["jobs"], [])
            queued = self.post(data=command); self.assertEqual(queued.status_code, 202, queued.content)
            job_id = queued.json()["job"]["id"]
            self.assertEqual(self.post(data=command).json()["job"]["id"], job_id)
            self.assertEqual(self.client.get(self.base + "?idempotency_key=tls-api-request", secure=True).json()["jobs"][0]["id"], job_id)
            self.assertTrue(collection.execute_passive_tls_collection(job_id, fetcher=self.transport()))
            self.connection.request.assert_not_called()
            detail = self.client.get(self.base + f"{job_id}/", secure=True); self.assertEqual(detail.status_code, 200, detail.content)
            result = detail.json()["evidence"]["collection"]
            self.assertEqual(result["method"], "passive-tls-evidence-v1")
            self.assertEqual(result["observed_at"], result["evidence"]["certificate_dates"]["observed_at"])
            self.assertEqual(result["evidence"]["negotiated_tls"]["version"], "TLSv1.3")
            self.assertFalse({"status", "url", "subject", "raw_certificate"} & set(result))
            self.assertNotIn(b"private", detail.content); self.assertNotIn(b"OCSP", detail.content)
            self.assertIn("no-store", detail["Cache-Control"]); self.assertEqual(detail["X-Robots-Tag"], "noindex, nofollow")
            pending = self.post(data=self.command("tls-api-cancel")).json()["job"]["id"]
            self.assertEqual(self.post(f"{pending}/", {}).status_code, 202)
            self.assertEqual(JobRun.objects.get(pk=pending).status, "cancelled")

    def test_strict_independent_permission_digest_route_and_handler_cannot_be_selected_by_client(self):
        command = self.command()
        for change in ({"collection_permission": 1}, {"observations": ["response_headers"]}, {"observations": ["negotiated_tls", "certificate_dates"]},
            {"origin": self.project.canonical_origin + "/"}, {"origin": self.project.canonical_origin + ":443"},
            {"selection_digest": "a" * 64}, {"handler": "collect_passive_headers"}, {"url": self.project.canonical_origin + "/"}):
            self.assertIn(self.post(data={**command, **change}).status_code, (403, 409))
        header = self.base.replace("passive-tls/", "passive-headers/")
        self.assertEqual(self.client.post(header, json.dumps(command), content_type="application/json", secure=True,
            HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/").status_code, 409)
        self.assertEqual(self.client.post(self.base, json.dumps(command), content_type="application/json", secure=True).status_code, 403)
        self.assertEqual(Client().get(self.base, secure=True).status_code, 401)
        self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
        self.client.force_login(self.member); self.assertEqual(self.client.get(self.base, secure=True).status_code, 403)

    def test_four_shared_ip_budgets_are_independent_of_each_other_and_headers(self):
        command = self.command(); job_id = self.post(data=command).json()["job"]["id"]
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        other = Client(); other.force_login(self.member); cache.clear()
        with override_settings(ACCOUNT_RATE_LIMITS={f"passive_tls_{action}": "1/m/ip" for action in ("read", "selection", "request", "cancel")}):
            self.assertEqual(self.client.get(self.base, secure=True).status_code, 200)
            self.assertEqual(other.get(self.base, secure=True).status_code, 429)
            self.assertEqual(self.client.get(self.base.replace("passive-tls/", "passive-headers/"), secure=True).status_code, 200)
            self.assertEqual(self.post("selection/").status_code, 200); self.assertEqual(self.post("selection/").status_code, 429)
            self.assertEqual(self.post(data=command).status_code, 202); self.assertEqual(self.post(data=command).status_code, 429)
            self.assertEqual(self.post(f"{job_id}/", {}).status_code, 202); self.assertEqual(self.post(f"{job_id}/", {}).status_code, 429)

    def test_foreign_nested_scope_other_actor_lookup_and_malformed_inputs(self):
        command = self.command(); job_id = self.post(data=command).json()["job"]["id"]
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        other = Client(); other.force_login(self.member)
        self.assertEqual(other.get(self.base + "?idempotency_key=tls-api-request", secure=True).json()["jobs"], [])
        foreign = create_organization(user=self.outsider, name="Foreign")
        project = create_project(organization=foreign, user=self.outsider, name="Other", canonical_origin="https://other.example.invalid")
        for org_id, project_id in ((foreign.pk, self.project.pk), (self.organization.pk, project.pk)):
            self.assertEqual(self.client.get(f"/api/organizations/{org_id}/projects/{project_id}/passive-tls/", secure=True).status_code, 404)
        second = Project.objects.create(organization=self.organization, name="Synthetic", canonical_origin="https://second.example.invalid")
        self.assertEqual(self.client.get(self.base.replace(f"projects/{self.project.pk}/", f"projects/{second.pk}/") + f"{job_id}/", secure=True).status_code, 403)
        header = self.base.replace("passive-tls/", "passive-headers/")
        self.assertEqual(self.client.get(header + f"{job_id}/", secure=True).status_code, 403)
        self.assertEqual(self.client.post(header + f"{job_id}/", "{}", content_type="application/json", secure=True,
            HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/").status_code, 403)
        for body in ('{"origin":"x","origin":"y"}', '{', '[]', 'null', '{"origin":NaN}', " " * 2049):
            self.assertEqual(self.client.post(self.base, body, content_type="application/json", secure=True,
                HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/").status_code, 409)
        self.assertEqual(self.post("?handler=collect_passive_headers", command).status_code, 400)
        for query in ("?idempotency_key=tls-api-request&idempotency_key=tls-api-request", "?handler=collect_passive_headers"):
            self.assertEqual(self.client.get(self.base + query, secure=True).status_code, 409)
        self.assertEqual(JobRun.objects.filter(handler=collection.HANDLER).count(), 1)

    def test_serialization_queue_rollback_hidden_source_usage_cancel_expiry_and_private_delivery_fences(self):
        command = self.command(); original = api._response
        def expire():
            OrganizationTrial.objects.filter(organization=self.organization).update(ends_at=timezone.now() - timedelta(microseconds=1))
        def revoke():
            ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64)
        for mutate in (revoke, expire):
            def changed(data, *args, **kwargs):
                response = original(data, *args, **kwargs)
                if "job" in data: mutate()
                return response
            with patch.object(api, "_response", changed): response = self.post(data=command)
            self.assertEqual(response.status_code, 403)
            self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
        job_id = self.post(data=command).json()["job"]["id"]
        for mutate in (revoke, expire, lambda: JobRun.objects.filter(pk=job_id).update(config_snapshot={}),
            lambda: UsageReservation.objects.filter(job_id=job_id).update(reserved_units=2),
            lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner)):
            with transaction.atomic():
                def changed(data, *args, **kwargs):
                    response = original(data, *args, **kwargs)
                    if "job" in data: mutate()
                    return response
                with patch.object(api, "_response", changed): response = self.post(data=command)
                self.assertEqual(response.status_code, 403, response.content); transaction.set_rollback(True)
        collection.execute_passive_tls_collection(job_id, fetcher=self.transport())
        for mutate in (revoke, expire, lambda: UsageReservation.objects.filter(job_id=job_id).update(actual_units=0)):
            with transaction.atomic():
                def changed(data, *args, **kwargs):
                    response = original(data, *args, **kwargs)
                    if "evidence" in data: mutate()
                    return response
                with patch.object(api, "_response", changed): response = self.client.get(self.base + f"{job_id}/", secure=True)
                self.assertIn(response.status_code, (403, 409)); self.assertNotIn(b"certificate_dates", response.content)
                transaction.set_rollback(True)

    def test_preview_and_history_final_hidden_changes_and_fixed_method_limits(self):
        original = api._response
        def changed_preview(data, *args, **kwargs):
            response = original(data, *args, **kwargs)
            if "selection" in data:
                ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(challenge_digest="a" * 64)
            return response
        with patch.object(api, "_response", changed_preview): response = self.post("selection/")
        self.assertEqual(response.status_code, 403)
        job_id = self.post(data=self.command()).json()["job"]["id"]
        for mutate in (lambda: JobRun.objects.filter(pk=job_id).update(config_snapshot={}),
            lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner)):
            with transaction.atomic():
                def changed_history(data, *args, **kwargs):
                    response = original(data, *args, **kwargs)
                    if "jobs" in data: mutate()
                    return response
                with patch.object(api, "_response", changed_history): response = self.client.get(self.base, secure=True)
                self.assertEqual(response.status_code, 403); transaction.set_rollback(True)
        self.assertEqual(self.client.get(self.base + "selection/", secure=True).status_code, 405)
        self.assertEqual(self.client.put(self.base, "", secure=True, HTTP_X_CSRFTOKEN=self.csrf,
            HTTP_REFERER="https://testserver/").status_code, 405)
