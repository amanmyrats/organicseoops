from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db import transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_api as api, competitor_collection as collection
from . import test_competitor_destination_inventory as fixtures
from .models import Artifact, JobCancellation, JobRun, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "destination-inventory-api"}},
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorDestinationInventoryApiTests(TransactionTestCase):
    setUp = fixtures.CompetitorDestinationInventoryTests.setUp
    transport = fixtures.CompetitorDestinationInventoryTests.transport
    fetcher = fixtures.CompetitorDestinationInventoryTests.fetcher
    HTML = fixtures.CompetitorDestinationInventoryTests.HTML
    collected = fixtures.CompetitorDestinationInventoryTests.collected

    def pair(self):
        cache.clear()
        first, second = fixtures.CompetitorDestinationInventoryTests.pair(self)
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/competitor-page-destinations/inventory/"
        self.query = f"?first_job_id={first.pk}&second_job_id={second.pk}"
        self.client.force_login(self.admin)
        return first, second

    def test_genuine_exact_resolved_uri_inventory_originals_independent_reader_private_no_new_work_or_network(self):
        first, second = self.pair(); counts = [model.objects.count() for model in (JobRun, Artifact, UsageReservation)]
        with patch("socket.create_connection", side_effect=AssertionError("No target fetch")):
            response = self.client.get(self.base + self.query, secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(set(response.json()), {"organization_id", "project_id", "inventory"})
        result = response.json()["inventory"]
        self.assertEqual(result["destination_reference_occurrences"], [[2, 1, 1, 1, 0], [0, 0, 0, 0, 1]])
        self.assertEqual(result["destinations"], [self.data["origin"] + path for path in
            ("/selected/b", "/selected/b/", "/selected/%62", "/selected/B", "/selected/a")])
        self.assertEqual([page["job_id"] for page in result["pages"]], [first.pk, second.pk])
        owner = Client(); owner.force_login(self.owner)
        self.assertEqual(owner.get(self.base + self.query, secure=True).json()["inventory"], result)
        self.assertEqual([model.objects.count() for model in (JobRun, Artifact, UsageReservation)], counts)
        self.assertEqual(response["Cache-Control"], "private, no-store"); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_bodyless_get_canonical_distinct_ids_exact_scope_and_methods(self):
        first, second = self.pair()
        for query in ("", self.query + "&extra=1", self.query + f"&first_job_id={first.pk}",
            f"?first_job_id=0{first.pk}&second_job_id={second.pk}",
            f"?first_job_id=9007199254740992&second_job_id={second.pk}",
            f"?first_job_id={first.pk}&second_job_id={first.pk}",
            f"?previous_job_id={first.pk}&current_job_id={second.pk}"):
            with self.subTest(query=query): self.assertEqual(self.client.get(self.base + query, secure=True).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.base + self.query, b"{}", content_type="application/json", secure=True).status_code, 400)
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
            result = self.client.generic(method, self.base + self.query, secure=True)
            self.assertEqual(result.status_code, 405); self.assertEqual(result["Allow"], "GET")
        self.assertEqual(Client().get(self.base + self.query, secure=True).status_code, 401)
        foreign = Client(); foreign.force_login(self.foreign)
        self.assertEqual(foreign.get(self.base + self.query, secure=True).status_code, 404)
        wrong = self.base.replace(f"projects/{self.project.pk}/", f"projects/{self.project.pk + 1}/")
        self.assertEqual(self.client.get(wrong + self.query, secure=True).status_code, 404)
        csrf = Client(enforce_csrf_checks=True); csrf.force_login(self.admin)
        self.assertEqual(csrf.post(self.base + self.query, {}, secure=True).status_code, 403)

    def test_shared_reference_read_budget_and_original_structure_and_dated_modes_stay_separate(self):
        self.pair()
        with override_settings(ACCOUNT_RATE_LIMITS={"competitor_page_destinations_read": "1/h/ip"}):
            self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)
            self.assertEqual(self.client.get(self.base.replace("inventory/", "structure/") + self.query, secure=True).status_code, 429)
        cache.clear()
        structure = self.client.get(self.base.replace("inventory/", "structure/") + self.query, secure=True)
        self.assertEqual(structure.status_code, 200, structure.content)
        self.assertIn("structure", structure.json()); self.assertNotIn("inventory", structure.json())
        self.assertEqual(self.client.get(self.base.replace("inventory/", "comparison/") + self.query, secure=True).status_code, 400)

    def test_unknown_empty_union_private_integrity_and_wrong_family_uri_or_origin_withhold(self):
        first, second = self.pair()
        empty = self.collected("/selected/empty", b"<p>Empty</p>", "inventory-api-empty")
        unknown = self.collected("/selected/unknown", b"<title>Unclosed", "inventory-api-unknown")
        result = self.client.get(self.base + f"?first_job_id={empty.pk}&second_job_id={unknown.pk}", secure=True)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["inventory"]["destinations"], [])
        self.assertEqual(result.json()["inventory"]["destination_reference_occurrences"], [[], None])
        self.assertFalse(result.json()["inventory"]["all_rows_observed"])
        same = self.collected("/selected/a", b"<p>Another sample</p>", "inventory-api-same")
        other = self.collected("/selected/other", b"<p>Other origin</p>", "inventory-api-other", origin="https://second.example.invalid")
        for row in (same, other):
            self.assertEqual(self.client.get(self.base + f"?first_job_id={first.pk}&second_job_id={row.pk}", secure=True).status_code, 409)
        read = collection.read_project_artifact
        with patch.object(collection, "read_project_artifact", side_effect=lambda **kwargs: read(**kwargs) + b" "):
            self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 409)
        root = collection.queue_competitor_collection(project=self.project, actor=self.owner,
            data={key: value for key, value in self.data.items() if key != "url"}, idempotency_key="inventory-api-root")
        self.assertTrue(collection.execute_competitor_collection(root.pk, fetcher=self.fetcher(body=b"<p>Root</p>")))
        self.assertEqual(self.client.get(self.base + f"?first_job_id={first.pk}&second_job_id={root.pk}", secure=True).status_code, 403)

    def test_serialized_original_metadata_actor_caller_configuration_all_cancellations_and_expiry_withhold(self):
        first, second = self.pair(); response = api._response
        for loss in ("artifact", "status", "usage", "actor", "caller", "configuration", "first-cancel", "second-cancel", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                cache.clear(); calls = 0
                def late(data, *args, **kwargs):
                    nonlocal calls
                    result = response(data, *args, **kwargs)
                    if "inventory" in data:
                        calls += 1
                        if loss == "artifact": Artifact.objects.filter(job=first).update(size_bytes=1)
                        elif loss == "status": JobRun.objects.filter(pk=first.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=first).update(actual_units=2)
                        elif loss in ("actor", "caller"):
                            OrganizationMembership.objects.filter(organization=self.organization,
                                user=self.owner if loss == "actor" else self.admin).update(role="viewer")
                        elif loss == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                        elif loss in ("first-cancel", "second-cancel"):
                            JobCancellation.objects.create(job=first if loss == "first-cancel" else second, requested_by=self.owner)
                        else:
                            now = timezone.now()
                            OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31), ends_at=now-timedelta(seconds=1))
                    return result
                with patch.object(api, "_response", side_effect=late): result = self.client.get(self.base + self.query, secure=True)
                self.assertEqual(calls, 1); self.assertEqual(result.status_code, 403, result.content)
                self.assertNotIn("inventory", result.json()); self.assertIn("no-store", result["Cache-Control"])
                transaction.set_rollback(True)
        cache.clear(); self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)

    def test_last_serialized_fresh_pair_source_original_metadata_usage_status_and_both_cancellations_withhold(self):
        first, second = self.pair(); response = api._response; source = api._read_pair_sources
        for loss in ("artifact", "status", "usage", "first-cancel", "second-cancel"):
            with self.subTest(loss=loss), transaction.atomic():
                cache.clear(); final = False; calls = 0
                def serialized(data, *args, **kwargs):
                    nonlocal final
                    result = response(data, *args, **kwargs)
                    if "inventory" in data: final = True
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
                self.assertNotIn("inventory", result.json())
                transaction.set_rollback(True)
        cache.clear(); self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)
