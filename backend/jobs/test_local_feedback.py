from django.test import TransactionTestCase
from datetime import datetime, timezone as utc

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .local_feedback import POLICY_VERSION, SOURCE_KIND, validate_local_feedback


NOW = datetime(2026, 10, 1, 12, tzinfo=utc.utc)
ORIGIN = "https://feedback.example.invalid"


def feedback():
    return {"policy_version": POLICY_VERSION, "source_kind": SOURCE_KIND, "assessment_id": 12,
        "configuration_revision": 3, "source_url": ORIGIN + "/customer-feedback/selected",
        "feedback_reference": "customer-feedback-1", "received_at": "2026-10-01T13:00:00+03:00",
        "feedback_excerpt": "Synthetic own feedback <script>literal</script> &amp;\nTürkçe",
        "theme": "Human judgment, not measured frequency", "reply_draft": "Unapproved human reply draft.",
        "evidence_note": "Independent customer-owned fixture; no provider API or real customer.",
        "storage_permission": True, "not_api_derived": True}


class LocalFeedbackIntakeTests(SimpleTestCase):
    def validate(self, data, **changes):
        return validate_local_feedback(data, **{**dict(approved_origin=ORIGIN, as_of=NOW), **changes})

    def test_scalar_evidence_is_unchanged_frozen_and_missing_theme_or_reply_remains_absent(self):
        data = feedback()
        result = self.validate(data)
        self.assertEqual(result, data)
        self.assertIsNot(result, data)
        result["reply_draft"] = "Changed later"
        self.assertEqual(data["reply_draft"], "Unapproved human reply draft.")
        empty = {**data, "theme": "", "reply_draft": ""}
        self.assertEqual(self.validate(empty), empty)
        self.assertEqual(self.validate(data)["received_at"], "2026-10-01T13:00:00+03:00")

    def test_provider_objects_unknown_scope_and_unaffirmed_permission_fail_without_coercion(self):
        for changes in ({"source_kind": "google_business_profile"}, {"policy_version": "other"},
            {"storage_permission": False}, {"storage_permission": 1}, {"not_api_derived": None},
            {"not_api_derived": "true"}, {"assessment_id": True}, {"assessment_id": 0},
            {"assessment_id": 2**53}, {"configuration_revision": True}, {"configuration_revision": -1},
            {"reviewId": "returned-provider-id"}, {"reviewer": {"displayName": "private"}},
            {"feedback_excerpt": {"comment": "API object"}}, {"feedback_reference": "person@example.invalid"},
            {"feedback_reference": "accounts/1/locations/2/reviews/3"}):
            with self.subTest(keys=list(changes)), self.assertRaises(ValidationError):
                self.validate({**feedback(), **changes})
        for data in ([], None, {}, {key: value for key, value in feedback().items() if key != "storage_permission"}):
            with self.assertRaises(ValidationError):
                self.validate(data)

    def test_same_hostname_is_not_exact_origin_and_source_urls_cannot_carry_query_or_credentials(self):
        for url in ("http://feedback.example.invalid/source", "https://feedback.example.invalid:8443/source",
            "https://foreign.example.invalid/source", "https://maps.google.com/place/selected",
            ORIGIN + "/source?token=secret", ORIGIN + "/source#private", "https://user:password@feedback.example.invalid/source",
            ORIGIN + "/bad path", ORIGIN + "/bad\\path", "javascript:alert(1)"):
            with self.subTest(url_length=len(url)), self.assertRaises(ValidationError):
                self.validate({**feedback(), "source_url": url})
        with self.assertRaises(ValidationError):
            self.validate(feedback(), approved_origin=ORIGIN + "/not-an-origin")

    def test_time_unicode_control_and_actual_serialized_size_bounds(self):
        for changes in ({"received_at": "2026-10-01T14:00:00+00:00"}, {"received_at": "2026-10-01T10:00:00"},
            {"received_at": "not-a-time"}, {"received_at": True}, {"feedback_excerpt": ""},
            {"feedback_excerpt": "x" * 2001}, {"theme": "x" * 501}, {"reply_draft": "x" * 2001},
            {"evidence_note": "  "}, {"theme": "private\x00text"}, {"reply_draft": "\ud800"},
            {"feedback_excerpt": "😀" * 2000, "reply_draft": "😀" * 2000}):
            with self.subTest(keys=list(changes)), self.assertRaises(ValidationError):
                self.validate({**feedback(), **changes})
        self.validate({**feedback(), "received_at": NOW.isoformat()})
        with self.assertRaises(ValidationError):
            self.validate(feedback(), as_of=datetime(2026, 10, 1, 12))
        with self.assertRaises(ValidationError):
            self.validate(feedback(), as_of=False)


