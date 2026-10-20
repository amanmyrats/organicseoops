from tenancy.customer_artifact_barrier import project_artifact_barrier
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch
from zipfile import ZipFile

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, DatabaseError, transaction
from django.core.cache import cache
from django.core.files.storage import storages
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from kombu.exceptions import OperationalError

from config.artifacts import read_private_artifact, save_private_artifact
from config.test_foundations import TEST_STORAGES
from jobs.models import JobRun, JobStep
from .artifacts import iter_project_artifact_keys, save_project_artifact
from .customer_export import CUSTOMER
from .customer_snapshot import recover_stale_customer_snapshots, reserve_bounded_customer_snapshot
from .customer_source_parts import FORMAT, capture_source_stage, descriptor, encoded
from .models import MembershipRole, OrganizationCustomerExport, OrganizationMembership
from .services import create_organization, create_project


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_MAX_BYTES=100 * 1024 * 1024,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "application/zip"}), DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "source-parts"}})
class CustomerSourcePartTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.tasks.execute_job_task.apply_async", return_value=None)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        capture = patch("tenancy.tasks.capture_customer_snapshot_task.apply_async", return_value=None)
        self.addCleanup(capture.stop)
        capture.start()
        cache.clear()
        self.owner = get_user_model().objects.create_user("source-owner@example.invalid", password="test-password")
        self.other = get_user_model().objects.create_user("source-other@example.invalid", password="test-password")
        for user in (self.owner, self.other):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        self.org = create_organization(user=self.owner, name="Source fixture")
        self.project = create_project(organization=self.org, user=self.owner, name="Source project",
                                      canonical_origin="https://source.example.invalid")
        self.client.force_login(self.owner)

    def reserve(self, key="a"):
        return reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner,
            request_key=key * 32, format=FORMAT)

    def finish(self, snapshot):
        for step in range(1500):
            snapshot.refresh_from_db()
            if snapshot.state != snapshot.State.PREPARING:
                break
            self.assertTrue(capture_source_stage(snapshot.pk, snapshot.progress.get("step", 0)), snapshot.progress)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.state, snapshot.State.READY, snapshot.progress)

    @override_settings(CUSTOMER_EXPORT_COPY_POLICY_REFERENCE="fixture-review", CUSTOMER_EXPORT_COPY_LIFETIME_DAYS=1)
    def test_reviewed_copy_expiry_covers_all_formats_and_denies_read_crossing_deadline(self):
        from .customer_snapshot import capture_reserved_customer_snapshot
        from . import customer_snapshot as reader
        for index, format in enumerate(("bounded-zip-v1", "source-parts-v2", "coherent-parts-v3")):
            with self.subTest(format=format):
                snapshot = reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner,
                    request_key=str(index) * 32, format=format)
                if format == "source-parts-v2":
                    self.finish(snapshot)
                else:
                    self.assertTrue(capture_reserved_customer_snapshot(snapshot.pk))
                snapshot.refresh_from_db()
                expiry = snapshot.completed_at + timedelta(days=1)
                self.assertEqual(snapshot.expires_at, expiry)
                self.assertEqual(snapshot.expiry_policy_reference, "fixture-review")
                path = f"/api/organizations/{self.org.pk}/export/snapshots/{snapshot.pk}/"
                manifest = self.client.get(path)
                self.assertEqual(manifest.status_code, 200, manifest.content[:200])
                self.assertEqual(manifest.json()["expires_at"], expiry.isoformat())
                self.assertFalse(manifest.json()["legal_export_complete"])
                part = manifest.json()["parts"][0]["download_path"]
                self.assertEqual(self.client.get(part).status_code, 200)
                clock = timezone.now()
                original_read = reader.read_private_artifact
                def cross_boundary(key):
                    nonlocal clock
                    data = original_read(key)
                    clock = expiry
                    return data
                with patch("django.utils.timezone.now", side_effect=lambda: clock), \
                        patch.object(reader, "read_private_artifact", side_effect=cross_boundary):
                    self.assertEqual(self.client.get(part).status_code, 404)
                with override_settings(CUSTOMER_EXPORT_COPY_POLICY_REFERENCE="", CUSTOMER_EXPORT_COPY_LIFETIME_DAYS=0), \
                        patch("django.utils.timezone.now", return_value=expiry):
                    self.assertEqual(self.client.get(path).status_code, 404)
                    self.assertEqual(self.client.get(part).status_code, 404)
                    history = self.client.get(f"/api/organizations/{self.org.pk}/export/snapshots/").json()
                    row = next(row for row in history["snapshots"] if row["id"] == snapshot.pk)
                    self.assertEqual(row["state"], "expired")
                    self.assertIsNone(row["manifest_path"])
                    self.assertEqual(row["expires_at"], expiry.isoformat())

    def test_large_rows_and_object_are_checkpointed_verified_and_manifest_is_paged(self):
        job = JobRun.objects.create(organization=self.org, project=self.project, actor=self.owner,
            handler="diagnostic_probe", method_version="diagnostic-v1", input_snapshot={"message": "fixture"})
        JobStep.objects.bulk_create([JobStep(job=job, sequence=index, name="source fixture", status="succeeded",
            output={"api_key": "never-export-this", "text": "observed"}) for index in range(5001)])
        data = b"x" * (35 * 1024 * 1024)
        with project_artifact_barrier(self.project.organization_id, shared=True):
            source_key = save_project_artifact(project=self.project, content=data, content_type="application/json")
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            snapshot = self.reserve()
            self.finish(snapshot)
        self.assertGreater(snapshot.size_bytes, 32 * 1024 * 1024)
        chain = "00" * 32
        rows, object_bytes, completed_tables = [], bytearray(), set()
        for part in snapshot.parts.order_by("position").iterator(chunk_size=20):
            content = read_private_artifact(part.storage_key)
            self.assertEqual(sha256(content).hexdigest(), part.content_sha256)
            self.assertLessEqual(len(content), 8 * 1024 * 1024)
            self.assertNotIn(b"never-export-this", content)
            self.assertNotIn(source_key.encode(), content)
            chain = sha256(bytes.fromhex(chain) + encoded(descriptor(part))).hexdigest()
            with ZipFile(BytesIO(content)) as archive:
                source = json.loads(archive.read("source.json"))
                if source["kind"] == "rows":
                    if source["table_complete"]:
                        completed_tables.add(source["model"])
                    if source["model"] == "jobs.JobStep":
                        page = json.loads(archive.read("data"))
                        self.assertLessEqual(len(page), 50)
                        rows.extend(page)
                if source["kind"] == "artifact_chunk":
                    self.assertEqual(source["offset"], len(object_bytes))
                    object_bytes.extend(archive.read("data"))
                if source["kind"] == "artifact_complete":
                    self.assertEqual(source["sha256"], sha256(data).hexdigest())
        self.assertEqual(len(rows), 5001)
        self.assertEqual(len({row["id"] for row in rows}), 5001)
        self.assertEqual(set(CUSTOMER), completed_tables)
        self.assertEqual(object_bytes, data)
        self.assertEqual(chain, snapshot.content_sha256)
        path = f"/api/organizations/{self.org.pk}/export/snapshots/{snapshot.pk}/"
        positions = []
        next_position = 0
        while next_position is not None:
            response = self.client.get(path, {"position": next_position})
            self.assertEqual(response.status_code, 200, response.content[:200])
            manifest = response.json()
            self.assertEqual(manifest["version"], FORMAT)
            self.assertIn("not_transactional", manifest["scope"])
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertLessEqual(len(manifest["parts"]), 50)
            self.assertNotIn(source_key.encode(), response.content)
            positions.extend(part["position"] for part in manifest["parts"])
            next_position = manifest["next_position"]
        self.assertEqual(positions, list(range(snapshot.parts.count())))
        self.assertEqual(self.client.get(path, {"position": "-1"}).status_code, 400)
        self.assertEqual(self.client.get(path, {"position": ["0", "1"]}).status_code, 400)
        outsider = Client(); outsider.force_login(self.other)
        self.assertEqual(outsider.get(path).status_code, 404)
        first = self.client.get(f"{path}parts/0/")
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first["Content-Disposition"].endswith('.zip"'))

    def test_only_committed_stage_recovery_replays_and_revocation_denies_next_write(self):
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async", side_effect=OperationalError("fixture")):
            snapshot = self.reserve()
            self.assertTrue(capture_source_stage(snapshot.pk, 0))
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.progress["step"], 1)
        self.assertFalse(snapshot.progress["in_flight"])
        count = snapshot.parts.count()
        self.assertFalse(capture_source_stage(snapshot.pk, 0))
        self.assertEqual(snapshot.parts.count(), count)
        old = timezone.now() - timedelta(minutes=16)
        OrganizationCustomerExport.objects.filter(pk=snapshot.pk).update(last_progress_at=old)
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async") as dispatch:
            self.assertEqual(recover_stale_customer_snapshots(), 1)
        dispatch.assert_called_once_with(args=[snapshot.pk, 1], queue="audit",
                                         task_id=f"customer-export-{snapshot.pk}-1", retry=False)
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role=MembershipRole.VIEWER)
        with patch("tenancy.customer_source_parts.save_private_artifact", side_effect=AssertionError("revoked")):
            self.assertFalse(capture_source_stage(snapshot.pk, 1))
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.state, snapshot.State.FAILED)
        self.assertEqual(snapshot.parts.count(), count)

    def test_unknown_write_and_truncated_readback_never_resume_or_expose_ready(self):
        snapshot = self.reserve()
        with patch("tenancy.customer_source_parts.read_private_artifact", return_value=b"truncated"):
            self.assertFalse(capture_source_stage(snapshot.pk, 0))
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.state, snapshot.State.FAILED)
        self.assertEqual(snapshot.parts.count(), 0)
        self.assertEqual(self.client.get(f"/api/organizations/{self.org.pk}/export/snapshots/{snapshot.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/organizations/{self.org.pk}/export/snapshots/{snapshot.pk}/discard/",
            "{}", content_type="application/json").status_code, 200)
        self.assertFalse(OrganizationCustomerExport.objects.filter(pk=snapshot.pk).exists())
        uncertain = self.reserve("b")
        OrganizationCustomerExport.objects.filter(pk=uncertain.pk).update(
            progress={"step": 0, "in_flight": True}, last_progress_at=timezone.now() - timedelta(minutes=16))
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async") as dispatch:
            self.assertEqual(recover_stale_customer_snapshots(), 1)
        dispatch.assert_not_called()
        uncertain.refresh_from_db()
        self.assertEqual(uncertain.state, uncertain.State.FAILED)
        self.assertFalse(capture_source_stage(uncertain.pk, 0))

    def test_keyset_cursor_has_same_lexical_order_for_nested_local_artifacts(self):
        from config.artifacts import save_private_artifact
        root = f"organizations/{self.org.pk}/projects/{self.project.pk}"
        with project_artifact_barrier(self.org.pk, shared=True):
            keys = [save_private_artifact(scope=scope, content=b"{}", content_type="application/json", key_stem=stem * 32)
                    for scope, stem in [(root, "f"), (root + "/jobs/1", "a"), (root, "0")]]
        self.assertEqual(list(iter_project_artifact_keys(project=self.project)), sorted(keys))
        self.assertEqual(list(iter_project_artifact_keys(project=self.project, after_key=sorted(keys)[1])), sorted(keys)[2:])

    def test_opt_in_api_captures_more_than_thousand_objects_and_keeps_closed_copies_private(self):
        for index in range(1001):
            with project_artifact_barrier(self.project.organization_id, shared=True):
                save_project_artifact(project=self.project, content=b"{}", content_type="application/json",
                                      key_stem=f"{index:032x}")
        path = f"/api/organizations/{self.org.pk}/export/snapshots/"
        body = json.dumps({"request_key": "c" * 32, "format": FORMAT})
        csrf = Client(enforce_csrf_checks=True); csrf.force_login(self.owner)
        self.assertEqual(csrf.post(path, body, content_type="application/json").status_code, 403)
        csrf.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": csrf.cookies["csrftoken"].value}
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            response = csrf.post(path, body, content_type="application/json", **headers)
            self.assertEqual(response.status_code, 202, response.content)
            self.assertEqual(response.json()["format"], FORMAT)
            snapshot = OrganizationCustomerExport.objects.get(pk=response.json()["snapshot_id"])
            self.finish(snapshot)
        self.assertEqual(snapshot.parts.filter(source__kind="artifact_complete").count(), 1001)
        marker = snapshot.parts.get(source__kind="project_artifacts_complete")
        self.assertEqual(marker.source["visible_objects_observed"], 1001)
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role=MembershipRole.VIEWER)
        self.assertEqual(csrf.get(f"{path}{snapshot.pk}/").status_code, 404)
        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role=MembershipRole.OWNER)
        from .models import Organization
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        self.assertEqual(csrf.get(f"{path}{snapshot.pk}/parts/0/").status_code, 404)

    def test_row_inventory_loss_fails_instead_of_completing_a_partial_table(self):
        job = JobRun.objects.create(organization=self.org, project=self.project, actor=self.owner,
            handler="diagnostic_probe", method_version="diagnostic-v1", input_snapshot={"message": "fixture"})
        JobStep.objects.bulk_create([JobStep(job=job, sequence=index, name="source fixture", status="succeeded")
                                    for index in range(51)])
        snapshot = self.reserve()
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            while not snapshot.parts.filter(source__model="jobs.JobStep").exists():
                self.assertTrue(capture_source_stage(snapshot.pk, snapshot.progress.get("step", 0)))
                snapshot.refresh_from_db()
            JobStep.objects.filter(job=job).order_by("pk").last().delete()
            self.assertFalse(capture_source_stage(snapshot.pk, snapshot.progress["step"]))
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.state, snapshot.State.FAILED)
        self.assertFalse(snapshot.parts.filter(source__model="jobs.JobStep", source__table_complete=True).exists())


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "application/zip"}))
class SourceStageClaimTests(TransactionTestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("source-claim@example.invalid", password="test-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, primary=True, verified=True)
        self.org = create_organization(user=self.owner, name="Source claim fixture")

    def clear_joined_fixture_mutations(self):
        from .models import ProjectArtifactMutation, ProjectArtifactMutationAttempt
        attempts = ProjectArtifactMutationAttempt.objects.filter(organization=self.org)
        self.assertFalse(ProjectArtifactMutation.objects.filter(attempt__in=attempts, settled_at__isnull=True).exists())
        ProjectArtifactMutation.objects.filter(attempt__in=attempts).delete()
        attempts.delete()  # Only used after these synthetic writers exited/joined; no production reconciler.

    def test_coherent_consumer_persists_original_view_bounded_parts_and_private_chain(self):
        from .customer_coherent_parts import FORMAT as coherent_format, CONSISTENCY
        from .customer_coherent_snapshot import capture_coherent_customer_snapshot, current_coherent_customer_snapshot
        from .customer_snapshot import capture_reserved_customer_snapshot, current_customer_snapshot
        from . import customer_source_parts as parts
        project = create_project(organization=self.org, user=self.owner, name="Original project",
                                 canonical_origin="https://consumer.example.invalid")
        job = JobRun.objects.create(organization=self.org, project=project, actor=self.owner,
            handler="diagnostic_probe", method_version="diagnostic-v1", input_snapshot={"message": "fixture"})
        JobStep.objects.bulk_create([JobStep(job=job, sequence=index, name="Paged capture", status="succeeded")
                                    for index in range(2501)])
        data = b"x" * (parts.PART_BYTES + 123)
        with project_artifact_barrier(self.org.pk, shared=True):
            save_project_artifact(project=project, content=data, content_type="application/json")
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        client.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        url = f"/api/organizations/{self.org.pk}/export/snapshots/"
        request_body = json.dumps({"request_key": "c" * 32, "format": coherent_format})
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async") as dispatched:
            response = client.post(url, request_body, content_type="application/json", **headers)
            self.assertEqual(response.status_code, 202)
            snapshot = OrganizationCustomerExport.objects.get(pk=response.json()["snapshot_id"])
            self.assertEqual(response.json()["format"], coherent_format)
            self.assertEqual(response.json()["scope"], "coherent_customer_content_only")
            self.assertEqual(reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner,
                request_key="c" * 32, format=coherent_format).pk, snapshot.pk)
        dispatched.assert_called_once_with(args=[snapshot.pk], queue="audit",
            task_id=f"customer-export-{snapshot.pk}", retry=False)
        from .tasks import capture_customer_snapshot_task
        self.assertFalse(capture_customer_snapshot_task.run(snapshot.pk, stage=0))
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.progress, {})
        self.assertIsNone(snapshot.last_progress_at)
        original_store = parts._store
        observed = []
        def store(*args, **kwargs):
            def committed_claim():
                close_old_connections()
                try:
                    row = OrganizationCustomerExport.objects.get(pk=snapshot.pk)
                    return row.progress, row.last_progress_at
                finally:
                    connection.close()
            with ThreadPoolExecutor(max_workers=1) as pool:
                progress, heartbeat = pool.submit(committed_claim).result(timeout=10)
            self.assertTrue(progress["in_flight"])
            self.assertTrue(progress["write_in_flight"])
            self.assertTrue(progress["intended_key"].startswith(f"organizations/{self.org.pk}/exports/{snapshot.pk}/"))
            self.assertEqual(progress["parts"], len(observed))
            self.assertIsNotNone(heartbeat)
            observed.append(heartbeat)
            if len(observed) == 1:
                type(project).objects.filter(pk=project.pk).update(name="Later project")
            return original_store(*args, **kwargs)
        with patch("tenancy.customer_coherent_snapshot._store", side_effect=store):
            from .tasks import capture_customer_snapshot_task
            self.assertTrue(capture_customer_snapshot_task.run(snapshot.pk))
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.state, snapshot.State.READY)
        self.assertFalse(snapshot.progress["in_flight"])
        chain, size, objects, projects = "00" * 32, 0, [], []
        for part in snapshot.parts.order_by("position"):
            content = read_private_artifact(part.storage_key)
            self.assertEqual(sha256(content).hexdigest(), part.content_sha256)
            self.assertLessEqual(len(content), 8 * 1024 * 1024)
            with ZipFile(BytesIO(content)) as archive:
                source = json.loads(archive.read("source.json"))
                self.assertEqual(source["version"], coherent_format)
                self.assertEqual(source["consistency"], CONSISTENCY)
                self.assertEqual(source["logfile_window"], snapshot.progress["logfile_window"])
                if source.get("model") == "tenancy.Project":
                    projects.extend(json.loads(archive.read("data")))
                if source["kind"] == "artifact_chunk":
                    objects.append(archive.read("data"))
            chain = sha256(bytes.fromhex(chain) + encoded(descriptor(part))).hexdigest()
            size += len(content)
        self.assertEqual(b"".join(objects), data)
        self.assertEqual(projects[0]["name"], "Original project")
        self.assertEqual((chain, size), (snapshot.content_sha256, snapshot.size_bytes))
        self.assertEqual(observed, sorted(observed))
        self.assertEqual(current_coherent_customer_snapshot(organization=self.org, actor=self.owner,
            snapshot_id=snapshot.pk).pk, snapshot.pk)
        from .customer_coherent_snapshot import private_coherent_snapshot_part
        first = snapshot.parts.order_by("position").first()
        self.assertEqual(private_coherent_snapshot_part(organization=self.org, actor=self.owner,
            snapshot_id=snapshot.pk, position=0), (read_private_artifact(first.storage_key), first.content_sha256))
        self.assertFalse(capture_coherent_customer_snapshot(snapshot.pk))
        self.assertFalse(capture_reserved_customer_snapshot(snapshot.pk))
        self.assertFalse(capture_customer_snapshot_task.run(snapshot.pk, stage=0))
        self.assertEqual(current_customer_snapshot(organization=self.org, actor=self.owner,
            snapshot_id=snapshot.pk).pk, snapshot.pk)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner,
                request_key="c" * 32, format="bounded-zip-v1")
        self.assertEqual(client.post(url, request_body, content_type="application/json", **headers).status_code, 200)
        history = client.get(f"/api/organizations/{self.org.pk}/export/snapshots/")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["snapshots"][0]["format"], coherent_format)
        path = f"/api/organizations/{self.org.pk}/export/snapshots/{snapshot.pk}/"
        positions, position = [], 0
        while position is not None:
            response = client.get(path, {"position": position})
            self.assertEqual(response.status_code, 200)
            page = response.json()
            self.assertEqual(page["version"], coherent_format)
            self.assertEqual(page["consistency"], CONSISTENCY)
            self.assertEqual(page["scope"], "coherent_customer_content_only")
            self.assertEqual(page["sha256"], chain)
            self.assertNotIn("storage_key", response.content.decode())
            self.assertLessEqual(len(page["parts"]), 50)
            positions.extend(part["position"] for part in page["parts"])
            position = page["next_position"]
        self.assertGreater(len(positions), 50)
        self.assertEqual(positions, list(range(snapshot.parts.count())))
        self.assertEqual(client.get(path + "?position=0&position=1").status_code, 400)
        delivered = client.get(path + "parts/0/")
        self.assertEqual(delivered.status_code, 200)
        self.assertTrue(delivered["Content-Disposition"].endswith('.zip"'))
        self.assertEqual(delivered.content, read_private_artifact(first.storage_key))
        self.assertEqual(delivered["Cache-Control"], "private, no-store")
        with self.assertRaises(ValidationError):
            reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner,
                request_key="e" * 32, format="future-parts")
        self.assertFalse(capture_customer_snapshot_task.run(snapshot.pk + 1000))
        part = snapshot.parts.first()
        type(part).objects.filter(pk=part.pk).update(source={**part.source, "kind": "tampered"})
        from config.artifacts import ArtifactStorageError
        with self.assertRaises(ArtifactStorageError):
            current_coherent_customer_snapshot(organization=self.org, actor=self.owner, snapshot_id=snapshot.pk)
        self.assertEqual(client.get(path).status_code, 503)

    def test_coherent_consumer_claim_is_committed_and_duplicate_delivery_cannot_take_ownership(self):
        from contextlib import contextmanager
        from . import customer_coherent_snapshot as consumer
        from .customer_coherent_parts import FORMAT as coherent_format
        snapshot = OrganizationCustomerExport.objects.create(organization=self.org, actor=self.owner,
            request_key="c" * 32, format=coherent_format)
        original = consumer.coherent_customer_content
        admitted, release = Event(), Event()
        @contextmanager
        def pause(*args, **kwargs):
            with original(*args, **kwargs) as payload:
                admitted.set()
                if not release.wait(10):
                    raise AssertionError("Coherent consumer fixture did not release admission")
                yield payload
        def capture():
            close_old_connections()
            try:
                return consumer.capture_coherent_customer_snapshot(snapshot.pk)
            finally:
                connection.close()
        with patch.object(consumer, "coherent_customer_content", side_effect=pause), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(capture)
            try:
                self.assertTrue(admitted.wait(10))
                claimed = OrganizationCustomerExport.objects.get(pk=snapshot.pk)
                self.assertTrue(claimed.progress["in_flight"])
                self.assertIsNotNone(claimed.last_progress_at)
                self.assertFalse(pool.submit(capture).result(timeout=10))
                snapshot.refresh_from_db()
                self.assertEqual(snapshot.progress, claimed.progress)
                self.assertEqual(snapshot.last_progress_at, claimed.last_progress_at)
            finally:
                release.set()
            self.assertTrue(first.result(timeout=20))
        with transaction.atomic(), self.assertRaises(RuntimeError):
            consumer.capture_coherent_customer_snapshot(snapshot.pk)

    def test_coherent_consumer_unknown_write_and_stale_recovery_preserve_cleanup_scope(self):
        from . import customer_coherent_snapshot as consumer
        from . import customer_coherent_parts as coherent
        from .customer_snapshot import discard_failed_customer_snapshot
        from .artifacts import (delete_closed_organization_export_batch, delete_failed_organization_export_batch,
                                organization_export_versions_remain)
        from .models import Organization
        from config.artifacts import ArtifactStorageError
        for boundary in ("unknown_write", "stale_between_parts", "never_started"):
            with self.subTest(boundary=boundary):
                snapshot = OrganizationCustomerExport.objects.create(organization=self.org, actor=self.owner,
                    request_key=boundary, format=coherent.FORMAT)
                if boundary == "unknown_write":
                    def unknown(**kwargs):
                        save_private_artifact(**kwargs)
                        raise ArtifactStorageError("Unknown acknowledged write")
                    with patch("tenancy.customer_source_parts.save_private_artifact", side_effect=unknown):
                        self.assertFalse(consumer.capture_coherent_customer_snapshot(snapshot.pk))
                elif boundary == "stale_between_parts":
                    original = coherent._coherent_content_pages
                    def expire(*args):
                        with closing(original(*args)) as pages:
                            yield next(pages)
                            self.assertEqual(recover_stale_customer_snapshots(now=timezone.now() + timedelta(minutes=16)), 1)
                            yield next(pages)
                    with patch.object(coherent, "_coherent_content_pages", side_effect=expire):
                        self.assertFalse(consumer.capture_coherent_customer_snapshot(snapshot.pk))
                    self.assertEqual(snapshot.parts.count(), 1)
                else:
                    OrganizationCustomerExport.objects.filter(pk=snapshot.pk).update(
                        created_at=timezone.now() - timedelta(minutes=16))
                    self.assertEqual(recover_stale_customer_snapshots(), 1)
                snapshot.refresh_from_db()
                self.assertEqual(snapshot.state, snapshot.State.FAILED)
                with patch.object(consumer, "_store", side_effect=AssertionError("Lost view cannot replay")):
                    self.assertFalse(consumer.capture_coherent_customer_snapshot(snapshot.pk))
                if boundary == "unknown_write":
                    self.assertTrue(snapshot.progress["in_flight"])
                    for cleanup in (discard_failed_customer_snapshot, delete_failed_organization_export_batch):
                        with self.assertRaises(PermissionDenied):
                            cleanup(organization=self.org, actor=self.owner, snapshot_id=snapshot.pk)
                    scope = f"organizations/{self.org.pk}/exports/{snapshot.pk}"
                    storage = storages["artifacts"]
                    for name in storage.listdir(scope)[1]:
                        storage.delete(f"{scope}/{name}")
                    self.assertEqual(storage.listdir(scope)[1], [])
                elif boundary == "never_started":
                    self.assertEqual(discard_failed_customer_snapshot(organization=self.org, actor=self.owner,
                        snapshot_id=snapshot.pk), ("discarded", 0))
                else:
                    self.assertFalse(snapshot.progress["in_flight"])
                    self.assertEqual(discard_failed_customer_snapshot(organization=self.org, actor=self.owner,
                        snapshot_id=snapshot.pk), ("discarded", 1))
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        self.assertTrue(organization_export_versions_remain(organization=self.org))
        with self.assertRaises(ArtifactStorageError):
            delete_closed_organization_export_batch(organization=self.org)

    def test_coherent_consumer_final_readback_rejects_tamper_expiry_and_original_session_loss(self):
        from . import customer_coherent_snapshot as consumer
        from . import customer_coherent_parts as coherent
        for boundary in ("tamper", "expiry", "session_loss", "revocation"):
            with self.subTest(boundary=boundary):
                snapshot = OrganizationCustomerExport.objects.create(organization=self.org, actor=self.owner,
                    request_key=boundary, format=coherent.FORMAT)
                original = consumer.read_private_artifact
                lost = []
                def read(key):
                    data = original(key)
                    if not lost:
                        lost.append(True)
                        if boundary == "session_loss":
                            with connection.cursor() as cursor:
                                cursor.execute("SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted "
                                    "AND mode = 'ExclusiveLock' AND objsubid = 2 AND classid = 0 AND objid = %s "
                                    "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())", [self.org.pk])
                                pid, = cursor.fetchone()
                                cursor.execute("SELECT pg_terminate_backend(%s)", [pid])
                                self.assertTrue(cursor.fetchone()[0])
                        if boundary == "expiry":
                            clock.return_value = coherent.CONTENT_LIFETIME_SECONDS + 1
                        if boundary == "revocation":
                            def revoke():
                                close_old_connections()
                                try:
                                    from .models import Organization
                                    with transaction.atomic():
                                        Organization.objects.select_for_update().get(pk=self.org.pk)
                                        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
                                finally:
                                    connection.close()
                            with ThreadPoolExecutor(max_workers=1) as pool:
                                pool.submit(revoke).result(timeout=10)
                    return data[:-1] if boundary == "tamper" else data
                with patch.object(coherent, "monotonic", return_value=0) as clock, \
                        patch.object(consumer, "read_private_artifact", side_effect=read):
                    self.assertFalse(consumer.capture_coherent_customer_snapshot(snapshot.pk))
                snapshot.refresh_from_db()
                self.assertEqual(snapshot.state, snapshot.State.FAILED)
                self.assertIsNone(snapshot.completed_at)
                self.assertFalse(snapshot.progress["in_flight"])
                self.assertTrue(snapshot.parts.exists())
                self.assertTrue(lost)
                if boundary == "revocation":
                    OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="owner")

    def test_coherent_consumer_binds_original_logfile_lineage_at_parts_and_delivery(self):
        from jobs.test_bot_log_import import BotLogImportTests
        from jobs.bot_log_import import source_current
        from . import customer_coherent_snapshot as consumer
        from .customer_coherent_parts import FORMAT as coherent_format
        BotLogImportTests.setUp(self)
        job = BotLogImportTests.queue(self)
        other = get_user_model().objects.create_user("coherent-reader@example.invalid", password="test-password")
        EmailAddress.objects.create(user=other, email=other.email, primary=True, verified=True)
        OrganizationMembership.objects.create(organization=self.org, user=other, role="owner")
        for boundary in ("replacement_before_commit", "ready_download"):
            snapshot = OrganizationCustomerExport.objects.create(organization=self.org, actor=self.owner,
                request_key=boundary, format=coherent_format)
            if boundary == "replacement_before_commit":
                original = consumer._store
                def replace(*args, **kwargs):
                    result = original(*args, **kwargs)
                    JobRun.objects.filter(pk=job.pk).update(actor=other)
                    self.assertTrue(source_current(JobRun.objects.get(pk=job.pk)))
                    return result
                with patch.object(consumer, "_store", side_effect=replace):
                    self.assertFalse(consumer.capture_coherent_customer_snapshot(snapshot.pk))
                self.assertFalse(snapshot.parts.exists())
                JobRun.objects.filter(pk=job.pk).update(actor=self.owner)
            else:
                self.assertTrue(consumer.capture_coherent_customer_snapshot(snapshot.pk))
                self.assertEqual(consumer.current_coherent_customer_snapshot(organization=self.org, actor=other,
                    snapshot_id=snapshot.pk).pk, snapshot.pk)
                client = Client()
                client.force_login(other)
                path = f"/api/organizations/{self.org.pk}/export/snapshots/{snapshot.pk}/"
                self.assertEqual(client.get(path).status_code, 200)
                from . import customer_snapshot as bounded
                original_read = bounded.read_private_artifact
                def revoke_after_read(key):
                    data = original_read(key)
                    JobRun.objects.filter(pk=job.pk).update(actor=other)
                    return data
                with patch.object(bounded, "read_private_artifact", side_effect=revoke_after_read), self.assertRaises(PermissionDenied):
                    consumer.private_coherent_snapshot_part(organization=self.org, actor=other,
                        snapshot_id=snapshot.pk, position=0)
                with patch.object(bounded, "read_private_artifact", side_effect=revoke_after_read):
                    self.assertEqual(client.get(path + "parts/0/").status_code, 404)
                self.assertEqual(JobRun.objects.get(pk=job.pk).actor_id, self.owner.pk)  # Denial rolls back read audit/mutation.
                for loss in ("replacement", "owner", "removal"):
                    if loss == "replacement":
                        JobRun.objects.filter(pk=job.pk).update(actor=other)
                        self.assertTrue(source_current(JobRun.objects.get(pk=job.pk)))
                    elif loss == "owner":
                        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
                    else:
                        job.usage.delete()
                        JobRun.objects.filter(pk=job.pk).delete()
                    with self.assertRaises(PermissionDenied):
                        consumer.current_coherent_customer_snapshot(organization=self.org, actor=other,
                            snapshot_id=snapshot.pk)
                    self.assertEqual(client.get(path).status_code, 404)
                    self.assertEqual(client.get(path + "parts/0/").status_code, 404)
                    if loss == "replacement":
                        JobRun.objects.filter(pk=job.pk).update(actor=self.owner)
                    elif loss == "owner":
                        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="owner")

    def test_coherent_objects_share_row_admission_and_close_on_revocation_expiry_or_session_loss(self):
        from tempfile import TemporaryDirectory
        from config.artifacts import ArtifactStorageError
        from . import customer_coherent_parts as coherent
        from .customer_source_parts import PART_BYTES
        root = TemporaryDirectory()
        self.addCleanup(root.cleanup)
        filesystem = self.settings(STORAGES={**TEST_STORAGES, "artifacts": {
            "BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": root.name}}})
        filesystem.enable()
        self.addCleanup(filesystem.disable)  # InMemoryStorage.close is a no-op; exercise real handle cleanup.
        project = create_project(organization=self.org, user=self.owner, name="Coherent object fixture",
                                 canonical_origin="https://coherent-object.example.invalid")
        data = b"a" * (PART_BYTES + 100)
        with project_artifact_barrier(self.org.pk, shared=True):
            save_project_artifact(project=project, content=data, content_type="application/json")
        foreign_actor = get_user_model().objects.create_user("foreign-object@example.invalid", password="test-password")
        EmailAddress.objects.create(user=foreign_actor, email=foreign_actor.email, primary=True, verified=True)
        foreign_org = create_organization(user=foreign_actor, name="Foreign coherent object")
        foreign_project = create_project(organization=foreign_org, user=foreign_actor, name="Foreign project",
                                         canonical_origin="https://foreign-object.example.invalid")
        with project_artifact_barrier(foreign_org.pk, shared=True):
            foreign_key = save_project_artifact(project=foreign_project, content=b"foreign", content_type="application/json")
        def writer():
            close_old_connections()
            try:
                with project_artifact_barrier(self.org.pk, shared=True, timeout_ms=10000):
                    return save_project_artifact(project=project, content=b"late", content_type="application/json")
            finally:
                close_old_connections()
        with closing(coherent.coherent_customer_content_pages(organization_id=self.org.pk, actor_id=self.owner.pk)) as pages:
            first = next(pages)
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(writer)
                try:
                    self.wait_for_artifact_admission()
                    captured = [first, *pages]
                finally:
                    pages.close()
                late_key = pending.result(timeout=10)
        chunks = [(body, source) for body, source in captured if source["kind"] == "artifact_chunk"]
        self.assertEqual(b"".join(body for body, source in chunks), data)
        self.assertEqual([source["offset"] for body, source in chunks], [0, PART_BYTES])
        self.assertTrue(all(len(body) <= PART_BYTES and source["project_id"] == project.pk for body, source in chunks))
        complete = [source for body, source in captured if source["kind"] == "artifact_complete"]
        self.assertEqual([(source["size_bytes"], source["sha256"]) for source in complete], [(len(data), sha256(data).hexdigest())])
        self.assertEqual([source["visible_objects_observed"] for body, source in captured
                          if source["kind"] == "project_artifacts_complete"], [1])
        self.assertEqual(read_private_artifact(late_key), b"late")
        self.assertEqual(read_private_artifact(foreign_key), b"foreign")

        storage = storages["artifacts"]
        original_open = storage.open
        for failure in ("revoked", "expired", "terminated"):
            opened = []
            def open_source(*args, **kwargs):
                file = original_open(*args, **kwargs)
                opened.append(file)
                return file
            with self.subTest(failure=failure), patch.object(storage, "open", side_effect=open_source), \
                    closing(coherent.coherent_customer_content_pages(organization_id=self.org.pk, actor_id=self.owner.pk)) as pages:
                while next(pages)[1]["kind"] != "artifact_chunk":
                    pass
                self.assertEqual(len(opened), 1)
                if failure == "revoked":
                    OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
                    with self.assertRaises(PermissionDenied):
                        next(pages)
                    OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="owner")
                elif failure == "expired":
                    with patch.object(coherent, "monotonic", return_value=monotonic() + coherent.CONTENT_LIFETIME_SECONDS + 1), \
                            self.assertRaisesRegex(ArtifactStorageError, "expired"):
                        next(pages)
                else:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted "
                            "AND mode = 'ExclusiveLock' AND objsubid = 2 AND classid = 0 AND objid = %s "
                            "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())", [self.org.pk])
                        pid, = cursor.fetchone()
                        cursor.execute("SELECT pg_terminate_backend(%s)", [pid])
                        self.assertTrue(cursor.fetchone()[0])
                    with self.assertRaisesRegex(ArtifactStorageError, "admission was lost"):
                        next(pages)
                self.assertTrue(opened[0].closed)
        self.assertTrue(list(coherent.coherent_customer_content_pages(organization_id=self.org.pk, actor_id=self.owner.pk)))

    def wait_for_artifact_admission(self):
        deadline = monotonic() + 10
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype = 'advisory' "
                    "AND NOT granted AND objsubid = 2 AND classid = 0 AND objid = %s "
                    "AND database = (SELECT oid FROM pg_database WHERE datname = current_database()))", [self.org.pk])
                if cursor.fetchone()[0]:
                    return
            sleep(0.01)
        self.fail("Artifact admission fixture did not reach the actual PostgreSQL wait")

    def test_inflight_storage_loss_durably_blocks_capture_even_after_request_returns(self):
        from config.artifacts import ArtifactStorageError
        from .artifacts import delete_project_artifact, project_artifact_scope, _delete_scope_batch
        from .customer_coherent_parts import coherent_customer_row_pages
        from .models import Organization, ProjectArtifactMutationAttempt, ProjectArtifactMutation
        from types import SimpleNamespace
        from unittest.mock import Mock
        project = create_project(organization=self.org, user=self.owner, name="Inflight fixture",
                                 canonical_origin="https://inflight.example.invalid")
        storage = storages["artifacts"]
        with project_artifact_barrier(self.org.pk, shared=True):
            key = save_project_artifact(project=project, content=b"{}", content_type="application/json")
        other = Organization.objects.create(name="Independent inflight fixture")
        for operation in ("save", "delete", "delete_version"):
            with self.subTest(operation=operation):
                started, release = Event(), Event()
                pid, requested_keys = [], []
                client = Mock()
                client.get_paginator.return_value.paginate.return_value = iter([
                    {"Versions": [{"Key": key, "VersionId": "exact-fixture-version"}]}])
                s3 = SimpleNamespace(bucket_name="fixture", location="", _normalize_name=lambda value: value,
                    connection=SimpleNamespace(meta=SimpleNamespace(client=client)))
                def inflight(*args, **kwargs):
                    requested_keys.append(args[0] if operation in {"save", "delete"} else kwargs["Key"])
                    started.set()
                    if not release.wait(timeout=15):
                        raise AssertionError("Inflight fixture did not release")
                    return key if operation == "save" else None
                def writer():
                    close_old_connections()
                    try:
                        with project_artifact_barrier(self.org.pk, shared=True) as owner:
                            with owner.cursor() as cursor:
                                cursor.execute("SELECT pg_backend_pid()")
                                pid.append(cursor.fetchone()[0])
                            with transaction.atomic():
                                Organization.objects.filter(pk=self.org.pk).update(name="Rolled back inflight")
                                if operation == "save":
                                    with patch.object(storage, "save", side_effect=inflight):
                                        save_project_artifact(project=project, content=b"{}", content_type="application/json")
                                elif operation == "delete":
                                    with patch.object(storage, "delete", side_effect=inflight):
                                        delete_project_artifact(project=project, key=key)
                                else:
                                    client.delete_object.side_effect = inflight
                                    _delete_scope_batch(scope=project_artifact_scope(project), limit=1, storage=s3)
                    finally:
                        close_old_connections()
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(writer)
                    try:
                        self.assertTrue(started.wait(timeout=10))
                        attempt = ProjectArtifactMutationAttempt.objects.get(organization=self.org)
                        mutation = attempt.mutations.get()
                        self.assertEqual((mutation.project_id, mutation.operation, mutation.storage_key),
                                         (project.pk, operation, requested_keys[0]))
                        self.assertTrue(mutation.storage_key.startswith(project_artifact_scope(project) + "/"))
                        self.assertEqual(mutation.version_id, "exact-fixture-version" if operation == "delete_version" else "")
                        self.assertIsNone(mutation.settled_at)
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT pg_terminate_backend(%s)", [pid[0]])
                            self.assertTrue(cursor.fetchone()[0])
                        with self.assertRaisesRegex(ArtifactStorageError, "mutation is unresolved"):
                            next(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
                        with project_artifact_barrier(other.pk, shared=False, timeout_ms=1000):
                            pass
                    finally:
                        release.set()
                    with self.assertRaisesRegex(ArtifactStorageError, "admission was lost"):
                        pending.result(timeout=10)
                self.org.refresh_from_db()
                self.assertEqual(self.org.name, "Source claim fixture")
                mutation.refresh_from_db()
                self.assertIsNone(mutation.settled_at)
                self.assertTrue(ProjectArtifactMutationAttempt.objects.filter(pk=attempt.pk).exists())
                with self.assertRaisesRegex(ArtifactStorageError, "mutation is unresolved"):
                    next(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
                # Only this terminated, joined synthetic fixture is removed; production has no age cleanup.
                ProjectArtifactMutation.objects.filter(attempt=attempt).delete()
                attempt.delete()

    def test_mutation_attempt_settles_after_nested_owning_commit_and_retains_caught_unknown(self):
        from config.artifacts import ArtifactStorageError, delete_private_artifact
        from .customer_coherent_parts import coherent_customer_row_pages
        from .models import ProjectArtifactMutationAttempt
        project = create_project(organization=self.org, user=self.owner, name="Settlement fixture",
                                 canonical_origin="https://settlement.example.invalid")
        storage = storages["artifacts"]
        committed = []
        with project_artifact_barrier(self.org.pk, shared=True):
            with transaction.atomic():
                with project_artifact_barrier(self.org.pk, shared=True):
                    key = save_project_artifact(project=project, content=b"{}", content_type="application/json")
                def on_commit():
                    self.assertEqual(ProjectArtifactMutationAttempt.objects.filter(organization=self.org).count(), 1)
                    delete_private_artifact(key)
                    committed.append(True)
                transaction.on_commit(on_commit)
                self.assertEqual(ProjectArtifactMutationAttempt.objects.filter(organization=self.org).count(), 1)
            self.assertEqual(committed, [True])
            self.assertTrue(ProjectArtifactMutationAttempt.objects.filter(organization=self.org).exists())
        self.assertFalse(ProjectArtifactMutationAttempt.objects.filter(organization=self.org).exists())
        self.assertTrue(list(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk)))
        real_save, renamed = storage.save, []
        def rename(key, file):
            renamed.append(key[:-5] + "_fixture.json")
            return real_save(renamed[-1], file)
        with project_artifact_barrier(self.org.pk, shared=True):
            with patch.object(storage, "save", side_effect=rename), self.assertRaisesRegex(ArtifactStorageError, "collision"):
                save_project_artifact(project=project, content=b"{}", content_type="application/json")
            mutations = ProjectArtifactMutationAttempt.objects.get(organization=self.org).mutations.order_by("created_at")
            self.assertEqual(list(mutations.values_list("operation", flat=True)), ["save", "delete"])
            self.assertEqual(mutations.first().result_key, renamed[0])
            self.assertEqual(mutations.last().storage_key, renamed[0])
            self.assertFalse(mutations.filter(settled_at__isnull=True).exists())
        self.assertFalse(storage.exists(renamed[0]))
        self.assertFalse(ProjectArtifactMutationAttempt.objects.filter(organization=self.org).exists())
        with project_artifact_barrier(self.org.pk, shared=True):
            with patch.object(storage, "save", side_effect=TimeoutError("fixture unknown write")):
                with self.assertRaises(ArtifactStorageError):
                    save_project_artifact(project=project, content=b"{}", content_type="application/json")
        attempt = ProjectArtifactMutationAttempt.objects.get(organization=self.org)
        self.assertIsNone(attempt.mutations.get().settled_at)
        with self.assertRaisesRegex(ArtifactStorageError, "mutation is unresolved"):
            next(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))

    def test_two_connections_cannot_repeat_a_claimed_source_stage(self):
        writing, release = Event(), Event()
        writes = []

        def pause(**kwargs):
            writes.append(kwargs["scope"])
            writing.set()
            if not release.wait(timeout=10):
                raise AssertionError("Source stage fixture did not release write")
            return save_private_artifact(**kwargs)

        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            snapshot = reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner,
                                                         request_key="1" * 32, format=FORMAT)
            with patch("tenancy.customer_source_parts.save_private_artifact", side_effect=pause):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(capture_source_stage, snapshot.pk, 0)
                    self.assertTrue(writing.wait(timeout=10))
                    second = pool.submit(capture_source_stage, snapshot.pk, 0)
                    release.set()
                    self.assertTrue(first.result(timeout=20))
                    self.assertFalse(second.result(timeout=20))
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.state, snapshot.State.PREPARING)
        self.assertEqual(snapshot.progress["step"], 1)
        self.assertEqual(len(writes), 1)
        self.assertEqual(snapshot.parts.count(), 1)

    def test_coherent_pages_keep_original_rows_and_related_reads_across_concurrent_writes(self):
        from .customer_coherent_parts import coherent_customer_row_pages
        project = create_project(organization=self.org, user=self.owner, name="Coherent fixture",
                                 canonical_origin="https://coherent.example.invalid")
        job = JobRun.objects.create(organization=self.org, project=project, actor=self.owner,
            handler="diagnostic_probe", method_version="diagnostic-v1", input_snapshot={"message": "fixture"})
        JobStep.objects.bulk_create([JobStep(job=job, sequence=index, name="original", status="succeeded", output={"text": "original"})
                                    for index in range(51)])
        last_id = job.steps.order_by("pk").last().pk

        def change_content():
            close_old_connections()
            try:
                with transaction.atomic():
                    JobStep.objects.filter(job=job).update(output={"text": "changed"})
                    JobStep.objects.filter(pk=last_id).delete()
                    JobStep.objects.create(job=job, sequence=99, name="late", status="succeeded", output={"text": "late"})
                    JobRun.objects.filter(pk=job.pk).update(output={"text": "changed"})
                    get_user_model().objects.filter(pk=self.owner.pk).update(email="changed@example.invalid")
            finally:
                close_old_connections()

        with closing(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk)) as pages:
            captured = [next(pages)]
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(change_content).result(timeout=10)  # Capture holds no organization write lock.
            captured.extend(pages)
        by_model = {}
        for data, source in captured:
            by_model.setdefault(source["model"], []).extend(json.loads(data))
        steps = by_model["jobs.JobStep"]
        self.assertEqual(len(steps), 51)
        self.assertIn(last_id, [row["id"] for row in steps])
        self.assertEqual({row["output"]["text"] for row in steps}, {"original"})
        self.assertEqual(by_model["jobs.JobRun"][0]["output"], {})
        self.assertEqual(by_model["tenancy.OrganizationMembership"][0]["member_email"], self.owner.email)
        self.assertEqual(job.steps.count(), 51)
        self.assertFalse(job.steps.filter(pk=last_id).exists())

    def test_coherent_pages_observe_fresh_owner_account_closure_and_retention_revocation(self):
        from .customer_coherent_parts import coherent_customer_row_pages
        from .models import Organization, OrganizationTrial
        for boundary in ("role", "account", "closure", "retention"):
            with self.subTest(boundary=boundary):
                with closing(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk)) as pages:
                    next(pages)
                    if boundary == "role":
                        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
                    elif boundary == "account":
                        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
                    elif boundary == "closure":
                        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
                    else:
                        OrganizationTrial.objects.filter(organization=self.org).update(
                            started_at=timezone.now() - timedelta(days=130), ends_at=timezone.now() - timedelta(days=100))
                    with self.assertRaises(PermissionDenied):
                        next(pages)
                OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="owner")
                get_user_model().objects.filter(pk=self.owner.pk).update(is_active=True)
                Organization.objects.filter(pk=self.org.pk).update(is_suspended=False, closed_at=None)

    def test_coherent_source_helpers_keep_content_view_but_fresh_source_loss_denies_completion(self):
        from jobs.test_bot_log_import import BotLogImportTests
        from .customer_coherent_parts import coherent_customer_row_pages
        # Reuse the real crawl/indexation/logfile fixture and source validator.
        BotLogImportTests.setUp(self)
        job = BotLogImportTests.queue(self)
        for boundary in ("revocation", "replacement", "removal"):
            with self.subTest(boundary=boundary):
                with closing(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk)) as pages:
                    next(pages)
                    if boundary == "revocation":
                        self.verification.state = "revoked"
                        self.verification.revoked_at = timezone.now()
                        self.verification.save()
                    elif boundary == "replacement":
                        other = get_user_model().objects.create_user("replacement-source@example.invalid", password="test-password")
                        EmailAddress.objects.create(user=other, email=other.email, primary=True, verified=True)
                        OrganizationMembership.objects.create(organization=self.org, user=other, role="owner")
                        JobRun.objects.filter(pk=job.pk).update(actor=other)
                        from jobs.bot_log_import import source_current
                        self.assertTrue(source_current(JobRun.objects.get(pk=job.pk)))
                    else:
                        job.usage.delete()
                        JobRun.objects.filter(pk=job.pk).delete()
                    captured = []
                    with self.assertRaises(PermissionDenied):
                        while True:
                            captured.append(next(pages))
                row = next(row for data, source in captured if source["model"] == "jobs.JobRun"
                           for row in json.loads(data) if row["id"] == job.pk)
                self.assertTrue(row["source_current"])
                self.assertEqual(row["input_snapshot"], job.input_snapshot)
                if boundary == "revocation":
                    with self.assertRaises(PermissionDenied):
                        next(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
                    type(self.verification).objects.filter(pk=self.verification.pk).update(
                        state="verified", revoked_at=None)
                elif boundary == "replacement":
                    JobRun.objects.filter(pk=job.pk).update(actor=self.owner)

    def test_coherent_reads_reject_shared_transactions_and_accidental_content_writes(self):
        from django.db import DatabaseError
        from .customer_coherent_parts import coherent_customer_row_pages
        with transaction.atomic():
            with self.assertRaises(RuntimeError):
                next(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
        def write_content(*args):
            OrganizationMembership.objects.filter(organization=self.org).update(role="viewer")
        with patch("tenancy.customer_coherent_parts._rows_page", side_effect=write_content):
            with self.assertRaises(DatabaseError):
                next(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
        self.assertEqual(OrganizationMembership.objects.get(organization=self.org).role, "owner")
        with patch("tenancy.customer_coherent_parts.monotonic", return_value=0) as clock:
            with closing(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk)) as pages:
                next(pages)
                clock.return_value = 540
                from config.artifacts import ArtifactStorageError
                with self.assertRaises(ArtifactStorageError):
                    next(pages)
        from .customer_source_parts import _rows_page
        with patch("tenancy.customer_coherent_parts.monotonic", return_value=0) as clock:
            def finish_after_deadline(*args):
                page = _rows_page(*args)
                clock.return_value = 540
                return page
            with patch("tenancy.customer_coherent_parts._rows_page", side_effect=finish_after_deadline):
                with self.assertRaises(ArtifactStorageError):
                    next(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
        from .customer_artifact_barrier import project_artifact_barrier
        def blocked_capture():
            close_old_connections()
            try:
                return list(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
            finally:
                close_old_connections()
        with project_artifact_barrier(self.org.pk, shared=True), \
                patch("tenancy.customer_coherent_parts.CONTENT_LIFETIME_SECONDS", 0.1), \
                patch("tenancy.customer_coherent_parts._current_owner", side_effect=AssertionError("No admitted snapshot")):
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(blocked_capture)
                with self.assertRaisesRegex(ArtifactStorageError, "Artifact admission is unavailable"):
                    pending.result(timeout=5)
        from contextlib import contextmanager
        @contextmanager
        def late_admission(*args, **kwargs):
            with project_artifact_barrier(*args, **kwargs) as owner:
                clock.return_value = 540
                yield owner
        with patch("tenancy.customer_coherent_parts.monotonic", return_value=0) as clock, \
                patch("tenancy.customer_coherent_parts.project_artifact_barrier", side_effect=late_admission), \
                patch("tenancy.customer_coherent_parts._current_owner", side_effect=AssertionError("No expired snapshot")):
            with self.assertRaisesRegex(ArtifactStorageError, "Coherent content capture expired"):
                next(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
        from . import customer_coherent_parts as coherent
        original_owner, original_probe = coherent._current_owner, coherent.require_artifact_admission
        for boundary in ("page", "completion"):
            with self.subTest(late_probe=boundary):
                final_checks = 0
                def owner_check(*args, **kwargs):
                    nonlocal final_checks
                    original_owner(*args, **kwargs)
                    if kwargs.get("check_sources"):
                        final_checks += 1
                def late_probe(*args, **kwargs):
                    result = original_probe(*args, **kwargs)
                    if boundary == "page" or final_checks == 2:
                        clock.return_value = 540
                    return result
                with patch("tenancy.customer_coherent_parts.monotonic", return_value=0) as clock, \
                        patch("tenancy.customer_coherent_parts._current_owner", side_effect=owner_check), \
                        patch("tenancy.customer_coherent_parts.require_artifact_admission", side_effect=late_probe):
                    with self.assertRaisesRegex(ArtifactStorageError, "Coherent content capture expired"):
                        list(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
        # The failed wait releases its connection without stranding the next capture.
        self.assertTrue(list(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk)))
        OrganizationMembership.objects.filter(organization=self.org).update(role="admin")
        self.assertEqual(OrganizationMembership.objects.get(organization=self.org).role, "admin")

    def test_artifact_writer_commit_precedes_capture_snapshot(self):
        from .customer_artifact_barrier import project_artifact_barrier
        from .customer_coherent_parts import coherent_customer_row_pages
        from .models import Organization
        writing, release = Event(), Event()
        def writer():
            close_old_connections()
            try:
                with project_artifact_barrier(self.org.pk, shared=True):
                    with transaction.atomic():
                        Organization.objects.filter(pk=self.org.pk).update(name="Committed writer")
                        writing.set()
                        if not release.wait(timeout=15):
                            raise AssertionError("Artifact writer fixture did not release")
            finally:
                close_old_connections()
        def capture():
            close_old_connections()
            try:
                return list(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(writer)
            try:
                self.assertTrue(writing.wait(timeout=10))
                second = pool.submit(capture)
                self.wait_for_artifact_admission()
            finally:
                release.set()
            first.result(timeout=20)
            captured = second.result(timeout=20)
        organization_rows = [row for data, source in captured if source["model"] == "tenancy.Organization"
                             for row in json.loads(data)]
        self.assertEqual(organization_rows[0]["name"], "Committed writer")

    def test_waiting_artifact_writer_leaves_revocation_and_other_organization_prompt(self):
        from .customer_artifact_barrier import project_artifact_barrier
        from .customer_coherent_parts import coherent_customer_row_pages
        from .models import Organization
        other = Organization.objects.create(pk=2**32 + 2**31 + self.org.pk, name="Independent barrier fixture")
        def writer(organization_id):
            close_old_connections()
            try:
                with project_artifact_barrier(organization_id, shared=True):
                    with transaction.atomic():
                        Organization.objects.filter(pk=organization_id).update(name="Admitted writer")
                return True
            finally:
                close_old_connections()
        with closing(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk)) as pages:
            next(pages)
            with ThreadPoolExecutor(max_workers=2) as pool:
                waiting = pool.submit(writer, self.org.pk)
                try:
                    self.wait_for_artifact_admission()
                    self.assertTrue(pool.submit(writer, other.pk).result(timeout=10))
                    with transaction.atomic():
                        OrganizationMembership.objects.select_for_update().get(organization=self.org, user=self.owner)
                        OrganizationMembership.objects.filter(organization=self.org, user=self.owner).update(role="viewer")
                    with self.assertRaises(PermissionDenied):
                        next(pages)
                finally:
                    pages.close()
                self.assertTrue(waiting.result(timeout=10))
        other.refresh_from_db()
        self.assertEqual(other.name, "Admitted writer")
        self.assertEqual(OrganizationMembership.objects.get(organization=self.org, user=self.owner).role, "viewer")

    def test_artifact_admission_nests_through_rollback_and_releases_on_failure(self):
        from .customer_artifact_barrier import project_artifact_barrier
        from .customer_coherent_parts import coherent_customer_row_pages
        with self.assertRaises(ValueError):
            with project_artifact_barrier(True, shared=True):
                pass
        with transaction.atomic():
            with self.assertRaises(RuntimeError):
                with project_artifact_barrier(self.org.pk, shared=True):
                    pass
        with self.assertRaisesRegex(ValueError, "fixture failure"):
            with project_artifact_barrier(self.org.pk, shared=True):
                with self.assertRaises(RuntimeError):
                    next(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
                try:
                    with transaction.atomic():
                        with project_artifact_barrier(self.org.pk, shared=True):
                            OrganizationMembership.objects.filter(organization=self.org).update(role="viewer")
                            raise ValueError("fixture rollback")
                except ValueError:
                    self.assertEqual(OrganizationMembership.objects.get(organization=self.org).role, "owner")
                raise ValueError("fixture failure")
        # A live original session proves this rolled-back writer never entered storage.
        captured = list(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
        self.assertTrue(captured)
        failed_boundary = patch.object(connection, "get_autocommit", side_effect=DatabaseError("fixture failed verification"))
        try:
            with self.assertRaisesRegex(PermissionDenied, "original fixture denial"):
                with project_artifact_barrier(self.org.pk, shared=True):
                    failed_boundary.start()
                    raise PermissionDenied("original fixture denial")
        finally:
            failed_boundary.stop()
        from config.artifacts import ArtifactStorageError
        with self.assertRaisesRegex(ArtifactStorageError, "mutation is unresolved"):
            next(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
        self.clear_joined_fixture_mutations()

    def test_brief_and_report_admit_before_row_locks_and_keep_commit_failure_cleanup_private(self):
        from jobs import content_brief, reporting, test_content_brief as brief_fixtures
        from jobs.models import ContentBriefSnapshot, ProjectReportSnapshot
        from .customer_coherent_parts import coherent_customer_row_pages
        from .artifacts import delete_project_artifact
        brief_fixtures.ContentBriefTests.setUp(self)
        producers = (
            (content_brief, ContentBriefSnapshot, lambda key: brief_fixtures.ContentBriefTests.create(self, request_key=key)),
            (reporting, ProjectReportSnapshot, lambda key: reporting.create_project_report(
                project=self.project, actor=self.owner, request_key=key, content_format="json",
                finding_ids=[], action_review_ids=[self.action.pk], outcome_ids=[])),
        )
        for module, model, create in producers:
            with self.subTest(producer=module.__name__):
                def writer():
                    close_old_connections()
                    try:
                        return create("admitted-writer-001")
                    finally:
                        close_old_connections()
                with closing(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk)) as pages:
                    next(pages)
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        pending = pool.submit(writer)
                        try:
                            self.wait_for_artifact_admission()
                            with transaction.atomic():
                                # Waiting for capture must not hold a revocation/closure row lock.
                                self.org.__class__.objects.select_for_update(nowait=True).get(pk=self.org.pk)
                            captured = list(pages)
                        finally:
                            pages.close()
                        saved = pending.result(timeout=15)
                self.assertFalse([row for data, source in captured if source["model"] == model._meta.label
                                  for row in json.loads(data)])
                self.assertTrue(storages["artifacts"].exists(saved.artifact_key))
                self.assertEqual(create("admitted-writer-001").pk, saved.pk)

                deleting, release = Event(), Event()
                removed = []
                def compensate(**kwargs):
                    removed.append(kwargs["key"])
                    deleting.set()
                    if not release.wait(timeout=15):
                        raise AssertionError("Compensating deletion fixture did not release")
                    delete_project_artifact(**kwargs)
                def failed_writer():
                    close_old_connections()
                    try:
                        with patch.object(connection, "commit", side_effect=DatabaseError("fixture commit failure")), \
                                patch(module.__name__ + ".delete_project_artifact", side_effect=compensate):
                            return create("failed-commit-001")
                    finally:
                        close_old_connections()
                def capture():
                    close_old_connections()
                    try:
                        return list(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
                    finally:
                        close_old_connections()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    failed = pool.submit(failed_writer)
                    try:
                        self.assertTrue(deleting.wait(timeout=10))
                        self.assertFalse(model.objects.filter(project=self.project, request_key="failed-commit-001").exists())
                        self.assertTrue(storages["artifacts"].exists(removed[0]))
                        after_cleanup = pool.submit(capture)
                        self.wait_for_artifact_admission()
                    finally:
                        release.set()
                    with self.assertRaisesRegex(DatabaseError, "fixture commit failure"):
                        failed.result(timeout=15)
                    from config.artifacts import ArtifactStorageError
                    with self.assertRaisesRegex(ArtifactStorageError, "mutation is unresolved"):
                        after_cleanup.result(timeout=15)
                self.clear_joined_fixture_mutations()
                captured = capture()
                self.assertFalse(storages["artifacts"].exists(removed[0]))
                rows = [row for data, source in captured if source["model"] == model._meta.label for row in json.loads(data)]
                self.assertEqual([row["id"] for row in rows], [saved.pk])

    @override_settings(GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
    def test_research_and_performance_admit_before_source_attempt_and_hold_through_provider_output(self):
        import os
        from jobs import test_research as research_fixtures, test_performance_job as performance_fixtures
        from jobs.research import execute_research
        from jobs.performance_job import execute_performance_audit
        from jobs.models import Artifact
        from .customer_coherent_parts import coherent_customer_row_pages
        for kind in ("research", "performance"):
            with self.subTest(producer=kind):
                producing, release = Event(), Event()
                def provider_gate():
                    producing.set()
                    if not release.wait(timeout=15):
                        raise AssertionError("Provider fixture did not release")
                if kind == "research":
                    self.url = research_fixtures.ResearchTests.url
                    research_fixtures.ResearchTests.setUp(self)
                    with patch("jobs.services.dispatch_pending"):
                        job = research_fixtures.ResearchTests.queue(self)
                    fetcher = research_fixtures.ResearchTests.fetcher(self)
                    def request(**kwargs):
                        provider_gate()
                        return research_fixtures.ResearchTests.response(self, **kwargs)
                    execute = lambda: execute_research(job.pk, fetcher=fetcher, request=request)
                else:
                    self.date_part = performance_fixtures.PerformanceSnapshotTests.date_part
                    performance_fixtures.PerformanceSnapshotTests.setUp(self)
                    self.org = self.organization
                    with patch("jobs.services.dispatch_pending"):
                        job = performance_fixtures.PerformanceSnapshotTests.queue(self, ["crux_current"])
                    def fetch(**kwargs):
                        provider_gate()
                        return self.crux
                    execute = lambda: execute_performance_audit(job.pk, fetch=fetch)
                def writer():
                    close_old_connections()
                    try:
                        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-not-real"}):
                            return execute()
                    finally:
                        close_old_connections()
                def capture():
                    close_old_connections()
                    try:
                        return list(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
                    finally:
                        close_old_connections()
                with closing(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk)) as pages:
                    next(pages)
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        pending = pool.submit(writer)
                        try:
                            self.wait_for_artifact_admission()
                            self.assertFalse(producing.is_set())
                            self.assertFalse(JobStep.objects.filter(job=job).exists())
                            with transaction.atomic():
                                self.org.__class__.objects.select_for_update(nowait=True).get(pk=self.org.pk)
                            pages.close()
                            self.assertTrue(producing.wait(timeout=10))
                            captured_after = pool.submit(capture)
                            self.wait_for_artifact_admission()
                            self.assertTrue(JobStep.objects.filter(job=job, status="running").exists())
                        finally:
                            pages.close()
                            release.set()
                        self.assertTrue(pending.result(timeout=15))
                        captured = captured_after.result(timeout=15)
                job.refresh_from_db()
                self.assertEqual(job.status, "succeeded" if kind == "research" else "partially_succeeded")
                self.assertEqual(job.usage.state, "settled")
                artifact_ids = list(Artifact.objects.filter(job=job).values_list("pk", flat=True))
                self.assertEqual(len(artifact_ids), 1)
                captured_ids = [row["id"] for data, source in captured if source["model"] == "jobs.Artifact"
                                for row in json.loads(data)]
                self.assertIn(artifact_ids[0], captured_ids)
                captured_jobs = [row for data, source in captured if source["model"] == "jobs.JobRun"
                                 for row in json.loads(data) if row["id"] == job.pk]
                self.assertEqual([row["status"] for row in captured_jobs], [job.status])

    @override_settings(ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv", "application/json", "application/zip"}))
    def test_csv_import_and_cleanup_admit_before_locks_and_hold_through_commit_compensation(self):
        from integrations import search_console, test_search_console as fixtures
        from integrations.models import PendingArtifactCleanup
        from jobs.models import Artifact
        from .customer_artifact_barrier import project_artifact_barrier
        from .customer_coherent_parts import coherent_customer_row_pages
        fixtures.SearchConsoleCSVImportTests.setUp(self)
        self.org = self.organization
        data = b"Top queries,Clicks,Impressions,CTR,Position\ncoherent,1,2,50%,1\n"
        def queue(content=data):
            return search_console.queue_search_console_csv_import(connection=self.connection, user=self.owner,
                content=content, date_start=self.start, date_end=self.end)
        def worker(call):
            close_old_connections()
            try:
                return call()
            finally:
                close_old_connections()
        with closing(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk)) as pages:
            next(pages)
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(worker, queue)
                try:
                    self.wait_for_artifact_admission()
                    with transaction.atomic():
                        type(self.org).objects.select_for_update(nowait=True).get(pk=self.org.pk)
                    self.assertFalse(PendingArtifactCleanup.objects.exists())
                    captured = list(pages)
                finally:
                    pages.close()
                saved = pending.result(timeout=15)
        self.assertFalse([row for body, source in captured if source["model"] == "jobs.Artifact"
                          for row in json.loads(body)])
        self.assertEqual(queue().pk, saved.pk)
        self.assertTrue(storages["artifacts"].exists(saved.artifacts.get().key))

        deleting, release = Event(), Event()
        removed = []
        from .artifacts import delete_project_artifact
        def failed_writer():
            real_commit = connection.commit
            commits = 0
            def commit():
                nonlocal commits
                commits += 1
                if commits == 2:
                    raise DatabaseError("fixture publication commit failure")
                return real_commit()
            def discard(**kwargs):
                removed.append(kwargs["key"])
                deleting.set()
                if not release.wait(timeout=15):
                    raise AssertionError("Import compensation fixture did not release")
                delete_project_artifact(**kwargs)
            with patch.object(connection, "commit", side_effect=commit), \
                    patch("integrations.search_console.delete_project_artifact", side_effect=discard):
                return queue(data.replace(b"coherent", b"failed"))
        def capture():
            return list(coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
        with ThreadPoolExecutor(max_workers=2) as pool:
            failed = pool.submit(worker, failed_writer)
            try:
                self.assertTrue(deleting.wait(timeout=10))
                self.assertEqual(Artifact.objects.count(), 1)
                self.assertTrue(storages["artifacts"].exists(removed[0]))
                after_cleanup = pool.submit(worker, capture)
                self.wait_for_artifact_admission()
            finally:
                release.set()
            with self.assertRaisesRegex(DatabaseError, "fixture publication commit failure"):
                failed.result(timeout=15)
            from config.artifacts import ArtifactStorageError
            with self.assertRaisesRegex(ArtifactStorageError, "mutation is unresolved"):
                after_cleanup.result(timeout=15)
        self.clear_joined_fixture_mutations()
        self.assertTrue(capture())
        self.assertFalse(storages["artifacts"].exists(removed[0]))
        self.assertFalse(PendingArtifactCleanup.objects.exists())

        for reconcile in (False, True):
            with self.subTest(reconcile=reconcile):
                with project_artifact_barrier(self.project.organization_id, shared=True):
                    key = save_project_artifact(project=self.project, content=b'{}', content_type="application/json")
                cleanup = PendingArtifactCleanup.objects.create(project=self.project, key=key)
                PendingArtifactCleanup.objects.filter(pk=cleanup.pk).update(created_at=timezone.now() - timedelta(minutes=6))
                def clean():
                    return (search_console.reconcile_search_console_artifacts() if reconcile else
                            search_console._discard_staged_artifact(project=self.project, key=key))
                with ThreadPoolExecutor(max_workers=1) as pool:
                    with project_artifact_barrier(self.org.pk, shared=False):
                        pending = pool.submit(worker, clean)
                        self.wait_for_artifact_admission()
                        with transaction.atomic():
                            type(self.org).objects.select_for_update(nowait=True).get(pk=self.org.pk)
                        self.assertTrue(storages["artifacts"].exists(key))
                        self.assertTrue(PendingArtifactCleanup.objects.filter(pk=cleanup.pk).exists())
                    pending.result(timeout=15)
                self.assertFalse(storages["artifacts"].exists(key))
                self.assertFalse(PendingArtifactCleanup.objects.filter(pk=cleanup.pk).exists())

    def test_project_version_deletion_admits_after_claim_and_holds_through_completion_commit(self):
        from types import SimpleNamespace
        from . import artifacts, deletion, test_deletion as fixtures
        from .customer_artifact_barrier import project_artifact_barrier
        from .models import OrganizationDeletionRun
        fixtures.CustomerDeletionTests.setUp(self)
        type(self.org).objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        with project_artifact_barrier(self.project.organization_id, shared=True):
            key = save_project_artifact(project=self.project, content=b'{}', content_type="application/json")
        def worker(call):
            close_old_connections()
            try:
                return call()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with project_artifact_barrier(self.org.pk, shared=False):
                pending = pool.submit(worker, lambda: artifacts.delete_closed_project_artifact_batch(
                    organization=self.org, project=self.project))
                self.wait_for_artifact_admission()
                with transaction.atomic():
                    type(self.org).objects.select_for_update(nowait=True).get(pk=self.org.pk)
                self.assertTrue(storages["artifacts"].exists(key))
            self.assertEqual(pending.result(timeout=15), (1, True))
        self.assertFalse(storages["artifacts"].exists(key))

        prefix = "private/" + artifacts.project_artifact_scope(self.project) + "/"
        class Client:
            fail_once = True
            versions = [{"Key": prefix + "a" * 32 + ".json", "VersionId": "version"}]
            markers = [{"Key": prefix + "a" * 32 + ".json", "VersionId": "marker"}]
            def get_paginator(inner, name):
                self.assertEqual(name, "list_object_versions")
                return inner
            def paginate(inner, *, Bucket, Prefix):
                self.assertEqual(Bucket, "private-bucket")
                return iter([{"Versions": [row for row in inner.versions if row["Key"].startswith(Prefix)],
                              "DeleteMarkers": [row for row in inner.markers if row["Key"].startswith(Prefix)]}])
            def delete_object(inner, *, Bucket, Key, VersionId):
                self.assertEqual(Bucket, "private-bucket")
                self.assertTrue(Key.startswith(prefix))
                if inner.fail_once:
                    inner.fail_once = False
                    raise OSError("fixture unknown deletion result")
                inner.versions = [row for row in inner.versions if row["VersionId"] != VersionId]
                inner.markers = [row for row in inner.markers if row["VersionId"] != VersionId]
        client = Client()
        storage = SimpleNamespace(bucket_name="private-bucket", location="private",
            connection=SimpleNamespace(meta=SimpleNamespace(client=client)),
            _normalize_name=lambda name: "private/" + name)
        run = deletion.prepare_customer_data_deletion(organization=self.org)
        for failure in (True, False):
            with self.subTest(storage_failure=failure):
                completing, release = Event(), Event()
                def sweep():
                    real_commit = connection.commit
                    commits = 0
                    def commit():
                        nonlocal commits
                        commits += 1
                        if commits == 2:
                            completing.set()
                            if not release.wait(timeout=15):
                                raise AssertionError("Deletion completion fixture did not release")
                        return real_commit()
                    with patch.object(connection, "commit", side_effect=commit):
                        return deletion.sweep_customer_artifact_versions(run=run, storage=storage)
                def capture():
                    with project_artifact_barrier(self.org.pk, shared=False):
                        return OrganizationDeletionRun.objects.get(pk=run.pk)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    with project_artifact_barrier(self.org.pk, shared=False):
                        pending = pool.submit(worker, sweep)
                        self.wait_for_artifact_admission()
                        # Claim commits before admission waits, leaving closure/role metadata prompt.
                        claimed = OrganizationDeletionRun.objects.get(pk=run.pk)
                        self.assertIsNotNone(claimed.claimed_at)
                        self.assertEqual(claimed.attempts, 1 if failure else 2)
                        with transaction.atomic():
                            type(self.org).objects.select_for_update(nowait=True).get(pk=self.org.pk)
                        self.assertEqual((len(client.versions), len(client.markers)), (1, 1))
                    try:
                        self.assertTrue(completing.wait(timeout=10))
                        captured = pool.submit(worker, capture)
                        self.wait_for_artifact_admission()
                        self.assertIsNotNone(OrganizationDeletionRun.objects.get(pk=run.pk).claimed_at)
                    finally:
                        release.set()
                    completed = pending.result(timeout=15)
                    observed = captured.result(timeout=15)
                self.assertIsNone(observed.claimed_at)
                self.assertEqual(observed.state, completed.state)
                self.assertEqual(completed.last_error_category, "artifact_unavailable" if failure else "")
                self.assertEqual(completed.state, run.State.PENDING if failure else run.State.STORAGE_CLEARED)
        self.assertEqual(completed.storage_removed_count, 2)
        self.assertEqual((client.versions, client.markers), ([], []))

    def test_coherent_capture_denies_page_and_completion_after_admission_session_loss(self):
        from config.artifacts import ArtifactStorageError
        from . import customer_coherent_parts as coherent
        from .customer_artifact_barrier import project_artifact_barrier, require_artifact_admission
        for boundary in ("page", "completion"):
            with self.subTest(boundary=boundary):
                original = coherent._current_owner
                started, terminated = False, []
                def lose_session(*args, **kwargs):
                    nonlocal started
                    original(*args, **kwargs)
                    if started and not terminated and ((boundary == "page" and not kwargs) or
                            (boundary == "completion" and kwargs.get("check_sources"))):
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted "
                                "AND mode = 'ExclusiveLock' AND objsubid = 2 AND classid = 0 AND objid = %s "
                                "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())", [self.org.pk])
                            pid, = cursor.fetchone()
                            cursor.execute("SELECT pg_terminate_backend(%s)", [pid])
                            self.assertTrue(cursor.fetchone()[0])
                            terminated.append(pid)
                    started = True
                with patch("tenancy.customer_coherent_parts._current_owner", side_effect=lose_session):
                    pages = coherent.coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk)
                    if boundary == "page":
                        with self.assertRaisesRegex(ArtifactStorageError, "Artifact admission was lost"):
                            next(pages)
                    else:
                        with self.assertRaisesRegex(ArtifactStorageError, "Artifact admission was lost"):
                            list(pages)
                self.assertEqual(len(terminated), 1)
                self.assertTrue(list(coherent.coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk)))
        with self.assertRaisesRegex(ArtifactStorageError, "Artifact admission was lost"), \
                project_artifact_barrier(self.org.pk, shared=True) as owner:
            owner.close()
            owner.ensure_connection()
            with self.assertRaisesRegex(ArtifactStorageError, "Artifact admission was lost"):
                require_artifact_admission(self.org.pk, shared=True)
            with self.assertRaisesRegex(ArtifactStorageError, "Artifact admission was lost"):
                with project_artifact_barrier(self.org.pk, shared=True):
                    self.fail("A reconnected session cannot inherit original admission")
        with self.assertRaisesRegex(ArtifactStorageError, "mutation is unresolved"):
            list(coherent.coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk))
        self.clear_joined_fixture_mutations()
        self.assertTrue(list(coherent.coherent_customer_row_pages(organization_id=self.org.pk, actor_id=self.owner.pk)))

    def test_project_storage_mutations_require_original_live_writer_admission(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from unittest.mock import Mock
        from config.artifacts import ArtifactStorageError, cleanup_private_artifacts, delete_private_artifact
        from .artifacts import _delete_scope_batch, project_artifact_scope
        self.project = create_project(organization=self.org, user=self.owner, name="Mutation fixture",
                                      canonical_origin="https://mutation.example.invalid")
        scope = project_artifact_scope(self.project)
        storage = storages["artifacts"]
        with project_artifact_barrier(self.org.pk, shared=True):
            key = save_private_artifact(scope=scope, content=b"{}", content_type="application/json")
        page = {"Versions": [{"Key": key, "VersionId": "fixture-version"}]}
        client = Mock()
        client.get_paginator.return_value.paginate.side_effect = lambda **kwargs: iter([page])
        s3 = SimpleNamespace(bucket_name="fixture", location="", _normalize_name=lambda value: value,
                             connection=SimpleNamespace(meta=SimpleNamespace(client=client)))
        operations = {
            "save": lambda: save_private_artifact(scope=scope, content=b"{}", content_type="application/json"),
            "delete": lambda: delete_private_artifact(key),
            "cleanup": lambda: cleanup_private_artifacts(scope=scope, keep_keys=[]),
            "versions": lambda: _delete_scope_batch(scope=scope, limit=1, storage=s3),
        }
        for mode in ("missing", "capture", "closed", "reconnected", "terminated", "late_loss"):
            for name, mutate in operations.items():
                with self.subTest(mode=mode, mutation=name):
                    admission = (nullcontext() if mode == "missing" else
                                 project_artifact_barrier(self.org.pk, shared=mode != "capture"))
                    client.delete_object.reset_mock()
                    exit_error = (self.assertRaises(ArtifactStorageError) if mode in {
                        "closed", "reconnected", "terminated", "late_loss"} else nullcontext())
                    with exit_error, admission as owner, patch.object(storage, "save") as save, patch.object(storage, "delete") as delete:
                        if mode in {"closed", "reconnected"}:
                            owner.close()
                            if mode == "reconnected":
                                owner.ensure_connection()
                        elif mode == "terminated":
                            with owner.cursor() as cursor:
                                cursor.execute("SELECT pg_backend_pid()")
                                pid, = cursor.fetchone()
                            with connection.cursor() as cursor:
                                cursor.execute("SELECT pg_terminate_backend(%s)", [pid])
                                self.assertTrue(cursor.fetchone()[0])
                        boundary = nullcontext()
                        if mode == "late_loss":
                            if name == "save":
                                def lost_exists(*args):
                                    owner.close()
                                    return False
                                boundary = patch.object(storage, "exists", side_effect=lost_exists)
                            elif name == "cleanup":
                                original = storage.listdir
                                def lost_listing(*args):
                                    result = original(*args)
                                    owner.close()
                                    return result
                                boundary = patch.object(storage, "listdir", side_effect=lost_listing)
                            elif name == "versions":
                                def lost_versions(**kwargs):
                                    owner.close()
                                    return iter([page])
                                boundary = patch.object(client.get_paginator.return_value, "paginate", side_effect=lost_versions)
                            else:
                                # Storage resolution is the last callback before the delete guard.
                                class LostStorage:
                                    def __getitem__(self, alias):
                                        owner.close()
                                        return storage
                                boundary = patch("config.artifacts.storages", LostStorage())
                        expected = RuntimeError if mode in {"missing", "capture"} else ArtifactStorageError
                        with boundary, self.assertRaises(expected):
                            mutate()
                        save.assert_not_called()
                        delete.assert_not_called()
                        client.delete_object.assert_not_called()
        self.assertEqual(read_private_artifact(key), b"{}")
        with project_artifact_barrier(self.org.pk, shared=True):
            self.assertEqual(cleanup_private_artifacts(scope=scope, keep_keys=[]), 1)

    @override_settings(DEBUG=True)
    def test_bounded_writer_refusal_preserves_queued_work_and_returns_retryable_api_errors(self):
        from jobs.crawler import queue_crawl
        from jobs.models import CrawlRun, ContentBriefSnapshot, ProjectReportSnapshot
        from jobs.services import reconcile_dispatch
        from jobs.tasks import execute_crawl_job_task
        from config.artifacts import ArtifactStorageError
        project = create_project(organization=self.org, user=self.owner, name="Bounded writer",
                                 canonical_origin="https://bounded-writer.example.invalid")
        with patch("jobs.tasks.execute_crawl_job_task.apply_async") as initial:
            job = queue_crawl(project=project, actor=self.owner, seeds=[], page_limit=1, idempotency_key="bounded-writer")
        initial.assert_called_once()
        def refused():
            close_old_connections()
            try:
                with patch("jobs.crawler._execute_crawl_job", side_effect=AssertionError("No pre-admission work")) as work:
                    with self.assertRaises(ArtifactStorageError):
                        execute_crawl_job_task(job.pk)
                    work.assert_not_called()
                client = Client(); client.force_login(self.owner)
                base = f"/api/organizations/{self.org.pk}/projects/{project.pk}/"
                for route, body in (
                    ("briefs", {"request_key": "bounded-brief", "research_job_id": 1,
                        "action_id": "00000000-0000-0000-0000-000000000001", "title_options": ["Fixture"],
                        "angle": "Fixture", "outline": ["Fixture"], "questions": []}),
                    ("reports", {"request_key": "bounded-report", "format": "json", "finding_ids": [1],
                        "action_review_ids": [], "outcome_ids": []}),
                ):
                    response = client.post(base + route + "/", json.dumps(body), content_type="application/json", secure=True)
                    self.assertEqual(response.status_code, 503, response.content)
                    self.assertIn("no-store", response.headers["Cache-Control"])
                    self.assertNotIn(b"pg_advisory", response.content)
            finally:
                close_old_connections()
        with patch("tenancy.customer_artifact_barrier.WRITER_ADMISSION_TIMEOUT_MS", 100):
            with project_artifact_barrier(self.org.pk, shared=False), ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(refused).result(timeout=10)
        job.refresh_from_db()
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.usage.actual_units, 0)
        self.assertFalse(job.steps.exists())
        self.assertFalse(CrawlRun.objects.filter(job=job).exists())
        self.assertFalse(ContentBriefSnapshot.objects.exists())
        self.assertFalse(ProjectReportSnapshot.objects.exists())
        JobRun.objects.filter(pk=job.pk).update(dispatched_at=timezone.now() - timedelta(seconds=61))
        with patch("jobs.tasks.execute_crawl_job_task.apply_async") as retry:
            self.assertEqual(reconcile_dispatch(), 1)
        retry.assert_called_once_with(args=[job.pk], queue="crawl", task_id=f"job-{job.pk}", retry=False)
        self.assertEqual(queue_crawl(project=project, actor=self.owner, seeds=[], page_limit=1,
                                   idempotency_key="bounded-writer").pk, job.pk)

    def test_bounded_cleanup_refusal_clears_own_claim_and_leaves_unrelated_cleanup_prompt(self):
        from . import test_deletion as fixtures
        from .deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions
        from .artifacts import project_artifact_scope
        from integrations.models import PendingArtifactCleanup
        from integrations.search_console import reconcile_search_console_artifacts
        fixtures.CustomerDeletionTests.setUp(self)
        type(self.org).objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        run = prepare_customer_data_deletion(organization=self.org)
        own = [PendingArtifactCleanup.objects.create(project=self.project,
               key=f"{project_artifact_scope(self.project)}/{stem * 32}.json") for stem in ("a", "b")]
        foreign = PendingArtifactCleanup.objects.create(project=self.other_project,
            key=f"{project_artifact_scope(self.other_project)}/{'c' * 32}.json")
        PendingArtifactCleanup.objects.update(created_at=timezone.now() - timedelta(minutes=6))
        def refused():
            close_old_connections()
            try:
                result = sweep_customer_artifact_versions(run=run)
                self.assertIsNone(result.claimed_at)
                self.assertEqual((result.state, result.last_error_category, result.storage_removed_count),
                                 (run.State.PENDING, "artifact_unavailable", 0))
                with patch("integrations.search_console.WRITER_ADMISSION_TIMEOUT_MS", 100):
                    self.assertEqual(reconcile_search_console_artifacts(), 1)
                self.assertFalse(PendingArtifactCleanup.objects.filter(pk=foreign.pk).exists())
                self.assertEqual(PendingArtifactCleanup.objects.filter(pk__in=[row.pk for row in own]).count(), 2)
                with patch("integrations.search_console.monotonic", side_effect=[0, 0, 3.1]), \
                        patch("integrations.search_console.WRITER_ADMISSION_TIMEOUT_MS", 100):
                    self.assertEqual(reconcile_search_console_artifacts(), 0)
            finally:
                close_old_connections()
        with patch("tenancy.customer_artifact_barrier.WRITER_ADMISSION_TIMEOUT_MS", 100):
            with project_artifact_barrier(self.org.pk, shared=False), ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(refused).result(timeout=10)
        self.assertEqual(reconcile_search_console_artifacts(), 2)
        self.assertEqual(sweep_customer_artifact_versions(run=run).state, run.State.STORAGE_CLEARED)
