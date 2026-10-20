from django.test import TransactionTestCase
from datetime import datetime, timezone as utc
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .local_visibility import METHOD, SOURCE, validate_local_visibility

NOW = datetime(2026, 10, 1, 12, tzinfo=utc.utc)
ORIGIN = "https://visibility.example.invalid"


def observation():
    return {"method_version": METHOD, "source_kind": SOURCE, "platform": "google_search", "surface": "organic_links",
        "assessment_id": 12, "configuration_revision": 3, "origin": ORIGIN, "observation_reference": "own-manual-1",
        "query": "Synthetic actual service query", "observed_at": "2026-10-01T13:00:00+03:00",
        "requested_location": "Customer service region", "requested_language": "en", "requested_device": "mobile",
        "applied_location": "", "applied_language": "", "applied_device": "unknown", "inspection_limit": 10,
        "inspected_count": 5, "status": "observed", "ordinal": 4, "matched_url": ORIGIN + "/own-service",
        "evidence_note": "Customer-owned numerical observation, no Google API/snippet/content, partial context unknown.",
        "storage_permission": True, "not_api_derived": True}


class LocalVisibilityIntakeTests(SimpleTestCase):
    def validate(self, data, **changes):
        return validate_local_visibility(data, **{**dict(approved_origin=ORIGIN, as_of=NOW), **changes})

    def test_original_scalar_query_context_time_preserved_and_unknown_applied_controls_not_inferred(self):
        data = observation()
        result = self.validate(data)
        self.assertEqual(result, data)
        self.assertIsNot(result, data)
        result["query"] = "Changed later"
        self.assertNotEqual(data["query"], result["query"])
        self.assertEqual(self.validate(data)["applied_location"], "")
        self.assertEqual(self.validate(data)["applied_device"], "unknown")
        self.validate({**data, "applied_location": "Different customer-reported region", "applied_device": "desktop",
            "applied_language": "tr", "requested_language": "unknown"})

    def test_partial_not_seen_and_unavailable_are_null_ordinals_not_negative_or_zero_rank(self):
        for status, count in (("not_seen_in_inspected_set", 5), ("unavailable", 0)):
            result = self.validate({**observation(), "status": status, "inspected_count": count, "ordinal": None, "matched_url": ""})
            self.assertIsNone(result["ordinal"])
        for changes in ({"ordinal": 0}, {"ordinal": 6}, {"ordinal": True}, {"inspected_count": 0},
            {"inspected_count": 11}, {"inspection_limit": 21}, {"inspection_limit": True},
            {"status": "not_seen_in_inspected_set"}, {"status": "unavailable", "ordinal": None, "matched_url": ""},
            {"status": "not_seen_in_inspected_set", "ordinal": None, "matched_url": "", "inspected_count": 0},
            {"status": "global_not_ranked"}, {"ordinal": "4"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.validate({**observation(), **changes})

    def test_api_objects_wrong_platform_scope_unaffirmed_rights_and_source_urls_are_rejected(self):
        for changes in ({"platform": "google_business_profile"}, {"surface": "local_pack"}, {"method_version": "average-position"},
            {"source_kind": "serp_api"}, {"storage_permission": 1}, {"not_api_derived": False}, {"assessment_id": True},
            {"assessment_id": 2**53}, {"configuration_revision": -1}, {"query": {"snippet": "API content"}},
            {"snippet": "Google result content"}, {"origin": "http://visibility.example.invalid"},
            {"matched_url": "https://foreign.example.invalid/result"}, {"matched_url": ORIGIN + ":8443/result"},
            {"matched_url": ORIGIN + "/result?private=secret"}, {"matched_url": ORIGIN + "/result#personal"},
            {"matched_url": "https://user:pass@visibility.example.invalid/result"}, {"matched_url": "javascript:alert(1)"},
            {"observation_reference": "person@example.invalid"}, {"requested_device": "simulated-location"}):
            with self.subTest(keys=list(changes)), self.assertRaises(ValidationError):
                self.validate({**observation(), **changes})
        for data in (None, [], {}, {key: value for key, value in observation().items() if key != "storage_permission"}):
            with self.assertRaises(ValidationError):
                self.validate(data)

    def test_aware_nonfuture_time_valid_text_and_actual_default_json_byte_limit(self):
        for changes in ({"observed_at": "2026-10-01T14:00:00+00:00"}, {"observed_at": "2026-10-01T10:00:00"},
            {"observed_at": "not-time"}, {"observed_at": False}, {"query": ""}, {"query": "x" * 241},
            {"query": "query\x00"}, {"evidence_note": "\ud800"}, {"requested_location": ""},
            {"requested_language": "not-a-language"}, {"applied_language": "unknown"},
            {"query": "😀" * 240, "requested_location": "😀" * 240, "applied_location": "😀" * 240,
             "evidence_note": "😀" * 500, "matched_url": ORIGIN + "/" + "😀" * 200}):
            with self.subTest(keys=list(changes)), self.assertRaises(ValidationError):
                self.validate({**observation(), **changes})
        self.validate({**observation(), "observed_at": NOW.isoformat()})
        with self.assertRaises(ValidationError):
            self.validate(observation(), as_of=datetime(2026, 10, 1))
        with self.assertRaises(ValidationError):
            self.validate(observation(), as_of=False)


from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier
from zipfile import ZipFile
import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.core.cache import cache
from django.utils import timezone
from allauth.account.models import EmailAddress

from config.test_foundations import TEST_STORAGES
from tenancy.models import MembershipRole, Organization, OrganizationMembership, OrganizationTrial, Project, ProjectOriginVerification
from .local_assessment import review_local_business
from .local_visibility import record_local_visibility, visibility_source_current
from .models import LocalVisibilityObservation
from .test_local_feedback import FeedbackFixture


class VisibilityFixture(FeedbackFixture):
    def setUp(self):
        super().setUp()
        self.visibility_data = {**observation(), "assessment_id": self.assessment.pk, "configuration_revision": 0,
            "origin": self.project.canonical_origin, "matched_url": self.project.canonical_origin + "/actual-service",
            "requested_location": self.assessment.service_areas[0], "requested_language": "unknown",
            "observed_at": (timezone.now() - timedelta(hours=1)).isoformat()}

    def observe(self, **changes):
        return record_local_visibility(**{**dict(project=self.project, actor=self.owner,
            request_key="visibility-own-1", intake=self.visibility_data, reason="Actual human context/coverage report."), **changes})


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "application/zip"}))
class LocalVisibilityHistoryTests(VisibilityFixture, TransactionTestCase):
    def test_immutable_exact_context_time_and_ordinal_corrections_do_not_search_or_create_jobs(self):
        first = self.observe()
        self.assertEqual(self.observe().pk, first.pk)
        self.assertEqual(first.intake, self.visibility_data)
        with self.assertRaises(ValidationError):
            first.save()
        corrected = self.observe(request_key="visibility-correction-1", observation_id=first.observation_id, expected_revision=1,
            intake={**first.intake, "ordinal": None, "matched_url": "", "status": "not_seen_in_inspected_set"})
        self.assertEqual(corrected.revision, 2)
        self.assertIsNone(corrected.intake["ordinal"])
        first.refresh_from_db()
        self.assertEqual(first.intake["ordinal"], 4)
        self.assertEqual(first.intake["applied_device"], "unknown")
        with self.assertRaises(ValidationError):
            self.observe(request_key="visibility-stale-edit", observation_id=first.observation_id, expected_revision=1)
        with self.assertRaises(ValidationError):
            self.observe()  # Earlier key cannot silently return stale source history as current.
        from .models import JobRun, Artifact
        self.assertEqual((JobRun.objects.count(), Artifact.objects.count()), (0, 0))

    def test_foreign_actor_project_location_language_and_revoked_source_are_denied(self):
        with self.assertRaises(PermissionDenied):
            self.observe(actor=self.other)
        membership = OrganizationMembership.objects.create(organization=self.org, user=self.other, role=MembershipRole.MEMBER)
        with self.assertRaises(PermissionDenied):
            self.observe(actor=self.other)
        membership.role = MembershipRole.ADMIN
        membership.save()
        first = self.observe(actor=self.other)
        membership.role = MembershipRole.MEMBER
        membership.save()
        self.assertFalse(visibility_source_current(first))
        membership.role = MembershipRole.ADMIN
        membership.save()
        get_user_model().objects.filter(pk=self.other.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.observe(actor=self.other, request_key="visibility-stale-user")
        foreign = Project.objects.create(organization=self.org, name="Synthetic foreign observation", canonical_origin="https://foreign.example.invalid")
        for changes in ({"project": foreign}, {"intake": {**self.visibility_data, "requested_location": "Invented office"}},
            {"intake": {**self.visibility_data, "requested_language": "fr"}},
            {"intake": {**self.visibility_data, "assessment_id": self.assessment.pk + 10000}}):
            with self.subTest(keys=list(changes)), self.assertRaises(PermissionDenied):
                self.observe(**changes)
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        with self.assertRaises(PermissionDenied):
            self.observe(request_key="visibility-unverified-user")

    def test_latest_actual_manual_assessment_config_verification_time_and_retention_are_rechecked(self):
        first = self.observe()
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(verified_at=timezone.now())
        self.assertFalse(visibility_source_current(first))
        with self.assertRaises(ValidationError):
            self.observe()
        fresh = self.observe(request_key="visibility-new-source-attestation", observation_id=first.observation_id, expected_revision=1)
        self.assertTrue(visibility_source_current(fresh))
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="revoked", revoked_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.observe(request_key="visibility-revoked-source")
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="verified", revoked_at=None)
        revised = review_local_business(**{**self.assessment_values, "request_key": "visibility-business-correction", "expected_revision": 1})
        with self.assertRaises(PermissionDenied):
            self.observe(request_key="visibility-old-business")
        self.visibility_data["assessment_id"] = revised.pk
        self.config.revision = 1
        self.config.save(update_fields=["revision"])
        with self.assertRaises(PermissionDenied):
            self.observe(request_key="visibility-old-config")
        self.config.revision = 0
        self.config.save(update_fields=["revision"])
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.org).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied):
            self.observe(request_key="visibility-retention-cutoff")

    def test_private_export_keeps_human_scope_and_closure_deletes_customer_observations_before_sources(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        first = self.observe()
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="revoked", revoked_at=timezone.now())
        with ZipFile(BytesIO(complete_bounded_customer_archive(organization=self.org, actor=self.owner))) as archive:
            rows = json.loads(archive.read("records/jobs/LocalVisibilityObservation.json"))
            self.assertEqual(rows[0]["intake"], first.intake)
            self.assertFalse(rows[0]["source_current_at_capture"])
            self.assertEqual(rows[0]["scope"], "historical_customer_report_not_verified_or_universal_rank")
            self.assertNotIn("request_key", rows[0])
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.observe(request_key="visibility-closed-project")
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.org))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(LocalVisibilityObservation.objects.exists())

    def test_actual_stored_and_sequential_export_delivery_retains_only_historical_customer_reports(self):
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        first = self.observe()
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            stored = reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner, request_key="c" * 32)
            self.assertTrue(capture_reserved_customer_snapshot(stored.pk))
            data, _digest = private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=stored.pk, position=0)
            with ZipFile(BytesIO(data)) as archive:
                row = json.loads(archive.read("records/jobs/LocalVisibilityObservation.json"))[0]
                self.assertEqual(row["intake"], first.intake)
                self.assertTrue(row["source_current_at_capture"])
                self.assertEqual(row["scope"], "historical_customer_report_not_verified_or_universal_rank")
            ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="revoked", revoked_at=timezone.now())
            # A retained private history copy is not asserted to be current/provider-verified rank evidence.
            self.assertEqual(private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=stored.pk, position=0)[0], data)
            parts = reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner, request_key="d" * 32, format="source-parts-v2")
            for _ in range(len(CUSTOMER) * 2 + 10):
                parts.refresh_from_db()
                if parts.state != parts.State.PREPARING:
                    break
                self.assertTrue(capture_source_stage(parts.pk, parts.progress.get("step", 0)))
            parts.refresh_from_db()
            self.assertEqual(parts.state, parts.State.READY)
            part = parts.parts.filter(source__model="jobs.LocalVisibilityObservation").first()
            data, _digest = private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=parts.pk, position=part.position)
            with ZipFile(BytesIO(data)) as archive:
                row = json.loads(archive.read("data"))[0]
                self.assertEqual(row["intake"]["ordinal"], 4)
                self.assertEqual(row["intake"]["applied_device"], "unknown")
                self.assertFalse(row["source_current_at_capture"])
                self.assertNotIn("request_key", row)
        with self.assertRaises(PermissionDenied):
            private_snapshot_part(organization=self.org, actor=self.other, snapshot_id=stored.pk, position=0)
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.org).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied):
            private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=stored.pk, position=0)
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.org))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(LocalVisibilityObservation.objects.exists())


