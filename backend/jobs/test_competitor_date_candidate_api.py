from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, OrganizationTrial, Project, ProjectConfiguration
from . import competitor_date_candidate_api as api, competitor_collection as lifecycle
from . import competitor_page_dates_collection as collection, test_competitor_page_dates_api as fixtures
from .models import Artifact, JobCancellation, JobRun, JobStep, SourceCitation, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "date-candidates-api"}})
class CompetitorDateCandidateApiTests(TransactionTestCase):
    setUp = fixtures.CompetitorPageDatesApiTests.setUp
    transport = fixtures.CompetitorPageDatesApiTests.transport
    fetcher = fixtures.CompetitorPageDatesApiTests.fetcher
    HTML = fixtures.CompetitorPageDatesApiTests.HTML
    post = fixtures.CompetitorPageDatesApiTests.post
    command = fixtures.CompetitorPageDatesApiTests.command
    revoke = fixtures.CompetitorPageDatesApiTests.revoke

    def collected(self, body=None):
        job_id = self.post(data=self.command()).json()["job"]["id"]
        self.assertTrue(collection.execute_competitor_page_dates_collection(job_id,
            fetcher=self.fetcher(**({"body": body} if body is not None else {}))))
        return JobRun.objects.get(pk=job_id)

    def get(self, job, suffix="", *, client=None):
        return (client or self.client).get(self.base + f"{job.pk}/candidates/" + suffix, secure=True)

    def test_genuine_saved_original_private_get_independent_reader_preserves_old_detail_and_no_work(self):
        job = self.collected()
        old = self.client.get(self.base + f"{job.pk}/", secure=True).json()
        counts = (JobRun.objects.count(), Artifact.objects.count(), UsageReservation.objects.count())
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            response = self.get(job)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual((JobRun.objects.count(), Artifact.objects.count(), UsageReservation.objects.count()), counts)
        packet = response.json()["candidates"]
        self.assertEqual(packet["collection"], old["evidence"]["collection"])
        self.assertEqual([item["state"] for item in packet["candidates"]], ["calendar_literal", "unsupported_literal"])
        other = Client(); other.force_login(self.admin)
        self.assertEqual(self.get(job, client=other).json(), response.json())
        self.assertEqual(self.client.get(self.base + f"{job.pk}/", secure=True).json(), old)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        for value in (self.owner.email.encode(), b"config_snapshot", b"private-contact", b"storage_key"):
            self.assertNotIn(value, response.content)

    def test_bodyless_exact_get_only_safe_scoped_success_and_shared_existing_date_read_budget(self):
        job = self.collected()
        path = self.base + f"{job.pk}/candidates/"
        self.assertEqual(self.get(job, client=Client()).status_code, 401)
        for method in ("post", "put", "delete"):
            response = getattr(self.client, method)(path, "{}", content_type="application/json", secure=True,
                HTTP_X_CSRFTOKEN=self.csrf, HTTP_REFERER="https://testserver/")
            self.assertEqual(response.status_code, 405); self.assertEqual(response["Allow"], "GET")
        for query in ("?job_id=1", "?handler=collect_competitor_root", "?a=1&a=2"):
            self.assertEqual(self.get(job, query).status_code, 400)
        self.assertEqual(self.client.generic("GET", path, "{}", content_type="application/json", secure=True).status_code, 400)
        for key in (0, 2**53):
            self.assertEqual(self.client.get(self.base + f"{key}/candidates/", secure=True).status_code, 400)
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other.example.invalid")
        wrong = path.replace(f"projects/{self.project.pk}/", f"projects/{other.pk}/")
        self.assertEqual(self.client.get(wrong, secure=True).status_code, 403)
        self.client.force_login(self.foreign); self.assertEqual(self.get(job).status_code, 404)
        self.client.force_login(self.owner)
        for changes in ({"handler": "collect_competitor_page_formats"}, {"status": "failed"}):
            with transaction.atomic():
                JobRun.objects.filter(pk=job.pk).update(**changes)
                self.assertEqual(self.get(job).status_code, 403)
                transaction.set_rollback(True)
        cache.clear()
        with override_settings(ACCOUNT_RATE_LIMITS={"competitor_page_dates_read": "1/h/ip", "competitor_page_formats_read": "1/h/ip"}):
            self.assertEqual(self.get(job).status_code, 200)
            self.assertEqual(self.client.get(self.base, secure=True).status_code, 429)
            self.assertEqual(self.client.get(self.base.replace("competitor-page-dates", "competitor-page-formats"), secure=True).status_code, 200)

    def test_unavailable_originals_are_whole_null_and_bad_private_readbacks_are_not_results(self):
        job = self.collected(b"<title>Unclosed")
        response = self.get(job)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["candidates"]["candidates"])
        with patch.object(lifecycle, "read_project_artifact", return_value=b"{}"):
            response = self.get(job)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("candidates", response.json())

    def test_post_serialization_original_actor_caller_source_metadata_and_natural_commercial_losses_withhold(self):
        job = self.collected()
        serialize = api._response
        for loss in ("actor", "caller", "configuration", "artifact", "step", "citation", "usage", "cancel", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                other = Client(); other.force_login(self.admin)
                ends = timezone.now()+timedelta(seconds=20)
                OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends-timedelta(days=30), ends_at=ends)
                injected = [False]; actual = timezone.now
                def changed(payload, *args):
                    result = serialize(payload, *args)
                    if "candidates" in payload:
                        injected[0] = True
                        if loss == "actor": self.revoke()
                        elif loss == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                        elif loss == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                        elif loss == "artifact": Artifact.objects.filter(job=job).update(created_at=actual())
                        elif loss == "step": JobStep.objects.filter(job=job).update(created_at=actual())
                        elif loss == "citation": SourceCitation.objects.filter(job=job).update(source_title="replacement")
                        elif loss == "usage": UsageReservation.objects.filter(job=job).update(actual_units=2)
                        elif loss == "cancel": JobCancellation.objects.create(job=job, requested_by=self.owner)
                    return result
                with patch.object(api, "_response", side_effect=changed), patch("jobs.usage.timezone.now",
                    side_effect=lambda: ends if injected[0] and loss == "expiry" else actual()): response = self.get(job, client=other)
                self.assertTrue(injected[0]); self.assertIn(response.status_code, (403, 409))
                self.assertNotIn("candidates", response.json()); transaction.set_rollback(True)

    def test_actual_last_api_metadata_source_losses_and_final_source_original_metadata_losses_are_withheld(self):
        job = self.collected()
        other = Client(); other.force_login(self.admin)
        metadata, read_source = api._metadata, lifecycle._read_source
        for boundary, losses in (("metadata", ("actor", "caller", "configuration")), ("source", ("artifact", "step", "citation", "status", "usage", "cancel"))):
            for loss in losses:
                with self.subTest(boundary=boundary, loss=loss), transaction.atomic():
                    pins, injected = [0], [False]
                    def mutate():
                        injected[0] = True
                        if loss == "actor": self.revoke()
                        elif loss == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                        elif loss == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                        elif loss == "artifact": Artifact.objects.filter(job=job).update(created_at=timezone.now())
                        elif loss == "step": JobStep.objects.filter(job=job).update(created_at=timezone.now())
                        elif loss == "citation": SourceCitation.objects.filter(job=job).update(source_title="replacement")
                        elif loss == "status": JobRun.objects.filter(pk=job.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=job).update(actual_units=2)
                        else: JobCancellation.objects.create(job=job, requested_by=self.owner)
                    def pin(key):
                        result = metadata(key); pins[0] += 1
                        if pins[0] == 3 and boundary == "metadata": mutate()
                        return result
                    def source_changed(*args):
                        result = read_source(*args)
                        if pins[0] == 3 and boundary == "source" and not injected[0]: mutate()
                        return result
                    with patch.object(api, "_metadata", side_effect=pin), patch.object(lifecycle, "_read_source", side_effect=source_changed):
                        response = self.get(job, client=other)
                    self.assertTrue(injected[0]); self.assertEqual(pins[0], 3)
                    self.assertIn(response.status_code, (403, 409)); self.assertNotIn("candidates", response.json())
                    transaction.set_rollback(True)
        self.assertEqual(self.get(job, client=other).status_code, 200)
