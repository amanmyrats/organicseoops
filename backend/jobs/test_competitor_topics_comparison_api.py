import json
from datetime import timedelta
from time import perf_counter
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from providers.models import AIModel, AIProviderAccount
from tenancy.models import OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_synthesis_api as api, competitor_synthesis_job as original, competitor_topics_source as topic_source
from . import test_competitor_topics_comparison as fixtures
from .models import AIUsageRecord, Artifact, JobCancellation, JobRun, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "topic-comparison-api"}},
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorTopicsComparisonApiTests(TransactionTestCase):
    setUp = fixtures.CompetitorTopicsComparisonTests.setUp
    queue = fixtures.CompetitorTopicsComparisonTests.queue
    transport = fixtures.CompetitorTopicsComparisonTests.transport
    input_data = fixtures.CompetitorTopicsComparisonTests.input_data
    queued = fixtures.CompetitorTopicsComparisonTests.queued
    response = fixtures.CompetitorTopicsComparisonTests.response
    execute = fixtures.CompetitorTopicsComparisonTests.execute

    def pair(self, **kwargs):
        cache.clear()
        sources, jobs = fixtures.CompetitorTopicsComparisonTests.pair(self, **kwargs)
        self.base = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/competitor-heading-topics/comparison/"
        self.query = f"?first_job_id={jobs[0].pk}&second_job_id={jobs[1].pk}"
        self.client = Client(); self.client.force_login(self.owner)
        return sources, jobs

    def test_genuine_original_packet_independent_reader_literal_indices_privacy_and_no_new_processing(self):
        sources, jobs = self.pair()
        counts = [model.objects.count() for model in (JobRun, Artifact, UsageReservation, AIUsageRecord)]
        with patch("socket.create_connection", side_effect=AssertionError("No new source")), patch("providers.services.resolve_provider_secret", side_effect=AssertionError("No key")):
            response = self.client.get(self.base + self.query, secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(set(response.json()), {"organization_id", "project_id", "comparison"})
        result = response.json()["comparison"]
        self.assertEqual(result["exact_label_match_indices"], [[0, 0], [1, 0]])
        self.assertEqual(result["unmatched_topic_indices"], [[2, 3, 4], [1, 2]])
        self.assertEqual([sample["job_id"] for sample in result["samples"]], [job.pk for job in jobs])
        self.assertEqual([sample["synthesis"]["observation"]["job_id"] for sample in result["samples"]], [source.pk for source in sources])
        other = Client(); other.force_login(self.admin)
        self.assertEqual(other.get(self.base + self.query, secure=True).json()["comparison"], result)
        reversed_query = f"?first_job_id={jobs[1].pk}&second_job_id={jobs[0].pk}"
        reverse = self.client.get(self.base + reversed_query, secure=True).json()["comparison"]
        self.assertEqual(reverse["samples"], result["samples"][::-1]); self.assertEqual(reverse["exact_label_match_indices"], [[0, 0], [0, 1]])
        self.assertEqual([model.objects.count() for model in (JobRun, Artifact, UsageReservation, AIUsageRecord)], counts)
        self.assertEqual(response["Cache-Control"], "private, no-store"); self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_bodyless_get_strict_canonical_distinct_topic_ids_methods_and_current_private_scope(self):
        sources, jobs = self.pair()
        for query in ("", self.query + "&extra=1", self.query + f"&first_job_id={jobs[0].pk}",
            f"?first_job_id=0{jobs[0].pk}&second_job_id={jobs[1].pk}", f"?first_job_id=9007199254740992&second_job_id={jobs[1].pk}",
            f"?first_job_id={jobs[0].pk}&second_job_id={jobs[0].pk}", self.query.replace("first_job_id", "previous_job_id")):
            self.assertEqual(self.client.get(self.base + query, secure=True).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.base + self.query, b"{}", content_type="application/json", secure=True).status_code, 400)
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
            result = self.client.generic(method, self.base + self.query, secure=True)
            self.assertEqual(result.status_code, 405); self.assertEqual(result["Allow"], "GET")
        self.assertEqual(Client().get(self.base + self.query, secure=True).status_code, 401)
        self.client.force_login(self.foreign); self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.base.replace(f"projects/{self.project.pk}/", f"projects/{self.project.pk + 1}/") + self.query, secure=True).status_code, 404)
        wrong = f"?first_job_id={sources[0].pk}&second_job_id={jobs[1].pk}"
        self.assertEqual(self.client.get(self.base + wrong, secure=True).status_code, 403)
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 403)

    def test_maintained_topic_read_budget_and_separate_original_heading_synthesis_family(self):
        self.pair()
        with override_settings(ACCOUNT_RATE_LIMITS={"competitor_heading_topics_read": "1/h/ip"}):
            self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)
            other = Client(); other.force_login(self.admin)
            self.assertEqual(other.get(self.base.removesuffix("comparison/"), secure=True).status_code, 429)
            self.assertEqual(other.get(self.base.replace("competitor-heading-topics/comparison", "competitor-heading-syntheses"), secure=True).status_code, 200)

    def test_same_uri_and_different_exact_origin_refuse_semantic_or_missing_topic_fabrication(self):
        for changes in ({"same_uri": True}, {"second_origin": "https://second.example.invalid"}):
            self.pair(**changes)
            result = self.client.get(self.base + self.query, secure=True)
            self.assertEqual(result.status_code, 409); self.assertNotIn("comparison", result.json())

    def test_complete_original_metadata_models_actor_caller_source_all_cancellations_and_expiry_after_serialization_withhold(self):
        sources, jobs = self.pair(); response = api._response
        for loss in ("artifact", "status", "usage", "heading", "collector", "job-actor", "caller", "config", "model", "account", "first-cancel", "second-cancel", "heading-cancel", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                cache.clear()
                def changed(data, *args, **kwargs):
                    result = response(data, *args, **kwargs)
                    if "comparison" not in data: return result
                    if loss == "artifact": Artifact.objects.filter(job=jobs[0]).update(size_bytes=1)
                    elif loss == "status": JobRun.objects.filter(pk=jobs[0].pk).update(status="failed")
                    elif loss == "usage": AIUsageRecord.objects.filter(job=jobs[0]).update(status="unknown")
                    elif loss == "heading": Artifact.objects.filter(job=sources[0]).update(size_bytes=1)
                    elif loss in {"collector", "job-actor", "caller"}:
                        OrganizationMembership.objects.filter(organization=self.organization, user=self.admin if loss == "job-actor" else self.owner).update(role="viewer")
                    elif loss == "config": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                    elif loss == "model": AIModel.objects.filter(pk=self.model.pk).update(enabled=False)
                    elif loss == "account": AIProviderAccount.objects.filter(pk=self.account.pk).update(state="revoked", revoked_at=timezone.now())
                    elif loss.endswith("cancel"):
                        JobCancellation.objects.create(job=sources[0] if loss == "heading-cancel" else jobs[0] if loss == "first-cancel" else jobs[1], requested_by=self.owner)
                    else:
                        now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31), ends_at=now-timedelta(seconds=1))
                    return result
                with patch.object(api, "_response", side_effect=changed): result = self.client.get(self.base + self.query, secure=True)
                self.assertIn(result.status_code, (403, 409), result.content); self.assertNotIn("comparison", result.json())
                self.assertEqual(result["Cache-Control"], "private, no-store")
                transaction.set_rollback(True)

    def test_first_original_metadata_and_all_cancellations_during_last_second_fresh_source_read_withhold(self):
        sources, jobs = self.pair(); response = api._response; source = original._reader_source
        for loss in ("artifact", "status", "usage", "heading", "first-cancel", "second-cancel", "heading-cancel"):
            with self.subTest(loss=loss), transaction.atomic():
                cache.clear(); final = False; calls = 0
                def serialized(data, *args, **kwargs):
                    nonlocal final
                    result = response(data, *args, **kwargs)
                    if "comparison" in data: final = True
                    return result
                def late(job, project, actor):
                    nonlocal calls
                    result = source(job, project, actor)
                    if final and job.pk == jobs[1].pk:
                        calls += 1
                        if loss == "artifact": Artifact.objects.filter(job=jobs[0]).update(size_bytes=1)
                        elif loss == "status": JobRun.objects.filter(pk=jobs[0].pk).update(status="failed")
                        elif loss == "usage": AIUsageRecord.objects.filter(job=jobs[0]).update(status="unknown")
                        elif loss == "heading": Artifact.objects.filter(job=sources[0]).update(size_bytes=1)
                        else: JobCancellation.objects.create(job=sources[0] if loss == "heading-cancel" else jobs[0] if loss == "first-cancel" else jobs[1], requested_by=self.owner)
                    return result
                with patch.object(api, "_response", side_effect=serialized), patch.object(original, "_reader_source", side_effect=late):
                    result = self.client.get(self.base + self.query, secure=True)
                self.assertEqual(calls, 1); self.assertEqual(result.status_code, 403, result.content); self.assertNotIn("comparison", result.json())
                transaction.set_rollback(True)
        self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)

    def test_actual_last_unchanged_api_metadata_withholds_original_authority_and_private_source_loss(self):
        sources, jobs = self.pair(); metadata = api._metadata
        with patch.object(api, "_metadata", wraps=metadata) as healthy:
            self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)
        expected = [call.args[0].pk for call in healthy.call_args_list]
        self.assertEqual(expected, [job.pk for job in jobs] * 4)
        terminal = expected[:6]
        for loss in ("collector", "job-actor", "revision", "origins", "model", "account", "heading", "topic", "cancel", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                cache.clear(); reached = []
                def late(job, **kwargs):
                    value = metadata(job, **kwargs); reached.append(job.pk)
                    if reached == terminal:
                        if loss == "collector": OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
                        elif loss == "job-actor": OrganizationMembership.objects.filter(organization=self.organization, user=self.admin).update(role="viewer")
                        elif loss == "revision": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                        elif loss == "origins": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[])
                        elif loss == "model": AIModel.objects.filter(pk=self.model.pk).update(enabled=False)
                        elif loss == "account": AIProviderAccount.objects.filter(pk=self.account.pk).update(state="revoked", revoked_at=timezone.now())
                        elif loss == "heading": Artifact.objects.filter(job=sources[0]).update(size_bytes=1)
                        elif loss == "topic": Artifact.objects.filter(job=jobs[0]).update(size_bytes=1)
                        elif loss == "cancel": JobCancellation.objects.create(job=sources[0], requested_by=self.owner)
                        else:
                            now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31), ends_at=now-timedelta(seconds=1))
                    return value
                with patch.object(api, "_metadata", side_effect=late), patch("socket.create_connection", side_effect=AssertionError("No provider or site")):
                    result = self.client.get(self.base + self.query, secure=True)
                self.assertEqual(reached[:6], terminal)
                self.assertIn(result.status_code, (403, 409), result.content); self.assertNotIn("comparison", result.json())
                transaction.set_rollback(True)
        self.assertEqual(self.client.get(self.base + self.query, secure=True).status_code, 200)

    @override_settings(DEBUG=False)
    def test_debug_disabled_genuine_private_read_query_cost_and_late_model_revocation(self):
        self.assertFalse(settings.DEBUG)
        sources, jobs = self.pair(); metadata = api._metadata
        counts = [model.objects.count() for model in (JobRun, Artifact, UsageReservation, AIUsageRecord)]
        queries, writes = [], []
        def count(execute, sql, params, many, context):
            queries.append(1)
            if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")): writes.append(1)
            return execute(sql, params, many, context)
        call_cost = {}
        def measured(function, name):
            def observed(*args, **kwargs):
                before, started = len(queries), perf_counter()
                try:
                    return function(*args, **kwargs)
                finally:
                    cost = call_cost.setdefault(name, {"calls": 0, "queries": 0, "inclusive_ms": 0})
                    cost["calls"] += 1; cost["queries"] += len(queries) - before
                    cost["inclusive_ms"] += (perf_counter() - started) * 1000
            return observed
        started = perf_counter()
        with (
            connection.execute_wrapper(count),
            patch.object(original, "_reader_source", measured(original._reader_source, "synthesis_reader")),
            patch.object(original, "_model_snapshot", measured(original._model_snapshot, "model_preparation")),
            patch.object(topic_source, "read_competitor_page_headings_observation", measured(topic_source.read_competitor_page_headings_observation, "heading_private_reader")),
            patch.object(original.collection, "_read_source", measured(original.collection._read_source, "original_source_check")),
            patch("socket.create_connection", side_effect=AssertionError("No site or provider")),
            patch("providers.services.resolve_provider_secret", side_effect=AssertionError("No key")),
        ):
            result = self.client.get(self.base + self.query, secure=True)
        healthy_ms = round((perf_counter() - started) * 1000, 3)
        self.assertEqual(result.status_code, 200, result.content)
        value = result.json()["comparison"]
        self.assertEqual(value["exact_label_match_indices"], [[0, 0], [1, 0]])
        self.assertEqual([row["job_id"] for row in value["samples"]], [job.pk for job in jobs])
        self.assertNotIn(b"private-contact", result.content)
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        self.assertGreater(len(queries), 0)
        self.assertLessEqual(len(queries), 17000)
        metrics = {"debug": False, "healthy_ms": healthy_ms, "healthy_queries": len(queries), "healthy_writes": len(writes),
            "healthy_call_cost": {name: dict(cost) for name, cost in call_cost.items()}}
        with transaction.atomic():
            cache.clear(); reached = []; queries.clear(); writes.clear(); call_cost.clear()
            def late(job, **kwargs):
                value = metadata(job, **kwargs); reached.append(job.pk)
                if len(reached) == 6: AIModel.objects.filter(pk=self.model.pk).update(enabled=False)
                return value
            started = perf_counter()
            with (
                connection.execute_wrapper(count), patch.object(api, "_metadata", side_effect=late),
                patch.object(original, "_reader_source", measured(original._reader_source, "synthesis_reader")),
                patch.object(original, "_model_snapshot", measured(original._model_snapshot, "model_preparation")),
                patch.object(topic_source, "read_competitor_page_headings_observation", measured(topic_source.read_competitor_page_headings_observation, "heading_private_reader")),
                patch.object(original.collection, "_read_source", measured(original.collection._read_source, "original_source_check")),
                patch("socket.create_connection", side_effect=AssertionError("No site or provider")),
                patch("providers.services.resolve_provider_secret", side_effect=AssertionError("No key")),
            ):
                denied = self.client.get(self.base + self.query, secure=True)
            metrics.update(revoked_ms=round((perf_counter() - started) * 1000, 3), revoked_queries=len(queries), revoked_writes=len(writes),
                revoked_call_cost={name: dict(cost) for name, cost in call_cost.items()})
            self.assertEqual(reached, [job.pk for job in jobs] * 3)
            self.assertIn(denied.status_code, (403, 409), denied.content)
            self.assertNotIn("comparison", denied.json())
            self.assertEqual(denied["Cache-Control"], "private, no-store")
            self.assertEqual(denied["X-Robots-Tag"], "noindex, nofollow")
            transaction.set_rollback(True)
        self.assertEqual([model.objects.count() for model in (JobRun, Artifact, UsageReservation, AIUsageRecord)], counts)
        print("TOPIC_PAIR_DEBUG_DISABLED_PROFILE " + json.dumps(metrics, sort_keys=True))
