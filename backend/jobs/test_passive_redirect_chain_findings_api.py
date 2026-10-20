import json
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, ProjectOriginVerification
from . import passive_header_api as api
from . import passive_header_collection as lifecycle
from . import test_passive_redirect_chain_persistence as fixtures
from . import test_passive_redirect_chain_api as api_fixtures
from . import test_passive_header_findings_api as header_checks
from .models import Finding, JobCancellation, JobRun, Opportunity, Recommendation, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "chain-finding-api"}})
class RedirectChainFindingApiTests(TransactionTestCase):
    verified = fixtures.PassiveRedirectChainFindingTests.verified
    queue = fixtures.PassiveRedirectChainFindingTests.queue
    post = api_fixtures.PassiveRedirectChainApiTests.post

    def setUp(self):
        fixtures.PassiveRedirectChainFindingTests.setUp(self)
        self.client = Client(enforce_csrf_checks=True); self.client.force_login(self.owner)
        self.client.get("/_allauth/browser/v1/auth/session", secure=True)
        self.csrf = self.client.cookies["csrftoken"].value
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/passive-redirect-chain/"

    def collected(self, key="chain-finding-api", **kwargs):
        job = fixtures.PassiveRedirectChainFindingTests.collected(self, key, **kwargs)
        self.suffix = f"{job.pk}/findings/"; self.path = self.base + self.suffix
        return job.pk

    def save(self, digest): return self.post(self.suffix, {"candidate_digest": digest})

    test_methods_csrf_strict_json_digest_query_and_scope = header_checks.HeaderFindingApiTests.test_methods_csrf_strict_json_digest_query_and_scope
    test_natural_exact_expiry_after_serialization_rolls_back_post = header_checks.HeaderFindingApiTests.test_natural_exact_expiry_after_serialization_rolls_back_post

    def test_genuine_two_fact_read_only_get_digest_post_idempotent_original_private_without_new_work(self):
        job_id = self.collected()
        with CaptureQueriesContext(connection) as queries: result = self.client.get(self.path, secure=True)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        initial = result.json(); digest = initial["candidate_digest"]
        self.assertEqual(digest, api._digest(initial["candidates"]))
        self.assertEqual(initial["finding_set"]["state"], "no_retained_materialized_findings")
        self.assertEqual(initial["candidates"]["binding"], JobRun.objects.get(pk=job_id).config_snapshot["binding"])
        self.assertEqual(len(initial["candidates"]["candidates"]), 2)
        counts = (JobRun.objects.count(), UsageReservation.objects.count())
        with patch("socket.create_connection", side_effect=AssertionError("No network")):
            saved = self.save(digest); self.assertEqual(saved.status_code, 200, saved.content)
            self.assertEqual(self.save(digest).json(), saved.json()); self.assertEqual(self.client.get(self.path, secure=True).json(), saved.json())
        facts = saved.json()["finding_set"]["findings"]
        self.assertEqual(len(facts), 2); self.assertEqual({row["source_passive_redirect_chain_id"] for row in facts}, {job_id})
        self.assertEqual((JobRun.objects.count(), UsageReservation.objects.count()), counts)
        self.assertEqual((Opportunity.objects.count(), Recommendation.objects.count()), (0, 0))
        self.assertEqual((result["Cache-Control"], result["X-Robots-Tag"]), ("private, no-store", "noindex, nofollow"))
        for secret in (self.challenge.encode(), self.owner.email.encode(), b"raw_location", b"private", b"secret=value"):
            self.assertNotIn(secret, saved.content)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.client.force_login(self.member); self.assertEqual(self.save(digest).json(), saved.json())
        self.assertEqual(set(Finding.objects.values_list("actor_id", flat=True)), {self.owner.pk})
        for conn, response in zip(self.connections, self.responses): conn.request.assert_called_once(); response.read.assert_not_called()

    def test_family_roles_failed_sources_before_pin_empty_and_maximum_original_paths(self):
        job_id = self.collected()
        for actor, status in ((self.member, 403), (self.outsider, 404)):
            client = Client(); client.force_login(actor); self.assertEqual(client.get(self.path, secure=True).status_code, status)
        for family in ("passive-headers", "passive-tls", "passive-resources", "passive-redirects"):
            with patch.object(lifecycle, "_read_metadata", side_effect=AssertionError("No premature full pin")):
                self.assertEqual(self.client.get(self.path.replace("passive-redirect-chain", family), secure=True).status_code, 403)
        for field, values in (("handler", set(lifecycle.PASSIVE_HANDLERS)-{"collect_passive_redirect_chain"}),
            ("status", ("queued", "running", "failed", "cancelled"))):
            for value in values:
                with transaction.atomic():
                    JobRun.objects.filter(pk=job_id).update(**{field: value})
                    with patch.object(lifecycle, "_read_metadata", side_effect=AssertionError("No premature full pin")):
                        self.assertEqual(self.client.get(self.path, secure=True).status_code, 403)
                    transaction.set_rollback(True)
        self.collected("empty", fields=b"Location: javascript:private\r\n")
        initial = self.client.get(self.path, secure=True).json(); self.assertEqual(initial["candidates"]["candidates"], [])
        self.assertEqual(self.save(initial["candidate_digest"]).json(), initial); self.assertFalse(Finding.objects.exists())
        urls = [(self.https if index%2 == 0 else self.http) + f"/page-{index}-" for index in range(6)]
        urls = [prefix+"x"*(1024-len(prefix)) for prefix in urls]
        self.data = {**self.data, "url": urls[0], "target_urls": urls[1:]}; self.collected("maximum")
        initial = self.client.get(self.path, secure=True).json(); saved = self.save(initial["candidate_digest"])
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(initial["candidates"]["binding"]["target_urls"], urls[1:])
        for row in saved.json()["finding_set"]["findings"]:
            self.assertEqual(len(row["evidence"]["captures"]), 6); self.assertLessEqual(len(lifecycle._encode(row["evidence"])), 4096)

    def test_independent_user_ip_read_write_budgets_preserve_original_chain_and_finding_families(self):
        self.collected(); digest = self.client.get(self.path, secure=True).json()["candidate_digest"]
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        other = Client(); other.force_login(self.member)
        for limit in ("1/m/user", "1/m/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={action: limit for action in ("passive_redirect_chain_findings_read", "passive_redirect_chain_findings_write")}):
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 200)
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 429)
                self.assertEqual(self.save(digest).status_code, 200); self.assertEqual(self.save(digest).status_code, 429)
                self.assertEqual(self.client.get(self.path.replace("findings/", "candidates/"), secure=True).status_code, 200)
                self.assertEqual(self.client.get(self.base, secure=True).status_code, 200)
                for family in ("passive-headers", "passive-tls", "passive-resources", "passive-redirects"):
                    self.assertEqual(self.client.get(self.base.replace("passive-redirect-chain", family), secure=True).status_code, 200)
                if limit.endswith("ip"):
                    self.assertEqual(other.get(self.path, secure=True).status_code, 429)
                    self.assertEqual(other.post(self.path, json.dumps({"candidate_digest": digest}), content_type="application/json", secure=True).status_code, 429)

    def test_post_serialization_every_origin_unvisited_rows_actor_cancel_private_bytes_loss_roll_back(self):
        unvisited = self.verified("https://www.security.example.com")
        self.data["target_urls"].append(unvisited.origin+"/unvisited")
        job_id = self.collected(fields=f"Location: {self.data['url']}\r\n".encode())
        initial = self.client.get(self.path, secure=True).json()
        self.assertEqual((initial["candidates"]["availability"]["selected_urls"], initial["candidates"]["availability"]["observed_hops"]), (3, 1))
        digest = initial["candidate_digest"]
        response = api._response
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        self.client.force_login(self.member)
        changes = [lambda: JobRun.objects.filter(pk=job_id).update(idempotency_key="changed-original"),
            lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer"),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
            lambda: Finding.objects.filter(source_passive_redirect_chain_id=job_id).update(actor=self.owner),
            lambda: Finding.objects.filter(source_passive_redirect_chain_id=job_id).update(detected_at=timezone.now()),
            lambda: Finding.objects.filter(source_passive_redirect_chain_id=job_id).order_by("pk").first().delete()]
        for verification in (self.http_verification, self.https_verification, unvisited):
            changes.append(lambda pk=verification.pk: ProjectOriginVerification.objects.filter(pk=pk).update(updated_at=timezone.now()))
        for method in ("POST", "GET"):
            if method == "GET": self.assertEqual(self.save(digest).status_code, 200)
            for change in changes:
                with self.subTest(method=method, change=change), transaction.atomic():
                    def serialized(data, *args, **kwargs):
                        result = response(data, *args, **kwargs)
                        if "finding_set" in data: change()
                        return result
                    with patch.object(api, "_response", side_effect=serialized):
                        result = self.save(digest) if method == "POST" else self.client.get(self.path, secure=True)
                    self.assertIn(result.status_code, (403, 409), result.content); self.assertNotIn(b"collection_sha256", result.content)
                    if method == "POST": self.assertFalse(Finding.objects.exists())
                    transaction.set_rollback(True)
        from tenancy.artifacts import read_project_artifact
        finished = False
        def serialized(data, *args, **kwargs):
            nonlocal finished
            result = response(data, *args, **kwargs)
            if "finding_set" in data: finished = True
            return result
        def changed_bytes(**kwargs): return b"{}" if finished else read_project_artifact(**kwargs)
        with patch.object(api, "_response", side_effect=serialized), patch.object(lifecycle, "read_project_artifact", side_effect=changed_bytes):
            self.assertEqual(self.client.get(self.path, secure=True).status_code, 409)
