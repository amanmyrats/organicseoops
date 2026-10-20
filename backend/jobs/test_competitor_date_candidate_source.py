from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import read_project_artifact
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, Project, ProjectConfiguration
from . import competitor_collection as lifecycle, competitor_date_candidate_source as source
from . import competitor_page_dates_collection as collection, test_competitor_page_dates_collection as fixtures
from .models import Artifact, JobCancellation, JobRun, JobStep, SourceCitation, UsageReservation
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CurrentDateCandidateTests(TransactionTestCase):
    setUp = fixtures.CompetitorPageDatesCollectionTests.setUp
    queue = fixtures.CompetitorPageDatesCollectionTests.queue
    transport = fixtures.CompetitorPageDatesCollectionTests.transport
    fetcher = fixtures.CompetitorPageDatesCollectionTests.fetcher
    revoke = fixtures.CompetitorPageDatesCollectionTests.revoke
    HTML = fixtures.CompetitorPageDatesCollectionTests.HTML

    def collected(self, key="candidate", body=None):
        job = self.queue(key)
        self.assertTrue(collection.execute_competitor_page_dates_collection(job.pk,
            fetcher=self.fetcher(**({"body": body} if body is not None else {}))))
        job.refresh_from_db()
        return job

    def read(self, job, **changes):
        return source.current_date_candidates(**{**dict(project=self.project, actor=self.admin, job_id=job.pk), **changes})

    def test_genuine_private_original_and_independent_reader_no_writes_network_new_jobs_or_units(self):
        job = self.collected()
        counts = (JobRun.objects.count(), Artifact.objects.count(), UsageReservation.objects.count())
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(connection) as queries:
            result = self.read(job)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual((JobRun.objects.count(), Artifact.objects.count(), UsageReservation.objects.count()), counts)
        self.assertEqual((result["job_id"], result["source_current"]), (job.pk, True))
        self.assertEqual(result["collection"], collection.read_competitor_page_dates_observation(
            project=self.project, actor=self.owner, job_id=job.pk)["collection"])
        self.assertEqual(result["candidates"], [dict(declaration_index=0, state="calendar_literal", calendar_date="2099-01-01",
            utc_instant=None, after_observation=None), dict(declaration_index=1, state="unsupported_literal",
            calendar_date=None, utc_instant=None, after_observation=None)])
        self.assertNotIn("evidence", result)
        expected = deepcopy(result)
        result["candidates"][0]["calendar_date"] = "private"
        result["collection"]["evidence"]["declarations"].clear()
        self.assertEqual(self.read(job), expected)
        self.assertEqual(self.read(job, actor=self.owner), expected)
        for value in (self.owner.email, "private-contact", "secret", "storage_key", "config_snapshot"):
            self.assertNotIn(value, json.dumps(expected))
        self.assertEqual((job.usage.actual_units, job.usage.state), (1, "settled"))

    def test_empty_and_wholly_unavailable_originals_remain_distinct_without_dates_or_freshness(self):
        for state, body, candidates in (("observed", b"<p>No dates</p>", []), ("unavailable", b"<title>Unclosed", None)):
            job = self.collected(state, body)
            result = self.read(job)
            self.assertEqual(result["collection"]["evidence"]["state"], state)
            self.assertEqual(result["candidates"], candidates)
            self.assertFalse({"age", "freshness", "published_at"} & set(result))

    def test_invalid_ids_tenant_family_status_and_independent_caller_or_original_actor_are_denied(self):
        job = self.collected()
        other = Project.objects.create(organization=self.organization, name="Other", canonical_origin="https://other.example.invalid")
        with self.assertRaises(PermissionDenied): self.read(job, project=other)
        for key in (True, 0, -1, 2**53, "1"):
            with self.assertRaises(ValidationError): self.read(job, job_id=key)
        for changes in ({"handler": "collect_competitor_page_formats"}, {"status": "failed"}, {"output": {}}):
            with transaction.atomic():
                JobRun.objects.filter(pk=job.pk).update(**changes)
                with self.assertRaises((PermissionDenied, ValidationError)): self.read(job)
                transaction.set_rollback(True)
        for change in (lambda: self.revoke(),
            lambda: OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")):
            with transaction.atomic():
                change()
                with self.assertRaises(PermissionDenied): self.read(job)
                transaction.set_rollback(True)

    def test_closed_size_and_actual_corrupt_original_private_bytes_are_withheld(self):
        job = self.collected()
        with patch.object(source, "MAX_RESULT_BYTES", 10), self.assertRaises(ValidationError): self.read(job)
        original = read_project_artifact
        def corrupted(**kwargs):
            self.assertTrue(original(**kwargs))
            return b"{}"
        with patch.object(lifecycle, "read_project_artifact", side_effect=corrupted), self.assertRaises(ValidationError): self.read(job)
        self.assertEqual(self.read(job)["job_id"], job.pk)

    def test_post_projection_metadata_source_actor_caller_cancel_and_natural_commercial_loss_withhold(self):
        job = self.collected()
        healthy = self.read(job)
        projector = source.article_date_literal_candidates
        for loss in ("actor", "caller", "configuration", "approval", "artifact", "step", "citation", "usage", "cancel", "organization", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                ends = timezone.now() + timedelta(seconds=20)
                OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends-timedelta(days=30), ends_at=ends)
                done = [False]
                def changed(*args):
                    result = projector(*args); done[0] = True
                    if loss == "actor": self.revoke()
                    elif loss == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                    elif loss == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                    elif loss == "approval": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[])
                    elif loss == "artifact": Artifact.objects.filter(job=job).update(created_at=timezone.now())
                    elif loss == "step": JobStep.objects.filter(job=job).update(created_at=timezone.now())
                    elif loss == "citation": SourceCitation.objects.filter(job=job).update(source_title="replacement")
                    elif loss == "usage": UsageReservation.objects.filter(job=job).update(actual_units=2)
                    elif loss == "cancel": JobCancellation.objects.create(job=job, requested_by=self.owner)
                    elif loss == "organization": Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True)
                    return result
                actual = timezone.now
                with patch.object(source, "article_date_literal_candidates", side_effect=changed), patch("jobs.usage.timezone.now",
                    side_effect=lambda: ends if done[0] and loss == "expiry" else actual()), self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                    self.read(job)
                self.assertTrue(done[0]); transaction.set_rollback(True)
        self.assertEqual(self.read(job), healthy)

    def test_actual_final_fresh_source_metadata_status_usage_and_cancel_losses_are_withheld(self):
        job = self.collected()
        original = lifecycle._read_source
        healthy = self.read(job)
        pins = []
        def observe(current, project, actor):
            result = original(current, project, actor); pins.append(current.pk); return result
        with patch.object(lifecycle, "_read_source", side_effect=observe): self.assertEqual(self.read(job), healthy)
        self.assertEqual(pins, [job.pk] * 6)
        for loss in ("artifact", "step", "citation", "status", "usage", "cancel"):
            with self.subTest(loss=loss), transaction.atomic():
                calls, injected = [0], [False]
                def changed(current, project, actor):
                    result = original(current, project, actor); calls[0] += 1
                    if calls[0] == len(pins):
                        injected[0] = True
                        if loss == "artifact": Artifact.objects.filter(job=job).update(created_at=timezone.now())
                        elif loss == "step": JobStep.objects.filter(job=job).update(created_at=timezone.now())
                        elif loss == "citation": SourceCitation.objects.filter(job=job).update(source_title="replacement")
                        elif loss == "status": JobRun.objects.filter(pk=job.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=job).update(actual_units=2)
                        else: JobCancellation.objects.create(job=job, requested_by=self.owner)
                    return result
                with patch.object(lifecycle, "_read_source", side_effect=changed), self.assertRaises((PermissionDenied, ValidationError)):
                    self.read(job)
                self.assertTrue(injected[0]); transaction.set_rollback(True)
        self.assertEqual(self.read(job), healthy)
