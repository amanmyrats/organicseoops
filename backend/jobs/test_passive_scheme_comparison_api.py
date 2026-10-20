from unittest.mock import patch

from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, Project, ProjectOriginVerification
from . import passive_header_api as api
from . import test_passive_scheme_comparison as fixtures
from .models import Artifact, JobCancellation, JobRun


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "scheme-pair-api"}},
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class PassiveSchemeComparisonApiTests(TransactionTestCase):
    verified = fixtures.PassiveSchemeComparisonTests.verified
    transport = fixtures.PassiveSchemeComparisonTests.transport
    collected = fixtures.PassiveSchemeComparisonTests.collected

    def setUp(self):
        fixtures.PassiveSchemeComparisonTests.setUp(self)
        self.http = self.collected("http", "pair-api-http")
        self.https = self.collected("https", "pair-api-https", actor=self.member)
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/passive-http-redirects/"
        self.url = self.base + f"comparison/?http_job_id={self.http.pk}&https_job_id={self.https.pk}"
        self.client.force_login(self.owner); cache.clear()

    def test_genuine_original_pair_independent_reader_bodyless_private_get_without_new_request(self):
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No pair collection")), CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url, secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual(response["Cache-Control"], "private, no-store"); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        pair = response.json()["comparison"]
        self.assertEqual((pair["http"]["job_id"], pair["https"]["job_id"]), (self.http.pk, self.https.pk))
        self.assertEqual(pair["http"]["binding"], self.http.config_snapshot["binding"])
        self.assertEqual(pair["https"]["binding"], self.https.config_snapshot["binding"])
        self.assertIn("not_location_target_path_followed_upgrade", pair["interpretation"])
        self.client.force_login(self.member); self.assertEqual(self.client.get(self.url, secure=True).json()["comparison"], pair)
        for value in (b"secret=value", b"/different", self.challenge.encode(), self.owner.email.encode()): self.assertNotIn(value, response.content)

    def test_fixed_get_only_exact_canonical_distinct_query_tenant_family_and_current_role(self):
        comparison = self.base + "comparison/"
        query = self.url.split("?", 1)[1]
        for suffix in ("", "?http_job_id=1", "?http_job_id=01&https_job_id=2", "?http_job_id=true&https_job_id=2",
            "?http_job_id=9007199254740992&https_job_id=2", "?" + query + "&extra=1", "?" + query + f"&http_job_id={self.http.pk}",
            f"?http_job_id={self.http.pk}&https_job_id={self.http.pk}"):
            self.assertEqual(self.client.get(comparison + suffix, secure=True).status_code, 400, suffix)
        self.assertEqual(self.client.generic("GET", self.url, b"{}", content_type="application/json", secure=True).status_code, 400)
        self.assertEqual(self.client.post(self.url, {}, secure=True).status_code, 405)
        self.assertEqual(Client().get(self.url, secure=True).status_code, 401)
        self.assertEqual(self.client.get(comparison + f"?http_job_id={self.https.pk}&https_job_id={self.http.pk}", secure=True).status_code, 403)
        self.assertEqual(self.client.get(self.url.replace("passive-http-redirects", "passive-redirects"), secure=True).status_code, 404)
        self.client.force_login(self.outsider); self.assertEqual(self.client.get(self.url, secure=True).status_code, 404)
        self.client.force_login(self.member)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer")
        self.assertEqual(self.client.get(self.url, secure=True).status_code, 403)

    def test_shared_maintained_http_read_budget_is_distinct_from_https_reads(self):
        with override_settings(ACCOUNT_RATE_LIMITS={"passive_http_redirect_read": "1/h/ip"}):
            self.assertEqual(self.client.get(self.url, secure=True).status_code, 200)
            other = Client(); other.force_login(self.member)
            self.assertEqual(other.get(self.base, secure=True).status_code, 429)
            self.assertEqual(other.get(self.base.replace("passive-http-redirects", "passive-redirects"), secure=True).status_code, 200)

    def test_ineligible_either_job_denied_before_any_original_metadata_read(self):
        foreign = Project.objects.create(organization=self.organization, name="Foreign pair", canonical_origin="http://foreign.example.invalid")
        for job in (self.http, self.https):
            for changes in ({"project_id": foreign.pk}, {"handler": "collect_passive_headers"}, {"status": "failed"}):
                with self.subTest(job=job.pk, changes=changes), transaction.atomic():
                    JobRun.objects.filter(pk=job.pk).update(**changes)
                    with patch.object(api, "_metadata", wraps=api._metadata) as metadata:
                        response = self.client.get(self.url, secure=True)
                    self.assertEqual(response.status_code, 403, response.content)
                    self.assertNotIn("comparison", response.json())
                    metadata.assert_not_called()
                    transaction.set_rollback(True)

    def test_either_original_source_metadata_cancel_and_reader_loss_during_serialization_withholds_pair(self):
        original = api._response
        mutations = [lambda job=job: Artifact.objects.filter(job=job).update(size_bytes=job.artifacts.get().size_bytes + 1) for job in (self.http, self.https)]
        mutations += [lambda row=row: ProjectOriginVerification.objects.filter(pk=row.pk).update(challenge_digest="a" * 64) for row in (self.verification, self.https_verification)]
        mutations += [lambda job=job: JobCancellation.objects.create(job=job, requested_by=self.owner) for job in (self.http, self.https)]
        mutations += [lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer")]
        self.client.force_login(self.member)
        for mutate in mutations:
            with transaction.atomic():
                def changed(data, *args, **kwargs):
                    response = original(data, *args, **kwargs)
                    if "comparison" in data: mutate()
                    return response
                with patch.object(api, "_response", side_effect=changed): response = self.client.get(self.url, secure=True)
                self.assertIn(response.status_code, (403, 409), response.content)
                self.assertNotIn("comparison", response.json()); transaction.set_rollback(True)

    def test_natural_expiry_during_last_current_role_read_withholds_serialized_pair(self):
        current = api._current; now = [timezone.now()]; end = self.organization.trial.ends_at; calls = 0
        def slow(*args, **kwargs):
            nonlocal calls
            result = current(*args, **kwargs); calls += 1
            if calls == 2: now[0] = end
            return result
        with patch.object(api, "_current", side_effect=slow), patch("jobs.usage.timezone.now", side_effect=lambda: now[0]):
            response = self.client.get(self.url, secure=True)
        self.assertEqual(response.status_code, 403); self.assertNotIn("comparison", response.json()); self.assertEqual(calls, 2)
