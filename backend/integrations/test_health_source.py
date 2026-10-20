from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, Project, ProjectOriginVerification
from . import health_source, test_search_console_sync as fixtures
from .google_oauth import revoke_google_grant
from .models import GA4OAuthGrant, GoogleOAuthGrant, IntegrationConnection, SyncCursor
from .search_console_sync import execute_search_console_sync, queue_search_console_sync
from .search_console_transport import SearchConsoleTransportError
from .services import create_connection, set_csv_source_state, update_sync_cursor


@override_settings(GOOGLE_OAUTH_CLIENT_ID="fixture-client", GOOGLE_OAUTH_CLIENT_SECRET="fixture-secret",
                   GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),))
class IntegrationHealthSourceTests(TestCase):
    def setUp(self):
        fixtures.SearchConsoleSyncTests.setUp(self)

    def queue(self, *, dimensions=None, key="fixture-sync"):
        return fixtures.SearchConsoleSyncTests.queue(self, dimensions=dimensions, key=key)

    def inspect(self, project=None, actor=None):
        return health_source.integration_health_metadata(project=project or self.project, actor=actor or self.user)

    def execute(self, *, key="fixture-sync", query=None, dimensions=None):
        job = self.queue(key=key, dimensions=dimensions)
        self.assertTrue(execute_search_console_sync(job.pk, refresh=self.refresh, verify_site=self.site,
            query=query or (lambda **_: {"responseAggregationType": "byProperty", "rows": []})))
        return job

    def test_real_worker_success_partial_quota_failure_and_original_dates_are_read_only(self):
        initial = self.inspect()["rows"][0]
        self.assertEqual((initial["source_state"], initial["sync"]), ("api_sync_metadata", None))
        self.execute()
        saved = SyncCursor.objects.get(connection=self.connection)
        with CaptureQueriesContext(connection) as queries, \
                patch("integrations.google_tokens.http.client.HTTPSConnection", side_effect=AssertionError("network")), \
                patch("jobs.summary_delivery.send_mail", side_effect=AssertionError("SMTP")), \
                patch("jobs.services.dispatch_pending", side_effect=AssertionError("dispatch")):
            row = self.inspect()["rows"][0]
        self.assertFalse(any(q["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for q in queries))
        self.assertEqual(set(row), {"connection_id", "provider", "connection_state", "source_state", "sync"})
        self.assertEqual(row["sync"], {"status": "succeeded", "quota_state": "available", "error_category": "",
            "last_attempt_at": saved.last_attempt_at.isoformat(), "last_success_at": saved.last_success_at.isoformat(),
            "fresh_through": self.day.isoformat()})
        self.assertNotIn("fixture", str(row)); self.assertNotIn(self.project.canonical_origin, str(row))
        self.assertNotIn("job_id", str(row))
        # A successful older backfill must not erase the newer recorded freshness.
        self.day -= timedelta(days=1)
        self.execute(key="older")
        self.assertEqual(self.inspect()["rows"][0]["sync"]["fresh_through"], saved.fresh_through.isoformat())
        prior_success = SyncCursor.objects.get(connection=self.connection).last_success_at
        def quota(*, dimension, **_):
            if dimension == "page": raise SearchConsoleTransportError("quota_limited")
            return {"responseAggregationType": "byProperty", "rows": []}
        self.execute(key="quota", query=quota, dimensions=["query", "page"])
        row = self.inspect()["rows"][0]["sync"]
        self.assertEqual((row["status"], row["quota_state"], row["error_category"], row["last_success_at"]),
            ("waiting_provider", "limited", "quota_limited", prior_success.isoformat()))
        SyncCursor.objects.filter(connection=self.connection).update(retry_after=timezone.now() - timedelta(seconds=1))
        def partial(*, dimension, **_):
            if dimension == "page": raise SearchConsoleTransportError("malformed_response")
            return {"responseAggregationType": "byProperty", "rows": []}
        self.execute(key="partial", query=partial, dimensions=["query", "page"])
        self.assertEqual(self.inspect()["rows"][0]["sync"]["status"], "partially_succeeded")
        def fail(**_): raise OSError("synthetic raw customer secret")
        self.execute(key="failed", query=fail)
        self.assertEqual(self.inspect()["rows"][0]["sync"]["error_category"], "handler_failed")
        SyncCursor.objects.filter(connection=self.connection).update(error_category="raw customer secret")
        self.assertEqual(self.inspect()["rows"][0]["sync"]["error_category"], "unclassified_failure")

    def test_actual_reconnect_and_revocation_are_distinct_from_missing_scope_or_authorization(self):
        def denied(**_): raise SearchConsoleTransportError("authorization_unavailable")
        self.execute(query=denied)
        row = self.inspect()["rows"][0]
        self.assertEqual((row["connection_state"], row["source_state"], row["sync"]["status"]),
            ("disconnected", "reconnect_required", "unavailable"))
        self.grant.refresh_from_db()
        revoke_google_grant(grant=self.grant, user=self.user, expected_revision=self.grant.revision,
                            remote_revoke=lambda **_: True)
        self.assertEqual(self.inspect()["rows"][0]["source_state"], "disconnected")
        IntegrationConnection.objects.filter(pk=self.connection.pk).update(state="active")
        self.assertEqual(self.inspect()["rows"][0]["source_state"], "authorization_unavailable")
        Project.objects.filter(pk=self.project.pk).update(canonical_origin="https://changed.example.invalid")
        self.assertEqual(self.inspect()["rows"][0]["source_state"], "scope_unavailable")
        IntegrationConnection.objects.filter(pk=self.connection.pk).update(state="unavailable")
        self.assertEqual(self.inspect()["rows"][0]["source_state"], "unavailable")

    def test_service_cursor_without_success_csv_and_ga4_unavailable_do_not_become_failed_sync(self):
        update_sync_cursor(connection=self.connection, user=self.user, expected_revision=0, status="running")
        self.assertEqual(self.inspect()["rows"][0]["sync"]["last_success_at"], None)
        other = Project.objects.create(organization=self.project.organization, name="CSV fixture",
            canonical_origin="https://csv.example.invalid")
        csv = create_connection(project=other, user=self.user, provider="google_search_console",
            external_property_id=other.canonical_origin, capabilities=["csv_import", "query_metrics"],
            available_dimensions=["query"], source_semantics="search_console_performance", source_semantics_version="csv-v1")
        self.assertEqual(self.inspect(project=other)["rows"][0]["source_state"], "csv_only")
        set_csv_source_state(connection=csv, user=self.user, active=False)
        self.assertEqual(self.inspect(project=other)["rows"][0]["source_state"], "disconnected")
        grant = GA4OAuthGrant.objects.create(organization=self.project.organization, project=self.project, actor=self.user,
            encrypted_refresh_token="v1:synthetic-secret", scope="https://www.googleapis.com/auth/analytics.readonly",
            property_id="12345", selected_origins=[self.project.canonical_origin], state="active", verified_at=timezone.now())
        ga4 = IntegrationConnection.objects.create(project=self.project, provider="google_analytics_4",
            external_property_id="12345", credential_reference=grant.credential_reference,
            capabilities=["api_sync", "landing_metrics"], available_dimensions=["hostname", "landing_page"],
            source_semantics="ga4_landing_pages", source_semantics_version="ga4-data-v1", currency="USD")
        # Hypothetical legacy success is explicitly not usable exact-origin reporting.
        SyncCursor.objects.create(project=self.project, connection=ga4, status="succeeded", last_success_at=timezone.now())
        row = self.inspect()["rows"][-1]
        self.assertEqual((row["source_state"], row["sync"]), ("exact_origin_attribution_unavailable", None))

    def test_genuine_domain_binding_requires_current_selected_verified_origin(self):
        verified = ProjectOriginVerification.objects.create(organization=self.project.organization, project=self.project,
            origin=self.project.canonical_origin, challenge_digest="a" * 64, state="verified", verified_at=timezone.now())
        grant = GoogleOAuthGrant.objects.create(organization=self.project.organization, project=self.project, actor=self.user,
            scope=self.grant.scope, encrypted_refresh_token="v1:fixture-only", state="active", verified_at=timezone.now(),
            selected_property_id="sc-domain:sync.example", selected_site_url="sc-domain:sync.example",
            selected_origins=[self.project.canonical_origin])
        domain = IntegrationConnection.objects.create(project=self.project, provider="google_search_console",
            external_property_id=grant.selected_property_id, credential_reference=grant.credential_reference,
            capabilities=["api_sync", "page_metrics"], available_dimensions=["page"],
            source_semantics="search_console_domain_pages", source_semantics_version="gsc-domain-page-v1",
            timezone="America/Los_Angeles")
        with patch("jobs.services.dispatch_pending"):
            job = queue_search_console_sync(project=self.project, actor=self.user, connection=domain, grant=grant,
                day=self.day, dimensions=["page"], idempotency_key="domain-health")
        execute_search_console_sync(job.pk, refresh=self.refresh,
            verify_site=lambda **_: {"siteUrl": grant.selected_site_url, "permissionLevel": "siteOwner"},
            query=lambda **_: {"responseAggregationType": "byPage", "rows": []})
        self.assertEqual(self.inspect()["rows"][-1]["source_state"], "api_sync_metadata")
        ProjectOriginVerification.objects.filter(pk=verified.pk).update(state="revoked", revoked_at=timezone.now())
        self.assertEqual(self.inspect()["rows"][-1]["source_state"], "scope_unavailable")

    def test_retained_reader_foreign_scope_final_source_authority_and_corrupt_cursor_fences(self):
        self.execute()
        reader = get_user_model().objects.create_user("health-reader@example.invalid", "test-password")
        OrganizationMembership.objects.create(organization=self.project.organization, user=reader, role="viewer")
        OrganizationTrial.objects.filter(organization=self.project.organization).update(state="expired")
        EmailAddress.objects.filter(user=self.user).update(verified=False)
        self.assertEqual(self.inspect(actor=reader)["rows"][0]["sync"]["status"], "succeeded")
        other = Project.objects.create(organization=self.project.organization, name="Other health",
            canonical_origin="https://other-health.example.invalid")
        self.assertEqual(self.inspect(project=other)["rows"], [])
        Project.objects.filter(pk=other.pk).update(access_restricted=True)
        with self.assertRaises(PermissionDenied): self.inspect(project=other, actor=reader)
        original = health_source._row
        changes = [lambda: SyncCursor.objects.filter(connection=self.connection).update(revision=99),
            lambda: IntegrationConnection.objects.filter(pk=self.connection.pk).update(state="disconnected"),
            lambda: GoogleOAuthGrant.objects.filter(pk=self.grant.pk).update(revision=99),
            lambda: Project.objects.filter(pk=self.project.pk).update(canonical_origin="https://lost.example.invalid"),
            lambda: OrganizationMembership.objects.filter(user=reader).delete(),
            lambda: get_user_model().objects.filter(pk=reader.pk).update(is_active=False),
            lambda: Organization.objects.filter(pk=self.project.organization_id).update(is_suspended=True),
            lambda: Organization.objects.filter(pk=self.project.organization_id).update(is_suspended=True, closed_at=timezone.now())]
        for change in changes:
            with transaction.atomic():
                def mutate(record, origins, assessed):
                    result = original(record, origins, assessed); change(); return result
                with patch("integrations.health_source._row", side_effect=mutate), self.assertRaises((ValidationError, PermissionDenied)):
                    self.inspect(actor=reader)
                transaction.set_rollback(True)
        cursor = SyncCursor.objects.get(connection=self.connection)
        for changes in ({"project": other}, {"last_success_at": timezone.now() + timedelta(days=1)},
                        {"fresh_through": timezone.now().date() + timedelta(days=1)}):
            with transaction.atomic():
                SyncCursor.objects.filter(pk=cursor.pk).update(**changes)
                with self.assertRaises(ValidationError): self.inspect(actor=reader)
                transaction.set_rollback(True)
        SyncCursor.objects.filter(pk=cursor.pk).update(last_attempt_at=timezone.now() - timedelta(days=100),
            last_success_at=timezone.now() - timedelta(days=100), fresh_through=timezone.now().date() - timedelta(days=100))
        self.assertEqual(self.inspect(actor=reader)["rows"][0]["sync"]["status"], "succeeded")

    def test_explicit_synthetic_fifty_row_cap_order_and_selected_collection_drift(self):
        # Synthetic negative GA4 metadata for collection bounds; never reported as analytics collection.
        IntegrationConnection.objects.bulk_create([IntegrationConnection(project=self.project, provider="google_analytics_4",
            external_property_id=str(index), capabilities=["api_sync"], source_semantics="synthetic-bounds",
            source_semantics_version="synthetic-v1") for index in range(1, 51)])
        result = self.inspect()
        self.assertTrue(result["has_more"]); self.assertEqual(len(result["rows"]), 50)
        self.assertEqual([row["connection_id"] for row in result["rows"]],
            list(IntegrationConnection.objects.filter(project=self.project).order_by("pk").values_list("pk", flat=True)[:50]))
        original = health_source._row
        overflow = IntegrationConnection.objects.filter(project=self.project).order_by("-pk").first()
        def remove_overflow(record, origins, assessed):
            result = original(record, origins, assessed)
            IntegrationConnection.objects.filter(pk=overflow.pk).delete()
            return result
        with patch("integrations.health_source._row", side_effect=remove_overflow), self.assertRaises(ValidationError):
            self.inspect()
