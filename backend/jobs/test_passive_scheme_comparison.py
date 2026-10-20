import json
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import OrganizationMembership, Project, ProjectOriginVerification
from . import passive_header_collection as lifecycle
from . import passive_http_redirect_collection as http
from . import passive_redirect_collection as https
from . import passive_scheme_comparison as comparison
from . import test_passive_http_redirect_collection as fixtures
from .models import Artifact, JobCancellation, JobRun
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/plain", "application/json", "application/zip"}))
class PassiveSchemeComparisonTests(TransactionTestCase):
    verified = fixtures.PassiveHTTPRedirectCollectionTests.verified
    transport = fixtures.PassiveHTTPRedirectCollectionTests.transport

    def setUp(self):
        fixtures.PassiveHTTPRedirectCollectionTests.setUp(self)
        self.https_verification = self.verified(self.https_origin)
        OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="admin")

    def collected(self, family, key, *, path="/public", actor=None, wire=None):
        source = http if family == "http" else https
        data = {"url": (self.project.canonical_origin if family == "http" else self.https_origin) + path,
            "observations": ["http_response_location" if family == "http" else "response_location"], "collection_permission": True}
        queue = source.queue_passive_http_redirect_collection if family == "http" else source.queue_passive_redirect_collection
        execute = source.execute_passive_http_redirect_collection if family == "http" else source.execute_passive_redirect_collection
        job = queue(project=self.project, actor=actor or self.owner, data=data, idempotency_key=key)
        fetcher = self.transport(wire=wire or b"HTTP/1.1 200 OK\r\nLocation: https://security.example.com/different?secret=value\r\n\r\nprivate")
        with patch("socket.create_connection", side_effect=AssertionError("No real egress")):
            self.assertTrue(execute(job.pk, fetcher=fetcher))
        self.connection.request.assert_called_once(); job.refresh_from_db()
        self.assertEqual(job.status, "succeeded", job.error_category)
        return job

    def compare(self, first, second, **changes):
        return comparison.compare_http_https_observations(**{**dict(project=self.project, actor=self.owner,
            http_job_id=first.pk, https_job_id=second.pk), **changes})

    def test_genuine_independent_original_dual_verifiers_captures_actors_dates_private_pair_no_write_network_or_target_claim(self):
        # HTTPS can predate HTTP, and a different original actor never rewrites provenance.
        second = self.collected("https", "pair-https", actor=self.member)
        first = self.collected("http", "pair-http")
        with patch("jobs.crawling.SafeFetcher.fetch", side_effect=AssertionError("No pair request")), CaptureQueriesContext(connection) as queries:
            result = self.compare(first, second, actor=self.member)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        for name, job in (("http", first), ("https", second)):
            self.assertEqual(result[name]["binding"], job.config_snapshot["binding"])
            self.assertEqual(result[name]["collection"]["observed_at"], job.output["observed_at"])
            self.assertEqual(result[name]["collection"]["status"], 200)
        self.assertNotEqual(result["http"]["binding"]["actor_id"], result["https"]["binding"]["actor_id"])
        self.assertNotEqual(result["http"]["binding"]["verification_id"], result["https"]["binding"]["verification_id"])
        location = result["http"]["collection"]["evidence"]["response_location"]
        self.assertEqual((location["redirect_status"], location["same_hostname_default_https"]), (False, True))
        self.assertIn("not_location_target_path_followed_upgrade", result["interpretation"])
        for value in ("/different", "secret=value", "private", self.challenge, self.owner.email, "artifact_id", "derived_sha256"):
            self.assertNotIn(value, json.dumps(result))
        result["http"]["binding"]["observations"].clear()
        self.assertEqual(self.compare(first, second)["http"]["binding"]["observations"], ["http_response_location"])

    def test_only_exact_distinct_original_family_project_path_and_current_independent_sources_are_eligible(self):
        first = self.collected("http", "exact-http"); second = self.collected("https", "exact-https")
        for value in (True, 0, -1, 2**53, str(first.pk), None):
            with self.assertRaises(ValidationError): self.compare(first, second, http_job_id=value)
        with self.assertRaises(ValidationError): self.compare(first, first)
        with self.assertRaises(PermissionDenied): self.compare(second, first)
        with self.assertRaises(PermissionDenied): self.compare(first, second, actor=self.outsider)
        foreign = Project.objects.create(organization=self.organization, name="Other", canonical_origin="http://other.example.invalid")
        with self.assertRaises(PermissionDenied): self.compare(first, second, project=foreign)
        different = self.collected("https", "other-path", path="/other")
        with self.assertRaises(ValidationError): self.compare(first, different)
        for job in (first, second):
            with transaction.atomic():
                JobCancellation.objects.create(job=job, requested_by=self.owner)
                with self.assertRaises(PermissionDenied): self.compare(first, second)
                transaction.set_rollback(True)
        for verification in (self.verification, self.https_verification):
            with transaction.atomic():
                ProjectOriginVerification.objects.filter(pk=verification.pk).update(challenge_digest="c" * 64)
                with self.assertRaises((PermissionDenied, ValidationError)): self.compare(first, second)
                transaction.set_rollback(True)

    def test_second_actual_readback_cannot_change_either_original_metadata_source_cancellation_or_caller(self):
        first = self.collected("http", "late-http"); second = self.collected("https", "late-https")
        read = lifecycle.read_project_artifact
        mutations = [lambda job=job: Artifact.objects.filter(job=job).update(created_at=job.artifacts.get().created_at - timedelta(microseconds=1)) for job in (first, second)]
        mutations += [lambda row=row: ProjectOriginVerification.objects.filter(pk=row.pk).update(challenge_digest="d" * 64) for row in (self.verification, self.https_verification)]
        mutations += [lambda: OrganizationMembership.objects.filter(organization=self.organization, user=self.member).update(role="viewer"),
            lambda: JobCancellation.objects.create(job=first, requested_by=self.owner)]
        for mutate in mutations:
            with transaction.atomic():
                calls = 0
                def late(**kwargs):
                    nonlocal calls
                    content = read(**kwargs); calls += 1
                    if calls == 2: mutate()
                    return content
                with patch.object(lifecycle, "read_project_artifact", side_effect=late), self.assertRaises((PermissionDenied, ValidationError)):
                    self.compare(first, second, actor=self.member)
                self.assertEqual(calls, 2); transaction.set_rollback(True)
        self.assertEqual(JobRun.objects.filter(handler__in=(http.HANDLER, https.HANDLER)).count(), 2)

    def test_final_slow_metadata_source_and_current_caller_reads_cannot_carry_allowance_past_natural_expiry(self):
        first = self.collected("http", "expiry-http"); second = self.collected("https", "expiry-https")
        for module, attribute in ((comparison, "_metadata"), (comparison.verified_source, "_source"), (comparison, "require_project_action")):
            original = getattr(module, attribute)
            with patch.object(module, attribute, wraps=original) as count: self.compare(first, second)
            last = count.call_count; now = [timezone.now()]; end = self.organization.trial.ends_at; calls = 0
            def slow(*args, **kwargs):
                nonlocal calls
                result = original(*args, **kwargs); calls += 1
                if calls == last: now[0] = end
                return result
            with patch.object(module, attribute, side_effect=slow), patch("jobs.usage.timezone.now", side_effect=lambda: now[0]), self.assertRaises((PermissionDenied, UsageLimitError)):
                self.compare(first, second)
            self.assertEqual(calls, last)

    def test_current_source_loss_during_final_pair_metadata_read_withholds_both_originals(self):
        first = self.collected("http", "final-http"); second = self.collected("https", "final-https")
        metadata = comparison._metadata
        for verification in (self.verification, self.https_verification):
            with transaction.atomic():
                calls = 0
                def late(*args, **kwargs):
                    nonlocal calls
                    value = metadata(*args, **kwargs); calls += 1
                    if calls == 4: ProjectOriginVerification.objects.filter(pk=verification.pk).update(challenge_digest="f" * 64)
                    return value
                with patch.object(comparison, "_metadata", side_effect=late), self.assertRaises(PermissionDenied): self.compare(first, second)
                self.assertEqual(calls, 4); transaction.set_rollback(True)
