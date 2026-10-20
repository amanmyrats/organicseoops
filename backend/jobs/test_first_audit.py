import json
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TransactionTestCase, override_settings

from config.test_foundations import TEST_STORAGES
from tenancy.models import MembershipRole, OrganizationMembership, ProjectConfiguration
from tenancy.services import create_organization, create_project
from .models import JobRun, JobStatus


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/html"}),
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "first-audit-fixtures"}},
                   DEBUG=True)
class FirstAuditTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        users = get_user_model().objects
        self.owner = users.create_user("first-audit@example.invalid", password="test-password")
        self.viewer = users.create_user("first-audit-viewer@example.invalid", password="test-password")
        self.foreign = users.create_user("first-audit-foreign@example.invalid", password="test-password")
        for user in (self.owner, self.viewer, self.foreign):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        self.org = create_organization(user=self.owner, name="First audit fixture")
        self.project = create_project(organization=self.org, user=self.owner, name="Audited source fixture",
            canonical_origin="https://first-audit.example.invalid")
        OrganizationMembership.objects.create(organization=self.org, user=self.viewer, role=MembershipRole.VIEWER)
        self.path = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/first-audit/"

    def test_private_first_audit_initial_state_budget_duplicate_and_permission_rechecks(self):
        client = Client(enforce_csrf_checks=True); client.force_login(self.owner)
        empty = client.get(self.path)
        self.assertEqual(empty.status_code, 200, empty.content)
        self.assertEqual(empty.json()["candidate_state"], "no_current_candidates_observed_not_clean")
        self.assertEqual(empty.json()["candidates"], [])
        self.assertEqual(empty.json()["crawl"], [])
        body = json.dumps({"page_limit": 2, "idempotency_key": "first-audit-001"})
        self.assertEqual(client.post(self.path, body, content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        with patch("jobs.services.dispatch_pending") as send:
            created = client.post(self.path, body, content_type="application/json", **headers)
            repeated = client.post(self.path, body, content_type="application/json", **headers)
        self.assertEqual(created.status_code, 202, created.content)
        self.assertEqual(created.json()["job"], repeated.json()["job"])
        self.assertEqual(created.json()["job"]["estimated_units"], 2)
        self.assertEqual(JobRun.objects.filter(project=self.project, handler="crawl_site").count(), 1)
        self.assertEqual(JobRun.objects.get(pk=created.json()["job"]["id"]).config_snapshot["first_audit_entrypoint"],
                         "bounded-first-audit-request-v1")
        self.assertEqual(client.post(self.path, json.dumps({"page_limit": 6, "idempotency_key": "too-many"}),
                                     content_type="application/json", **headers).status_code, 409)
        viewer = Client(); viewer.force_login(self.viewer)
        self.assertEqual(viewer.get(self.path).status_code, 200)
        self.assertEqual(viewer.post(self.path, body, content_type="application/json").status_code, 403)
        foreign = Client(); foreign.force_login(self.foreign)
        self.assertEqual(foreign.get(self.path).status_code, 404)
        self.assertEqual(foreign.get(f"{self.path}{created.json()['job']['id']}/").status_code, 404)
        detail = client.get(f"{self.path}{created.json()['job']['id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["job"]["handler"], "crawl_site")
        self.assertEqual(client.post(f"{self.path}{created.json()['job']['id']}/", "{}",
            content_type="application/json", **headers).status_code, 200)
        job = JobRun.objects.get(pk=created.json()["job"]["id"])
        self.assertEqual(job.status, JobStatus.CANCELLED)

    def test_stopped_trial_denies_budgeted_audit_before_creating_job(self):
        from tenancy.models import OrganizationTrial
        from django.utils import timezone
        from datetime import timedelta
        OrganizationTrial.objects.filter(organization=self.org).update(
            started_at=timezone.now() - timedelta(days=31), ends_at=timezone.now() - timedelta(days=1))
        client = Client(); client.force_login(self.owner)
        response = client.post(self.path, json.dumps({"page_limit": 1, "idempotency_key": "expired-audit"}),
                               content_type="application/json")
        self.assertIn(response.status_code, (403, 429))
        self.assertFalse(JobRun.objects.filter(project=self.project, handler="crawl_site").exists())

    def test_synthetic_demo_cannot_launch_or_mix_real_job_data(self):
        from tenancy.services import update_project_configuration
        update_project_configuration(project=self.project, user=self.owner, expected_revision=0,
                                     changes={"source_choice": "synthetic_demo"})
        client = Client(); client.force_login(self.owner)
        demo = client.get(self.path)
        self.assertEqual(demo.status_code, 200)
        self.assertEqual(demo.json()["mode"], "synthetic_demo_separate_no_live_observation")
        self.assertEqual(demo.json()["crawl"], [])
        self.assertEqual(demo.json()["candidates"], [])
        attempted = client.post(self.path, json.dumps({"page_limit": 1, "idempotency_key": "demo-must-not-run"}),
                                content_type="application/json")
        self.assertEqual(attempted.status_code, 409)
        self.assertFalse(JobRun.objects.filter(project=self.project).exists())

    def test_ordinary_crawl_key_cannot_be_promoted_and_request_cannot_supply_server_origin_marker(self):
        from .crawler import queue_crawl
        from .first_audit import queue_first_audit
        from django.core.exceptions import ValidationError
        with patch("jobs.services.dispatch_pending"):
            ordinary = queue_crawl(project=self.project, actor=self.owner, seeds=[], page_limit=1,
                                   idempotency_key="ordinary-provenance")
            self.assertNotIn("first_audit_entrypoint", ordinary.config_snapshot)
            with self.assertRaises(ValidationError):
                queue_first_audit(project=self.project, actor=self.owner, page_limit=1, idempotency_key="ordinary-provenance")
        ordinary.refresh_from_db()
        self.assertNotIn("first_audit_entrypoint", ordinary.config_snapshot)
        self.client.force_login(self.owner)
        rejected = self.client.post(self.path, json.dumps({"page_limit": 1, "idempotency_key": "forged-first-audit",
            "first_audit_entrypoint": "bounded-first-audit-request-v1"}), content_type="application/json")
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(JobRun.objects.count(), 1)
        self.client.post(f"{self.path}{ordinary.pk}/", "{}", content_type="application/json")
        unmarked = self.client.post(f"{self.path}{ordinary.pk}/", json.dumps({"idempotency_key": "unmarked-retry"}),
            content_type="application/json")
        self.assertEqual(unmarked.status_code, 409)
        self.assertEqual(JobRun.objects.count(), 1)

    def test_queue_rechecks_current_source_mode_actor_and_bounds_and_does_not_accept_cached_demo_state(self):
        from .crawler import queue_crawl
        from .first_audit import queue_first_audit
        from django.core.exceptions import PermissionDenied, ValidationError
        from tenancy.services import update_project_configuration
        configuration = update_project_configuration(project=self.project, user=self.owner, expected_revision=0,
            changes={"source_choice": "skip"})
        _cached = self.project.configuration
        ProjectConfiguration.objects.filter(pk=configuration.pk).update(source_choice="synthetic_demo")
        with patch("jobs.services.dispatch_pending"):
            with self.assertRaises(ValidationError):
                queue_first_audit(project=self.project, actor=self.owner, page_limit=1, idempotency_key="current-demo-denied")
            ProjectConfiguration.objects.filter(pk=configuration.pk).update(source_choice="skip")
            for actor in (self.viewer, self.foreign):
                with self.assertRaises(PermissionDenied):
                    queue_first_audit(project=self.project, actor=actor, page_limit=1, idempotency_key="current-role-denied")
            for value in (True, 0, 6):
                with self.assertRaises(ValidationError):
                    queue_first_audit(project=self.project, actor=self.owner, page_limit=value, idempotency_key="bounded-audit-denied")
            with self.assertRaises(ValidationError):
                queue_crawl(project=self.project, actor=self.owner, seeds=[self.project.canonical_origin + "/other"],
                    page_limit=1, idempotency_key="seeded-audit-denied", first_audit=True)
        self.assertFalse(JobRun.objects.exists())

    def test_original_generic_retry_keeps_origin_lineage_without_success_or_new_conversion(self):
        from .first_audit import queue_first_audit
        from .services import cancel_job, retry_job
        from tenancy.acquisition import acquisition_milestones
        with patch("jobs.services.dispatch_pending"):
            job = queue_first_audit(project=self.project, actor=self.owner, page_limit=1, idempotency_key="marked-first-audit")
            repeated = queue_first_audit(project=self.project, actor=self.owner, page_limit=1, idempotency_key="marked-first-audit")
            self.assertEqual(repeated.pk, job.pk)
            cancel_job(job=job, actor=self.owner)
            retried = retry_job(job=job, actor=self.owner, idempotency_key="marked-first-audit-retry")
        self.assertEqual(retried.config_snapshot, job.config_snapshot)
        self.assertEqual(retried.retry_of_id, job.pk)
        self.assertEqual(retried.status, JobStatus.QUEUED)
        self.assertEqual(acquisition_milestones()["milestones"]["first_audit_succeeded"], {"state": "derivable", "grain": "organization", "count": 0})
        from .models import JobStep
        from tenancy.services import update_project_configuration
        JobStep.objects.bulk_create([JobStep(job=job, sequence=index, name="Observed stage", status="failed",
            progress_percent=100, error_category="synthetic_failure", output={"private": "not projected"})
            for index in range(1, 22)])
        client = Client(enforce_csrf_checks=True); client.force_login(self.owner)
        path = f"{self.path}{job.pk}/"
        body = json.dumps({"idempotency_key": "private-audit-retry"})
        self.assertEqual(client.post(path, body, content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        detail = client.get(path).json()["job"]
        self.assertTrue(detail["retry_supported"])
        self.assertEqual(len(detail["steps"]), 20)
        self.assertTrue(detail["steps_has_more"])
        self.assertEqual(detail["steps"][0], {"sequence": 1, "name": "Observed stage", "status": "failed",
            "progress_percent": 100, "error_category": "synthetic_failure"})
        with patch("jobs.services.dispatch_pending"), override_settings(DEBUG=False):
            response = client.post(path, body, content_type="application/json", **headers)
            replay = client.post(path, body, content_type="application/json", **headers)
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json(), replay.json())
        new_job = JobRun.objects.get(pk=response.json()["job"]["id"])
        self.assertEqual(new_job.retry_of_id, job.pk)
        self.assertEqual(new_job.input_snapshot, job.input_snapshot)
        self.assertEqual(new_job.config_snapshot, job.config_snapshot)
        self.assertEqual(new_job.usage.reserved_units, 1)
        self.assertEqual(JobRun.objects.count(), 3)
        for payload in ('{"idempotency_key":"a","idempotency_key":"b"}', '{"idempotency_key":"a","page_limit":5}'):
            self.assertEqual(client.post(path, payload, content_type="application/json", **headers).status_code, 409)
        update_project_configuration(project=self.project, user=self.owner, expected_revision=0,
            changes={"source_choice": "synthetic_demo"})
        self.assertEqual(client.post(path, body, content_type="application/json", **headers).status_code, 409)
        ProjectConfiguration.objects.filter(project=self.project).update(source_choice="skip")
        self.assertEqual(client.post(path, body, content_type="application/json", **headers).status_code, 429)
        cache.clear()
        from tenancy.models import OrganizationTrial, Project
        from django.utils import timezone
        from datetime import timedelta
        Project.objects.filter(pk=self.project.pk).update(canonical_origin="https://changed-audit.example.invalid")
        self.assertEqual(client.post(path, body, content_type="application/json", **headers).status_code, 409)
        Project.objects.filter(pk=self.project.pk).update(canonical_origin=self.project.canonical_origin)
        OrganizationTrial.objects.filter(organization=self.org).update(
            started_at=timezone.now() - timedelta(days=31), ends_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(client.post(path, json.dumps({"idempotency_key": "expired-audit-retry"}),
            content_type="application/json", **headers).status_code, 403)
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
        self.assertEqual(client.post(path, body, content_type="application/json", **headers).status_code, 403)
        self.assertEqual(JobRun.objects.count(), 3)


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv", "application/json", "text/html"}), DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "first-audit-source-flow"}})
class FirstAuditSourceFlowTests(TransactionTestCase):
    def test_completed_csv_import_yields_only_actual_source_candidates_and_loses_them_after_revocation(self):
        from .test_findings import FindingEvidenceTests
        from .findings import record_csv_findings
        FindingEvidenceTests.setUp(self)
        path = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/first-audit/"
        client = Client(); client.force_login(self.owner)
        before = client.get(path)
        self.assertEqual(before.status_code, 200, before.content)
        self.assertEqual(before.json()["imports"][0]["state"], "succeeded")
        self.assertEqual(before.json()["candidates"], [])
        findings, _truncated = record_csv_findings(project=self.project, actor=self.owner,
            connection=self.connection, import_id=self.run.pk)
        observed = client.get(path)
        self.assertEqual(observed.status_code, 200)
        self.assertEqual(len(observed.json()["candidates"]), len(findings))
        self.assertEqual({row["id"] for row in observed.json()["candidates"]}, {item.pk for item in findings})
        self.assertEqual(observed.json()["candidate_state"], "candidates")
        from integrations.models import IntegrationConnection
        IntegrationConnection.objects.filter(pk=self.connection.pk).update(state="disconnected")
        revoked = client.get(path)
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(revoked.json()["candidates"], [])
        self.assertEqual(revoked.json()["candidate_state"], "no_current_candidates_observed_not_clean")
