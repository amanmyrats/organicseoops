from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
from threading import Barrier, Event
from unittest.mock import patch
from zoneinfo import ZoneInfo

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import storages
from django.core.cache import cache
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from config.artifacts import ArtifactNotFound, ArtifactStorageError, ArtifactValidationError
from jobs.models import Artifact, JobRun, JobStatus, UsageReservation
from jobs.usage import UsageLimitError
from jobs.recovery import reconcile_diagnostic_jobs
from jobs.services import execute_job, retry_job
from tenancy.artifacts import project_artifact_scope, save_project_artifact
from tenancy.models import OrganizationMembership, Project
from tenancy.services import create_organization, create_project, update_project

from .models import (
    ImportRun,
    IntegrationConnection,
    ImportExecutionState,
    IntegrationCapability,
    PendingArtifactCleanup,
    SearchMetricObservation,
    SourceDimension,
)
from .search_console import MAX_CSV_BYTES, queue_search_console_csv_import, reconcile_search_console_artifacts
from .services import create_connection


@override_settings(
    STORAGES=TEST_STORAGES,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv"}),
    ARTIFACT_MAX_BYTES=2 * 1024 * 1024,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "csv-browser-tests"}},
)
class SearchConsoleCSVImportTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        cache.clear()
        users = get_user_model().objects
        self.owner = users.create_user("csv-owner@example.com", password="test-password")
        self.outsider = users.create_user("csv-outsider@example.com", password="test-password")
        for user in (self.owner, self.outsider):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        self.organization = create_organization(user=self.owner, name="CSV organization")
        self.project = create_project(
            organization=self.organization,
            user=self.owner,
            name="CSV project",
            canonical_origin="https://example.com",
            aliases=["https://www.example.com"],
        )
        other_organization = create_organization(user=self.outsider, name="Other CSV organization")
        self.other_project = create_project(
            organization=other_organization,
            user=self.outsider,
            name="Other CSV project",
            canonical_origin="https://other.example",
        )
        self.connection = create_connection(
            project=self.project,
            user=self.owner,
            provider="google_search_console",
            external_property_id="https://example.com",
            capabilities=[
                IntegrationCapability.CSV_IMPORT,
                IntegrationCapability.QUERY_METRICS,
                IntegrationCapability.PAGE_METRICS,
            ],
            available_dimensions=[
                SourceDimension.DATE,
                SourceDimension.QUERY,
                SourceDimension.PAGE,
                SourceDimension.COUNTRY,
                SourceDimension.DEVICE,
                SourceDimension.SEARCH_APPEARANCE,
            ],
            source_semantics="search_console_performance",
            source_semantics_version="csv-v1",
            timezone="America/Los_Angeles",
            backfill_limit_days=90,
        )
        self.end = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=2)
        self.start = self.end - timedelta(days=6)

    def queue(
        self, content, *, connection=None, user=None, search_type=SearchMetricObservation.SearchType.WEB,
        date_granularity=None,
    ):
        return queue_search_console_csv_import(
            connection=connection or self.connection,
            user=user or self.owner,
            content=content,
            date_start=self.start,
            date_end=self.end,
            search_type=search_type,
            date_granularity=date_granularity,
        )

    def csv_browser(self, user):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        client.get('/_allauth/browser/v1/auth/session')
        return client

    def csv_post(self, client, *, content=None, connection_id=None, headers=None, csrf=True, property=None):
        path = f'/api/organizations/{self.organization.pk}/projects/{self.project.pk}/sources/'
        options = {'HTTP_X_CSRFTOKEN': client.cookies['csrftoken'].value} if csrf else {}
        if content is None:
            return client.post(path + 'csv/', json.dumps({'property': property or 'https://example.com'}),
                               content_type='application/json', **options)
        options.update({'HTTP_X_CSV_START': self.start.isoformat(), 'HTTP_X_CSV_END': self.end.isoformat(),
                        'HTTP_X_CSV_SEARCH_TYPE': 'web', 'HTTP_X_CSV_DATE_GRANULARITY': 'range',
                        'HTTP_X_CSV_AUTHORIZATION': 'true'})
        options.update(headers or {})
        return client.post(path + f'{connection_id or self.connection.pk}/csv/', content,
                           content_type='text/csv', **options)

    def test_browser_csv_source_setup_upload_replay_and_scoped_history(self):
        client = self.csv_browser(self.owner)
        source = self.csv_post(client, property='https://www.example.com/')
        self.assertEqual(source.status_code, 200, source.content)
        connection_id = source.json()['id']
        self.assertEqual(self.csv_post(client, property='https://www.example.com').json()['id'], connection_id)
        connection = IntegrationConnection.objects.get(pk=connection_id)
        self.assertIsNone(connection.credential_reference)
        self.assertNotIn('api_sync', connection.capabilities)
        content = b'Top queries,Clicks,Impressions,CTR,Position\nbrowser fixture,1,2,50%,1\n'
        result = self.csv_post(client, content=content, connection_id=connection_id)
        self.assertEqual(result.status_code, 202, result.content)
        self.assertIn('no-store', result['Cache-Control'])
        job = result.json()['job']
        self.assertEqual(job['source_checksum'], hashlib.sha256(content).hexdigest())
        self.assertEqual(self.csv_post(client, content=content, connection_id=connection_id).json()['job']['id'], job['id'])
        self.assertEqual((JobRun.objects.count(), Artifact.objects.count(), PendingArtifactCleanup.objects.count()), (1, 1, 0))
        self.assertTrue(execute_job(job['id']))
        history = client.get(f'/api/organizations/{self.organization.pk}/projects/{self.project.pk}/sources/{connection_id}/imports/')
        self.assertEqual(history.json()['imports'][0]['rows_imported'], 1)
        self.assertEqual(history.json()['imports'][0]['source_completeness'], 'provider_export_unknown')
        self.assertEqual(self.csv_post(client, content=content, connection_id=connection_id,
                                      headers={'HTTP_X_CSV_SEARCH_TYPE': 'image'}).status_code, 409)

    def test_browser_csv_role_csrf_scope_and_upload_bounds_fail_before_staging(self):
        client = self.csv_browser(self.owner)
        content = b'Top queries,Clicks,Impressions,CTR,Position\nfixture,1,2,50%,1\n'
        self.assertEqual(self.csv_post(client, csrf=False).status_code, 403)
        self.assertEqual(self.csv_post(client, content=content, csrf=False).status_code, 403)
        outsider = self.csv_browser(self.outsider)
        self.assertEqual(self.csv_post(outsider).status_code, 404)
        self.assertEqual(self.csv_post(outsider, content=content).status_code, 404)
        OrganizationMembership.objects.create(organization=self.organization, user=self.outsider, role='member')
        self.assertEqual(self.csv_post(outsider).status_code, 403)
        self.assertEqual(self.csv_post(outsider, content=content).status_code, 403)
        for property in ('https://other.example', 'sc-domain:example.com', 'https://example.com/path'):
            self.assertEqual(self.csv_post(client, property=property).status_code, 409)
        for headers in ({'HTTP_X_CSV_AUTHORIZATION': 'false'}, {'HTTP_X_CSV_DATE_GRANULARITY': ''},
                        {'HTTP_X_CSV_START': 'bad'}, {'HTTP_X_CSV_SEARCH_TYPE': 'unsupported'},
                        {'CONTENT_LENGTH': str(MAX_CSV_BYTES + 1)}):
            self.assertEqual(self.csv_post(client, content=content, headers=headers).status_code, 409)
        with patch('django.http.HttpRequest.read', return_value=content[:-1]):
            self.assertEqual(self.csv_post(client, content=content).status_code, 409)
        self.assertEqual(self.csv_post(client, content=content, connection_id=999999).status_code, 404)
        self.assertEqual((JobRun.objects.count(), Artifact.objects.count(), PendingArtifactCleanup.objects.count()), (0, 0, 0))
        self.connection.state = 'disconnected'
        self.connection.save()
        self.assertEqual(self.csv_post(client).json()['state'], 'disconnected')
        self.assertEqual(self.csv_post(client, content=content).status_code, 409)
        self.connection.credential_reference = '11111111-1111-1111-1111-111111111111'
        self.connection.save()
        self.assertEqual(self.csv_post(client).status_code, 409)
        self.assertEqual(self.csv_post(client, content=content).status_code, 409)

    def test_browser_csv_failed_quota_and_storage_keep_private_cleanup_contract(self):
        client = self.csv_browser(self.owner)
        content = b'Top queries,Clicks,Impressions,CTR,Position\nfixture,1,2,50%,1\n'
        with patch('jobs.services.queue_job', side_effect=UsageLimitError('trial_units_exhausted')):
            self.assertEqual(self.csv_post(client, content=content).status_code, 429)
        self.assertEqual((JobRun.objects.count(), Artifact.objects.count(), PendingArtifactCleanup.objects.count()), (0, 0, 0))
        with patch('integrations.search_console.save_project_artifact', side_effect=ArtifactStorageError('offline')):
            self.assertEqual(self.csv_post(client, content=content).status_code, 503)
        self.assertEqual((JobRun.objects.count(), Artifact.objects.count(), PendingArtifactCleanup.objects.count()), (0, 0, 0))

    def test_valid_query_import_is_source_aware_and_repeated_request_is_idempotent(self):
        content = (
            b"Top queries,Clicks,Impressions,CTR,Position\n"
            b"organic seo,10,100,10%,3.25\n"
            b"missing metrics,-,~,~,~\n"
        )
        job = self.queue(content)
        repeated = self.queue(content)
        self.assertEqual(repeated.pk, job.pk)
        self.assertEqual(Artifact.objects.filter(job=job).count(), 1)

        self.assertTrue(execute_job(job.pk))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        run = ImportRun.objects.get(job=job)
        self.assertEqual(run.observation_dimensions, [SourceDimension.QUERY])
        self.assertEqual(run.source_timezone, "America/Los_Angeles")
        self.assertIsNone(run.fresh_through)
        metrics = list(run.search_metrics.order_by("source_row"))
        self.assertEqual(len(metrics), 2)
        self.assertEqual((metrics[0].clicks, metrics[0].impressions), (10, 100))
        self.assertEqual((metrics[0].ctr, metrics[0].position), (Decimal("0.100000000000"), Decimal("3.25000000")))
        self.assertEqual(metrics[1].unavailable_metrics, ["clicks", "impressions", "ctr", "position"])
        self.assertIsNone(metrics[1].clicks)
        self.assertTrue(run.coverage["numeric_zero_may_mean_provider_unavailable"])
        self.assertFalse(execute_job(job.pk))
        self.assertEqual(SearchMetricObservation.objects.count(), 2)
        with self.assertRaisesRegex(ValidationError, "different import request"):
            self.queue(content, search_type=SearchMetricObservation.SearchType.IMAGE)

    def test_date_and_page_exports_keep_distinct_grains_and_normalize_scoped_urls(self):
        daily = (
            f"Dates,Clicks,Impressions,CTR,Position\n{self.start.isoformat()},1,4,25%,2\n"
        ).encode()
        daily_job = self.queue(daily, date_granularity=SearchMetricObservation.TimeGranularity.DAY)
        execute_job(daily_job.pk)
        daily_metric = ImportRun.objects.get(job=daily_job).search_metrics.get()
        self.assertEqual(daily_metric.time_granularity, SearchMetricObservation.TimeGranularity.DAY)
        self.assertEqual(daily_metric.date_start, self.start)

        pages = (
            b"Top pages,Clicks,Impressions,CTR,Position\n"
            b"HTTPS://EXAMPLE.COM:443/a b,2,10,20%,4\n"
            b"https://www.example.com/alias,1,4,25%,2\n"
        )
        page_job = self.queue(pages, search_type=SearchMetricObservation.SearchType.IMAGE)
        execute_job(page_job.pk)
        page_run = ImportRun.objects.get(job=page_job)
        page_metric = page_run.search_metrics.get()
        self.assertEqual(page_run.status, ImportRun.Status.PARTIALLY_SUCCEEDED)
        self.assertEqual(page_run.errors.get().category, "invalid_or_out_of_scope_page")
        self.assertEqual(page_metric.time_granularity, SearchMetricObservation.TimeGranularity.RANGE)
        self.assertEqual(page_metric.page, "https://example.com/a%20b")
        self.assertEqual((page_metric.date_start, page_metric.date_end), (self.start, self.end))
        self.assertNotEqual(daily_metric.grain_hash, page_metric.grain_hash)

    def test_row_errors_and_existing_grain_conflicts_produce_partial_provenance(self):
        first = self.queue(b"Top queries,Clicks,Impressions,CTR,Position\nsame,1,10,10%,2\n")
        execute_job(first.pk)
        second = self.queue(
            b"Top queries,Clicks,Impressions,CTR,Position\n"
            b"same,2,20,10%,2\n"
            b"new,3,30,10%,3\n"
            b"bad,nope,10,10%,4\n"
        )
        execute_job(second.pk)
        second.refresh_from_db()
        run = ImportRun.objects.get(job=second)
        self.assertEqual(second.status, JobStatus.PARTIALLY_SUCCEEDED)
        self.assertEqual((run.rows_seen, run.rows_imported, run.row_errors), (3, 1, 2))
        self.assertEqual(
            list(run.errors.values_list("source_row", "category", "field")),
            [(1, "source_grain_conflict", ""), (3, "invalid_metric", "clicks")],
        )
        self.assertEqual(run.search_metrics.get().query, "new")
        self.assertEqual(SearchMetricObservation.objects.filter(import_run__connection=self.connection).count(), 2)

    def test_identical_grains_from_two_properties_stay_separate(self):
        content = b"Top queries,Clicks,Impressions,CTR,Position\nshared,1,2,50%,1\n"
        first = self.queue(content)
        execute_job(first.pk)
        second_connection = create_connection(
            project=self.project,
            user=self.owner,
            provider="google_search_console",
            external_property_id="https://www.example.com",
            capabilities=[IntegrationCapability.CSV_IMPORT, IntegrationCapability.QUERY_METRICS],
            available_dimensions=[SourceDimension.QUERY],
            source_semantics="search_console_performance",
            source_semantics_version="csv-v1",
            timezone="America/Los_Angeles",
        )
        second = self.queue(content, connection=second_connection)
        execute_job(second.pk)
        observations = list(SearchMetricObservation.objects.order_by("pk"))
        self.assertEqual(len(observations), 2)
        self.assertNotEqual(observations[0].grain_hash, observations[1].grain_hash)
        self.assertEqual({row.import_run.connection_id for row in observations}, {self.connection.pk, second_connection.pk})

        with self.assertRaises(PermissionDenied):
            self.queue(content, connection=second_connection, user=self.outsider)
        self.assertEqual(SearchMetricObservation.objects.count(), 2)

    def test_malformed_encoding_layout_scope_and_size_fail_without_metrics(self):
        fixtures = (
            (b"\xff\xfeinvalid", "invalid_encoding"),
            (b"Query,Clicks,Impressions\nterm,1,2\n", "unsupported_layout"),
            (
                b"Top pages,Clicks,Impressions,CTR,Position\nhttps://outside.example/,1,2,50%,1\n",
                "row_errors",
            ),
            (
                b"Top pages,Clicks,Impressions,CTR,Position\nhttp://example.com/wrong-scheme,1,2,50%,1\n",
                "row_errors",
            ),
        )
        for index, (content, category) in enumerate(fixtures):
            with self.subTest(category=category):
                job = self.queue(content, search_type=SearchMetricObservation.SearchType.values[index])
                execute_job(job.pk)
                job.refresh_from_db()
                self.assertEqual(job.status, JobStatus.FAILED)
                self.assertEqual(job.error_category, category)
                self.assertEqual(ImportRun.objects.get(job=job).rows_imported, 0)
        self.assertEqual(SearchMetricObservation.objects.count(), 0)

        with self.assertRaisesRegex(ArtifactValidationError, "import size limit"):
            self.queue(b"x" * (MAX_CSV_BYTES + 1))
        self.assertEqual(Artifact.objects.count(), len(fixtures))

    def test_revocation_tampering_and_generic_retry_have_controlled_outcomes(self):
        content = b"Top queries,Clicks,Impressions,CTR,Position\nterm,1,2,50%,1\n"
        revoked = self.queue(content)
        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
        execute_job(revoked.pk)
        revoked.refresh_from_db()
        self.assertEqual((revoked.status, revoked.error_category), (JobStatus.CANCELLED, "actor_revoked"))
        self.assertEqual(revoked.usage.state, UsageReservation.State.RELEASED)
        self.assertFalse(hasattr(revoked, "import_run"))

        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=True)
        self.owner.refresh_from_db()
        tampered = self.queue(content.replace(b"term", b"other"), search_type=SearchMetricObservation.SearchType.IMAGE)
        with patch("integrations.search_console.read_project_artifact", return_value=b"different"):
            execute_job(tampered.pk)
        tampered.refresh_from_db()
        self.assertEqual((tampered.status, tampered.error_category), (JobStatus.FAILED, "source_mismatch"))
        self.assertEqual(tampered.usage.state, UsageReservation.State.SETTLED)
        with self.assertRaisesRegex(ValidationError, "new source upload"):
            retry_job(job=tampered, actor=self.owner, idempotency_key="retry-import")

    def test_failed_queue_cleans_untracked_source_artifact(self):
        content = b"Top queries,Clicks,Impressions,CTR,Position\nterm,1,2,50%,1\n"
        with patch("jobs.services.queue_job", side_effect=ValidationError("forced queue failure")):
            with self.assertRaisesRegex(ValidationError, "forced queue failure"):
                self.queue(content)
        _directories, files = storages["artifacts"].listdir(project_artifact_scope(self.project))
        self.assertEqual(files, [])

        with (
            patch("jobs.services.queue_job", side_effect=ValidationError("forced queue failure")),
            patch("integrations.search_console.delete_project_artifact", side_effect=ArtifactStorageError("offline")),
        ):
            with self.assertRaisesRegex(ValidationError, "forced queue failure"):
                self.queue(content.replace(b"term", b"pending"))
        self.assertEqual(PendingArtifactCleanup.objects.count(), 1)
        PendingArtifactCleanup.objects.update(created_at=timezone.now() - timedelta(minutes=6))
        self.assertEqual(reconcile_diagnostic_jobs()["integration_artifacts"], 1)
        self.assertEqual(PendingArtifactCleanup.objects.count(), 0)
        _directories, files = storages["artifacts"].listdir(project_artifact_scope(self.project))
        self.assertEqual(files, [])

    def test_date_exports_require_an_explicit_daily_granularity(self):
        content = (
            f"Date,Clicks,Impressions,CTR,Position\n{self.start.isoformat()},1,2,50%,1\n"
        ).encode()
        job = self.queue(content)
        execute_job(job.pk)
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.FAILED, "unsupported_time_granularity"))
        with self.assertRaisesRegex(ValidationError, "Only declared daily"):
            self.queue(content, date_granularity="week")

    def test_current_capability_and_backfill_policy_are_rechecked_before_persistence(self):
        capability_job = self.queue(
            b"Top queries,Clicks,Impressions,CTR,Position\ncapability,1,2,50%,1\n"
        )
        self.connection.capabilities = [IntegrationCapability.CSV_IMPORT]
        self.connection.save()
        execute_job(capability_job.pk)
        capability_job.refresh_from_db()
        self.assertEqual(
            (capability_job.status, capability_job.error_category),
            (JobStatus.CANCELLED, "source_scope_revoked"),
        )
        self.assertEqual(capability_job.usage.state, UsageReservation.State.SETTLED)

        self.connection.capabilities = [
            IntegrationCapability.CSV_IMPORT,
            IntegrationCapability.QUERY_METRICS,
            IntegrationCapability.PAGE_METRICS,
        ]
        self.connection.save()
        backfill_job = self.queue(
            b"Top queries,Clicks,Impressions,CTR,Position\nbackfill,1,2,50%,1\n"
        )
        self.connection.backfill_limit_days = 1
        self.connection.save()
        execute_job(backfill_job.pk)
        backfill_job.refresh_from_db()
        self.assertEqual(
            (backfill_job.status, backfill_job.error_category),
            (JobStatus.CANCELLED, "source_scope_revoked"),
        )
        self.assertEqual(backfill_job.usage.state, UsageReservation.State.RELEASED)
        self.assertEqual(ImportRun.objects.count(), 0)

    def test_disabling_csv_source_before_dispatch_blocks_queued_import(self):
        from .services import set_csv_source_state

        job = self.queue(b"Top queries,Clicks,Impressions,CTR,Position\nqueued source,1,2,50%,1\n")
        set_csv_source_state(connection=self.connection, user=self.owner, active=False)
        self.assertTrue(execute_job(job.pk))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category), (JobStatus.CANCELLED, "source_scope_revoked"))
        self.assertEqual(job.usage.state, UsageReservation.State.RELEASED)
        self.assertEqual((ImportRun.objects.count(), SearchMetricObservation.objects.count()), (0, 0))

    def test_transient_storage_failure_retries_the_same_job_once(self):
        content = b"Top queries,Clicks,Impressions,CTR,Position\ntransient,1,2,50%,1\n"
        job = self.queue(content)
        with patch(
            "integrations.search_console.read_project_artifact",
            side_effect=ArtifactStorageError("temporarily unavailable"),
        ):
            self.assertFalse(execute_job(job.pk))
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertEqual(job.dispatch_error, "artifact_storage_unavailable")
        self.assertEqual(job.usage.state, UsageReservation.State.RESERVED)
        ImportExecutionState.objects.filter(job=job).update(retry_after=timezone.now() - timedelta(seconds=1))

        self.assertTrue(execute_job(job.pk))
        job.refresh_from_db()
        self.assertEqual((job.status, job.dispatch_error), (JobStatus.SUCCEEDED, ""))
        self.assertEqual(job.usage.state, UsageReservation.State.SETTLED)
        self.assertEqual(ImportRun.objects.filter(job=job).count(), 1)
        self.assertEqual(SearchMetricObservation.objects.count(), 1)

    def test_persistent_storage_failure_exhausts_bounded_retries(self):
        job = self.queue(b"Top queries,Clicks,Impressions,CTR,Position\nretry limit,1,2,50%,1\n")
        with patch(
            "integrations.search_console.read_project_artifact",
            side_effect=ArtifactStorageError("persistently unavailable"),
        ):
            self.assertFalse(execute_job(job.pk))
            ImportExecutionState.objects.filter(job=job).update(retry_after=timezone.now() - timedelta(seconds=1))
            self.assertFalse(execute_job(job.pk))
            ImportExecutionState.objects.filter(job=job).update(retry_after=timezone.now() - timedelta(seconds=1))
            self.assertTrue(execute_job(job.pk))
        job.refresh_from_db()
        state = ImportExecutionState.objects.get(job=job)
        run = ImportRun.objects.get(job=job)
        self.assertEqual((job.status, job.error_category), (JobStatus.FAILED, "artifact_storage_unavailable"))
        self.assertEqual((state.storage_failures, state.retry_after), (3, None))
        self.assertEqual(run.status, ImportRun.Status.UNAVAILABLE)
        self.assertEqual(job.usage.state, UsageReservation.State.RELEASED)

    def test_staging_record_recovers_process_loss_after_upload(self):
        content = b"Top queries,Clicks,Impressions,CTR,Position\nstaged,1,2,50%,1\n"

        def store_then_exit(**kwargs):
            save_project_artifact(**kwargs)
            raise SystemExit

        with patch("integrations.search_console.save_project_artifact", side_effect=store_then_exit):
            with self.assertRaises(SystemExit):
                self.queue(content)
        self.assertEqual(PendingArtifactCleanup.objects.count(), 1)
        _directories, files = storages["artifacts"].listdir(project_artifact_scope(self.project))
        self.assertEqual(len(files), 1)
        PendingArtifactCleanup.objects.update(created_at=timezone.now() - timedelta(minutes=6))
        self.assertEqual(reconcile_search_console_artifacts(), 1)
        self.assertEqual(PendingArtifactCleanup.objects.count(), 0)

    def test_expired_cleanup_winning_before_promotion_prevents_dangling_metadata(self):
        content = b"Top queries,Clicks,Impressions,CTR,Position\nexpired,1,2,50%,1\n"

        def store_then_reconcile(**kwargs):
            key = save_project_artifact(**kwargs)
            PendingArtifactCleanup.objects.update(created_at=timezone.now() - timedelta(minutes=6))
            self.assertEqual(reconcile_search_console_artifacts(), 1)
            return key

        with patch("integrations.search_console.save_project_artifact", side_effect=store_then_reconcile):
            with self.assertRaises(ArtifactNotFound):
                self.queue(content)
        self.assertEqual((Artifact.objects.count(), ImportExecutionState.objects.count()), (0, 0))
        self.assertEqual(PendingArtifactCleanup.objects.count(), 0)

    def test_worker_loss_rolls_back_and_redelivery_commits_once(self):
        job = self.queue(b"Top queries,Clicks,Impressions,CTR,Position\nworker loss,1,2,50%,1\n")
        with patch.object(SearchMetricObservation.objects, "bulk_create", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                execute_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertEqual(job.usage.state, UsageReservation.State.RESERVED)
        self.assertEqual((ImportRun.objects.count(), SearchMetricObservation.objects.count()), (0, 0))

        execute_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertEqual((ImportRun.objects.count(), SearchMetricObservation.objects.count()), (1, 1))

    def test_non_default_port_page_must_match_the_exact_property(self):
        project = Project.objects.create(
            organization=self.organization,
            name="Port CSV project",
            canonical_origin="https://port.example:8443",
        )
        connection = create_connection(
            project=project,
            user=self.owner,
            provider="google_search_console",
            external_property_id="https://port.example:8443",
            capabilities=[IntegrationCapability.CSV_IMPORT, IntegrationCapability.PAGE_METRICS],
            available_dimensions=[SourceDimension.PAGE],
            source_semantics="search_console_performance",
            source_semantics_version="csv-v1",
            timezone="America/Los_Angeles",
        )
        job = self.queue(
            b"Top pages,Clicks,Impressions,CTR,Position\nhttps://port.example:8443/path,1,2,50%,1\n",
            connection=connection,
        )
        execute_job(job.pk)
        metric = ImportRun.objects.get(job=job).search_metrics.get()
        self.assertEqual(metric.page, "https://port.example:8443/path")

    def test_cross_project_actor_cannot_queue_or_rebind_an_import(self):
        with self.assertRaises(PermissionDenied):
            self.queue(
                b"Top queries,Clicks,Impressions,CTR,Position\nterm,1,2,50%,1\n",
                user=self.outsider,
            )
        self.assertEqual(Artifact.objects.count(), 0)
        self.assertEqual(self.connection.project_id, self.project.pk)
        self.assertFalse(OrganizationMembership.objects.filter(
            organization=self.organization,
            user=self.outsider,
        ).exists())


@override_settings(
    STORAGES=TEST_STORAGES,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv"}),
    ARTIFACT_MAX_BYTES=2 * 1024 * 1024,
)
class SearchConsoleCSVConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.owner = get_user_model().objects.create_user("csv-race-owner@example.com", password="test-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, primary=True, verified=True)
        self.organization = create_organization(user=self.owner, name="CSV race organization")
        self.project = create_project(
            organization=self.organization,
            user=self.owner,
            name="CSV race project",
            canonical_origin="https://race.example",
        )
        self.connection = create_connection(
            project=self.project,
            user=self.owner,
            provider="google_search_console",
            external_property_id="https://race.example",
            capabilities=[IntegrationCapability.CSV_IMPORT, IntegrationCapability.QUERY_METRICS],
            available_dimensions=[SourceDimension.QUERY],
            source_semantics="search_console_performance",
            source_semantics_version="csv-v1",
            timezone="America/Los_Angeles",
        )
        end = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=2)
        with patch("jobs.services.dispatch_pending", return_value=False):
            self.job = queue_search_console_csv_import(
                connection=self.connection,
                user=self.owner,
                content=b"Top queries,Clicks,Impressions,CTR,Position\nrace,1,2,50%,1\n",
                date_start=end - timedelta(days=1),
                date_end=end,
            )

    def test_duplicate_delivery_creates_one_result(self):
        barrier = Barrier(2)

        def run(_value):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return execute_job(self.job.pk)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(run, [1, 2]))
        self.assertCountEqual(results, [True, False])
        self.assertEqual((ImportRun.objects.count(), SearchMetricObservation.objects.count()), (1, 1))
        self.job.refresh_from_db()
        self.assertEqual((self.job.status, self.job.usage.actual_units), (JobStatus.SUCCEEDED, 1))

    def test_project_scope_update_serializes_after_import_commit(self):
        from .search_console import parse_search_console_csv

        parsed = Event()
        release = Event()

        def blocking_parse(**kwargs):
            result = parse_search_console_csv(**kwargs)
            parsed.set()
            release.wait(timeout=5)
            return result

        def run_import():
            close_old_connections()
            try:
                with patch("integrations.search_console.parse_search_console_csv", side_effect=blocking_parse):
                    return execute_job(self.job.pk)
            finally:
                close_old_connections()

        def change_scope():
            close_old_connections()
            try:
                return update_project(
                    project=type(self.project).objects.get(pk=self.project.pk),
                    user=get_user_model().objects.get(pk=self.owner.pk),
                    canonical_origin="https://changed.example",
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            import_future = executor.submit(run_import)
            self.assertTrue(parsed.wait(timeout=5))
            scope_future = executor.submit(change_scope)
            self.assertFalse(scope_future.done())
            release.set()
            self.assertTrue(import_future.result(timeout=10))
            scope_future.result(timeout=10)
        self.assertEqual((ImportRun.objects.count(), SearchMetricObservation.objects.count()), (1, 1))
        self.project.refresh_from_db()
        self.assertEqual(self.project.canonical_origin, "https://changed.example")