class LocalVisibilityConcurrencyTests(VisibilityFixture, TransactionTestCase):
    def test_actual_two_connection_optimistic_corrections_cannot_overwrite_history(self):
        first = self.observe()
        barrier = Barrier(2)
        def write(key):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return self.observe(request_key=key, observation_id=first.observation_id, expected_revision=1).revision
                except ValidationError:
                    return "conflict"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ["visibility-concurrent-1", "visibility-concurrent-2"]))
        self.assertCountEqual(results, [2, "conflict"])
        self.assertEqual(LocalVisibilityObservation.objects.filter(observation_id=first.observation_id).count(), 2)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "local-observation-api"}})
class LocalVisibilityApiTests(VisibilityFixture, TestCase):
    def test_actual_private_csrf_observation_correction_context_history_and_request_lookup(self):
        cache.clear()
        url = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/local-visibility/"
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(url).status_code, 401)
        client.force_login(self.owner)
        data = {"request_key": "visibility-api-first", "intake": self.visibility_data, "reason": "Original manual observation."}
        self.assertEqual(client.post(url, json.dumps(data), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        def post(path, payload):
            return client.post(path, json.dumps(payload), content_type="application/json", **headers)
        response = post(url, data)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        row = response.json()["observation"]
        self.assertEqual(row["intake"], self.visibility_data)
        self.assertEqual(row["basis"], "customer_reported_not_provider_verified")
        self.assertEqual(post(url, data).json()["observation"]["id"], row["id"])
        history = url + row["observation_id"] + "/"
        correction = {**data, "request_key": "visibility-api-correction", "expected_revision": 1,
            "intake": {**self.visibility_data, "status": "unavailable", "ordinal": None, "matched_url": "", "inspected_count": 0},
            "reason": "Original manual coverage report was incorrect; unavailable."}
        result = post(history, correction)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertIsNone(result.json()["observation"]["intake"]["ordinal"])
        self.assertEqual(post(history, {**correction, "request_key": "visibility-api-stale"}).status_code, 409)
        self.assertEqual([item["revision"] for item in client.get(history).json()["observations"]], [2, 1])
        current = client.get(url).json()
        self.assertEqual(current["assessments"][0]["locations"], self.assessment.service_areas)
        self.assertEqual(current["method_version"], METHOD)
        self.assertEqual(current["automated_collection"], "unavailable")
        lookup = client.get(url, {"request_key": data["request_key"]}).json()
        self.assertEqual(lookup["lookup"], "found")
        self.assertFalse(lookup["observations"][0]["is_latest"])
        self.assertEqual(client.get(url, {"request_key": "visibility-api-unknown"}).json()["lookup"], "not_found")
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="revoked", revoked_at=timezone.now())
        self.assertFalse(client.get(history).json()["observations"][0]["source_current"])
        self.assertEqual(post(url, {**data, "request_key": "visibility-api-revoked"}).status_code, 403)

    def test_foreign_member_and_unsafe_json_and_non_current_location_do_not_create_observations(self):
        cache.clear()
        url = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/local-visibility/"
        client = Client()
        client.force_login(self.other)
        self.assertEqual(client.get(url).status_code, 404)
        membership = OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        self.assertEqual(client.get(url).status_code, 200)
        self.assertFalse(client.get(url).json()["can_review"])
        self.assertEqual(client.post(url, "{}", content_type="application/json").status_code, 403)
        membership.role = "admin"
        membership.save()
        data = {"request_key": "visibility-api-bad", "intake": self.visibility_data, "reason": "Reason"}
        duplicate = json.dumps(data)[:-1] + ',"reason":"Changed duplicate"}'
        self.assertEqual(client.post(url, duplicate, content_type="application/json").status_code, 409)
        self.assertEqual(client.post(url, "x" * (20 * 1024 + 1), content_type="application/json").status_code, 409)
        self.assertEqual(client.post(url, json.dumps({**data, "intake": {**self.visibility_data, "ordinal": float("nan")}}), content_type="application/json").status_code, 409)
        self.assertEqual(client.get(url + "?request_key=a&request_key=b").status_code, 400)
        self.assertEqual(client.get(url, {"extra": "unsupported"}).status_code, 400)
        self.assertEqual(client.post(url, json.dumps({**data, "intake": {**self.visibility_data, "requested_location": "Unconfigured city"}}), content_type="application/json").status_code, 403)
        self.assertEqual(LocalVisibilityObservation.objects.count(), 0)
