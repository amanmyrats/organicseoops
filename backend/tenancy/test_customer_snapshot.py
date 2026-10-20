from tenancy.customer_artifact_barrier import project_artifact_barrier
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from tempfile import SpooledTemporaryFile
from threading import Event
from unittest.mock import patch
from zipfile import ZipFile

from allauth.account.models import EmailAddress
from kombu.exceptions import OperationalError
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.artifacts import ArtifactNotFound, ArtifactStorageError, read_private_artifact, save_private_artifact
from config.test_foundations import TEST_STORAGES
from jobs.tasks import reconcile_jobs_task

from .artifacts import save_project_artifact
from .deletion import delete_customer_database_records, prepare_customer_data_deletion, sweep_customer_artifact_versions
from .customer_snapshot import (capture_reserved_customer_snapshot, recover_stale_customer_snapshots,
                                reserve_bounded_customer_snapshot)
from .models import (MembershipRole, Organization, OrganizationCustomerExport,
                     OrganizationCustomerExportPart, OrganizationMembership)
from .services import create_organization, create_project


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "application/zip"}),
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                       "LOCATION": "customer-snapshot-fixtures"}}, DEBUG=True)
class CustomerSnapshotTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        capture = patch("tenancy.tasks.capture_customer_snapshot_task.apply_async")
        self.addCleanup(capture.stop)
        capture.start()
        cache.clear()
        users = get_user_model().objects
        self.owner = users.create_user("snapshot-owner@example.invalid", password="test-password")
        self.viewer = users.create_user("snapshot-viewer@example.invalid", password="test-password")
        self.other = users.create_user("snapshot-foreign@example.invalid", password="test-password")
        for user in (self.owner, self.viewer, self.other):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        self.org = create_organization(user=self.owner, name="Snapshot fixture")
        self.project = create_project(organization=self.org, user=self.owner, name="Snapshot project",
                                      canonical_origin="https://snapshot.example.invalid")
        OrganizationMembership.objects.create(organization=self.org, user=self.viewer, role=MembershipRole.VIEWER)
        self.foreign = create_organization(user=self.other, name="Other snapshot fixture")
        self.foreign_project = create_project(organization=self.foreign, user=self.other,
            name="Other snapshot project", canonical_origin="https://other-snapshot.example.invalid")

    def test_malformed_snapshot_format_is_rejected_without_reserving_a_capture(self):
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        owner.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": owner.cookies["csrftoken"].value}
        url = f"/api/organizations/{self.org.pk}/export/snapshots/"
        for value in ([], {}):
            with self.subTest(format=value):
                response = owner.post(url, json.dumps({"request_key": "c" * 32, "format": value}),
                                      content_type="application/json", **headers)
                self.assertEqual(response.status_code, 409, response.content[:200])
                self.assertFalse(OrganizationCustomerExport.objects.filter(organization=self.org).exists())

    def test_copy_policy_requires_review_and_preserves_legacy_copies(self):
        from django.core.exceptions import ValidationError
        from .customer_export_policy import reviewed_copy_lifetime
        from .customer_copy_cleanup import purge_expired_customer_copies
        with override_settings(CUSTOMER_EXPORT_COPY_POLICY_REFERENCE="", CUSTOMER_EXPORT_COPY_LIFETIME_DAYS=0):
            self.assertEqual(reviewed_copy_lifetime(), ("", None))
            legacy = OrganizationCustomerExport.objects.create(organization=self.org, actor=self.owner,
                request_key="1" * 32, state="ready", completed_at=timezone.now() - timedelta(days=2),
                size_bytes=1, content_sha256="a" * 64)
        with override_settings(CUSTOMER_EXPORT_COPY_POLICY_REFERENCE="fixture", CUSTOMER_EXPORT_COPY_LIFETIME_DAYS=1):
            self.assertEqual(purge_expired_customer_copies()["removed"], 0)
            legacy.refresh_from_db()
            self.assertIsNone(legacy.expires_at)
            self.assertEqual(legacy.delivery_state, "ready")
        for reference, days in (("", 1), ("review", 0), ("bad reference", 1), ("review", True), ("review", 36501)):
            with self.subTest(reference=reference, days=days), override_settings(
                    CUSTOMER_EXPORT_COPY_POLICY_REFERENCE=reference, CUSTOMER_EXPORT_COPY_LIFETIME_DAYS=days):
                with self.assertRaises(ValidationError):
                    reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner, request_key="2" * 32)
        self.assertEqual(self.org.customer_exports.count(), 1)

    @override_settings(CUSTOMER_EXPORT_COPY_POLICY_REFERENCE="fixture-review", CUSTOMER_EXPORT_COPY_LIFETIME_DAYS=1)
    def test_expired_copy_cleanup_retries_bounded_scope_and_preserves_failed_metadata(self):
        from .customer_copy_cleanup import purge_expired_customer_copies
        from .tasks import purge_expired_customer_copies_task
        from django.db import IntegrityError, transaction
        now = timezone.now()
        expired = OrganizationCustomerExport.objects.create(organization=self.org, actor=self.owner,
            request_key="1" * 32, state="ready", completed_at=now - timedelta(days=2),
            size_bytes=1, content_sha256="a" * 64)
        fresh = OrganizationCustomerExport.objects.create(organization=self.foreign, actor=self.other,
            request_key="2" * 32, state="ready", completed_at=now, size_bytes=1, content_sha256="b" * 64)
        foreign_key = save_private_artifact(scope=f"organizations/{self.foreign.pk}/exports/{fresh.pk}",
            content=b"foreign", content_type="application/zip")
        from django.core.exceptions import PermissionDenied
        from .artifacts import delete_expired_organization_export_batch
        for organization, identity in ((self.org, fresh.pk), (self.foreign, fresh.pk), (self.foreign, expired.pk)):
            with self.assertRaises(PermissionDenied):
                delete_expired_organization_export_batch(organization=organization, snapshot_id=identity)
        OrganizationCustomerExport.objects.filter(pk=expired.pk).update(format="coherent-parts-v3",
                                                                        progress={"in_flight": True})
        self.assertEqual(purge_expired_customer_copies()["failed"], 1)
        self.assertTrue(OrganizationCustomerExport.objects.filter(pk=expired.pk).exists())
        OrganizationCustomerExport.objects.filter(pk=expired.pk).update(format="source-parts-v2",
                                                                        progress={"in_flight": True})
        keys = [save_private_artifact(scope=f"organizations/{self.org.pk}/exports/{expired.pk}",
            content=b"orphan", content_type="application/zip") for _ in range(11)]
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizationCustomerExport.objects.filter(pk=expired.pk).update(expires_at=expired.completed_at)
        with patch("tenancy.customer_copy_cleanup.delete_expired_organization_export_batch",
                   side_effect=ArtifactStorageError("unknown")):
            self.assertEqual(purge_expired_customer_copies(), {"removed": 0, "pending": 0, "failed": 1})
        expired.refresh_from_db()
        self.assertEqual(expired.delivery_state, "expired")
        self.assertIsNotNone(expired.last_progress_at)
        self.assertEqual(purge_expired_customer_copies_task.run(), {"removed": 0, "pending": 1, "failed": 0})
        with patch("tenancy.customer_copy_cleanup.failed_export_versions_remain", return_value=True):
            self.assertEqual(purge_expired_customer_copies(), {"removed": 0, "pending": 1, "failed": 0})
        self.assertTrue(OrganizationCustomerExport.objects.filter(pk=expired.pk).exists())
        self.assertEqual(purge_expired_customer_copies(), {"removed": 1, "pending": 0, "failed": 0})
        self.assertFalse(OrganizationCustomerExport.objects.filter(pk=expired.pk).exists())
        self.assertEqual(read_private_artifact(foreign_key), b"foreign")
        for key in keys:
            with self.assertRaises(ArtifactNotFound):
                read_private_artifact(key)
        self.assertEqual(purge_expired_customer_copies()["removed"], 0)

    def test_owner_captures_private_multi_part_zip_and_current_permission_controls_delivery(self):
        source = b"x" * (9 * 1024 * 1024)
        with project_artifact_barrier(self.project.organization_id, shared=True):
            save_project_artifact(project=self.project, content=source, content_type="application/json")
        with project_artifact_barrier(self.foreign_project.organization_id, shared=True):
            foreign_key = save_project_artifact(project=self.foreign_project, content=b'"foreign"',
                                                content_type="application/json")
        url = f"/api/organizations/{self.org.pk}/export/snapshots/"
        body = json.dumps({"request_key": "a" * 32})
        viewer = Client()
        viewer.force_login(self.viewer)
        self.assertEqual(viewer.post(url, body, content_type="application/json").status_code, 403)
        outsider = Client()
        outsider.force_login(self.other)
        self.assertEqual(outsider.post(url, body, content_type="application/json").status_code, 404)
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        self.assertEqual(owner.post(url, body, content_type="application/json").status_code, 403)
        owner.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": owner.cookies["csrftoken"].value}
        created = owner.post(url, body, content_type="application/json", **headers)
        self.assertEqual(created.status_code, 202, created.content[:200])
        self.assertEqual(created.json()["state"], "preparing")
        self.assertIsNone(created.json()["manifest_path"])
        self.assertEqual(owner.post(url, body, content_type="application/json", **headers).json(), created.json())
        self.assertEqual(OrganizationCustomerExport.objects.filter(organization=self.org).count(), 1)
        snapshot_id = created.json()["snapshot_id"]
        spool = SpooledTemporaryFile(max_size=1024)
        with patch("tenancy.customer_snapshot.SpooledTemporaryFile", return_value=spool):
            self.assertTrue(capture_reserved_customer_snapshot(snapshot_id))
        self.assertTrue(spool._rolled)
        self.assertTrue(spool.closed)
        self.assertFalse(capture_reserved_customer_snapshot(snapshot_id))
        self.assertIsNotNone(OrganizationCustomerExport.objects.get(pk=snapshot_id).last_progress_at)
        history = owner.get(url)
        self.assertEqual(history.status_code, 200, history.content[:200])
        self.assertEqual(history.json()["snapshots"][0]["manifest_path"], f"{url}{snapshot_id}/")
        self.assertNotIn(f"organizations/{self.org.pk}/exports/", history.content.decode())
        self.assertEqual(viewer.get(url).status_code, 403)
        self.assertEqual(outsider.get(url).status_code, 404)
        manifest_url = f"{url}{snapshot_id}/"
        manifest_response = owner.get(manifest_url)
        self.assertEqual(manifest_response.status_code, 200, manifest_response.content[:200])
        manifest = manifest_response.json()
        self.assertEqual(manifest["scope"], "captured_bounded_customer_content_not_legal_or_backup_export")
        self.assertEqual(len(manifest["parts"]), 2)
        self.assertEqual(manifest_response["Cache-Control"], "private, no-store")
        self.assertNotIn(f"organizations/{self.org.pk}/exports/", manifest_response.content.decode())
        chunks = []
        for part in manifest["parts"]:
            response = owner.get(part["download_path"])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["X-Content-SHA256"], sha256(response.content).hexdigest())
            self.assertEqual(part["sha256"], response["X-Content-SHA256"])
            chunks.append(response.content)
        content = b"".join(chunks)
        self.assertEqual(sha256(content).hexdigest(), manifest["sha256"])
        with ZipFile(BytesIO(content)) as archive:
            self.assertEqual(archive.read(archive.namelist()[-2]), source)
        self.assertEqual(viewer.get(manifest_url).status_code, 404)
        self.assertEqual(outsider.get(manifest_url).status_code, 404)
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role=MembershipRole.VIEWER)
        self.assertEqual(owner.get(manifest["parts"][0]["download_path"]).status_code, 404)
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role=MembershipRole.OWNER)
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        self.assertEqual(owner.get(manifest_url).status_code, 404)
        run = prepare_customer_data_deletion(organization=self.org)
        run = sweep_customer_artifact_versions(run=run)
        self.assertEqual(run.state, run.State.STORAGE_CLEARED)
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(OrganizationCustomerExport.objects.filter(organization=self.org).exists())
        self.assertFalse(OrganizationCustomerExportPart.objects.exists())
        from .artifacts import read_project_artifact
        self.assertEqual(read_project_artifact(project=self.foreign_project, key=foreign_key), b'"foreign"')

    def test_failed_storage_capture_never_claims_a_ready_snapshot_or_replays_request(self):
        with project_artifact_barrier(self.project.organization_id, shared=True):
            save_project_artifact(project=self.project, content=b"y" * (9 * 1024 * 1024),
                                  content_type="application/json")
        client = Client()
        client.force_login(self.owner)
        path = f"/api/organizations/{self.org.pk}/export/snapshots/"
        body = json.dumps({"request_key": "b" * 32})
        attempts = []

        def fail_second(**kwargs):
            attempts.append(1)
            if len(attempts) == 2:
                raise ArtifactStorageError("unknown")
            return save_private_artifact(**kwargs)

        response = client.post(path, body, content_type="application/json")
        self.assertEqual(response.status_code, 202)
        with patch("tenancy.customer_snapshot.save_private_artifact", side_effect=fail_second):
            self.assertFalse(capture_reserved_customer_snapshot(response.json()["snapshot_id"]))
        record = OrganizationCustomerExport.objects.get(organization=self.org)
        self.assertEqual(record.state, record.State.FAILED)
        self.assertEqual(record.parts.count(), 1)
        staged_key = record.parts.first().storage_key
        self.assertEqual(client.get(path).json()["snapshots"][0]["state"], "failed")
        self.assertIsNone(client.get(path).json()["snapshots"][0]["manifest_path"])
        self.assertEqual(client.post(path, body, content_type="application/json").status_code, 409)
        self.assertEqual(client.get(f"{path}{record.pk}/").status_code, 404)
        discard = f"{path}{record.pk}/discard/"
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(discard, "{}", content_type="application/json").status_code, 403)
        viewer = Client()
        viewer.force_login(self.viewer)
        self.assertEqual(viewer.post(discard, "{}", content_type="application/json").status_code, 404)
        outsider = Client()
        outsider.force_login(self.other)
        self.assertEqual(outsider.post(discard, "{}", content_type="application/json").status_code, 404)
        with patch("tenancy.customer_snapshot.delete_failed_organization_export_batch",
                   side_effect=ArtifactStorageError("unknown outcome")):
            self.assertEqual(client.post(discard, "{}", content_type="application/json").status_code, 503)
        self.assertTrue(OrganizationCustomerExport.objects.filter(pk=record.pk).exists())
        for _ in range(10):
            save_private_artifact(scope=f"organizations/{self.org.pk}/exports/{record.pk}",
                                  content=b"partial", content_type="application/zip")
        self.assertEqual(client.post(discard, "{}", content_type="application/json").status_code, 202)
        self.assertEqual(client.post(discard, "{}", content_type="application/json").status_code, 200)
        self.assertFalse(OrganizationCustomerExport.objects.filter(pk=record.pk).exists())
        with self.assertRaises(ArtifactNotFound):
            read_private_artifact(staged_key)
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        run = prepare_customer_data_deletion(organization=self.org)
        self.assertEqual(sweep_customer_artifact_versions(run=run).state, run.State.STORAGE_CLEARED)
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(OrganizationCustomerExport.objects.filter(pk=record.pk).exists())

    def test_closure_between_parts_prevents_late_copy_after_storage_deletion(self):
        with project_artifact_barrier(self.project.organization_id, shared=True):
            save_project_artifact(project=self.project, content=b"z" * (9 * 1024 * 1024),
                                  content_type="application/json")
        client = Client()
        client.force_login(self.owner)
        original_create = OrganizationCustomerExportPart.objects.create
        written = []

        def close_after_first(**kwargs):
            part = original_create(**kwargs)
            written.append(part.position)
            Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
            return part

        response = client.post(f"/api/organizations/{self.org.pk}/export/snapshots/",
                               json.dumps({"request_key": "c" * 32}), content_type="application/json")
        self.assertEqual(response.status_code, 202)
        with patch("tenancy.customer_snapshot.OrganizationCustomerExportPart.objects.create",
                    side_effect=close_after_first):
            self.assertFalse(capture_reserved_customer_snapshot(response.json()["snapshot_id"]))
        self.assertEqual(written, [0])
        snapshot = OrganizationCustomerExport.objects.get(organization=self.org)
        self.assertEqual(snapshot.state, snapshot.State.FAILED)
        run = prepare_customer_data_deletion(organization=self.org)
        self.assertEqual(sweep_customer_artifact_versions(run=run).state, run.State.STORAGE_CLEARED)
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)

    def test_reconciliation_marks_only_stale_preparing_captures_failed_without_replay(self):
        now = timezone.now()
        stale = OrganizationCustomerExport.objects.create(organization=self.org, actor=self.owner,
                                                           request_key="d" * 32)
        fresh = OrganizationCustomerExport.objects.create(organization=self.org, actor=self.owner,
                                                           request_key="e" * 32)
        ready = OrganizationCustomerExport.objects.create(organization=self.org, actor=self.owner,
            request_key="f" * 32, state=OrganizationCustomerExport.State.READY,
            completed_at=now, size_bytes=1, content_sha256="a" * 64)
        other = OrganizationCustomerExport.objects.create(organization=self.foreign, actor=self.other,
                                                            request_key="g" * 32)
        progressing = OrganizationCustomerExport.objects.create(organization=self.org, actor=self.owner,
                                                                 request_key="h" * 32)
        OrganizationCustomerExport.objects.filter(pk=stale.pk).update(created_at=now - timedelta(minutes=17))
        OrganizationCustomerExport.objects.filter(pk=ready.pk).update(created_at=now - timedelta(minutes=16))
        OrganizationCustomerExport.objects.filter(pk=other.pk).update(created_at=now - timedelta(minutes=15, seconds=1))
        OrganizationCustomerExport.objects.filter(pk=progressing.pk).update(
            created_at=now - timedelta(hours=1), last_progress_at=now - timedelta(minutes=14))
        self.assertEqual(recover_stale_customer_snapshots(now=now, limit=1), 1)
        stale.refresh_from_db(); fresh.refresh_from_db(); other.refresh_from_db(); ready.refresh_from_db()
        progressing.refresh_from_db()
        self.assertEqual((stale.state, fresh.state, ready.state, other.state, progressing.state),
                         (stale.State.FAILED, fresh.State.PREPARING, ready.State.READY, other.State.PREPARING,
                          progressing.State.PREPARING))
        self.assertEqual(reconcile_jobs_task()["customer_exports"], 1)
        other.refresh_from_db()
        self.assertEqual(other.state, other.State.FAILED)
        self.assertEqual(recover_stale_customer_snapshots(now=now), 0)
        OrganizationCustomerExport.objects.filter(pk=progressing.pk).update(
            last_progress_at=now - timedelta(minutes=16))
        self.assertEqual(recover_stale_customer_snapshots(now=now), 1)
        progressing.refresh_from_db()
        self.assertEqual(progressing.state, progressing.State.FAILED)

    def test_reservation_dispatch_is_once_and_revocation_blocks_worker_storage(self):
        client = Client()
        client.force_login(self.owner)
        path = f"/api/organizations/{self.org.pk}/export/snapshots/"
        body = json.dumps({"request_key": "9" * 32})
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async",
                   side_effect=OperationalError("broker unavailable")) as dispatch:
            first = client.post(path, body, content_type="application/json")
            repeated = client.post(path, body, content_type="application/json")
        self.assertEqual((first.status_code, repeated.status_code), (202, 202))
        self.assertEqual(first.json(), repeated.json())
        dispatch.assert_called_once_with(args=[first.json()["snapshot_id"]], queue="audit",
                                         task_id=f'customer-export-{first.json()["snapshot_id"]}', retry=False)
        snapshot = OrganizationCustomerExport.objects.get(pk=first.json()["snapshot_id"])
        self.assertEqual(snapshot.state, snapshot.State.PREPARING)
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role=MembershipRole.VIEWER)
        with patch("tenancy.customer_snapshot.save_private_artifact",
                   side_effect=AssertionError("No revoked owner's data may be copied")):
            self.assertFalse(capture_reserved_customer_snapshot(snapshot.pk))
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.state, snapshot.State.FAILED)
        self.assertFalse(snapshot.parts.exists())
        self.assertFalse(capture_reserved_customer_snapshot(snapshot.pk))

    def test_storage_acknowledgement_without_matching_bytes_never_makes_a_ready_manifest(self):
        client = Client()
        client.force_login(self.owner)
        path = f"/api/organizations/{self.org.pk}/export/snapshots/"
        response = client.post(path, json.dumps({"request_key": "8" * 32}), content_type="application/json")
        self.assertEqual(response.status_code, 202)
        snapshot_id = response.json()["snapshot_id"]
        with patch("tenancy.customer_snapshot.read_private_artifact", return_value=b"truncated"):
            self.assertFalse(capture_reserved_customer_snapshot(snapshot_id))
        snapshot = OrganizationCustomerExport.objects.get(pk=snapshot_id)
        self.assertEqual(snapshot.state, snapshot.State.FAILED)
        self.assertEqual(snapshot.parts.count(), 1)
        self.assertEqual(client.get(f"{path}{snapshot_id}/").status_code, 404)
        self.assertIsNone(client.get(path).json()["snapshots"][0]["manifest_path"])
        self.assertEqual(client.post(f"{path}{snapshot_id}/discard/", "{}", content_type="application/json").status_code,
                         200)
        self.assertFalse(OrganizationCustomerExport.objects.filter(pk=snapshot_id).exists())

    def test_closure_after_queue_reservation_blocks_worker_before_any_copy(self):
        client = Client()
        client.force_login(self.owner)
        response = client.post(f"/api/organizations/{self.org.pk}/export/snapshots/",
                               json.dumps({"request_key": "7" * 32}), content_type="application/json")
        self.assertEqual(response.status_code, 202)
        snapshot_id = response.json()["snapshot_id"]
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        with patch("tenancy.customer_snapshot.save_private_artifact",
                   side_effect=AssertionError("Closure must deny every late export write")):
            self.assertFalse(capture_reserved_customer_snapshot(snapshot_id))
        snapshot = OrganizationCustomerExport.objects.get(pk=snapshot_id)
        self.assertEqual(snapshot.state, snapshot.State.FAILED)
        self.assertFalse(snapshot.parts.exists())
        self.assertEqual(client.get(f"/api/organizations/{self.org.pk}/export/snapshots/{snapshot_id}/").status_code, 404)


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "application/zip"}))
class CustomerSnapshotClaimTests(TransactionTestCase):
    def test_two_deliveries_cannot_write_the_same_private_part_twice(self):
        owner = get_user_model().objects.create_user("claim-owner@example.invalid", password="test-password")
        EmailAddress.objects.create(user=owner, email=owner.email, primary=True, verified=True)
        org = create_organization(user=owner, name="Claim fixture")
        create_project(organization=org, user=owner, name="Claim project",
                       canonical_origin="https://claim.example.invalid")
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            snapshot = reserve_bounded_customer_snapshot(organization=org, actor=owner, request_key="1" * 32)
        writing, release = Event(), Event()
        original = save_private_artifact
        writes = []

        def pause_first(**kwargs):
            writes.append(kwargs["scope"])
            writing.set()
            if not release.wait(timeout=10):
                raise AssertionError("Worker fixture did not release the first write")
            return original(**kwargs)

        with patch("tenancy.customer_snapshot.save_private_artifact", side_effect=pause_first):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(capture_reserved_customer_snapshot, snapshot.pk)
                self.assertTrue(writing.wait(timeout=10))
                second = pool.submit(capture_reserved_customer_snapshot, snapshot.pk)
                release.set()
                self.assertTrue(first.result(timeout=20))
                self.assertFalse(second.result(timeout=20))
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.state, snapshot.State.READY)
        self.assertEqual(len(writes), 1)
        self.assertEqual(snapshot.parts.count(), 1)
