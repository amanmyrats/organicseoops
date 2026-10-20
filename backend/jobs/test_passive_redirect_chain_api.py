import json
from unittest.mock import patch

from django.core.cache import cache
from django.db import transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, Project, ProjectOriginVerification
from . import passive_header_api as api
from . import passive_header_collection as lifecycle
from . import passive_redirect_chain_collection as collection
from . import test_passive_redirect_chain_collection as fixtures
from . import test_passive_redirect_api as api_fixtures
from .models import JobCancellation, JobRun


@override_settings(DEBUG=True, SECURE_SSL_REDIRECT=False, STORAGES=TEST_STORAGES,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "passive-chain-api"}})
class PassiveRedirectChainApiTests(TransactionTestCase):
    verified = fixtures.PassiveRedirectChainCollectionTests.verified
    transport = fixtures.PassiveRedirectChainCollectionTests.transport
    post = api_fixtures.PassiveRedirectApiTests.post

    def setUp(self):
        fixtures.PassiveRedirectChainCollectionTests.setUp(self)
        self.client = Client(enforce_csrf_checks=True); self.client.force_login(self.owner)
        self.client.get("/_allauth/browser/v1/auth/session", secure=True)
        self.csrf = self.client.cookies["csrftoken"].value
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/passive-redirect-chain/"

    def command(self, key="chain-api-request"):
        preview = self.post("selection/"); self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(preview.json()["selection"]["method"], collection.METHOD)
        self.assertEqual(preview.json()["selection"]["binding"]["observations"], ["redirect_chain"])
        return {**self.data, "idempotency_key": key, "selection_digest": preview.json()["selection_digest"]}

    def collected(self):
        command = self.command(); response = self.post(data=command); self.assertEqual(response.status_code, 202, response.content)
        job_id = response.json()["job"]["id"]
        self.assertTrue(collection.execute_passive_redirect_chain_collection(job_id, fetcher=self.transport()[0]))
        return job_id, command

    def test_genuine_no_egress_preview_queue_own_key_current_original_multi_hop_and_cancel_after_source_loss(self):
        unvisited = self.verified("https://www.security.example.com")
        self.data["target_urls"].append("https://www.security.example.com/unvisited")
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")):
            command = self.command(); self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
            queued = self.post(data=command); self.assertEqual(queued.status_code, 202, queued.content); job_id = queued.json()["job"]["id"]
            self.assertEqual(self.post(data=command).json()["job"]["id"], job_id)
            self.assertEqual(self.client.get(self.base + "?idempotency_key=" + command["idempotency_key"], secure=True).json()["jobs"][0]["id"], job_id)
            fetcher, connections, responses, *_ = self.transport({**self.data, "target_urls": self.data["target_urls"][:1]})
            self.assertTrue(collection.execute_passive_redirect_chain_collection(job_id, fetcher=fetcher))
            detail = self.client.get(self.base + f"{job_id}/", secure=True); self.assertEqual(detail.status_code, 200, detail.content)
            result = detail.json()["evidence"]["collection"]
            self.assertEqual([hop["url"] for hop in result["evidence"]["hops"]], [self.data["url"], self.data["target_urls"][0]])
            binding = detail.json()["evidence"]["binding"]
            self.assertEqual(binding, JobRun.objects.get(pk=job_id).config_snapshot["binding"])
            self.assertEqual(binding["target_urls"], self.data["target_urls"])
            self.assertEqual([row["origin"] for row in binding["origins"]], [self.http, self.https, "https://www.security.example.com"])
            self.assertEqual(result["evidence"]["state"], "terminal_response")
            self.assertEqual(result["observed_at"], result["evidence"]["hops"][0]["observed_at"])
            self.assertEqual(result["last_observed_at"], result["evidence"]["hops"][-1]["observed_at"])
            for raw in (b"private", b"secret", self.challenge.encode()): self.assertNotIn(raw, detail.content)
            for conn, response in zip(connections, responses): conn.request.assert_called_once(); response.read.assert_not_called()
            with transaction.atomic():
                ProjectOriginVerification.objects.filter(pk=unvisited.pk).update(challenge_digest="c" * 64)
                denied = self.client.get(self.base + f"{job_id}/", secure=True)
                self.assertEqual(denied.status_code, 403); self.assertNotIn(b"binding", denied.content)
                transaction.set_rollback(True)
            pending = self.post(data=self.command("chain-api-cancel")).json()["job"]["id"]
            ProjectOriginVerification.objects.filter(pk=self.http_verification.pk).update(challenge_digest="a" * 64)
            self.assertEqual(self.client.get(self.base + f"{job_id}/", secure=True).status_code, 403)
            self.assertEqual(self.client.get(self.base, secure=True).status_code, 200)
            self.assertEqual(self.post(f"{pending}/", {}).status_code, 202)
            self.assertEqual(JobRun.objects.get(pk=pending).status, "cancelled")

    def test_actual_six_maximum_paths_preview_queue_private_detail_and_exact_8k_command_bound(self):
        prefix = self.http + "/"; self.data["url"] = prefix + "x" * (1024 - len(prefix)); targets = []
        for index in range(5):
            prefix = self.https + f"/page-{index}-"; targets.append(prefix + "x" * (1024 - len(prefix)))
        self.data["target_urls"] = targets
        body = json.dumps(self.data); self.assertGreater(len(body.encode()), 2048)
        padded = body + " " * (8192 - len(body.encode()))
        preview = self.client.post(self.base + "selection/", padded, content_type="application/json", secure=True,
            HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/")
        self.assertEqual(preview.status_code, 200, preview.content)
        command = {**self.data, "idempotency_key": "chain-api-max-paths", "selection_digest": preview.json()["selection_digest"]}
        queued = self.post(data=command); self.assertEqual(queued.status_code, 202, queued.content); job_id = queued.json()["job"]["id"]
        collection.execute_passive_redirect_chain_collection(job_id, fetcher=self.transport()[0])
        detail = self.client.get(self.base + f"{job_id}/", secure=True); self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual([hop["url"] for hop in detail.json()["evidence"]["collection"]["evidence"]["hops"]], [self.data["url"], *targets])
        self.assertGreater(JobRun.objects.get(pk=job_id).artifacts.get().size_bytes, 8192)
        self.assertEqual(self.client.post(self.base + "selection/", padded + " ", content_type="application/json", secure=True,
            HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/").status_code, 409)
        with patch.object(api, "_response") as response:
            # The shared parser retains the original two-KiB default for all other consumers.
            request = type("Request", (), {"content_type": "application/json", "body": b" " * 2049})()
            from django.core.exceptions import ValidationError
            with self.assertRaises(ValidationError): api._payload(request, set())
            response.assert_not_called()

    def test_exact_named_permission_targets_csrf_duplicate_json_tenant_family_current_role_and_own_key(self):
        command = self.command()
        for changes in ({"collection_permission": 1}, {"observations": ["response_location"]}, {"target_urls": None},
            {"target_urls": [self.https + "/unselected"]}, {"handler": collection.HANDLER}, {"selection_digest": "a" * 64}):
            self.assertIn(self.post(data={**command, **changes}).status_code, (403, 409))
        families = ("passive-headers", "passive-tls", "passive-resources", "passive-redirects", "passive-http-redirects")
        for family in families:
            self.assertEqual(self.post(data=command, base=self.base.replace("passive-redirect-chain", family)).status_code, 409)
        self.assertEqual(self.client.post(self.base, json.dumps(command), content_type="application/json", secure=True).status_code, 403)
        self.assertEqual(Client().get(self.base, secure=True).status_code, 401)
        self.assertEqual(self.client.get(self.base + "selection/", secure=True).status_code, 405)
        self.assertEqual(self.post("?handler=collect_passive_redirects", command).status_code, 400)
        cache.clear()
        for body in ('{"url":"x","url":"y"}', '{', '[]', 'null', '{"url":NaN}', " " * 8193):
            self.assertEqual(self.client.post(self.base, body, content_type="application/json", secure=True,
                HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/").status_code, 409)
        self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
        cache.clear(); job_id = self.post(data=command).json()["job"]["id"]
        for family in families:
            self.assertEqual(self.client.get(self.base.replace("passive-redirect-chain", family) + f"{job_id}/", secure=True).status_code, 403)
        other = Project.objects.create(organization=self.organization, name="Other scope", canonical_origin="http://other.example.invalid")
        self.assertEqual(self.client.get(self.base.replace(f"projects/{self.project.pk}/", f"projects/{other.pk}/") + f"{job_id}/", secure=True).status_code, 403)
        self.client.force_login(self.member); self.assertEqual(self.client.get(self.base, secure=True).status_code, 403)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.assertEqual(self.client.get(self.base + "?idempotency_key=" + command["idempotency_key"], secure=True).json()["jobs"], [])

    def test_four_independent_maintained_chain_user_and_ip_budgets_preserve_original_family_reads(self):
        command = self.command(); job_id = self.post(data=command).json()["job"]["id"]
        for grain in ("user", "ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={f"passive_redirect_chain_{action}": f"1/m/{grain}" for action in ("read", "selection", "request", "cancel")}):
                self.assertEqual(self.client.get(self.base, secure=True).status_code, 200); self.assertEqual(self.client.get(self.base, secure=True).status_code, 429)
                for family in ("passive-headers", "passive-tls", "passive-resources", "passive-redirects", "passive-http-redirects"):
                    self.assertEqual(self.client.get(self.base.replace("passive-redirect-chain", family), secure=True).status_code, 200)
                self.assertEqual(self.post("selection/").status_code, 200); self.assertEqual(self.post("selection/").status_code, 429)
                self.assertEqual(self.post(data=command).status_code, 202); self.assertEqual(self.post(data=command).status_code, 429)
                self.assertEqual(self.post(f"{job_id}/", {}).status_code, 202); self.assertEqual(self.post(f"{job_id}/", {}).status_code, 429)

    def test_serialized_preview_and_queue_every_origin_loss_roll_back_without_dispatch_or_private_delivery(self):
        command = self.command(); response = api._response
        for origin in (self.http_verification, self.https_verification):
            for field in ("selection", "job"):
                def changed(data, *args, **kwargs):
                    value = response(data, *args, **kwargs)
                    if field in data: ProjectOriginVerification.objects.filter(pk=origin.pk).update(challenge_digest="a" * 64)
                    return value
                with patch.object(api, "_response", changed), patch("jobs.tasks.execute_passive_redirect_chain_collection_task.apply_async") as dispatch:
                    result = self.post("selection/") if field == "selection" else self.post(data=command)
                    self.assertEqual(result.status_code, 403, result.content); dispatch.assert_not_called()
                self.assertFalse(JobRun.objects.filter(handler=collection.HANDLER).exists())
                self.assertEqual(ProjectOriginVerification.objects.get(pk=origin.pk).challenge_digest, origin.challenge_digest)
        job_id, _ = self.collected()
        for mutate in (lambda: ProjectOriginVerification.objects.filter(pk=self.http_verification.pk).update(challenge_digest="b" * 64),
            lambda: ProjectOriginVerification.objects.filter(pk=self.https_verification.pk).update(challenge_digest="b" * 64),
            lambda: JobRun.objects.filter(pk=job_id).update(config_snapshot={}),
            lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member")):
            with transaction.atomic():
                def changed(data, *args, **kwargs):
                    value = response(data, *args, **kwargs)
                    if "evidence" in data: mutate()
                    return value
                with patch.object(api, "_response", changed): result = self.client.get(self.base + f"{job_id}/", secure=True)
                self.assertIn(result.status_code, (403, 409)); self.assertNotIn(b"hops", result.content)
                transaction.set_rollback(True)

    def test_post_serialization_actual_private_byte_recheck_and_final_natural_expiry_withhold_original_chain(self):
        job_id, _ = self.collected(); response = api._response; read = lifecycle.read_project_artifact; serialized = False
        def mark(data, *args, **kwargs):
            nonlocal serialized
            value = response(data, *args, **kwargs)
            if "evidence" in data: serialized = True
            return value
        def changed_bytes(**kwargs): return b"{}" if serialized else read(**kwargs)
        with patch.object(api, "_response", mark), patch.object(lifecycle, "read_project_artifact", changed_bytes):
            result = self.client.get(self.base + f"{job_id}/", secure=True)
        self.assertEqual(result.status_code, 409); self.assertNotIn(b"hops", result.content)
        for attribute, last in (("_metadata", 2), ("_current", 2)):
            original = getattr(api, attribute); now = [timezone.now()]; end = self.organization.trial.ends_at; calls = 0
            def slow(*args, **kwargs):
                nonlocal calls
                value = original(*args, **kwargs); calls += 1
                if calls == last: now[0] = end
                return value
            with patch.object(api, attribute, slow), patch("jobs.usage.timezone.now", side_effect=lambda: now[0]):
                result = self.client.get(self.base + f"{job_id}/", secure=True)
            self.assertEqual(result.status_code, 403); self.assertNotIn(b"hops", result.content); self.assertEqual(calls, last)