from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier
from zipfile import ZipFile
import json
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, transaction, IntegrityError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.core.cache import cache
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import (MembershipRole, Organization, OrganizationMembership, OrganizationTrial,
                            Project, ProjectConfiguration, ProjectOriginVerification)
from tenancy.services import create_organization, create_project
from .local_assessment import review_local_business
from .local_feedback import feedback_source_current, record_local_feedback
from .models import LocalFeedbackReview


class FeedbackFixture:
    def setUp(self):
        self.owner = get_user_model().objects.create_user("feedback-owner@example.invalid", "Test password 9!")
        self.other = get_user_model().objects.create_user("feedback-other@example.invalid", "Test password 9!")
        for user in (self.owner, self.other):
            EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        self.org = create_organization(user=self.owner, name="Synthetic own feedback")
        self.project = create_project(organization=self.org, user=self.owner, name="Feedback fixture", canonical_origin=ORIGIN)
        self.config = ProjectConfiguration.objects.create(project=self.project, service_areas=["Synthetic service region"])
        self.assessment_values = dict(project=self.project, actor=self.owner, request_key="feedback-business-1",
            expected_config_revision=0, location_label="", business_name="Synthetic service business", address_display="",
            phone="", hours="", services=["Actual customer-supplied service"], service_areas=["Synthetic service region"],
            profile_url="", eligibility="unknown", review_theme="", evidence_note="Manual service-area facts; no GBP listing.",
            suggested_action="")
        self.assessment = review_local_business(**self.assessment_values)
        self.verification = ProjectOriginVerification.objects.create(organization=self.org, project=self.project,
            origin=ORIGIN, state="verified", verified_at=timezone.now() - timedelta(minutes=5), challenge_digest="a" * 64)
        self.data = {**feedback(), "assessment_id": self.assessment.pk, "configuration_revision": 0,
                     "received_at": (timezone.now() - timedelta(days=1)).isoformat()}

    def record(self, **changes):
        return record_local_feedback(**{**dict(project=self.project, actor=self.owner, request_key="feedback-draft-1",
            intake=self.data, state="draft", reason="Human source and exact text decision."), **changes})

    def transition(self, row, state, **changes):
        return self.record(**{**dict(feedback_id=row.feedback_id, expected_revision=row.revision, intake=row.intake,
            state=state, request_key=f"feedback-{state}-{row.revision}"), **changes})


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "application/zip"}))
class LocalFeedbackReviewTests(FeedbackFixture, TransactionTestCase):
    def test_exact_review_approval_manual_report_and_correction_never_write_a_source(self):
        draft = self.record()
        self.assertEqual(self.record().pk, draft.pk)
        self.assertEqual(draft.intake, self.data)
        self.data["reply_draft"] = "Later caller dictionary edit"
        draft.refresh_from_db()
        self.assertNotEqual(draft.intake["reply_draft"], self.data["reply_draft"])
        with self.assertRaises(ValidationError):
            self.transition(draft, "approved")
        review = self.transition(draft, "review")
        with self.assertRaises(ValidationError):
            self.transition(review, "approved", intake={**review.intake, "reply_draft": "Unreviewed changed reply"})
        approved = self.transition(review, "approved")
        self.assertEqual((approved.reviewed_revision_id, approved.approved_by_id), (review.pk, self.owner.pk))
        self.assertIsNone(approved.executed_at)
        with self.assertRaises(ValidationError):
            self.transition(approved, "reported", executed_at=approved.approved_at - timedelta(seconds=1), execution_note="Wrong time")
        reported = self.transition(approved, "reported", executed_at=timezone.now(), execution_note="Human reports same exact reply on own website.")
        self.assertEqual(reported.reviewed_revision_id, review.pk)
        corrected = self.transition(reported, "draft", intake={**reported.intake, "source_url": ORIGIN + "/changed-target",
            "reply_draft": "New human text"})
        self.assertIsNone(corrected.approved_by_id)
        self.assertIsNone(corrected.reviewed_revision_id)
        self.assertIsNone(corrected.executed_at)
        with self.assertRaises(ValidationError):
            draft.save()
        with self.assertRaises(ValidationError):
            self.transition(review, "approved", request_key="feedback-stale-approval")
        from .models import JobRun, Artifact
        self.assertEqual((JobRun.objects.count(), Artifact.objects.count()), (0, 0))

    def test_scope_role_revoked_actor_and_email_fail_closed(self):
        with self.assertRaises(PermissionDenied):
            self.record(actor=self.other)
        membership = OrganizationMembership.objects.create(organization=self.org, user=self.other, role=MembershipRole.MEMBER)
        with self.assertRaises(PermissionDenied):
            self.record(actor=self.other)
        membership.role = MembershipRole.ADMIN
        membership.save()
        draft = self.record(actor=self.other)
        review = self.transition(draft, "review")
        membership.role = MembershipRole.MEMBER
        membership.save()
        self.assertFalse(feedback_source_current(review))
        with self.assertRaises(PermissionDenied):
            self.transition(review, "approved")
        membership.role = MembershipRole.ADMIN
        membership.save()
        get_user_model().objects.filter(pk=self.other.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.record(actor=self.other, request_key="feedback-stale-loaded-actor")
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        with self.assertRaises(PermissionDenied):
            self.record(request_key="feedback-unverified-owner")

    def test_actual_business_config_and_exact_verification_snapshot_are_required(self):
        foreign = Project.objects.create(organization=self.org, name="Foreign synthetic project", canonical_origin="https://foreign.example.invalid")
        with self.assertRaises(PermissionDenied):
            self.record(project=foreign)
        with self.assertRaises(PermissionDenied):
            self.record(intake={**self.data, "assessment_id": self.assessment.pk + 1000})
        draft = self.record()
        review = self.transition(draft, "review")
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(verified_at=timezone.now())
        self.assertFalse(feedback_source_current(review))
        with self.assertRaises(PermissionDenied):
            self.transition(review, "approved")
        replacement = self.transition(review, "draft")
        self.assertTrue(feedback_source_current(replacement))
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="revoked", revoked_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.transition(replacement, "review")
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="verified", revoked_at=None)
        review_local_business(**{**self.assessment_values, "request_key": "feedback-business-2", "expected_revision": 1})
        with self.assertRaises(PermissionDenied):
            self.record(request_key="feedback-old-assessment")
        self.config.revision = 1
        self.config.save(update_fields=["revision"])
        with self.assertRaises(PermissionDenied):
            self.record(request_key="feedback-old-configuration")

    def test_database_checks_cannot_forge_approval_and_edited_source_cannot_skip_draft(self):
        draft = self.record()
        with self.assertRaises(IntegrityError), transaction.atomic():
            LocalFeedbackReview.objects.filter(pk=draft.pk).update(state="approved")
        for key, value in (("source_url", ORIGIN + "/another"), ("theme", "Changed human interpretation"),
                           ("feedback_excerpt", "Different source text"), ("feedback_reference", "different-ref")):
            with self.subTest(field=key), self.assertRaises(ValidationError):
                self.transition(draft, "review", intake={**draft.intake, key: value})
        with self.assertRaises(ValidationError):
            self.record(request_key="feedback-empty-review", state="review", intake={**self.data, "reply_draft": ""})

    def test_private_export_labels_stale_history_and_closure_deletes_self_references(self):
        from tenancy.customer_export import complete_bounded_customer_archive, project_customer_rows
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        draft = self.record()
        approved = self.transition(self.transition(draft, "review"), "approved")
        with ZipFile(BytesIO(complete_bounded_customer_archive(organization=self.org, actor=self.owner))) as archive:
            rows = json.loads(archive.read("records/jobs/LocalFeedbackReview.json"))
            self.assertEqual(rows[-1]["intake"], approved.intake)
            self.assertNotIn("request_key", rows[-1])
            self.assertEqual(rows[-1]["scope"], "historical_customer_record_not_current_manual_use_authorization")
        ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="revoked", revoked_at=timezone.now())
        rows = project_customer_rows(organization=self.org, actor=self.owner, model_label="jobs.LocalFeedbackReview",
                                     after_id=0, through_id=approved.pk)["rows"]
        self.assertFalse(rows[-1]["source_current_at_capture"])
        with self.assertRaises(PermissionDenied):
            self.transition(approved, "reported", executed_at=timezone.now(), execution_note="Not allowed")
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            self.record(request_key="feedback-closed-project")
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.org))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(LocalFeedbackReview.objects.exists())

    def test_expiry_allows_retained_history_but_retention_cutoff_denies_operations(self):
        now = timezone.now()
        draft = self.record()
        OrganizationTrial.objects.filter(organization=self.org).update(started_at=now - timedelta(days=60), ends_at=now - timedelta(days=30))
        self.assertTrue(feedback_source_current(draft))
        self.transition(draft, "review")  # Zero-provider-cost manual review stays available during retention.
        OrganizationTrial.objects.filter(organization=self.org).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied):
            self.record(request_key="feedback-retention-cutoff")

    def test_actual_private_stored_and_sequential_exports_are_historical_not_manual_use_grants(self):
        from tenancy.customer_snapshot import (reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot,
                                               private_snapshot_part)
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        approved = self.transition(self.transition(self.record(), "review"), "approved")
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            bounded = reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner, request_key="a" * 32)
            self.assertTrue(capture_reserved_customer_snapshot(bounded.pk))
            data, _digest = private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=bounded.pk, position=0)
            with ZipFile(BytesIO(data)) as archive:
                row = json.loads(archive.read("records/jobs/LocalFeedbackReview.json"))[-1]
                self.assertTrue(row["source_current_at_capture"])
                self.assertEqual(row["scope"], "historical_customer_record_not_current_manual_use_authorization")
            ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="revoked", revoked_at=timezone.now())
            # Retained customer history/export rights survive source loss, but never grant manual reply use.
            self.assertEqual(private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=bounded.pk, position=0)[0], data)
            with self.assertRaises(PermissionDenied):
                self.transition(approved, "reported", executed_at=timezone.now(), execution_note="Denied stale-source use")
            sequential = reserve_bounded_customer_snapshot(organization=self.org, actor=self.owner,
                request_key="b" * 32, format="source-parts-v2")
            for _ in range(len(CUSTOMER) * 2 + 10):
                sequential.refresh_from_db()
                if sequential.state != sequential.State.PREPARING:
                    break
                self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
            sequential.refresh_from_db()
            self.assertEqual(sequential.state, sequential.State.READY)
            part = sequential.parts.filter(source__model="jobs.LocalFeedbackReview").first()
            data, _digest = private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=sequential.pk, position=part.position)
            with ZipFile(BytesIO(data)) as archive:
                row = json.loads(archive.read("data"))[-1]
                self.assertEqual(row["intake"], approved.intake)
                self.assertFalse(row["source_current_at_capture"])
                self.assertNotIn("request_key", row)
        with self.assertRaises(PermissionDenied):
            private_snapshot_part(organization=self.org, actor=self.other, snapshot_id=bounded.pk, position=0)
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            private_snapshot_part(organization=self.org, actor=self.owner, snapshot_id=bounded.pk, position=0)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.org))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(LocalFeedbackReview.objects.exists())


