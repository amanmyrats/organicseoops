from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db import transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_api as api, competitor_collection as collection
from . import test_competitor_reference_structure as fixtures
from .models import Artifact, JobCancellation, JobRun, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "reference-structure-api"}},
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorReferenceStructureApiTests(TransactionTestCase):
    setUp = fixtures.CompetitorReferenceStructureTests.setUp
    transport = fixtures.CompetitorReferenceStructureTests.transport
    fetcher = fixtures.CompetitorReferenceStructureTests.fetcher
    HTML = fixtures.CompetitorReferenceStructureTests.HTML
    collected = fixtures.CompetitorReferenceStructureTests.collected

    def pair(self):
        cache.clear()
        first, second = fixtures.CompetitorReferenceStructureTests.pair(self)
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/competitor-page-destinations/structure/"
        self.query = f"?first_job_id={first.pk}&second_job_id={second.pk}"
        self.client.force_login(self.admin)
        return first, second

    def test_genuine_original_packet_exact_variants_independent_reader_and_no_new_jobs_or_network(self):
        first, second = self.pair()
        counts = [model.objects.count() for model in (JobRun, Artifact, UsageReservation)]
        with patch("socket.create_connection", side_effect=AssertionError("No target fetch")):
            response = self.client.get(self.base + self.query, secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(set(response.json()), {"organization_id", "project_id", "structure"})
        result = response.json()["structure"]
        self.assertEqual(result["selected_uri_reference_occurrences"], [[0, 2], [1, 0]])
        self.assertEqual([row["job_id"] for row in result["pages"]], [first.pk, second.pk])
        self.assertEqual(result["pages"][0]["collection"]["evidence"]["destinations"],
            [self.data["origin"] + path for path in ("/selected/b", "/selected/b", "/selected/b/", "/selected/%62")])
        owner = Client(); owner.force_login(self.owner)
        self.assertEqual(owner.get(self.base + self.query, secure=True).json()["structure"], result)
        self.assertEqual([model.objects.count() for model in (JobRun, Artifact, UsageReservation)], counts)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_bodyless_get_canonical_distinct_ids_exact_scope_and_methods(self):
        first, second = self.pair()
        invalid = ("", self.query + "&extra=1", self.query + f"&first_job_id={first.pk}",
            f"?first_job_id=0{first.pk}&second_job_id={second.pk}",
            f"?first_job_id=9007199254740992&second_job_id={second.pk}",
            f"?first_job_id={first.pk}&second_job_id={first.pk}",
            f"?previous_job_id={first.pk}&current_job_id={second.pk}")
        for query in invalid:
            with self.subTest(query=query):
                self.assertEqual(self.client.get(self.base + query, secure=True).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.base + self.query, b"{}", content_type="application/json", secure=True).status_code, 400)
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
            response = self.client.generic(method, self.base + self.query, secure=True)
            self.assertEqual(response.status_code, 405)
            self.assertEqual(response["Allow"], "GET")
        self.assertEqual(Client().get(self.base + self.query, secure=True).status_code, 401)
        foreign = Client(); foreign.force_login(self.foreign)
        self.assertEqual(foreign.get(self.base + self.query, secure=True).status_code, 404)
        wrong = self.base.replace(f"projects/{self.project.pk}/", f"projects/{self.project.pk + 1}/")
        self.assertEqual(self.client.get(wrong + self.query, secure=True).status_code, 404)
        csrf = Client(enforce_csrf_checks=True); csrf.force_login(self.admin)
        self.assertEqual(csrf.post(self.base + self.query, {}, secure=True).status_code, 403)

    def test_shared_reference_read_budget_and_original_dated_comparison_contract_stays_separate(self):
        self.pair()
        with override_settings(ACCOUNT_RATE_LIMITS={"competitor_page_destinations_read": "1/h/ip"}):
            self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)
            self.assertEqual(self.client.get(self.base.removesuffix("structure/"), secure=True).status_code, 429)
        cache.clear()
        self.assertEqual(self.client.get(self.base.replace("structure/", "comparison/") + self.query, secure=True).status_code, 400)
        dated = self.query.replace("first_job_id", "previous_job_id").replace("second_job_id", "current_job_id")
        self.assertEqual(self.client.get(self.base.replace("structure/", "comparison/") + dated, secure=True).status_code, 409)

    def test_empty_unavailable_and_wrong_family_same_uri_or_different_origin_do_not_fabricate_structure(self):
        first, second = self.pair()
        empty = self.collected("/selected/empty", b"<p>Empty</p>", "structure-api-empty")
        unavailable = self.collected("/selected/unavailable", b"<title>Unclosed", "structure-api-unavailable")
        response = self.client.get(self.base + f"?first_job_id={empty.pk}&second_job_id={unavailable.pk}", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["structure"]["selected_uri_reference_occurrences"], [[0, 0], [None, None]])
        same = self.collected("/selected/a", b"<p>Another sample</p>", "structure-api-same")
        other = self.collected("/selected/other", b"<p>Other</p>", "structure-api-other", origin="https://second.example.invalid")
        for job in (same, other):
            self.assertEqual(self.client.get(self.base + f"?first_job_id={first.pk}&second_job_id={job.pk}", secure=True).status_code, 409)
        JobRun.objects.filter(pk=second.pk).update(handler=collection.HANDLER)
        response = self.client.get(self.base + self.query, secure=True)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("structure", response.json())

    def test_both_original_metadata_and_current_actor_caller_source_cancel_or_expiry_loss_after_serialization_withholds(self):
        first, second = self.pair(); original_response = api._response
        for loss in ("metadata", "actor", "caller", "source", "first-cancel", "second-cancel", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                def changed(data, *args, **kwargs):
                    response = original_response(data, *args, **kwargs)
                    if "structure" not in data: return response
                    if loss == "metadata": Artifact.objects.filter(job=first).update(size_bytes=1)
                    elif loss in {"actor", "caller"}:
                        OrganizationMembership.objects.filter(organization=self.organization,
                            user=self.owner if loss == "actor" else self.admin).update(role="viewer")
                    elif loss == "source": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                    elif loss.endswith("cancel"):
                        JobCancellation.objects.create(job=first if loss == "first-cancel" else second, requested_by=self.owner)
                    else:
                        now = timezone.now()
                        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31), ends_at=now-timedelta(seconds=1))
                    return response
                with patch.object(api, "_response", side_effect=changed):
                    response = self.client.get(self.base + self.query, secure=True)
                self.assertIn(response.status_code, (403, 409), response.content)
                self.assertNotIn("structure", response.json())
                self.assertEqual(response["Cache-Control"], "private, no-store")
                transaction.set_rollback(True)
        self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)

    def test_first_cancellation_during_last_second_source_read_after_unchanged_api_metadata_withholds(self):
        first, second = self.pair(); metadata = api._metadata; source = collection._read_source
        final = False; calls = 0
        def final_metadata(key):
            nonlocal final, calls
            result = metadata(key)
            if key == second.pk:
                calls += 1
                if calls == 2: final = True
            return result
        def late(job, project, actor):
            result = source(job, project, actor)
            if final and job.pk == second.pk:
                JobCancellation.objects.create(job=first, requested_by=self.owner)
            return result
        with patch.object(api, "_metadata", side_effect=final_metadata), patch.object(collection, "_read_source", side_effect=late):
            response = self.client.get(self.base + self.query, secure=True)
        self.assertTrue(final)
        self.assertEqual(response.status_code, 403, response.content)
        self.assertNotIn("structure", response.json())
        self.assertTrue(JobCancellation.objects.filter(job=first).exists())

    def test_last_serialized_detail_source_metadata_status_usage_and_cancellation_losses_withhold(self):
        first, _second = self.pair(); response = api._response; source = collection._read_source
        url = self.base.removesuffix("structure/") + f"{first.pk}/"
        healthy = self.client.get(url, secure=True); self.assertEqual(healthy.status_code, 200, healthy.content)
        expected = healthy.json()["evidence"]
        for loss in ("artifact", "status", "usage", "cancel"):
            with self.subTest(loss=loss), transaction.atomic():
                cache.clear(); final = False; calls = 0
                def serialized(data, *args, **kwargs):
                    nonlocal final
                    result = response(data, *args, **kwargs)
                    if "evidence" in data: final = True
                    return result
                def last(job, project, actor):
                    nonlocal calls
                    result = source(job, project, actor)
                    if final:
                        calls += 1
                        if loss == "artifact": Artifact.objects.filter(job=first).update(size_bytes=1)
                        elif loss == "status": JobRun.objects.filter(pk=first.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=first).update(actual_units=2)
                        else: JobCancellation.objects.create(job=first, requested_by=self.owner)
                    return result
                with patch.object(api, "_response", side_effect=serialized), patch.object(collection, "_read_source", side_effect=last):
                    result = self.client.get(url, secure=True)
                self.assertEqual(calls, 1); self.assertEqual(result.status_code, 403, result.content)
                self.assertNotIn("evidence", result.json())
                transaction.set_rollback(True)
        cache.clear(); self.assertEqual(self.client.get(url, secure=True).json()["evidence"], expected)

    def test_last_serialized_pair_source_first_metadata_status_usage_and_both_cancellations_withhold(self):
        first, second = self.pair(); response = api._response; source = api._read_pair_sources
        healthy = self.client.get(self.base + self.query, secure=True); self.assertEqual(healthy.status_code, 200, healthy.content)
        expected = healthy.json()["structure"]
        for loss in ("artifact", "status", "usage", "first-cancel", "second-cancel"):
            with self.subTest(loss=loss), transaction.atomic():
                cache.clear(); final = False; calls = 0
                def serialized(data, *args, **kwargs):
                    nonlocal final
                    result = response(data, *args, **kwargs)
                    if "structure" in data: final = True
                    return result
                def last(*args):
                    nonlocal calls
                    result = source(*args)
                    if final:
                        calls += 1
                        if loss == "artifact": Artifact.objects.filter(job=first).update(size_bytes=1)
                        elif loss == "status": JobRun.objects.filter(pk=first.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=first).update(actual_units=2)
                        else: JobCancellation.objects.create(job=first if loss == "first-cancel" else second, requested_by=self.owner)
                    return result
                with patch.object(api, "_response", side_effect=serialized), patch.object(api, "_read_pair_sources", side_effect=last):
                    result = self.client.get(self.base + self.query, secure=True)
                self.assertEqual(calls, 1); self.assertEqual(result.status_code, 403, result.content)
                self.assertNotIn("structure", result.json())
                transaction.set_rollback(True)
        cache.clear(); self.assertEqual(self.client.get(self.base + self.query, secure=True).json()["structure"], expected)
