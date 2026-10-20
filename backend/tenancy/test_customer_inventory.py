from tenancy.customer_artifact_barrier import project_artifact_barrier
import json
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.storage import storages
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from allauth.account.models import EmailAddress

from config.artifacts import save_private_artifact
from config.test_foundations import TEST_STORAGES

from providers.models import OrganizationPerformanceKey
from jobs.models import JobStep
from jobs.services import create_job

from .customer_inventory import CUSTOMER, GLOBAL, RESTRICTED, SECRETS, inventory_customer_data
from .customer_export import PRIVATE_FIELDS, SCHEMAS, _reviewed_fields
from .artifacts import project_artifact_scope, save_project_artifact
from .models import AuditEvent, AuditEventType, MembershipRole, OrganizationMembership
from .services import create_organization, create_project


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
                   DEBUG=True, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                                     "LOCATION": "owner-export-fixtures"}})
class CustomerInventoryTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.tasks.execute_job_task.apply_async", return_value=None)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        cache.clear()
        users = get_user_model().objects
        self.owner = users.create_user("export-owner@example.invalid", password="test-password")
        self.other = users.create_user("export-other@example.invalid", password="test-password")
        self.viewer = users.create_user("export-viewer@example.invalid", password="test-password")
        for user in (self.owner, self.other, self.viewer):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        self.organization = create_organization(user=self.owner, name="Inventory organization")
        self.project = create_project(organization=self.organization, user=self.owner, name="Own project",
                                      canonical_origin="https://inventory.example.invalid")
        self.other_organization = create_organization(user=self.other, name="Another organization")
        self.other_project = create_project(organization=self.other_organization, user=self.other,
            name="Foreign project", canonical_origin="https://foreign-inventory.example.invalid")
        OrganizationMembership.objects.create(organization=self.organization, user=self.viewer,
                                              role=MembershipRole.VIEWER)
        OrganizationPerformanceKey.objects.create(organization=self.organization,
            encrypted_secret="v1:never-return-this-value", rotated_at=timezone.now())
        OrganizationPerformanceKey.objects.create(organization=self.other_organization,
            encrypted_secret="v1:other-secret-value", rotated_at=timezone.now())

    def test_every_current_model_has_one_checked_ownership_class(self):
        available = {model._meta.label for model in apps.get_models()
                     if model._meta.app_label in {"accounts", "tenancy", "jobs", "integrations", "providers"}}
        groups = [set(CUSTOMER), set(RESTRICTED), set(SECRETS), GLOBAL]
        self.assertEqual(available, set.union(*groups))
        self.assertEqual(sum(len(group) for group in groups), len(available))
        self.assertEqual(set(SCHEMAS), set(CUSTOMER))
        self.assertIn("token_digest", PRIVATE_FIELDS)
        field = apps.get_model("jobs.JobRun")._meta.get_field("output")
        with patch.object(field.__class__, "get_internal_type", return_value="TextField"):
            with self.assertRaises(RuntimeError):
                _reviewed_fields("tenancy.Project")  # Another table's changed type blocks all exports.

    def test_inventory_is_owner_only_counts_scoped_and_never_exposes_secrets_or_keys(self):
        url = f"/api/organizations/{self.organization.pk}/export-inventory/"
        self.assertEqual(Client().get(url).status_code, 401)
        viewer = Client()
        viewer.force_login(self.viewer)
        self.assertEqual(viewer.get(url).status_code, 403)
        stranger = Client()
        stranger.force_login(self.other)
        self.assertEqual(stranger.get(url).status_code, 404)
        owner = Client()
        owner.force_login(self.owner)
        response = owner.get(url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        counts = response.json()
        self.assertEqual(counts["scope"], "record_counts_only_not_a_complete_export_or_deletion_receipt")
        self.assertEqual(next(item["count"] for item in counts["customer"]
                              if item["model"] == "tenancy.Project"), 1)
        self.assertEqual(next(item["count"] for item in counts["secret_bearing"]
                              if item["model"] == "providers.OrganizationPerformanceKey"), 1)
        self.assertNotIn("never-return-this-value", response.content.decode())
        self.assertNotIn("other-secret-value", response.content.decode())
        self.assertNotIn("https://foreign-inventory", response.content.decode())
        self.assertEqual(counts["artifact_counts"], {"job_artifacts": 0,
                         "report_artifacts": 0, "pending_cleanup": 0, "visible_storage_objects": 0,
                         "projects": [{"project_id": self.project.pk, "visible_count": 0}]})

    def test_inventory_counts_uncommitted_scoped_objects_without_exposing_storage_keys(self):
        with project_artifact_barrier(self.project.organization_id, shared=True):
            root = save_project_artifact(project=self.project, content=b"{}", content_type="application/json")
        with project_artifact_barrier(self.project.organization_id, shared=True):
            orphan = save_private_artifact(scope=f"{project_artifact_scope(self.project)}/jobs/42",
                                           content=b"{}", content_type="application/json")
        owner = Client()
        owner.force_login(self.owner)
        response = owner.get(f"/api/organizations/{self.organization.pk}/export-inventory/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["artifact_counts"]["visible_storage_objects"], 2)
        self.assertEqual(response.json()["artifact_counts"]["projects"], [
            {"project_id": self.project.pk, "visible_count": 2}])
        self.assertNotIn(root, response.content.decode())
        self.assertNotIn(orphan, response.content.decode())

    def test_owner_pages_current_customer_rows_with_csrf_and_secret_redaction(self):
        job = create_job(project=self.project, actor=self.owner, handler="diagnostic_probe",
            input_snapshot={"sample": "Authorization: Bearer secret-marker", "simulate_partial": False})
        type(job).objects.filter(pk=job.pk).update(input_snapshot={"api_key": "private-secret-marker",
            "sample": "Authorization: Bearer secret-marker"})
        JobStep.objects.bulk_create([JobStep(job=job, sequence=index, name=f"step {index}",
            status=JobStep.Status.SUCCEEDED) for index in range(1, 52)])
        url = f"/api/organizations/{self.organization.pk}/export/rows/"
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        request = {"model": "jobs.JobRun", "after_id": 0, "through_id": job.pk}
        self.assertEqual(owner.post(url, json.dumps(request), content_type="application/json").status_code, 403)
        owner.get("/_allauth/browser/v1/auth/session")
        csrf = {"HTTP_X_CSRFTOKEN": owner.cookies["csrftoken"].value}
        page = owner.post(url, json.dumps(request), content_type="application/json", **csrf)
        self.assertEqual(page.status_code, 200, page.content)
        self.assertEqual(page["Cache-Control"], "private, no-store")
        self.assertEqual(page.json()["rows"][0]["input_snapshot"]["api_key"], "[REDACTED]")
        self.assertNotIn("private-secret-marker", page.content.decode())
        self.assertNotIn("secret-marker", page.content.decode())
        self.assertNotIn("idempotency_key", page.content.decode())
        steps = {"model": "jobs.JobStep", "after_id": 0,
                 "through_id": JobStep.objects.order_by("-pk").values_list("pk", flat=True).first()}
        first = owner.post(url, json.dumps(steps), content_type="application/json", **csrf)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(len(first.json()["rows"]), 50)
        self.assertTrue(first.json()["has_more"])
        steps["after_id"] = first.json()["next_after_id"]
        second = owner.post(url, json.dumps(steps), content_type="application/json", **csrf)
        self.assertEqual((second.status_code, len(second.json()["rows"])), (200, 1))
        self.assertFalse(second.json()["has_more"])
        viewer = Client()
        viewer.force_login(self.viewer)
        self.assertEqual(viewer.post(url, json.dumps(request), content_type="application/json").status_code, 403)
        self.assertEqual(owner.post(url, json.dumps({**request, "model": "providers.AIProviderSecret"}),
                                    content_type="application/json", **csrf).status_code, 409)
        self.assertEqual(owner.post(f"/api/organizations/{self.other_organization.pk}/export/rows/",
                                    json.dumps(request), content_type="application/json", **csrf).status_code, 404)
        self.assertEqual(AuditEvent.objects.filter(organization=self.organization,
            event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED, details__kind="records").count(), 3)

    def test_owner_row_pages_shrink_at_byte_limit_without_skipping_a_record(self):
        jobs = [create_job(project=self.project, actor=self.owner, handler="diagnostic_probe",
                           input_snapshot={"sample": "fixture", "simulate_partial": False}) for _ in range(2)]
        for job in jobs:
            type(job).objects.filter(pk=job.pk).update(input_snapshot={"sample": "x" * (300 * 1024)})
        client = Client()
        client.force_login(self.owner)
        url = f"/api/organizations/{self.organization.pk}/export/rows/"
        selection = {"model": "jobs.JobRun", "after_id": 0, "through_id": jobs[-1].pk}
        first = client.post(url, json.dumps(selection), content_type="application/json")
        self.assertEqual(first.status_code, 200, first.content[:200])
        self.assertLessEqual(len(first.content), 512 * 1024)
        self.assertEqual([row["id"] for row in first.json()["rows"]], [jobs[0].pk])
        self.assertEqual(first.json()["next_after_id"], jobs[0].pk)
        self.assertTrue(first.json()["has_more"])
        selection["after_id"] = first.json()["next_after_id"]
        second = client.post(url, json.dumps(selection), content_type="application/json")
        self.assertEqual(second.status_code, 200, second.content[:200])
        self.assertEqual([row["id"] for row in second.json()["rows"]], [jobs[1].pk])
        self.assertFalse(second.json()["has_more"])
        type(jobs[1]).objects.filter(pk=jobs[1].pk).update(input_snapshot={"sample": "x" * (520 * 1024)})
        self.assertEqual(client.post(url, json.dumps(selection), content_type="application/json").status_code, 409)

    def test_owner_row_limit_counts_unicode_as_response_bytes(self):
        job = create_job(project=self.project, actor=self.owner, handler="diagnostic_probe",
                         input_snapshot={"sample": "fixture", "simulate_partial": False})
        type(job).objects.filter(pk=job.pk).update(input_snapshot={"sample": "é" * (100 * 1024)})
        client = Client()
        client.force_login(self.owner)
        response = client.post(f"/api/organizations/{self.organization.pk}/export/rows/",
            json.dumps({"model": "jobs.JobRun", "after_id": 0, "through_id": job.pk}),
            content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertFalse(AuditEvent.objects.filter(organization=self.organization,
            event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED, details__kind="records").exists())

    def test_owner_artifact_download_uses_numeric_scope_and_never_returns_private_storage_key(self):
        private = b'{"private": "customer fixture"}'
        with project_artifact_barrier(self.project.organization_id, shared=True):
            stored_key = save_project_artifact(project=self.project, content=private, content_type="application/json")
        with project_artifact_barrier(self.other_project.organization_id, shared=True):
            foreign_key = save_project_artifact(project=self.other_project, content=b'"other"',
                                                content_type="application/json")
        url = (f"/api/organizations/{self.organization.pk}/export/projects/{self.project.pk}/artifacts/0/")
        owner = Client()
        owner.force_login(self.owner)
        response = owner.get(url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.content, private)
        self.assertEqual(response["X-Content-SHA256"], sha256(private).hexdigest())
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertNotIn(stored_key, str(response.headers))
        self.assertNotIn(foreign_key, str(response.headers))
        viewer = Client()
        viewer.force_login(self.viewer)
        self.assertEqual(viewer.get(url).status_code, 403)
        other = Client()
        other.force_login(self.other)
        self.assertEqual(other.get(url).status_code, 404)
        self.assertEqual(owner.get(url.replace(f"/projects/{self.project.pk}/",
            "/projects/999999/")).status_code, 404)
        self.assertEqual(owner.get(url.replace("/artifacts/0/", "/artifacts/999/")).status_code, 404)
        self.assertEqual(AuditEvent.objects.filter(organization=self.organization,
            event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED, details__kind="artifact").count(), 1)

    def test_bounded_archive_contains_all_current_customer_models_and_visible_artifacts_without_secrets(self):
        private = b'{"customer": "synthetic"}'
        with project_artifact_barrier(self.project.organization_id, shared=True):
            stored = save_project_artifact(project=self.project, content=private, content_type="application/json")
        with project_artifact_barrier(self.other_project.organization_id, shared=True):
            foreign = save_project_artifact(project=self.other_project, content=b'"foreign-customer"',
                                            content_type="application/json")
        job = create_job(project=self.project, actor=self.owner, handler="diagnostic_probe",
            input_snapshot={"sample": "fixture", "simulate_partial": False})
        type(job).objects.filter(pk=job.pk).update(input_snapshot={"api_key": "never-export-provider-secret",
            "sample": "source only"})
        JobStep.objects.bulk_create([JobStep(job=job, sequence=index, name=f"step {index}",
            status=JobStep.Status.SUCCEEDED) for index in range(1, 53)])
        path = f"/api/organizations/{self.organization.pk}/export/archive/"
        self.assertEqual(Client().post(path, data="{}", content_type="application/json").status_code, 401)
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        self.assertEqual(owner.post(path, data="{}", content_type="application/json").status_code, 403)
        owner.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": owner.cookies["csrftoken"].value}
        response = owner.post(path, data="{}", content_type="application/json", **headers)
        self.assertEqual(response.status_code, 200, response.content[:500])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-SHA256"], sha256(response.content).hexdigest())
        with ZipFile(BytesIO(response.content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["scope"], "all_current_customer_models_and_visible_artifacts_only")
            self.assertEqual(manifest["consistency"], "sequential_observations_not_a_transactional_snapshot")
            window = manifest["capture_window"]
            start, end = (datetime.fromisoformat(window[key]) for key in ("started_at", "completed_at"))
            self.assertLessEqual(start, end)
            self.assertEqual(window["started_at"], manifest["captured_at"])
            self.assertTrue(all(start <= datetime.fromisoformat(row["observation_completed_at"]) <= end
                for row in [*manifest["tables"], *manifest["artifacts"]]))
            self.assertEqual(len(manifest["tables"]), len(CUSTOMER))
            self.assertEqual(len(manifest["artifacts"]), 1)
            file = manifest["artifacts"][0]
            self.assertEqual(archive.read(file["filename"]), private)
            self.assertEqual(file["sha256"], sha256(private).hexdigest())
            jobs = json.loads(archive.read("records/jobs/JobRun.json"))
            self.assertEqual(jobs[0]["input_snapshot"]["api_key"], "[REDACTED]")
            steps_data = archive.read("records/jobs/JobStep.json")
            self.assertEqual(len(json.loads(steps_data)), 52)
            self.assertEqual(next(row["sha256"] for row in manifest["tables"]
                if row["model"] == "jobs.JobStep"), sha256(steps_data).hexdigest())
            projects = json.loads(archive.read("records/tenancy/Project.json"))
            self.assertEqual([row["id"] for row in projects], [self.project.pk])
            members = json.loads(archive.read("records/tenancy/OrganizationMembership.json"))
            self.assertEqual({row["member_email"] for row in members}, {self.owner.email, self.viewer.email})
        self.assertNotIn("never-export-provider-secret", response.content.decode(errors="ignore"))
        self.assertNotIn("v1:never-return-this-value", response.content.decode(errors="ignore"))
        self.assertNotIn(stored, response.content.decode(errors="ignore"))
        self.assertNotIn(foreign, response.content.decode(errors="ignore"))
        self.assertEqual(AuditEvent.objects.filter(organization=self.organization,
            event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED, details__kind="bounded_archive").count(), 1)
        viewer = Client()
        viewer.force_login(self.viewer)
        self.assertEqual(viewer.post(path, data="{}", content_type="application/json").status_code, 403)

    def test_archive_limit_fails_before_auditing_or_delivering_an_incomplete_zip(self):
        client = Client()
        client.force_login(self.owner)
        path = f"/api/organizations/{self.organization.pk}/export/archive/"
        with patch("tenancy.customer_export.MAX_ARCHIVE_BYTES", 128):
            response = client.post(path, data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(b"PK\x03\x04", response.content)
        self.assertFalse(AuditEvent.objects.filter(organization=self.organization,
            event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED,
            details__kind="bounded_archive").exists())

    def test_record_ceiling_fails_before_delivering_or_auditing_a_partial_zip(self):
        client = Client()
        client.force_login(self.owner)
        with patch("tenancy.customer_export.MAX_ARCHIVE_RECORDS", 2):
            response = client.post(f"/api/organizations/{self.organization.pk}/export/archive/",
                                   "{}", content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertNotIn(b"PK\x03\x04", response.content)
        self.assertFalse(AuditEvent.objects.filter(organization=self.organization,
            event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED,
            details__kind="bounded_archive").exists())

    def test_oversized_zip_rejects_object_before_reading_its_contents(self):
        with project_artifact_barrier(self.project.organization_id, shared=True):
            save_project_artifact(project=self.project, content=b"v" * (2 * 1024 * 1024),
                                  content_type="application/json")
        client = Client()
        client.force_login(self.owner)
        with patch("tenancy.customer_export.MAX_ARCHIVE_BYTES", 1024 * 1024), patch.object(
                storages["artifacts"], "open",
                side_effect=AssertionError("Object should not be read for a doomed archive")):
            response = client.post(f"/api/organizations/{self.organization.pk}/export/archive/",
                                   "{}", content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertFalse(AuditEvent.objects.filter(organization=self.organization,
            event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED,
            details__kind="bounded_archive").exists())

    def test_archive_midstream_artifact_failure_never_returns_a_partial_zip(self):
        with project_artifact_barrier(self.project.organization_id, shared=True):
            save_project_artifact(project=self.project, content=b"x" * (2 * 1024 * 1024),
                                  content_type="application/json")
        class BrokenRead(BytesIO):
            def read(self, size=-1):
                if self.tell() >= 1024 * 1024:
                    raise OSError("injected read failure")
                return super().read(size)

        client = Client()
        client.force_login(self.owner)
        with patch.object(storages["artifacts"], "open", side_effect=lambda *_args, **_kwargs: BrokenRead(
                b"x" * (2 * 1024 * 1024))):
            response = client.post(f"/api/organizations/{self.organization.pk}/export/archive/",
                                   "{}", content_type="application/json")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"PK\x03\x04", response.content)
        self.assertFalse(AuditEvent.objects.filter(organization=self.organization,
            event_type=AuditEventType.ORGANIZATION_EXPORT_ACCESSED,
            details__kind="bounded_archive").exists())

    def test_deep_numeric_artifact_parts_remain_accessible_when_single_zip_is_over_limit(self):
        for index in range(1005):
            with project_artifact_barrier(self.project.organization_id, shared=True):
                save_project_artifact(project=self.project, content=f'{{"item":{index}}}'.encode(),
                                      content_type="application/json", key_stem=f"{index:032x}")
        client = Client()
        client.force_login(self.owner)
        inventory = client.get(f"/api/organizations/{self.organization.pk}/export-inventory/")
        self.assertEqual(inventory.status_code, 200, inventory.content)
        self.assertEqual(inventory.json()["artifact_counts"]["projects"][0]["visible_count"], 1005)
        part = client.get(f"/api/organizations/{self.organization.pk}/export/projects/"
                          f"{self.project.pk}/artifacts/1002/")
        self.assertEqual(part.status_code, 200, part.content[:200])
        self.assertEqual(part.content, b'{"item":1002}')
        self.assertEqual(client.post(f"/api/organizations/{self.organization.pk}/export/archive/",
                                     "{}", content_type="application/json").status_code, 409)


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
                   ARTIFACT_MAX_BYTES=12 * 1024 * 1024, DEBUG=True)
class LargeCustomerArtifactStreamTests(TransactionTestCase):
    def test_large_owned_artifact_download_streams_without_returning_a_partial_file(self):
        owner = get_user_model().objects.create_user("large-export@example.invalid", password="test-password")
        viewer = get_user_model().objects.create_user("large-viewer@example.invalid", password="test-password")
        stranger = get_user_model().objects.create_user("large-stranger@example.invalid", password="test-password")
        EmailAddress.objects.create(user=owner, email=owner.email, primary=True, verified=True)
        org = create_organization(user=owner, name="Large export")
        project = create_project(organization=org, user=owner, name="Large project",
                                 canonical_origin="https://large-export.example.invalid")
        OrganizationMembership.objects.create(organization=org, user=viewer, role=MembershipRole.VIEWER)
        data = b"v" * (10 * 1024 * 1024 + 1)
        with project_artifact_barrier(project.organization_id, shared=True):
            key = save_project_artifact(project=project, content=data, content_type="application/json")
        url = f"/api/organizations/{org.pk}/export/projects/{project.pk}/artifacts/0/"
        viewer_client = Client()
        viewer_client.force_login(viewer)
        self.assertEqual(viewer_client.get(url).status_code, 403)
        stranger_client = Client()
        stranger_client.force_login(stranger)
        self.assertEqual(stranger_client.get(url).status_code, 404)
        client = Client()
        client.force_login(owner)
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.streaming)
        self.assertEqual(response["Content-Length"], str(len(data)))
        self.assertEqual(response["X-Content-SHA256"], sha256(data).hexdigest())
        self.assertNotIn(key, str(response.headers))
        self.assertEqual(b"".join(response.streaming_content), data)
