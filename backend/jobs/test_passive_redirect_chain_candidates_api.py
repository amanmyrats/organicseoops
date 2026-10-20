from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import read_project_artifact
from tenancy.models import OrganizationMembership, OrganizationTrial, ProjectOriginVerification
from . import passive_header_api as api
from . import passive_header_collection as lifecycle
from . import passive_redirect_chain_collection as collector
from . import test_passive_redirect_chain_api as fixtures
from .models import Artifact, Finding, JobCancellation, JobRun, JobStep, SourceCitation, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "chain-candidates-api"}})
class RedirectChainCandidateApiTests(TransactionTestCase):
    setUp = fixtures.PassiveRedirectChainApiTests.setUp
    verified = fixtures.PassiveRedirectChainApiTests.verified
    transport = fixtures.PassiveRedirectChainApiTests.transport
    post = fixtures.PassiveRedirectChainApiTests.post
    command = fixtures.PassiveRedirectChainApiTests.command

    def collected(self, key="chain-candidate-api", *, transport_data=None):
        queued = self.post(data=self.command(key)); self.assertEqual(queued.status_code, 202, queued.content)
        job_id = queued.json()["job"]["id"]; fetcher, self.connections, self.responses, *_ = self.transport(transport_data)
        with patch("socket.create_connection", side_effect=AssertionError("No real network")):
            self.assertTrue(collector.execute_passive_redirect_chain_collection(job_id, fetcher=fetcher))
        self.path = self.base + f"{job_id}/candidates/"; return job_id

    def test_genuine_read_only_full_original_binding_unvisited_private_index_facts_independent_reader_no_materialization(self):
        unvisited = self.verified("https://www.security.example.com")
        self.data = {**self.data, "url": self.https + "/public", "target_urls": [self.http + "/public", unvisited.origin + "/unvisited"]}
        job_id = self.collected(transport_data={**self.data, "target_urls": self.data["target_urls"][:1]})
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin"); self.client.force_login(self.member)
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.client.get(self.path, secure=True)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        report = result.json()["candidates"]; job = JobRun.objects.get(pk=job_id)
        self.assertEqual((report["job_id"], report["source_current"], report["binding"]), (job_id, True, job.config_snapshot["binding"]))
        self.assertEqual((report["availability"]["selected_urls"], report["availability"]["observed_hops"]), (3, 2))
        self.assertEqual(report["candidates"], [{"detector": "observed_https_to_http_transition_candidate", "evidence": {"transitions": [{"from_hop": 0, "to_hop": 1}]}}])
        self.assertEqual((report["collection"]["observed_at"], report["collection"]["last_observed_at"]), (job.output["observed_at"], job.output["last_observed_at"]))
        self.assertFalse(Finding.objects.exists()); self.assertEqual(job.usage.actual_units, 1)
        for raw in (b"private", b"secret", b"raw_location", self.challenge.encode(), self.owner.email.encode()): self.assertNotIn(raw, result.content)
        self.assertEqual(result["Cache-Control"], "private, no-store"); self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        for conn, response in zip(self.connections, self.responses): conn.request.assert_called_once(); response.read.assert_not_called()

    def test_exact_bodyless_method_ids_roles_tenant_fixed_family_failed_no_premature_metadata(self):
        job_id = self.collected()
        self.assertEqual(Client().get(self.path, secure=True).status_code, 401)
        for query in ("?family=headers", "?job_id=1", "?extra=x"):
            self.assertEqual(self.client.get(self.path + query, secure=True).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.path, b"{}", content_type="application/json", secure=True).status_code, 400)
        self.assertEqual(self.post(f"{job_id}/candidates/", {}).status_code, 405); self.assertEqual(self.client.head(self.path, secure=True).status_code, 405)
        for actor, status in ((self.member, 403), (self.outsider, 404)):
            client = Client(); client.force_login(actor)
            with patch.object(lifecycle, "_read_metadata", side_effect=AssertionError("No premature unauthorized pin")):
                self.assertEqual(client.get(self.path, secure=True).status_code, status)
        for family in ("headers", "tls", "resources", "redirects"):
            with patch.object(lifecycle, "_read_metadata", side_effect=AssertionError("No premature wrong-family pin")):
                self.assertEqual(self.client.get(self.path.replace("passive-redirect-chain", "passive-" + family), secure=True).status_code, 403)
        for changes in ({"status": "failed"}, {"handler": "collect_passive_http_redirects"}, {"handler": "collect_passive_headers"}):
            with transaction.atomic():
                JobRun.objects.filter(pk=job_id).update(**changes)
                with patch.object(lifecycle, "_read_metadata", side_effect=AssertionError("No premature failed or family pin")):
                    self.assertEqual(self.client.get(self.path, secure=True).status_code, 403)
                transaction.set_rollback(True)
        for path in (self.path.replace(f"projects/{self.project.pk}/", "projects/9007199254740991/"), self.path.replace(f"/{job_id}/candidates/", "/9007199254740992/candidates/")):
            self.assertIn(self.client.get(path, secure=True).status_code, {400, 404})

    def test_reuses_only_current_chain_read_user_ip_budget_shared_with_history_not_original_families_or_selection(self):
        self.collected(); OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")
        other = Client(); other.force_login(self.member)
        for limit in ("1/m/user", "1/m/ip"):
            cache.clear()
            with override_settings(ACCOUNT_RATE_LIMITS={"passive_redirect_chain_read": limit}):
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 200)
                self.assertEqual(self.client.get(self.base, secure=True).status_code, 429); self.assertEqual(self.client.get(self.path, secure=True).status_code, 429)
                self.assertEqual(other.get(self.path, secure=True).status_code, 429 if limit.endswith("ip") else 200)
                for family in ("headers", "tls", "resources", "redirects", "http-redirects"):
                    self.assertEqual(self.client.get(self.base.replace("passive-redirect-chain", "passive-" + family), secure=True).status_code, 200)
                self.assertEqual(self.post("selection/").status_code, 200)

    def test_after_serialization_original_metadata_every_origin_private_bytes_cancel_and_natural_expiry_withhold(self):
        unvisited = self.verified("https://www.security.example.com"); self.data["target_urls"].append(unvisited.origin + "/unvisited")
        job_id = self.collected(transport_data={**self.data, "target_urls": self.data["target_urls"][:1]}); response = api._response
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin"); self.client.force_login(self.member)
        changes = [lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="member"),
            lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer"),
            lambda: JobRun.objects.filter(pk=job_id).update(idempotency_key="changed-original"),
            lambda: JobStep.objects.filter(job_id=job_id).update(created_at=timezone.now()),
            lambda: Artifact.objects.filter(job_id=job_id).update(created_at=timezone.now()),
            lambda: SourceCitation.objects.filter(job_id=job_id).update(source_title="Changed"),
            lambda: UsageReservation.objects.filter(job_id=job_id).update(period_start=timezone.now().date() - timedelta(days=1)),
            lambda: JobCancellation.objects.create(job_id=job_id, requested_by=self.owner)]
        changes += [lambda pk=record.pk: ProjectOriginVerification.objects.filter(pk=pk).update(updated_at=timezone.now())
            for record in (self.http_verification, self.https_verification, unvisited)]
        for change in changes:
            with transaction.atomic():
                def serialized(data, *args, **kwargs):
                    result = response(data, *args, **kwargs)
                    if "candidates" in data: change()
                    return result
                with patch.object(api, "_response", side_effect=serialized): result = self.client.get(self.path, secure=True)
                self.assertEqual(result.status_code, 403, result.content); self.assertNotIn(b"binding", result.content); transaction.set_rollback(True)
        trial = self.organization.trial; end = timezone.now() + timedelta(seconds=5)
        OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=end - timedelta(days=30), ends_at=end)
        finished = False
        def serialized(data, *args, **kwargs):
            nonlocal finished
            result = response(data, *args, **kwargs)
            if "candidates" in data: finished = True
            return result
        with patch.object(api, "_response", side_effect=serialized), patch("jobs.usage.timezone.now", side_effect=lambda: end if finished else end - timedelta(seconds=1)):
            self.assertEqual(self.client.get(self.path, secure=True).status_code, 403)
        OrganizationTrial.objects.filter(pk=trial.pk).update(started_at=trial.started_at, ends_at=trial.ends_at)
        finished = False
        def after_bytes(**kwargs): return b"{}" if finished else read_project_artifact(**kwargs)
        with patch.object(api, "_response", side_effect=serialized), patch.object(lifecycle, "read_project_artifact", side_effect=after_bytes):
            result = self.client.get(self.path, secure=True)
        self.assertEqual(result.status_code, 409); self.assertNotIn(b"binding", result.content)

    def test_six_maximum_original_selected_paths_full_candidate_report_is_not_truncated_to_first_response_limits(self):
        urls = []
        for index in range(6):
            prefix = (self.https if index % 2 == 0 else self.http) + "/"
            urls.append(prefix + str(index) * (1024 - len(prefix)))
        self.data = {**self.data, "url": urls[0], "target_urls": urls[1:]}; self.collected()
        result = self.client.get(self.path, secure=True); self.assertEqual(result.status_code, 200, result.content)
        self.assertGreater(len(result.content), 8192); report = result.json()["candidates"]
        self.assertEqual([hop["url"] for hop in report["collection"]["evidence"]["hops"]], urls)
        self.assertEqual(report["availability"], {"selected_urls": 6, "observed_hops": 6, "last_target_metadata": "unavailable"})
        self.assertEqual(report["candidates"][0]["evidence"]["transitions"], [{"from_hop": 0, "to_hop": 1}, {"from_hop": 2, "to_hop": 3}, {"from_hop": 4, "to_hop": 5}])
