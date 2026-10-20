import json
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from providers.models import AIModel, AIProvider, AIProviderAccount
from tenancy.models import OrganizationMembership, OrganizationTrial, Project, ProjectConfiguration
from . import competitor_collection as collection, competitor_page_headings_collection as headings
from . import competitor_synthesis_job as original, competitor_topics_comparison as comparison, competitor_topics_source as topic_source
from . import test_competitor_collection as root_fixtures, test_competitor_topics_job as fixtures
from .crawling import CrawlScope
from .models import Artifact, JobCancellation, JobRun, UsageReservation
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorTopicsComparisonTests(TransactionTestCase):
    setUp = fixtures.CompetitorTopicsJobTests.setUp
    queue = fixtures.CompetitorTopicsJobTests.queue
    transport = fixtures.CompetitorTopicsJobTests.transport
    input_data = fixtures.CompetitorTopicsJobTests.input_data
    queued = fixtures.CompetitorTopicsJobTests.queued
    response = fixtures.CompetitorTopicsJobTests.response
    execute = fixtures.CompetitorTopicsJobTests.execute

    def pair(self, *, second_origin=None, same_uri=False, first_labels=None, second_labels=None):
        self.pair_count = getattr(self, "pair_count", 0) + 1
        origin = self.data["origin"]
        origins = [origin] if not second_origin else [origin, second_origin]
        ProjectConfiguration.objects.filter(project=self.project).update(competitor_origins=origins)
        sources, jobs = [], []
        for index, selected_origin in enumerate((origin, second_origin or origin)):
            url = selected_origin + ("/selected/a" if not index or same_uri else "/selected/b")
            source = self.queue(f"labels-source-{self.pair_count}-{index}", data={**self.data, "origin": selected_origin, "url": url})
            fetcher = root_fixtures.CompetitorCollectionTests.fetcher(self,
                body=b'<h1>Selected</h1><h2>Selected</h2><p>private-contact@example.invalid</p>')
            fetcher.scope = CrawlScope(frozenset({urlsplit(selected_origin).hostname}), kind="competitor")
            with patch("socket.create_connection", side_effect=AssertionError("No actual source egress")):
                self.assertTrue(headings.execute_competitor_page_headings_collection(source.pk, fetcher=fetcher))
            source.refresh_from_db(); self.assertEqual(source.status, "succeeded", source.error_category)
            job = self.queued(source, key=f"labels-job-{self.pair_count}-{index}")
            labels = (first_labels or ["Topic", "Topic", "topic", "İlk", "Only first"]) if not index else (second_labels or ["Topic", "Only second", "I\u0307lk"])
            def request(*, checkpoint, **kwargs):
                checkpoint()
                return self.response({"topics": [{"label": label, "reference": "heading_0", "quote": "Selected"} for label in labels]})
            self.assertTrue(self.execute(job, request)); self.assertEqual(job.status, "succeeded", job.error_category)
            sources.append(source); jobs.append(job)
        return sources, jobs

    def compare(self, jobs, **changes):
        return comparison.compare_competitor_topic_labels(**{**dict(project=self.project, actor=self.owner,
            first_job_id=jobs[0].pk, second_job_id=jobs[1].pk), **changes})

    def test_genuine_original_order_duplicate_case_unicode_indices_private_independent_reader_no_writes_network_or_new_processing(self):
        sources, jobs = self.pair()
        reservations = list(UsageReservation.objects.values()); connection.queries_log.clear()
        query_count = 0; writes = []
        def capture(execute, sql, params, many, context):
            nonlocal query_count
            query_count += 1
            if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")): writes.append(sql)
            return execute(sql, params, many, context)
        with (patch("providers.services.resolve_provider_secret", side_effect=AssertionError("No key")),
            patch("providers.adapters.create_response", side_effect=AssertionError("No provider")),
            patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")),
            patch("socket.create_connection", side_effect=AssertionError("No egress")), connection.execute_wrapper(capture)):
            result = self.compare(jobs)
        self.assertGreater(query_count, 0); self.assertEqual(writes, [])
        self.assertEqual(set(result), {"method_version", "organization_id", "project_id", "source_current", "samples",
            "exact_label_match_indices", "unmatched_topic_indices", "interpretation"})
        self.assertEqual((result["method_version"], result["interpretation"]), (comparison.METHOD, comparison.INTERPRETATION))
        self.assertEqual(result["exact_label_match_indices"], [[0, 0], [1, 0]])
        self.assertEqual(result["unmatched_topic_indices"], [[2, 3, 4], [1, 2]])
        self.assertEqual([sample["job_id"] for sample in result["samples"]], [job.pk for job in jobs])
        self.assertEqual([sample["synthesis"]["observation"]["job_id"] for sample in result["samples"]], [source.pk for source in sources])
        self.assertEqual(result, self.compare(jobs, actor=self.admin))
        self.assertNotIn("PRIVATE RAW", json.dumps(result)); self.assertNotIn("private-contact", json.dumps(result))
        self.assertEqual(JobRun.objects.count(), 4); self.assertEqual(list(UsageReservation.objects.values()), reservations)
        result["samples"][0]["synthesis"]["topics"][0]["label"] = "Changed"
        self.assertEqual(self.compare(jobs)["samples"][0]["synthesis"]["topics"][0]["label"], "Topic")

    def test_reversed_order_all_literal_matches_and_no_matches_are_sample_indices_not_missing_topics(self):
        _, jobs = self.pair(first_labels=["Topic"] * 10, second_labels=["Topic"] * 10)
        result = self.compare(jobs)
        self.assertEqual(result["exact_label_match_indices"], [[i, j] for i in range(10) for j in range(10)])
        self.assertEqual(result["unmatched_topic_indices"], [[], []])
        _, distinct = self.pair(first_labels=["First"], second_labels=["first"])
        result = self.compare(distinct[::-1])
        self.assertEqual([sample["job_id"] for sample in result["samples"]], [job.pk for job in distinct[::-1]])
        self.assertEqual(result["exact_label_match_indices"], [])
        self.assertEqual(result["unmatched_topic_indices"], [[0], [0]])

    def test_actual_distinct_scope_fixed_family_safe_ids_and_original_uri_origin_are_required(self):
        sources, jobs = self.pair()
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other-owned.example.invalid")
        for changes in ({"actor": self.foreign}, {"project": other}, {"first_job_id": sources[0].pk},
            {"first_job_id": jobs[0].pk, "second_job_id": jobs[0].pk},
            *({"first_job_id": value} for value in (True, 0, -1, 2**53, str(jobs[0].pk), None))):
            with self.subTest(changes=changes), self.assertRaises((PermissionDenied, ValidationError)):
                self.compare(jobs, **changes)
        for kwargs in ({"same_uri": True}, {"second_origin": "https://second.example.invalid"}):
            _, invalid = self.pair(**kwargs)
            with self.assertRaises(ValidationError): self.compare(invalid)

    def test_actual_private_corruption_missing_or_unavailable_result_and_closed_packet_cap_withhold(self):
        sources, jobs = self.pair()
        empty = self.queued(sources[0], key="empty-label-result")
        self.assertTrue(self.execute(empty, lambda **kwargs: self.response({"topics": []})))
        self.assertEqual(empty.status, "failed"); self.assertEqual(empty.output, {})
        with self.assertRaises(PermissionDenied): self.compare([empty, jobs[1]])
        with patch.object(comparison, "MAX_RESULT_BYTES", 1), self.assertRaises(ValidationError): self.compare(jobs)
        with transaction.atomic():
            Artifact.objects.filter(job=jobs[0]).update(size_bytes=1)
            with self.assertRaises(ValidationError): self.compare(jobs)
            transaction.set_rollback(True)
        for job in (jobs[0], sources[0]):
            with transaction.atomic():
                JobRun.objects.filter(pk=job.pk).update(status="failed")
                with self.assertRaises((PermissionDenied, ValidationError)): self.compare(jobs)
                transaction.set_rollback(True)

    def test_after_serialization_all_original_metadata_actor_caller_config_model_cancellation_or_expiry_losses_withhold(self):
        sources, jobs = self.pair(); encode = collection._encode
        for kind in ("topic_metadata", "heading_metadata", "original_actor", "caller", "config", "model", "topic_cancel", "heading_cancel", "expiry"):
            with transaction.atomic():
                fired = False
                def project(value):
                    nonlocal fired
                    content = encode(value)
                    if type(value) is dict and value.get("method_version") == comparison.METHOD and not fired:
                        fired = True
                        if kind == "topic_metadata": Artifact.objects.filter(job=jobs[0]).update(size_bytes=1)
                        if kind == "heading_metadata": Artifact.objects.filter(job=sources[0]).update(size_bytes=1)
                        if kind == "original_actor": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                        if kind == "caller": OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
                        if kind == "config": ProjectConfiguration.objects.filter(project=self.project).update(revision=2)
                        if kind == "model": AIModel.objects.filter(pk=self.model.pk).update(enabled=False)
                        if kind in {"topic_cancel", "heading_cancel"}: JobCancellation.objects.create(job=jobs[0] if kind == "topic_cancel" else sources[0], requested_by=self.owner)
                        if kind == "expiry":
                            now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=31), ends_at=now - timedelta(seconds=1))
                    return content
                with self.subTest(kind=kind), patch.object(collection, "_encode", side_effect=project), self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                    self.compare(jobs)
                self.assertTrue(fired); transaction.set_rollback(True)

    def test_first_topic_metadata_status_or_any_original_cancel_during_last_second_fresh_source_read_withholds_both(self):
        sources, jobs = self.pair(); encode = collection._encode; reader = original._reader_source
        for loss in ("topic_cancel", "heading_cancel", "topic_artifact", "topic_status", "heading_artifact"):
            with transaction.atomic():
                projected = False; fired = False
                def project(value):
                    nonlocal projected
                    content = encode(value)
                    if type(value) is dict and value.get("method_version") == comparison.METHOD: projected = True
                    return content
                def read(job, project, actor):
                    nonlocal fired
                    result = reader(job, project, actor)
                    if projected and job.pk == jobs[1].pk:
                        if loss in {"topic_cancel", "heading_cancel"}:
                            JobCancellation.objects.create(job=jobs[0] if loss == "topic_cancel" else sources[0], requested_by=self.owner)
                        if loss == "topic_artifact": Artifact.objects.filter(job=jobs[0]).update(size_bytes=1)
                        if loss == "topic_status": JobRun.objects.filter(pk=jobs[0].pk).update(status="failed")
                        if loss == "heading_artifact": Artifact.objects.filter(job=sources[0]).update(size_bytes=1)
                        fired = True
                    return result
                with patch.object(collection, "_encode", side_effect=project), patch.object(original, "_reader_source", side_effect=read), self.assertRaises(PermissionDenied):
                    self.compare(jobs)
                self.assertTrue(fired); transaction.set_rollback(True)

    def test_actual_last_unchanged_heading_pins_withhold_original_authority_and_private_metadata_loss(self):
        sources, jobs = self.pair(); pins = comparison.synthesis._pins
        heading_ids = tuple(source.pk for source in sources)
        with patch.object(comparison.synthesis, "_pins", wraps=pins) as healthy:
            self.compare(jobs)
        self.assertEqual(sum(tuple(call.args[0]) == heading_ids for call in healthy.call_args_list), 4)
        for loss in ("collector", "job-actor", "caller", "revision", "origins", "model", "account", "heading", "topic", "cancel", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                reached = []
                def late(ids):
                    value = pins(ids)
                    if tuple(ids) == heading_ids:
                        reached.append(tuple(ids))
                        if len(reached) == 3:
                            if loss == "collector": OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
                            elif loss == "job-actor": OrganizationMembership.objects.filter(organization=self.organization, user=self.admin).update(role="viewer")
                            elif loss == "caller": type(self.owner).objects.filter(pk=self.owner.pk).update(is_active=False)
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
                with patch.object(comparison.synthesis, "_pins", side_effect=late), patch("socket.create_connection", side_effect=AssertionError("No provider or site")):
                    with self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                        self.compare(jobs)
                self.assertEqual(len(reached), 3)
                transaction.set_rollback(True)
        self.assertEqual(self.compare(jobs)["exact_label_match_indices"], [[0, 0], [1, 0]])

    def test_one_current_source_preparation_per_reader_and_fresh_actor_model_metadata_fences(self):
        sources, jobs = self.pair(); reader = topic_source.read_competitor_page_headings_observation
        with patch.object(topic_source, "read_competitor_page_headings_observation", wraps=reader) as reads:
            source, callers = original._reader_source(jobs[0], self.project, self.owner)
        self.assertEqual(reads.call_count, 1)
        self.assertEqual(source["observation"]["job_id"], sources[0].pk)
        self.assertEqual(source["observation"]["collection"]["evidence"], sources[0].output["evidence"])
        self.assertEqual(set(callers), {sources[0].pk})
        with patch.object(collection, "read_project_artifact", side_effect=AssertionError("Denied caller must not read private bytes")), self.assertRaises(PermissionDenied):
            original._reader_source(jobs[0], self.project, self.foreign)
        pair_sources = original._read_pair_sources
        for loss in ("collector", "job-actor", "caller", "revision", "origins", "model", "provider", "account", "heading", "status", "topic-cancel", "heading-cancel", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                reached = []
                def late(rows, project, actor):
                    value = pair_sources(rows, project, actor); reached.append(value)
                    if len(reached) == 3:
                        if loss == "collector": OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
                        elif loss == "job-actor": OrganizationMembership.objects.filter(organization=self.organization, user=self.admin).update(role="viewer")
                        elif loss == "caller": type(self.owner).objects.filter(pk=self.owner.pk).update(is_active=False)
                        elif loss == "revision": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                        elif loss == "origins": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[])
                        elif loss == "model": AIModel.objects.filter(pk=self.model.pk).update(enabled=False)
                        elif loss == "provider": AIProvider.objects.filter(pk=self.model.provider_id).update(enabled=False)
                        elif loss == "account": AIProviderAccount.objects.filter(pk=self.account.pk).update(state="revoked", revoked_at=timezone.now())
                        elif loss == "heading": Artifact.objects.filter(job=sources[0]).update(size_bytes=1)
                        elif loss == "status": JobRun.objects.filter(pk=sources[0].pk).update(status="failed")
                        elif loss in {"topic-cancel", "heading-cancel"}: JobCancellation.objects.create(job=jobs[0] if loss == "topic-cancel" else sources[0], requested_by=self.owner)
                        else:
                            now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31), ends_at=now-timedelta(seconds=1))
                    return value
                with patch.object(original, "_read_pair_sources", side_effect=late), patch("socket.create_connection", side_effect=AssertionError("No site/provider")), self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                    original._reader_source(jobs[0], self.project, self.owner)
                self.assertEqual(len(reached), 3)
                transaction.set_rollback(True)
        self.assertEqual(original._reader_source(jobs[0], self.project, self.owner), (source, callers))
