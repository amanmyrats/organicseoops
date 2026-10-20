from tenancy.customer_artifact_barrier import project_artifact_barrier
from django.test import TransactionTestCase
from types import SimpleNamespace
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.utils import timezone

from config.artifacts import ArtifactStorageError, ArtifactValidationError
from config.test_foundations import TEST_STORAGES

from .artifacts import (delete_closed_organization_export_batch, delete_closed_project_artifact_batch,
                         delete_failed_organization_export_batch, failed_export_versions_remain,
                         list_project_artifact_keys, organization_export_scope, organization_export_versions_remain,
                         project_artifact_page, project_artifact_scope, read_project_artifact, save_project_artifact)
from .models import OrganizationCustomerExport
from .services import create_organization, create_project


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}))
class ClosedArtifactDeletionTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        users = get_user_model().objects
        self.owner = users.create_user("storage-closure@example.invalid", password="test-password")
        self.other = users.create_user("storage-other@example.invalid", password="test-password")
        for user in (self.owner, self.other):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        self.org = create_organization(user=self.owner, name="Storage closure")
        self.project = create_project(organization=self.org, user=self.owner, name="Own storage",
                                      canonical_origin="https://own-storage.example.invalid")
        self.other_org = create_organization(user=self.other, name="Other storage")
        self.foreign_project = create_project(organization=self.other_org, user=self.other,
            name="Other project", canonical_origin="https://other-storage.example.invalid")

    def _close(self):
        type(self.org).objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())

    def test_scoped_batch_is_idempotent_and_does_not_touch_other_tenants(self):
        with project_artifact_barrier(self.project.organization_id, shared=True):
            own = save_project_artifact(project=self.project, content=b'"one"', content_type="application/json")
        with project_artifact_barrier(self.foreign_project.organization_id, shared=True):
            foreign = save_project_artifact(project=self.foreign_project, content=b'"foreign"',
                                            content_type="application/json")
        with self.assertRaises(PermissionDenied):
            delete_closed_project_artifact_batch(organization=self.org, project=self.project)
        self._close()
        self.assertEqual(delete_closed_project_artifact_batch(organization=self.org,
                                                               project=self.project, limit=1), (1, True))
        self.assertEqual(list_project_artifact_keys(project=self.project), [])
        self.assertEqual(delete_closed_project_artifact_batch(organization=self.org, project=self.project), (0, True))
        self.assertEqual(read_project_artifact(project=self.foreign_project, key=foreign), b'"foreign"')
        with self.assertRaises(PermissionDenied):
            delete_closed_project_artifact_batch(organization=self.org, project=self.foreign_project)
        self.assertNotEqual(own, foreign)

    def test_storage_failure_preserves_retryable_project_inventory(self):
        with project_artifact_barrier(self.project.organization_id, shared=True):
            saved = save_project_artifact(project=self.project, content=b'"original"',
                                          content_type="application/json")
        self._close()
        with patch("tenancy.artifacts.delete_project_artifact", side_effect=ArtifactStorageError("unavailable")):
            with self.assertRaises(ArtifactStorageError):
                delete_closed_project_artifact_batch(organization=self.org, project=self.project)
        self.assertEqual(list_project_artifact_keys(project=self.project), [saved])
        self.assertEqual(delete_closed_project_artifact_batch(organization=self.org, project=self.project), (1, True))

    def test_batch_can_progress_past_the_bounded_inventory_ceiling(self):
        for index in range(1005):
            with project_artifact_barrier(self.project.organization_id, shared=True):
                save_project_artifact(project=self.project, content=b'{}', content_type="application/json",
                                      key_stem=f"{index:032x}")
        with self.assertRaises(ArtifactValidationError):
            list_project_artifact_keys(project=self.project)
        page, more = project_artifact_page(project=self.project, offset=1000, limit=100)
        self.assertEqual((len(page), more), (5, False))
        self._close()
        self.assertEqual(delete_closed_project_artifact_batch(organization=self.org, project=self.project), (100, False))
        for _ in range(10):
            deleted, _complete = delete_closed_project_artifact_batch(organization=self.org, project=self.project)
            if deleted == 0:
                break
        self.assertEqual(list_project_artifact_keys(project=self.project), [])

    def test_s3_visible_listing_pages_exact_project_keys_without_collecting_a_directory(self):
        scope = project_artifact_scope(self.project)
        prefix = "private/" + scope + "/"
        owned = scope + "/" + "a" * 32 + ".json"
        nested = scope + "/jobs/3/" + "b" * 32 + ".json"

        class Client:
            unexpected = None

            def get_paginator(self, name):
                if name != "list_objects_v2":
                    raise AssertionError(name)
                return self

            def paginate(self, *, Bucket, Prefix, StartAfter=None):
                if (Bucket, Prefix) != ("private-bucket", prefix):
                    raise AssertionError("Cross-bucket or cross-project listing")
                if StartAfter is None:
                    yield {"Contents": [{"Key": prefix + "a" * 32 + ".json"}]}
                elif StartAfter != "private/" + owned:
                    raise AssertionError("Wrong private S3 cursor")
                yield {"Contents": [{"Key": self.unexpected or prefix + "jobs/3/" + "b" * 32 + ".json"}]}

        client = Client()
        storage = SimpleNamespace(bucket_name="private-bucket", location="private",
            connection=SimpleNamespace(meta=SimpleNamespace(client=client)),
            _normalize_name=lambda name: "private/" + name,
            listdir=lambda _: self.fail("S3 must use paginated object listing"))
        with patch("tenancy.artifacts.storages", {"artifacts": storage}):
            self.assertEqual(project_artifact_page(project=self.project, offset=1, limit=1), ([nested], False))
            self.assertEqual(list_project_artifact_keys(project=self.project), [owned, nested])
            from .artifacts import iter_project_artifact_keys
            self.assertEqual(list(iter_project_artifact_keys(project=self.project, after_key=owned)), [nested])
            client.unexpected = "private/" + project_artifact_scope(self.foreign_project) + "/" + "c" * 32 + ".json"
            with self.assertRaises(ArtifactValidationError):
                list_project_artifact_keys(project=self.project)
            client.unexpected = prefix + "invalid.txt"
            with self.assertRaises(ArtifactValidationError):
                list_project_artifact_keys(project=self.project)

    def test_versioned_s3_pass_deletes_only_exact_prefix_versions_and_markers(self):
        prefix = "private/" + project_artifact_scope(self.project) + "/"
        owned = prefix + "a" * 32 + ".json"
        older = prefix + "jobs/3/" + "b" * 32 + ".json"
        foreign = "private/" + project_artifact_scope(self.foreign_project) + "/" + "c" * 32 + ".json"

        class Client:
            versions = [{"Key": owned, "VersionId": "version-1"},
                        {"Key": older, "VersionId": "version-2"}]
            markers = [{"Key": owned, "VersionId": "marker-1"}]
            deletions = []
            inject_foreign = False
            fail_once = False

            def get_paginator(self, name):
                if name != "list_object_versions":
                    raise AssertionError(name)
                return self

            def paginate(self, *, Bucket, Prefix):
                if (Bucket, Prefix) != ("private-bucket", prefix):
                    raise AssertionError("Cross-bucket or cross-project version listing")
                first = [item for item in self.versions if item["Key"] == owned]
                if self.inject_foreign:
                    first.append({"Key": foreign, "VersionId": "outside"})
                return iter([{"Versions": first, "DeleteMarkers": []},
                             {"Versions": [item for item in self.versions if item["Key"] != owned],
                              "DeleteMarkers": list(self.markers)}])

            def delete_object(self, *, Bucket, Key, VersionId):
                if self.fail_once:
                    self.fail_once = False
                    raise OSError("unknown simulated delete outcome")
                self.deletions.append((Bucket, Key, VersionId))
                self.versions = [item for item in self.versions if item["VersionId"] != VersionId]
                self.markers = [item for item in self.markers if item["VersionId"] != VersionId]

        client = Client()
        storage = SimpleNamespace(bucket_name="private-bucket", location="private",
            connection=SimpleNamespace(meta=SimpleNamespace(client=client)),
            _normalize_name=lambda name: "private/" + name)
        self._close()
        client.inject_foreign = True
        with self.assertRaises(ArtifactValidationError):
            delete_closed_project_artifact_batch(organization=self.org, project=self.project, storage=storage)
        self.assertEqual(client.deletions, [])
        client.inject_foreign = False
        client.fail_once = True
        with self.assertRaises(ArtifactStorageError):
            delete_closed_project_artifact_batch(organization=self.org, project=self.project, storage=storage)
        self.assertEqual(client.deletions, [])
        self.assertEqual(delete_closed_project_artifact_batch(organization=self.org, project=self.project,
                                                               storage=storage, limit=1), (1, False))
        self.assertEqual(delete_closed_project_artifact_batch(organization=self.org, project=self.project,
                                                               storage=storage), (2, True))
        self.assertEqual(delete_closed_project_artifact_batch(organization=self.org, project=self.project,
                                                               storage=storage), (0, True))
        self.assertEqual({(key, version) for _bucket, key, version in client.deletions}, {
            (owned, "version-1"), (older, "version-2"), (owned, "marker-1")})

    def test_versioned_org_export_pass_removes_hidden_markers_without_crossing_tenants(self):
        prefix = "private/" + organization_export_scope(self.org) + "/"
        owned = prefix + "a" * 32 + "/" + "b" * 32 + ".json"
        foreign = "private/" + organization_export_scope(self.other_org) + "/" + "a" * 32 + "/" + "c" * 32 + ".json"

        class Client:
            versions = [{"Key": owned, "VersionId": "version-1"}]
            markers = [{"Key": owned, "VersionId": "marker-1"}]
            inject_foreign = True
            fail_once = False
            deletions = []

            def get_paginator(self, name):
                if name != "list_object_versions":
                    raise AssertionError(name)
                return self

            def paginate(self, *, Bucket, Prefix):
                if (Bucket, Prefix) != ("private-bucket", prefix):
                    raise AssertionError("Cross-organization export listing")
                first = list(self.versions)
                if self.inject_foreign:
                    first.append({"Key": foreign, "VersionId": "outside"})
                yield {"Versions": first, "DeleteMarkers": []}
                yield {"Versions": [], "DeleteMarkers": list(self.markers)}

            def delete_object(self, *, Bucket, Key, VersionId):
                if self.fail_once:
                    self.fail_once = False
                    raise OSError("unknown simulated delete outcome")
                self.deletions.append((Bucket, Key, VersionId))
                self.versions = [row for row in self.versions if row["VersionId"] != VersionId]
                self.markers = [row for row in self.markers if row["VersionId"] != VersionId]

        client = Client()
        storage = SimpleNamespace(bucket_name="private-bucket", location="private",
            connection=SimpleNamespace(meta=SimpleNamespace(client=client)),
            _normalize_name=lambda name: "private/" + name)
        with self.assertRaises(PermissionDenied):
            delete_closed_organization_export_batch(organization=self.org, storage=storage)
        self._close()
        with self.assertRaises(ArtifactValidationError):
            delete_closed_organization_export_batch(organization=self.org, storage=storage)
        self.assertEqual(client.deletions, [])
        client.inject_foreign = False
        self.assertTrue(organization_export_versions_remain(organization=self.org, storage=storage))
        client.fail_once = True
        with self.assertRaises(ArtifactStorageError):
            delete_closed_organization_export_batch(organization=self.org, storage=storage)
        self.assertEqual(delete_closed_organization_export_batch(organization=self.org, storage=storage,
                                                                  limit=1), (1, False))
        self.assertEqual(delete_closed_organization_export_batch(organization=self.org, storage=storage), (1, True))
        self.assertFalse(organization_export_versions_remain(organization=self.org, storage=storage))
        self.assertEqual({(key, version) for _bucket, key, version in client.deletions}, {
            (owned, "version-1"), (owned, "marker-1")})

    def test_failed_active_export_purges_only_its_own_s3_versions_and_markers(self):
        failed = OrganizationCustomerExport.objects.create(organization=self.org, actor=self.owner,
            request_key="c" * 32, state=OrganizationCustomerExport.State.FAILED)
        sibling = OrganizationCustomerExport.objects.create(organization=self.org, actor=self.owner,
            request_key="d" * 32, state=OrganizationCustomerExport.State.READY,
            size_bytes=1, content_sha256="a" * 64, completed_at=timezone.now())
        prefix = f"private/{organization_export_scope(self.org)}/{failed.pk}/"
        owned = prefix + "a" * 32 + ".json"
        other = f"private/{organization_export_scope(self.org)}/{sibling.pk}/" + "b" * 32 + ".json"

        class Client:
            versions = [{"Key": owned, "VersionId": "v1"}]
            markers = [{"Key": owned, "VersionId": "m1"}]
            foreign = True
            fail_once = False
            deleted = []

            def get_paginator(self, name):
                if name != "list_object_versions":
                    raise AssertionError(name)
                return self

            def paginate(self, *, Bucket, Prefix):
                if (Bucket, Prefix) != ("private-bucket", prefix):
                    raise AssertionError("Cross-export S3 prefix")
                first = list(self.versions)
                if self.foreign:
                    first.append({"Key": other, "VersionId": "other"})
                yield {"Versions": first, "DeleteMarkers": []}
                yield {"Versions": [], "DeleteMarkers": list(self.markers)}

            def delete_object(self, *, Bucket, Key, VersionId):
                if self.fail_once:
                    self.fail_once = False
                    raise OSError("unknown delete")
                self.deleted.append((Key, VersionId))
                self.versions = [row for row in self.versions if row["VersionId"] != VersionId]
                self.markers = [row for row in self.markers if row["VersionId"] != VersionId]

        client = Client()
        storage = SimpleNamespace(bucket_name="private-bucket", location="private",
            connection=SimpleNamespace(meta=SimpleNamespace(client=client)),
            _normalize_name=lambda name: "private/" + name)
        with self.assertRaises(PermissionDenied):
            delete_failed_organization_export_batch(organization=self.org, actor=self.other,
                                                     snapshot_id=failed.pk, storage=storage)
        with self.assertRaises(PermissionDenied):
            delete_failed_organization_export_batch(organization=self.org, actor=self.owner,
                                                     snapshot_id=sibling.pk, storage=storage)
        with self.assertRaises(ArtifactValidationError):
            delete_failed_organization_export_batch(organization=self.org, actor=self.owner,
                                                     snapshot_id=failed.pk, storage=storage)
        self.assertEqual(client.deleted, [])
        client.foreign = False
        client.fail_once = True
        with self.assertRaises(ArtifactStorageError):
            delete_failed_organization_export_batch(organization=self.org, actor=self.owner,
                                                     snapshot_id=failed.pk, storage=storage)
        self.assertEqual(delete_failed_organization_export_batch(organization=self.org, actor=self.owner,
                         snapshot_id=failed.pk, limit=1, storage=storage), (1, False))
        self.assertEqual(delete_failed_organization_export_batch(organization=self.org, actor=self.owner,
                         snapshot_id=failed.pk, storage=storage), (1, True))
        self.assertFalse(failed_export_versions_remain(organization=self.org, snapshot_id=failed.pk, storage=storage))
        self.assertEqual(set(client.deleted), {(owned, "v1"), (owned, "m1")})
