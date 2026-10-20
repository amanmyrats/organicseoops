from tenancy.customer_artifact_barrier import project_artifact_barrier
import json
from io import BytesIO
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from zipfile import ZipFile

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.mfa.models import Authenticator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from config.test_foundations import TEST_STORAGES

from . import support_staff as staff
from .models import AuditEvent, AuditEventType, Organization, SupportRequest, SupportRequestUpdate
from .support_requests import own_support_requests
from . import test_support_requests as request_fixtures


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES,
                   ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "application/zip"}))
class SupportStaffTests(TransactionTestCase):
    command = request_fixtures.SupportRequestTests.command
    submit = request_fixtures.SupportRequestTests.submit
    queue = request_fixtures.SupportRequestTests.queue
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        request_fixtures.SupportRequestTests.setUp(self)
        self.staff = get_user_model().objects.create_user("support-staff@example.invalid", password="fixture-password", is_staff=True)
        self.staff.user_permissions.add(*Permission.objects.filter(codename__in=["view_supportrequest", "change_supportrequest"], content_type__app_label="tenancy"))
        self.client.force_login(self.staff)
        Authenticator.objects.create(user=self.staff, type=Authenticator.Type.TOTP, data={"secret": "unused-fixture"})
        session = self.client.session
        session[AUTHENTICATION_METHODS_SESSION_KEY] = [{"method": "mfa", "at": timezone.now().timestamp()}]; session.save()
        self.request = RequestFactory().post("/admin/tenancy/supportrequest/scoped/")
        self.request.user, self.request.session = self.staff, self.client.session
        self.request_id = self.submit()["request"]["id"]

    def inspect_staff(self, **changes):
        return staff.inspect_staff_support(**{**dict(request=self.request, organization_id=self.organization.pk,
            project_id=self.project.pk, request_id=self.request_id, reason="customer_request"), **changes})

    def update(self, **changes):
        return self.inspect_staff(command={**dict(request_key="staff-response-001", expected_revision=0,
                                                   status="in_progress", response="We are investigating this job reference."), **changes})

    def test_exact_mfa_permission_scoped_access_and_append_only_current_status_prose_free_audits(self):
        initial = self.inspect_staff()
        self.assertEqual(initial["request"]["question"], "Why did my job stop?")
        saved = self.update()
        self.assertEqual(saved["request"]["revision"], 1)
        self.assertEqual(saved["request"]["status"], "in_progress")
        self.assertEqual(self.update(), saved)
        self.assertEqual(SupportRequestUpdate.objects.count(), 1)
        resolved = self.update(request_key="staff-response-002", expected_revision=1, status="resolved", response="The issue has been reviewed.")
        self.assertEqual(resolved["request"]["revision"], 2)
        self.assertEqual([row["revision"] for row in resolved["request"]["updates"]], [2, 1])
        own = own_support_requests(project=self.project, actor=self.owner, request_id=self.request_id)
        self.assertEqual(own["request"], resolved["request"])
        events = AuditEvent.objects.filter(event_type__startswith="support.")
        self.assertEqual(events.filter(event_type=AuditEventType.SUPPORT_REQUEST_UPDATED).count(), 2)
        self.assertEqual(events.filter(event_type=AuditEventType.SUPPORT_REQUEST_ACCESSED).count(), 4)
        for event in events:
            self.assertEqual((event.organization_id, event.project_id, event.actor_id), (self.organization.pk, self.project.pk, self.staff.pk))
            self.assertNotIn("question", event.details); self.assertNotIn("response", event.details)
        first = events.filter(event_type=AuditEventType.SUPPORT_REQUEST_UPDATED).order_by("pk").first()
        self.assertEqual(first.details["before"], {"status": "received", "revision": 0})
        row = SupportRequestUpdate.objects.first(); row.response = "Overwrite"
        with self.assertRaises(ValidationError): row.save()
        with self.assertRaises(ValidationError): self.update(response="Different original response")
        with self.assertRaises(ValidationError): self.update(request_key="stale-response-003")

    def test_staff_flag_customer_roles_missing_totp_or_persisted_session_never_grant_content_access(self):
        for mutate in (lambda: self.staff.user_permissions.clear(),
                       lambda: get_user_model().objects.filter(pk=self.staff.pk).update(is_staff=False),
                       lambda: get_user_model().objects.filter(pk=self.staff.pk).update(is_active=False),
                       lambda: Authenticator.objects.filter(user=self.staff).delete(),
                       lambda: Session.objects.filter(session_key=self.request.session.session_key).delete()):
            self.request.session = self.client.session
            with transaction.atomic():
                mutate()
                with self.assertRaises(PermissionDenied): self.inspect_staff()
                transaction.set_rollback(True)
        self.request.session = self.client.session
        self.staff.user_permissions.remove(Permission.objects.get(codename="change_supportrequest", content_type__app_label="tenancy"))
        self.assertEqual(self.inspect_staff()["request"]["id"], self.request_id)
        with self.assertRaises(PermissionDenied): self.update()
        session = self.client.session; session[AUTHENTICATION_METHODS_SESSION_KEY] = []; session.save()
        with self.assertRaises(PermissionDenied): self.inspect_staff()
        self.assertFalse(SupportRequestUpdate.objects.exists())

    def test_wrong_scope_category_input_and_suspended_closed_retention_access_denied(self):
        for changes in ({"organization_id": self.other_org.pk}, {"project_id": self.other_project.pk}, {"request_id": self.request_id + 99999}):
            with self.assertRaises(PermissionDenied): self.inspect_staff(**changes)
        for changes in ({"reason": "free text"}, {"reason": True}, {"request_id": 2**53}, {"organization_id": 0}):
            with self.assertRaises(ValidationError): self.inspect_staff(**changes)
        for changes in ({"response": "api_key=private"}, {"response": ""}, {"response": "x" * 2001},
                        {"status": "sent"}, {"expected_revision": True}, {"expected_revision": 2**31}, {"recipient_id": 1}):
            with self.assertRaises(ValidationError): self.update(**changes)
        for fields in ({"is_suspended": True}, {"is_suspended": True, "closed_at": timezone.now()}):
            with transaction.atomic():
                Organization.objects.filter(pk=self.organization.pk).update(**fields)
                with self.assertRaises(PermissionDenied): self.inspect_staff()
                transaction.set_rollback(True)
        self.assertFalse(AuditEvent.objects.filter(event_type__startswith="support.").exists())

    def test_after_insert_scope_session_permission_and_audit_failure_roll_back_response_and_access(self):
        create = SupportRequestUpdate.objects.create
        for mutate, error in ((lambda: self.staff.user_permissions.clear(), PermissionDenied),
                              (lambda: Session.objects.filter(session_key=self.request.session.session_key).delete(), PermissionDenied),
                              (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), PermissionDenied),
                              (lambda: SupportRequest.objects.filter(pk=self.request_id).update(question="Changed source"), ValidationError)):
            self.request.session = self.client.session
            def changed(**kwargs):
                result = create(**kwargs); mutate(); return result
            with patch("tenancy.support_staff.SupportRequestUpdate.objects.create", side_effect=changed), self.assertRaises(error): self.update()
            self.assertFalse(SupportRequestUpdate.objects.exists())
            self.assertFalse(AuditEvent.objects.filter(event_type__startswith="support.").exists())
        self.request.session = self.client.session
        with patch("tenancy.support_staff.AuditEvent.objects.create", side_effect=RuntimeError("fixture audit failure")), self.assertRaises(RuntimeError): self.update()
        self.assertFalse(SupportRequestUpdate.objects.exists())

    def test_full_customer_response_lifecycle_reuses_actual_request_export_and_erasure(self):
        self.update()
        from accounts.closure import close_personal_access
        from config.artifacts import read_private_artifact
        from .customer_export import project_customer_rows, _reviewed_fields, complete_bounded_customer_archive
        from .customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot
        from .customer_source_parts import capture_source_stage, FORMAT
        from .deletion import _customer_deletion_order, prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        _reviewed_fields("tenancy.SupportRequestUpdate")
        row = SupportRequestUpdate.objects.get()
        exported = project_customer_rows(organization=self.organization, actor=self.owner,
            model_label="tenancy.SupportRequestUpdate", after_id=0, through_id=row.pk)
        self.assertEqual(exported["rows"][0]["response"], row.response)
        self.assertNotIn("request_key", exported["rows"][0])
        labels = [model._meta.label for model, _ in _customer_deletion_order()]
        self.assertLess(labels.index("tenancy.SupportRequestUpdate"), labels.index("tenancy.SupportRequest"))
        with ZipFile(BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            self.assertEqual(json.loads(archive.read("records/tenancy/SupportRequestUpdate.json"))[0]["response"], row.response)
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            stored = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="b" * 32)
            self.assertTrue(capture_reserved_customer_snapshot(stored.pk))
            stored.refresh_from_db(); self.assertEqual(stored.state, stored.State.READY)
            with ZipFile(BytesIO(b"".join(read_private_artifact(part.storage_key) for part in stored.parts.order_by("position")))) as archive:
                self.assertEqual(json.loads(archive.read("records/tenancy/SupportRequestUpdate.json"))[0]["response"], row.response)
            snapshot = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="c" * 32, format=FORMAT)
            for _ in range(200):
                snapshot.refresh_from_db()
                if snapshot.state != snapshot.State.PREPARING: break
                self.assertTrue(capture_source_stage(snapshot.pk, snapshot.progress.get("step", 0)))
            snapshot.refresh_from_db(); self.assertEqual(snapshot.state, snapshot.State.READY)
            part = snapshot.parts.get(source__model="tenancy.SupportRequestUpdate")
            with ZipFile(BytesIO(read_private_artifact(part.storage_key))) as archive:
                self.assertEqual(json.loads(archive.read("data"))[0]["response"], row.response)
        with project_artifact_barrier(self.organization.pk, shared=True), transaction.atomic():
            Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())
            run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
            delete_customer_database_records(run=run)
            self.assertFalse(SupportRequestUpdate.objects.exists())
            self.assertFalse(AuditEvent.objects.filter(event_type__startswith="support.").exists())
            transaction.set_rollback(True)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())
        request = RequestFactory().post("/api/account/close/"); request.user = self.owner
        with patch("tenancy.services.did_recently_authenticate", return_value=True): close_personal_access(actor=self.owner, request=request)
        self.assertFalse(SupportRequestUpdate.objects.filter(request_id=self.request_id).exists())

    def test_genuine_response_history_cap_complete_ordered_reread_and_date_corruption(self):
        self.update()
        for revision in range(2, 22):
            self.update(request_key=f"response-history-{revision:04d}", expected_revision=revision - 1,
                        status="received" if revision == 21 else "in_progress", response=f"Response revision {revision}")
        result = own_support_requests(project=self.project, actor=self.owner, request_id=self.request_id)["request"]
        self.assertEqual((result["status"], result["revision"], result["updates_has_more"]), ("received", 21, True))
        self.assertEqual([row["revision"] for row in result["updates"]], list(range(21, 1, -1)))
        original = staff.validate_staff_update
        def changed(command):
            result = original(command)
            SupportRequestUpdate.objects.filter(request_id=self.request_id, revision=1).update(response="Changed covered overflow original")
            return result
        with patch("tenancy.support_staff.validate_staff_update", side_effect=changed), self.assertRaises(ValidationError):
            own_support_requests(project=self.project, actor=self.owner, request_id=self.request_id)
        SupportRequestUpdate.objects.filter(request_id=self.request_id, revision=21).update(created_at=timezone.now() + timedelta(seconds=1))
        with self.assertRaises(ValidationError): self.inspect_staff()


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES)
class ConcurrentSupportUpdateTests(TransactionTestCase):
    command = SupportStaffTests.command
    submit = SupportStaffTests.submit
    setUp = SupportStaffTests.setUp

    def test_two_sessions_expected_revision_zero_only_one_response_and_audit(self):
        session_key, store = self.request.session.session_key, self.request.session.__class__
        def update(index):
            connections.close_all()
            try:
                request = RequestFactory().post("/admin/tenancy/supportrequest/scoped/")
                request.user, request.session = self.staff, store(session_key=session_key)
                staff.inspect_staff_support(request=request, organization_id=self.organization.pk, project_id=self.project.pk,
                    request_id=self.request_id, reason="customer_request", command=dict(request_key=f"race-response-{index}",
                        expected_revision=0, status="in_progress", response=f"Response {index}"))
                return "saved"
            except ValidationError: return "stale"
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor: results = list(executor.map(update, range(2)))
        self.assertCountEqual(results, ["saved", "stale"])
        self.assertEqual(SupportRequestUpdate.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.SUPPORT_REQUEST_UPDATED).count(), 1)
