import json
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_collection as collection, competitor_comparison as comparison
from . import test_competitor_collection as fixtures
from .competitor_comparison import compare_competitor_roots
from .crawling import CrawlScope, SafeFetcher
from .models import Artifact, JobCancellation, JobRun, UsageReservation
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorComparisonTests(TransactionTestCase):
    setUp = fixtures.CompetitorCollectionTests.setUp
    queue = fixtures.CompetitorCollectionTests.queue
    transport = fixtures.CompetitorCollectionTests.transport

    def collected(self, key, body=b"<title>First</title><h1>Selected</h1>", **changes):
        job = self.queue(key, **changes)
        documents = []
        for document, kind in ((b"User-agent: *\nDisallow:\n", "text/plain"), (body, "text/html; charset=utf-8")):
            _, conn, *_ = self.transport(document, fields=f"Content-Length: {len(document)}\r\nContent-Type: {kind}\r\n".encode())
            documents.append(conn)
        fetcher = SafeFetcher(CrawlScope(frozenset({"competitor.example.invalid"}), kind="competitor"),
            resolver=lambda *args: ["93.184.216.34"], connection_factory=lambda *args: documents.pop(0), max_redirects=0, timeout=8, max_bytes=131072)
        with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
            self.assertTrue(collection.execute_competitor_collection(job.pk, fetcher=fetcher))
        job.refresh_from_db(); self.assertEqual(job.status, "succeeded", job.error_category)
        connection.queries_log.clear()
        return job

    def compare(self, before, after, **changes):
        return compare_competitor_roots(**{**dict(project=self.project, actor=self.owner,
            previous_job_id=before.pk, current_job_id=after.pk), **changes})

    def test_genuine_dated_private_literal_differences_independent_reader_no_write_network_or_raw_content(self):
        before = self.collected("compare-before")
        after = self.collected("compare-after", b'<title>Second</title><h2>New</h2><a href="/private">Link</a><p>private-contact@example.invalid</p>')
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No comparison fetch")), CaptureQueriesContext(connection) as queries:
            result = self.compare(before, after, actor=self.admin)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertTrue(result["comparable"]); self.assertTrue(result["body_changed"])
        self.assertEqual(result["metadata_changed"], {"title": True, "description": False})
        self.assertEqual(result["count_deltas"], {"h1": -1, "h2": 1, "h3": 0, "h4": 0, "h5": 0, "h6": 0, "href_anchors": 1, "json_ld_blocks": 0})
        self.assertEqual(result["previous"]["evidence"], before.output["evidence"])
        self.assertEqual(result["current"]["evidence"], after.output["evidence"])
        self.assertEqual(result["source_sha256"], before.config_snapshot["binding"]["source_sha256"])
        for private in ("private-contact", "/private", self.owner.email, "Private customer prose", "artifact_id"):
            self.assertNotIn(private, json.dumps(result))
        result["previous"]["evidence"]["counts"]["h1"] = 999
        self.assertEqual(self.compare(before, after)["previous"]["evidence"]["counts"]["h1"], 1)

    def test_observed_empty_is_comparable_but_ambiguous_truncated_or_overflow_is_incomparable_null_not_zero(self):
        before = self.collected("empty-before", b"<p>Empty selected metadata</p>")
        for index, body in enumerate((b"<p>Still empty</p>", b"<template>Unclosed", b"<title>" + b"x" * 501 + b"</title>", b"<h1>x</h1>" * 1001)):
            after = self.collected("coverage-" + str(index), body)
            result = self.compare(before, after)
            self.assertEqual(result["comparable"], index == 0)
            if index:
                self.assertEqual(result["state"], "incomparable_unavailable_or_truncated_metadata")
                self.assertIsNone(result["metadata_changed"]); self.assertIsNone(result["count_deltas"])
            else:
                self.assertEqual(result["metadata_changed"], {"title": False, "description": False})
                self.assertTrue(all(value == 0 for value in result["count_deltas"].values()))

    def test_exact_distinct_ids_increasing_dates_original_actor_and_current_scope_are_required(self):
        before = self.collected("source-before"); after = self.collected("source-after")
        for first, second in ((before, before), (after, before)):
            with self.assertRaises(ValidationError): self.compare(first, second)
        for value in (True, 0, -1, 2**53, str(before.pk), None):
            with self.assertRaises(ValidationError): self.compare(before, after, previous_job_id=value)
        with self.assertRaises(PermissionDenied): self.compare(before, after, actor=self.foreign)
        different_actor = self.collected("other-original-actor", actor=self.admin)
        with self.assertRaises(ValidationError): self.compare(before, different_actor)
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[])
        with self.assertRaises((PermissionDenied, ValidationError)): self.compare(before, after)

    def test_late_first_pair_row_source_caller_or_natural_expiry_during_second_readback_withholds_both(self):
        before = self.collected("late-before"); after = self.collected("late-after")
        original = collection.read_project_artifact
        artifact = before.artifacts.get()
        for kind in ("first-artifact", "caller", "configuration", "expiry"):
            calls = 0
            def late_read(**kwargs):
                nonlocal calls
                content = original(**kwargs); calls += 1
                if calls == 2:
                    if kind == "first-artifact": Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes + 1)
                    if kind == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                    if kind == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                    if kind == "expiry":
                        now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=31), ends_at=now - timedelta(days=1))
                return content
            with patch.object(collection, "read_project_artifact", side_effect=late_read), self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                self.compare(before, after, actor=self.admin)
            Artifact.objects.filter(pk=artifact.pk).update(size_bytes=artifact.size_bytes)
            OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="admin")
            ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=1)
            now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=1), ends_at=now + timedelta(days=1))
        self.assertEqual(JobRun.objects.filter(handler=before.handler).count(), 2)

    def test_last_second_metadata_return_fences_both_original_sources_and_independent_caller(self):
        before = self.collected("last-pin-before"); after = self.collected("last-pin-after")
        expected = self.compare(before, after, actor=self.admin)
        metadata, read = collection._read_metadata, collection.read_competitor_observation
        for loss in ("actor", "caller", "revision", "approval-list", "first-cancel", "organization", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                now = [timezone.now()]
                ends = now[0] + timedelta(seconds=20)
                OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends - timedelta(days=30), ends_at=ends)
                inner, pins = [False], []
                def private_read(**kwargs):
                    inner[0] = True
                    try: return read(**kwargs)
                    finally: inner[0] = False
                def last_pin(job_id):
                    result = metadata(job_id)
                    if not inner[0]:
                        pins.append(job_id)
                        if pins == [before.pk, after.pk, before.pk, after.pk]:
                            if loss == "actor": fixtures.CompetitorCollectionTests.revoke(self)
                            elif loss == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                            elif loss == "revision": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                            elif loss == "approval-list": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[self.data["origin"]])
                            elif loss == "first-cancel": JobCancellation.objects.create(job=before, requested_by=self.owner)
                            elif loss == "organization": Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True)
                            else: now[0] = ends
                    return result
                with (patch.object(collection, "read_competitor_observation", side_effect=private_read),
                    patch.object(collection, "_read_metadata", side_effect=last_pin),
                    patch("jobs.usage.timezone.now", side_effect=lambda: now[0])):
                    with self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                        self.compare(before, after, actor=self.admin)
                    self.assertEqual(pins, [before.pk, after.pk, before.pk, after.pk])
                transaction.set_rollback(True)
        self.assertEqual(self.compare(before, after, actor=self.admin), expected)

    def test_first_original_cancellation_during_last_second_source_read_withholds_whole_private_pair(self):
        before = self.collected("last-source-before"); after = self.collected("last-source-after")
        source, reader = collection._read_source, collection.read_competitor_observation
        done, injected = set(), [False]
        def private_read(**kwargs):
            result = reader(**kwargs); done.add(kwargs["job_id"]); return result
        def final_source(job, *args, **kwargs):
            result = source(job, *args, **kwargs)
            if done == {before.pk, after.pk} and job.pk == after.pk and not injected[0]:
                JobCancellation.objects.create(job=before, requested_by=self.owner)
                injected[0] = True
            return result
        denied = False
        with patch.object(collection, "read_competitor_observation", side_effect=private_read), patch.object(collection, "_read_source", side_effect=final_source):
            try: self.compare(before, after, actor=self.admin)
            except PermissionDenied: denied = True
        self.assertTrue(injected[0])
        self.assertTrue(denied, "Final second-source read cancelled the first original, yet its private pair escaped.")

    def test_last_dated_pair_source_first_metadata_status_usage_and_both_cancellations_withhold(self):
        before = self.collected("terminal-pair-before"); after = self.collected("terminal-pair-after")
        source = comparison._read_pair_sources
        expected = self.compare(before, after, actor=self.admin)
        for loss in ("artifact", "status", "usage", "first-cancel", "second-cancel"):
            with self.subTest(loss=loss), transaction.atomic():
                calls = 0
                def last(*args):
                    nonlocal calls
                    result = source(*args); calls += 1
                    if calls == 2:
                        if loss == "artifact": Artifact.objects.filter(job=before).update(size_bytes=1)
                        elif loss == "status": JobRun.objects.filter(pk=before.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=before).update(actual_units=2)
                        else: JobCancellation.objects.create(job=before if loss == "first-cancel" else after, requested_by=self.owner)
                    return result
                with patch.object(comparison, "_read_pair_sources", side_effect=last), self.assertRaises(PermissionDenied):
                    self.compare(before, after, actor=self.admin)
                self.assertEqual(calls, 2)
                transaction.set_rollback(True)
        self.assertEqual(self.compare(before, after, actor=self.admin), expected)
