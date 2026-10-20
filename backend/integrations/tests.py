import hashlib
from datetime import date, timedelta

from allauth.account.models import EmailAddress
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from jobs.models import Artifact, JobRun, JobStatus
from tenancy.artifacts import project_artifact_scope
from tenancy.models import MembershipRole, OrganizationMembership
from tenancy.services import create_organization, create_project

from .admin import IntegrationConnectionAdmin, SyncCursorAdmin
from .models import ImportRun, IntegrationCapability, IntegrationConnection, SourceDimension, SyncCursor
from .services import (
    SyncCursorConflict,
    UnsupportedIntegrationCapability,
    create_connection,
    record_import_run,
    require_connection_capability,
    update_sync_cursor,
)


@override_settings(ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv"}), ARTIFACT_MAX_BYTES=1024)
class IntegrationContractTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("integration-owner@example.com", password="test-password")
        self.member = users.create_user("integration-member@example.com", password="test-password")
        self.outsider = users.create_user("integration-outsider@example.com", password="test-password")
        for user in (self.owner, self.member, self.outsider):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        self.organization = create_organization(user=self.owner, name="Integration organization")
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.member,
            role=MembershipRole.MEMBER,
        )
        self.project = create_project(
            organization=self.organization,
            user=self.owner,
            name="Integration project",
            canonical_origin="https://example.com",
            aliases=["https://www.example.com", "https://m.example.com"],
        )
        other_organization = create_organization(user=self.outsider, name="Other integration organization")
        self.other_project = create_project(
            organization=other_organization,
            user=self.outsider,
            name="Other integration project",
            canonical_origin="https://example.com",
        )

    def connection(self, *, property_id="https://example.com", capabilities=None, dimensions=None, project=None, user=None):
        return create_connection(
            project=project or self.project,
            user=user or self.owner,
            provider="google_search_console",
            external_property_id=property_id,
            capabilities=capabilities or [IntegrationCapability.CSV_IMPORT, IntegrationCapability.QUERY_METRICS],
            available_dimensions=dimensions or [SourceDimension.DATE, SourceDimension.QUERY],
            source_semantics="search_console_performance",
            source_semantics_version="v1",
            timezone="UTC",
            backfill_limit_days=90,
        )

    def completed_job_and_artifact(
        self,
        project,
        actor,
        suffix,
        *,
        handler="import_search_console_csv",
        final_status=JobStatus.SUCCEEDED,
    ):
        job = JobRun.objects.create(
            organization=project.organization,
            project=project,
            actor=actor,
            handler=handler,
            input_snapshot={"source": "fixture"},
            method_version="search-console-csv-v1",
        )
        job.status = JobStatus.RUNNING
        job.save(update_fields=["status", "updated_at"])
        job.status = final_status
        job.save(update_fields=["status", "updated_at"])
        artifact = Artifact.objects.create(
            job=job,
            project=project,
            key=f"{project_artifact_scope(project)}/{hashlib.md5(suffix.encode(), usedforsecurity=False).hexdigest()}.csv",
            content_type="text/csv",
            size_bytes=10,
        )
        return job, artifact

    def test_acquisition_first_complete_import_is_one_per_organization_not_partial(self):
        from tenancy.acquisition import acquisition_milestones

        def record(connection, project, actor, suffix, status=ImportRun.Status.SUCCEEDED):
            job, artifact = self.completed_job_and_artifact(
                project, actor, suffix,
                final_status=(JobStatus.SUCCEEDED if status == ImportRun.Status.SUCCEEDED
                              else JobStatus.PARTIALLY_SUCCEEDED))
            return record_import_run(
                connection=connection, job=job, source_artifact=artifact,
                source_format=ImportRun.SourceFormat.SEARCH_CONSOLE_CSV,
                source_checksum=hashlib.sha256(suffix.encode()).hexdigest(),
                date_start=date(2026, 7, 1), date_end=date(2026, 7, 31),
                observation_dimensions=[SourceDimension.DATE, SourceDimension.QUERY],
                source_timezone="UTC", coverage_state=(ImportRun.CoverageState.COMPLETE
                   if status == ImportRun.Status.SUCCEEDED else ImportRun.CoverageState.PARTIAL),
                coverage={"export_shape": "date_query"}, status=status, rows_seen=2,
                rows_imported=(2 if status == ImportRun.Status.SUCCEEDED else 1),
                row_errors=(0 if status == ImportRun.Status.SUCCEEDED else 1),
            )

        first = self.connection()
        second = self.connection(property_id="https://www.example.com")
        other = self.connection(project=self.other_project, user=self.outsider)
        record(first, self.project, self.owner, "acquisition-one")
        record(second, self.project, self.owner, "acquisition-two")
        record(other, self.other_project, self.outsider, "acquisition-partial", ImportRun.Status.PARTIALLY_SUCCEEDED)
        self.assertEqual(acquisition_milestones()["milestones"]["first_import_succeeded"]["count"], 1)
        record(other, self.other_project, self.outsider, "acquisition-three")
        self.assertEqual(acquisition_milestones()["milestones"]["first_import_succeeded"]["count"], 2)

    def test_connection_requires_manage_permission_and_exact_project_property_scope(self):
        connection = self.connection(property_id="HTTPS://EXAMPLE.COM:443/")
        self.assertEqual(connection.external_property_id, "https://example.com")
        self.assertIsNone(connection.credential_reference)

        for user in (self.member, self.outsider):
            with self.subTest(user=user.email), self.assertRaises(PermissionDenied):
                self.connection(property_id="https://www.example.com", user=user)
        for property_id, message in (
            ("https://outside.example", "exact origin scope"),
            ("sc-domain:example.com", "exact origin scope"),
        ):
            with self.subTest(property_id=property_id), self.assertRaisesRegex(ValidationError, message):
                self.connection(property_id=property_id)

        same_identity_other_project = self.connection(project=self.other_project, user=self.outsider)
        self.assertNotEqual(connection.project_id, same_identity_other_project.project_id)
        with self.assertRaises(ValidationError):
            self.connection()

        alias_connection = self.connection(property_id="https://www.example.com")
        self.project.domain_aliases.filter(origin="https://www.example.com").delete()
        with self.assertRaises(UnsupportedIntegrationCapability):
            require_connection_capability(alias_connection, IntegrationCapability.CSV_IMPORT)
        connection.external_property_id = "https://m.example.com"
        with self.assertRaisesRegex(ValidationError, "immutable"):
            connection.save()

    def test_capabilities_and_dimensions_are_explicit_and_current_state_is_rechecked(self):
        connection = self.connection()
        self.assertEqual(
            require_connection_capability(
                connection,
                IntegrationCapability.CSV_IMPORT,
                dimensions=[SourceDimension.DATE, SourceDimension.QUERY],
            ).pk,
            connection.pk,
        )
        for capability, dimensions in (
            (IntegrationCapability.API_SYNC, []),
            (IntegrationCapability.CSV_IMPORT, [SourceDimension.PAGE]),
        ):
            with self.subTest(capability=capability, dimensions=dimensions), self.assertRaises(UnsupportedIntegrationCapability):
                require_connection_capability(connection, capability, dimensions=dimensions)

        IntegrationConnection.objects.filter(pk=connection.pk).update(state=IntegrationConnection.State.DISCONNECTED)
        with self.assertRaises(UnsupportedIntegrationCapability):
            require_connection_capability(connection, IntegrationCapability.CSV_IMPORT)
        with self.assertRaises(ValidationError):
            create_connection(
                project=self.project,
                user=self.owner,
                provider="unverified_engine",
                external_property_id="https://example.com",
                capabilities=[IntegrationCapability.CSV_IMPORT],
                available_dimensions=[SourceDimension.DATE],
                source_semantics="unknown",
                source_semantics_version="v1",
            )

    def test_import_provenance_keeps_connection_property_and_complete_grain(self):
        first = self.connection()
        second = self.connection(property_id="https://www.example.com")
        checksum = "a" * 64
        first_job, first_artifact = self.completed_job_and_artifact(self.project, self.owner, "first")
        import_request = dict(
            connection=first,
            job=first_job,
            source_artifact=first_artifact,
            source_format=ImportRun.SourceFormat.SEARCH_CONSOLE_CSV,
            source_checksum=checksum,
            date_start=date(2026, 7, 1),
            date_end=date(2026, 7, 31),
            observation_dimensions=[SourceDimension.DATE, SourceDimension.QUERY],
            source_timezone="UTC",
            coverage_state=ImportRun.CoverageState.COMPLETE,
            coverage={"export_shape": "date_query", "hidden_rows": "unknown"},
            fresh_through=date(2026, 7, 31),
            status=ImportRun.Status.SUCCEEDED,
            rows_seen=10,
            rows_imported=10,
        )
        run = record_import_run(**import_request)
        self.assertEqual(record_import_run(**import_request).pk, run.pk)
        second_job, second_artifact = self.completed_job_and_artifact(self.project, self.owner, "second")
        second_request = dict(
            connection=second,
            job=second_job,
            source_artifact=second_artifact,
            source_format=ImportRun.SourceFormat.SEARCH_CONSOLE_CSV,
            source_checksum=checksum,
            date_start=date(2026, 7, 1),
            date_end=date(2026, 7, 31),
            observation_dimensions=[SourceDimension.DATE, SourceDimension.QUERY],
            source_timezone="UTC",
            coverage_state=ImportRun.CoverageState.COMPLETE,
            coverage={"export_shape": "date_query"},
            status=ImportRun.Status.SUCCEEDED,
            rows_seen=10,
            rows_imported=10,
        )
        other_property_run = record_import_run(**second_request)
        self.assertNotEqual(run.connection_id, other_property_run.connection_id)
        self.assertEqual(run.observation_dimensions, [SourceDimension.DATE, SourceDimension.QUERY])
        self.assertEqual(
            (run.provider, run.external_property_id, run.source_semantics, run.source_semantics_version),
            (first.provider, first.external_property_id, first.source_semantics, first.source_semantics_version),
        )
        with self.assertRaisesRegex(ValidationError, "immutable"):
            run.save()
        first_artifact.size_bytes = 11
        with self.assertRaisesRegex(ValidationError, "immutable"):
            first_artifact.save()

        IntegrationConnection.objects.filter(pk=first.pk).update(state=IntegrationConnection.State.DISCONNECTED)
        self.assertEqual(record_import_run(**import_request).pk, run.pk)
        self.project.domain_aliases.filter(origin="https://www.example.com").delete()
        self.assertEqual(record_import_run(**second_request).pk, other_property_run.pk)
        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
        self.assertEqual(record_import_run(**import_request).pk, run.pk)
        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=True)
        IntegrationConnection.objects.filter(pk=first.pk).update(state=IntegrationConnection.State.ACTIVE)

        duplicate_job, duplicate_artifact = self.completed_job_and_artifact(self.project, self.owner, "duplicate")
        with self.assertRaises(ValidationError):
            record_import_run(
                connection=first,
                job=duplicate_job,
                source_artifact=duplicate_artifact,
                source_format=ImportRun.SourceFormat.SEARCH_CONSOLE_CSV,
                source_checksum=checksum,
                date_start=date(2026, 7, 1),
                date_end=date(2026, 7, 31),
                observation_dimensions=[SourceDimension.DATE, SourceDimension.QUERY],
                source_timezone="UTC",
                coverage_state=ImportRun.CoverageState.COMPLETE,
                coverage={},
                status=ImportRun.Status.SUCCEEDED,
            )

        wrong_job, wrong_artifact = self.completed_job_and_artifact(
            self.project,
            self.owner,
            "wrong-handler",
            handler="crawl_site",
        )
        wrong_job.handler = "import_search_console_csv"
        wrong_artifact.job_id = first_job.pk
        with self.assertRaisesRegex(ValidationError, "Search Console import job"):
            record_import_run(
                connection=first,
                job=wrong_job,
                source_artifact=wrong_artifact,
                source_format=ImportRun.SourceFormat.SEARCH_CONSOLE_CSV,
                source_checksum="c" * 64,
                date_start=date(2026, 7, 1),
                date_end=date(2026, 7, 31),
                observation_dimensions=[SourceDimension.DATE, SourceDimension.QUERY],
                source_timezone="UTC",
                coverage_state=ImportRun.CoverageState.COMPLETE,
                coverage={},
                status=ImportRun.Status.SUCCEEDED,
            )

        missing_grain_job, missing_grain_artifact = self.completed_job_and_artifact(self.project, self.owner, "missing-grain")
        with self.assertRaisesRegex(ValidationError, "complete observation grain"):
            record_import_run(
                connection=first,
                job=missing_grain_job,
                source_artifact=missing_grain_artifact,
                source_format=ImportRun.SourceFormat.SEARCH_CONSOLE_CSV,
                source_checksum="b" * 64,
                date_start=date(2026, 7, 1),
                date_end=date(2026, 7, 31),
                observation_dimensions=[],
                source_timezone="UTC",
                coverage_state=ImportRun.CoverageState.COMPLETE,
                coverage={},
                status=ImportRun.Status.SUCCEEDED,
            )

    def test_import_capability_and_outcome_claims_are_consistent(self):
        limited = self.connection(
            property_id="https://m.example.com",
            capabilities=[IntegrationCapability.CSV_IMPORT],
            dimensions=[SourceDimension.DATE, SourceDimension.QUERY],
        )
        limited_job, limited_artifact = self.completed_job_and_artifact(self.project, self.owner, "limited")
        with self.assertRaisesRegex(ValidationError, "query metric capability"):
            record_import_run(
                connection=limited,
                job=limited_job,
                source_artifact=limited_artifact,
                source_format=ImportRun.SourceFormat.SEARCH_CONSOLE_CSV,
                source_checksum="d" * 64,
                date_start=date(2026, 7, 1),
                date_end=date(2026, 7, 31),
                observation_dimensions=[SourceDimension.DATE, SourceDimension.QUERY],
                source_timezone="UTC",
                coverage_state=ImportRun.CoverageState.COMPLETE,
                coverage={},
                status=ImportRun.Status.SUCCEEDED,
            )

        connection = self.connection()
        job, artifact = self.completed_job_and_artifact(self.project, self.owner, "overstated")
        request = dict(
            connection=connection,
            job=job,
            source_artifact=artifact,
            source_format=ImportRun.SourceFormat.SEARCH_CONSOLE_CSV,
            source_checksum="e" * 64,
            date_start=date(2026, 7, 1),
            date_end=date(2026, 7, 31),
            observation_dimensions=[SourceDimension.DATE, SourceDimension.QUERY],
            source_timezone="UTC",
            coverage_state=ImportRun.CoverageState.COMPLETE,
            coverage={},
            status=ImportRun.Status.SUCCEEDED,
            rows_seen=10,
            rows_imported=9,
            row_errors=1,
        )
        with self.assertRaisesRegex(ValidationError, "account for every row"):
            record_import_run(**request)
        request.update(rows_imported=10, row_errors=0, fresh_through=date(2026, 8, 1))
        with self.assertRaisesRegex(ValidationError, "freshness"):
            record_import_run(**request)
        future = timezone.localdate() + timedelta(days=1)
        request.update(date_start=future, date_end=future, fresh_through=future)
        with self.assertRaisesRegex(ValidationError, "future"):
            record_import_run(**request)

    def test_sync_cursor_failure_quota_and_retry_state_is_isolated_per_connection(self):
        capabilities = [IntegrationCapability.API_SYNC, IntegrationCapability.QUERY_METRICS]
        dimensions = [SourceDimension.DATE, SourceDimension.QUERY]
        first = self.connection(capabilities=capabilities, dimensions=dimensions)
        second = self.connection(
            property_id="https://www.example.com",
            capabilities=capabilities,
            dimensions=dimensions,
        )
        update_sync_cursor(
            connection=first,
            user=self.owner,
            expected_revision=0,
            status=SyncCursor.Status.RUNNING,
        )
        first_cursor = update_sync_cursor(
            connection=first,
            user=self.owner,
            expected_revision=1,
            status=SyncCursor.Status.FAILED,
            position={"next_date": "2026-07-10", "start_row": 25000},
            quota_state=SyncCursor.QuotaState.EXHAUSTED,
            error_category="provider_quota",
        )
        update_sync_cursor(
            connection=second,
            user=self.owner,
            expected_revision=0,
            status=SyncCursor.Status.RUNNING,
        )
        second_cursor = update_sync_cursor(
            connection=second,
            user=self.owner,
            expected_revision=1,
            status=SyncCursor.Status.SUCCEEDED,
            position={"next_date": "2026-07-31", "start_row": 0},
            coverage_start=date(2026, 7, 1),
            coverage_end=date(2026, 7, 31),
            fresh_through=date(2026, 7, 31),
            error_category="stale_error",
            retry_after=timezone.now() + timedelta(minutes=5),
        )
        self.assertEqual(first_cursor.error_category, "provider_quota")
        self.assertEqual(second_cursor.status, SyncCursor.Status.SUCCEEDED)
        self.assertEqual((second_cursor.error_category, second_cursor.retry_after), ("", None))
        self.assertNotEqual(first_cursor.connection_id, second_cursor.connection_id)
        with self.assertRaises(SyncCursorConflict):
            update_sync_cursor(
                connection=first,
                user=self.owner,
                expected_revision=1,
                status=SyncCursor.Status.SUCCEEDED,
            )

        with self.assertRaises(PermissionDenied):
            update_sync_cursor(
                connection=first,
                user=self.outsider,
                expected_revision=2,
                status=SyncCursor.Status.RUNNING,
            )
        csv_only = self.connection(property_id="https://m.example.com")
        with self.assertRaises(UnsupportedIntegrationCapability):
            update_sync_cursor(
                connection=csv_only,
                user=self.owner,
                expected_revision=0,
                status=SyncCursor.Status.RUNNING,
            )

    def test_database_constraints_and_admin_keep_scope_and_sensitive_references_bounded(self):
        connection = self.connection()
        with self.assertRaises(ValidationError):
            IntegrationConnection.objects.create(
                project=self.project,
                provider="google_search_console",
                external_property_id="https://www.example.com",
                capabilities=[IntegrationCapability.CSV_IMPORT],
                available_dimensions=[SourceDimension.DATE],
                source_semantics="search_console_performance",
                source_semantics_version="v1",
                backfill_limit_days=0,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            IntegrationConnection.objects.bulk_create([
                IntegrationConnection(
                    project=self.project,
                    provider=connection.provider,
                    external_property_id=connection.external_property_id,
                    capabilities=connection.capabilities,
                    available_dimensions=connection.available_dimensions,
                    source_semantics=connection.source_semantics,
                    source_semantics_version=connection.source_semantics_version,
                )
            ])

        connection_admin = IntegrationConnectionAdmin(IntegrationConnection, admin.site)
        cursor_admin = SyncCursorAdmin(SyncCursor, admin.site)
        self.assertNotIn("credential_reference", connection_admin.get_fields(request=None, obj=connection))
        self.assertEqual(connection_admin.credential_status(connection), "missing")
        self.assertNotIn("position", cursor_admin.get_fields(request=None, obj=None))