class LocalFeedbackConcurrencyTests(FeedbackFixture, TransactionTestCase):
    def test_two_postgresql_connections_cannot_overwrite_the_same_review_revision(self):
        draft = self.record()
        barrier = Barrier(2)
        def write(key):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return self.transition(draft, "review", request_key=key).revision
                except ValidationError:
                    return "conflict"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ["feedback-concurrent-1", "feedback-concurrent-2"]))
        self.assertCountEqual(results, [2, "conflict"])
        self.assertEqual(LocalFeedbackReview.objects.filter(feedback_id=draft.feedback_id).count(), 2)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "feedback-api-fixtures"}})
class LocalFeedbackApiTests(FeedbackFixture, TestCase):
    def test_authenticated_csrf_native_review_history_and_exact_request_reconciliation(self):
        cache.clear()
        url = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/local-feedback/"
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(url).status_code, 401)
        client.force_login(self.owner)
        payload = {"request_key": "feedback-api-draft", "intake": self.data, "state": "draft",
                   "reason": "Actual human decision", "executed_at": None, "execution_note": ""}
        self.assertEqual(client.post(url, json.dumps(payload), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        def post(path, data):
            return client.post(path, json.dumps(data), content_type="application/json", **headers)
        response = post(url, payload)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        row = response.json()["review"]
        self.assertEqual(row["intake"], self.data)
        self.assertEqual(post(url, payload).json()["review"]["id"], row["id"])
        history = url + row["feedback_id"] + "/"
        for state in ("review", "approved", "reported"):
            payload = {**payload, "request_key": "feedback-api-" + state, "state": state, "expected_revision": row["revision"]}
            if state == "reported":
                payload.update(executed_at=timezone.now().isoformat(), execution_note="User reports exact approved reply manually.")
            result = post(history, payload)
            self.assertEqual(result.status_code, 200, result.content)
            row = result.json()["review"]
        current = client.get(url).json()
        self.assertEqual(current["verified_origins"], [ORIGIN])
        self.assertEqual(current["assessments"][0]["id"], self.assessment.pk)
        self.assertEqual(current["reviews"][0]["execution_state"], "customer_reported_not_verified")
        self.assertTrue(current["reviews"][0]["effective_approval"])
        self.assertEqual([item["revision"] for item in client.get(history).json()["reviews"]], [4, 3, 2, 1])
        lookup = client.get(url, {"request_key": "feedback-api-approved"}).json()
        self.assertEqual(lookup["lookup"], "found")
        self.assertFalse(lookup["reviews"][0]["is_latest"])
        self.assertFalse(lookup["reviews"][0]["effective_approval"])
        self.assertEqual(client.get(url, {"request_key": "feedback-unknown"}).json()["lookup"], "not_found")
        self.assertEqual(post(history, payload).status_code, 200)  # Idempotent report, no replayed source write.
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        self.assertFalse(client.get(url).json()["can_review"])
        self.assertFalse(client.get(url).json()["reviews"][0]["source_current"])
        self.assertEqual(post(history, payload).status_code, 403)

    def test_foreign_member_stale_source_and_duplicate_or_oversized_json_are_denied(self):
        cache.clear()
        draft = self.record()
        url = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/local-feedback/"
        history = url + str(draft.feedback_id) + "/"
        client = Client()
        client.force_login(self.other)
        self.assertEqual(client.get(history).status_code, 404)
        membership = OrganizationMembership.objects.create(organization=self.org, user=self.other, role="member")
        self.assertEqual(client.get(history).status_code, 200)
        self.assertFalse(client.get(url).json()["can_review"])
        self.assertEqual(client.get(url).json()["assessments"], [])
        self.assertEqual(client.post(history, "{}", content_type="application/json").status_code, 403)
        membership.role = "admin"
        membership.save()
        payload = dict(request_key="feedback-bad-json", intake=self.data, state="draft", reason="Reason", executed_at=None, execution_note="")
        duplicate = json.dumps(payload)[:-1] + ',"state":"approved"}'
        self.assertEqual(client.post(url, duplicate, content_type="application/json").status_code, 409)
        self.assertEqual(client.post(url, "x" * (36 * 1024 + 1), content_type="application/json").status_code, 409)
        self.assertEqual(client.post(url, json.dumps({**payload, "intake": {**self.data, "theme": float("nan")}}), content_type="application/json").status_code, 409)
        self.assertEqual(client.get(url + "?request_key=a&request_key=b").status_code, 400)
        self.assertEqual(client.get(url, {"extra": "invalid"}).status_code, 400)
        self.assertEqual(LocalFeedbackReview.objects.count(), 1)
        self.config.revision += 1
        self.config.save(update_fields=["revision"])
        response = client.get(history).json()
        self.assertFalse(response["reviews"][0]["source_current"])
        self.assertEqual(response["assessments"], [])
        self.assertEqual(client.post(url, json.dumps(payload), content_type="application/json").status_code, 403)
