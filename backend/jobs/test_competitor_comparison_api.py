from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.core.cache import cache
from django.db import transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_api as api
from . import test_competitor_comparison as fixtures
from .models import Artifact, JobCancellation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "competitor-comparison-api"}},
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorComparisonApiTests(TransactionTestCase):
    setUp = fixtures.CompetitorComparisonTests.setUp
    queue = fixtures.CompetitorComparisonTests.queue
    transport = fixtures.CompetitorComparisonTests.transport
    collected = fixtures.CompetitorComparisonTests.collected

    def pair(self):
        cache.clear()
        before = self.collected("api-pair-before")
        after = self.collected("api-pair-after", b"<title>Different</title><h2>Other</h2>")
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/competitor-roots/comparison/"
        self.query = f"?previous_job_id={before.pk}&current_job_id={after.pk}"
        self.client.force_login(self.owner)
        return before, after

    def test_genuine_exact_private_pair_and_shared_maintained_read_budget(self):
        before, after = self.pair()
        response = self.client.get(self.base + self.query, secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()["comparison"]
        self.assertEqual((result["previous"]["job_id"], result["current"]["job_id"]), (before.pk, after.pk))
        self.assertTrue(result["comparable"]); self.assertTrue(result["metadata_changed"]["title"])
        self.assertEqual(response["Cache-Control"], "private, no-store"); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        other = Client(); other.force_login(self.admin)
        self.assertEqual(other.get(self.base + self.query, secure=True).json()["comparison"], result)
        self.assertEqual(Client().get(self.base + self.query, secure=True).status_code, 401)
        cache.clear()
        with override_settings(ACCOUNT_RATE_LIMITS={"competitor_root_read": "1/h/ip"}):
            self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)
            self.assertEqual(other.get(self.base.removesuffix("comparison/"), secure=True).status_code, 429)

    def test_bodyless_canonical_distinct_query_only_and_current_scoped_source_denials(self):
        before, after = self.pair()
        for query in ("", "?previous_job_id=1", self.query + "&extra=1", self.query + f"&previous_job_id={before.pk}",
            f"?previous_job_id={before.pk}&current_job_id={before.pk}",
            "?previous_job_id=01&current_job_id=2", "?previous_job_id=+1&current_job_id=2",
            "?previous_job_id=true&current_job_id=2", "?previous_job_id=9007199254740992&current_job_id=2"):
            self.assertEqual(self.client.get(self.base + query, secure=True).status_code, 400, query)
        self.assertEqual(self.client.generic("GET", self.base + self.query, b"{}", content_type="application/json", secure=True).status_code, 400)
        self.assertEqual(self.client.post(self.base + self.query, {}, secure=True).status_code, 405)
        self.assertEqual(self.client.get(self.base + f"?previous_job_id={after.pk}&current_job_id={before.pk}", secure=True).status_code, 409)
        self.client.force_login(self.foreign); self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 404)
        self.client.force_login(self.admin)
        OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
        self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 403)
        OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="admin")
        EmailAddress.objects.filter(user=self.admin).update(verified=False)
        self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 403)

    def test_post_serialization_first_record_source_caller_cancellation_and_expiry_loss_withholds_pair(self):
        before, after = self.pair(); self.client.force_login(self.admin)
        artifact = before.artifacts.get(); original = api._response
        for kind in ("first-record", "config", "caller", "cancel", "expiry"):
            def late_response(data, *args, **kwargs):
                response = original(data, *args, **kwargs)
                if "comparison" in data:
                    if kind == "first-record": Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes + 1)
                    if kind == "config": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                    if kind == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                    if kind == "cancel": JobCancellation.objects.create(job=before, requested_by=self.owner)
                    if kind == "expiry":
                        now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31), ends_at=now-timedelta(days=1))
                return response
            with patch.object(api, "_response", side_effect=late_response):
                response = self.client.get(self.base + self.query, secure=True)
            self.assertIn(response.status_code, (403, 409), response.content); self.assertNotIn("comparison", response.json())
            Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes)
            ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=1)
            OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="admin")
            JobCancellation.objects.filter(job=before).delete()
            now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=1), ends_at=now+timedelta(days=1))

    def test_final_api_metadata_return_fences_original_authority_for_pair_and_root_detail(self):
        before, after = self.pair(); self.client.force_login(self.admin)
        original = api._metadata
        for phase in ("pair", "detail"):
            path = self.base + self.query if phase == "pair" else self.base.removesuffix("comparison/") + f"{before.pk}/"
            with patch.object(api, "_metadata", wraps=original) as healthy:
                self.assertEqual(self.client.get(path, secure=True).status_code, 200)
            expected_pins = [call.args[0] for call in healthy.call_args_list]
            if phase == "pair":
                self.assertEqual(set(expected_pins[:2]), {before.pk, after.pk})
                self.assertEqual(expected_pins, expected_pins[:2] * 4)
            else: self.assertEqual(expected_pins, [before.pk] * 3)
            for loss in ("actor", "caller-demoted", "caller-role", "revision", "approval-list", "first-cancel", "organization", "expiry"):
                with self.subTest(phase=phase, loss=loss), transaction.atomic():
                    cache.clear()
                    now = [timezone.now()]
                    ends = now[0] + timedelta(seconds=20)
                    OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends - timedelta(days=30), ends_at=ends)
                    pins = []
                    def last_pin(job_id):
                        result = original(job_id)
                        pins.append(job_id)
                        if pins == expected_pins:
                            if loss == "actor": OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
                            elif loss == "caller-demoted": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                            elif loss == "caller-role": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="owner")
                            elif loss == "revision": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                            elif loss == "approval-list": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[self.data["origin"]])
                            elif loss == "first-cancel": JobCancellation.objects.create(job=before, requested_by=self.owner)
                            elif loss == "organization": Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True)
                            else: now[0] = ends
                        return result
                    with patch.object(api, "_metadata", side_effect=last_pin), patch("jobs.usage.timezone.now", side_effect=lambda: now[0]):
                        response = self.client.get(path, secure=True)
                    self.assertEqual(pins, expected_pins)
                    self.assertIn(response.status_code, (403, 409), response.content)
                    self.assertNotIn("comparison", response.json()); self.assertNotIn("evidence", response.json())
                    self.assertEqual(response["Cache-Control"], "private, no-store")
                    self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
                    transaction.set_rollback(True)
            self.assertEqual(self.client.get(path, secure=True).status_code, 200)

    def test_first_original_cancellation_during_last_post_serialization_second_source_read_withholds_response(self):
        before, after = self.pair(); self.client.force_login(self.admin)
        source, render = api.collection._read_source, api._response
        rendered, injected, checked = [False], [False], []
        def response(data, *args, **kwargs):
            result = render(data, *args, **kwargs)
            if "comparison" in data: rendered[0] = True
            return result
        def final_source(job, *args, **kwargs):
            result = source(job, *args, **kwargs)
            if rendered[0]:
                checked.append(job.pk)
                if len(checked) == 2 and not injected[0]:
                    JobCancellation.objects.create(job_id=checked[0], requested_by=self.owner)
                    injected[0] = True
            return result
        with patch.object(api, "_response", side_effect=response), patch.object(api.collection, "_read_source", side_effect=final_source):
            result = self.client.get(self.base + self.query, secure=True)
        self.assertTrue(injected[0])
        self.assertEqual(result.status_code, 403, result.content)
        self.assertNotIn("comparison", result.json())
