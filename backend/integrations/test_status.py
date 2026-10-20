import json
from datetime import date

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from jobs.models import Artifact, JobRun, JobStatus
from tenancy.artifacts import project_artifact_scope
from tenancy.services import create_organization, create_project
from tenancy.models import AuditEvent, AuditEventType

from .google_tokens import SCOPE
from .models import GoogleOAuthGrant, ImportRun
from .services import create_connection, record_import_run


@override_settings(SECURE_SSL_REDIRECT=False, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv"}))
class ProjectSourcesTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("source-owner@example.com", password="test-password")
        self.other = users.create_user("source-other@example.com", password="test-password")
        for user in (self.owner, self.other):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        organization = create_organization(user=self.owner, name="Sources")
        self.project = create_project(organization=organization, user=self.owner, name="Site", canonical_origin="https://source.example")
        self.url = f"/api/organizations/{organization.pk}/projects/{self.project.pk}/sources/"
        self.connection = create_connection(
            project=self.project, user=self.owner, provider="google_search_console",
            external_property_id=self.project.canonical_origin,
            capabilities=["csv_import", "query_metrics"], available_dimensions=["query"],
            source_semantics="search_console_performance", source_semantics_version="csv-v1",
        )

    def test_source_status_is_scoped_and_does_not_claim_api_sync(self):
        client = Client()
        self.assertEqual(client.get(self.url, secure=True).status_code, 401)
        client.force_login(self.other)
        self.assertEqual(client.get(self.url, secure=True).status_code, 404)
        client.force_login(self.owner)
        initial = client.get(self.url, secure=True)
        self.assertEqual(initial.status_code, 200)
        self.assertIn("no-store", initial["Cache-Control"])
        source = initial.json()["sources"][0]
        self.assertTrue(source["scope_current"])
        self.assertTrue(source["csv_import_supported"])
        self.assertFalse(source["oauth_available"] or source["api_sync_available"])
        self.assertIsNone(source["latest_import"])

        job = JobRun.objects.create(
            organization=self.project.organization, project=self.project, actor=self.owner,
            handler="import_search_console_csv", method_version="search-console-csv-v1",
            input_snapshot={"source": "fixture"},
        )
        job.status = JobStatus.RUNNING
        job.save(update_fields=["status", "updated_at"])
        job.status = JobStatus.PARTIALLY_SUCCEEDED
        job.save(update_fields=["status", "updated_at"])
        artifact = Artifact.objects.create(
            job=job, project=self.project,
            key=f"{project_artifact_scope(self.project)}/{'a' * 32}.csv", content_type="text/csv", size_bytes=10,
        )
        run = record_import_run(
            connection=self.connection, job=job, source_artifact=artifact,
            source_format=ImportRun.SourceFormat.SEARCH_CONSOLE_CSV, source_checksum="a" * 64,
            date_start=date(2026, 1, 1), date_end=date(2026, 1, 2),
            observation_dimensions=["query"], source_timezone="America/Los_Angeles",
            coverage_state=ImportRun.CoverageState.PARTIAL,
            coverage={"export_shape": "query", "source_completeness": "provider_export_unknown"},
            status=ImportRun.Status.PARTIALLY_SUCCEEDED, rows_seen=2, rows_imported=1, row_errors=1,
        )
        latest = client.get(self.url, secure=True).json()["sources"][0]["latest_import"]
        self.assertEqual((latest["id"], latest["row_errors"], latest["coverage_state"]), (run.pk, 1, "partial"))
        self.assertNotIn("source_checksum", latest)
        history_path = f"{self.url}{self.connection.pk}/imports/"
        history = client.get(history_path, secure=True)
        self.assertEqual(history.status_code, 200)
        self.assertIn("no-store", history["Cache-Control"])
        self.assertEqual(history.json()["imports"][0]["source_completeness"], "provider_export_unknown")
        self.assertNotIn("source_checksum", history.json()["imports"][0])
        client.force_login(self.other)
        self.assertEqual(client.get(history_path, secure=True).status_code, 404)
        client.force_login(self.owner)
        self.project.canonical_origin = "https://changed.example"
        self.project.save()
        self.assertFalse(client.get(self.url, secure=True).json()["sources"][0]["scope_current"])

    def test_csv_source_state_is_audited_idempotent_and_scope_checked(self):
        path = f"{self.url}{self.connection.pk}/state/"
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        owner.get("/_allauth/browser/v1/auth/session", secure=True)
        headers = {"HTTP_REFERER": "https://testserver/", "HTTP_X_CSRFTOKEN": owner.cookies["csrftoken"].value}

        def patch(enabled, *, csrf=True):
            return owner.patch(path, data=json.dumps({"enabled": enabled}), content_type="application/json", secure=True,
                               **(headers if csrf else {"HTTP_REFERER": "https://testserver/"}))

        self.assertEqual(patch(False, csrf=False).status_code, 403)
        self.assertEqual(patch(False).json()["state"], "disconnected")
        self.assertEqual(patch(False).status_code, 200)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.SOURCE_DISABLED).count(), 1)
        self.project.canonical_origin = "https://changed.example"
        self.project.save()
        self.assertEqual(patch(True).status_code, 400)
        self.assertEqual(owner.get(self.url, secure=True).json()["sources"][0]["state"], "disconnected")
        self.project.canonical_origin = "https://source.example"
        self.project.save()
        self.assertEqual(patch(True).json()["state"], "active")
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.SOURCE_ENABLED).count(), 1)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.SOURCE_ENABLED).first().details["connection_id"], self.connection.pk)
        outsider = Client(enforce_csrf_checks=True)
        outsider.force_login(self.other)
        outsider.get("/_allauth/browser/v1/auth/session", secure=True)
        self.assertEqual(outsider.patch(path, data='{"enabled":false}', content_type="application/json", secure=True,
            HTTP_REFERER="https://testserver/", HTTP_X_CSRFTOKEN=outsider.cookies["csrftoken"].value).status_code, 404)

    def test_api_readiness_requires_current_grant_and_configured_client(self):
        self.connection.capabilities = ["api_sync", "query_metrics"]
        self.connection.save()
        grant = GoogleOAuthGrant.objects.create(
            organization=self.project.organization, project=self.project, actor=self.owner, scope=SCOPE,
            encrypted_refresh_token="v1:fixture-private", state=GoogleOAuthGrant.State.ACTIVE,
            verified_at=timezone.now(),
            selected_property_id=self.connection.external_property_id, selected_site_url="https://source.example/",
        )
        self.connection.credential_reference = grant.credential_reference
        self.connection.save()
        client = Client()
        client.force_login(self.owner)
        with override_settings(GOOGLE_OAUTH_CLIENT_ID="fixture", GOOGLE_OAUTH_CLIENT_SECRET="fixture-secret",
                               GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),),
                               GOOGLE_OAUTH_REDIRECT_URI="https://testserver/api/integrations/google-search-console/oauth/callback/"):
            source = client.get(self.url, secure=True).json()["sources"][0]
            self.assertTrue(source["api_sync_available"])
            self.assertNotIn("fixture-private", json.dumps(source))
            grant.state = GoogleOAuthGrant.State.RECONNECT_REQUIRED
            grant.revision += 1
            grant.save()
            self.assertFalse(client.get(self.url, secure=True).json()["sources"][0]["api_sync_available"])
