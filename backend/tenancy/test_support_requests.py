from tenancy.customer_artifact_barrier import project_artifact_barrier
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections, IntegrityError, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from jobs import tests as fixtures
from jobs.models import JobRun
from jobs.services import run_diagnostic
from jobs.usage import settle_usage
from . import support_requests as support
from .models import Organization, OrganizationMembership, OrganizationTrial, Project, ProjectMembership, SupportRequest


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES,
                   ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "application/zip"}))
class SupportRequestTests(TransactionTestCase):
    setUp = fixtures.JobFoundationTests.setUp
    queue = fixtures.JobFoundationTests.queue

    def command(self, **changes):
        return {**dict(request_key="support-request-001", category="job", question="Why did my job stop?",
                       job_id=None, no_sensitive_data=True), **changes}

    def submit(self, **changes):
        return support.create_support_request(project=self.project, actor=self.owner, command=self.command(**changes))

    def inspect(self, request_id=None, **changes):
        return support.own_support_requests(**{**dict(project=self.project, actor=self.owner, request_id=request_id), **changes})

    def test_real_job_binding_duplicate_original_dates_and_private_minimization_without_effects(self):
        job = run_diagnostic(self.queue())
        private = "poison-only-private-job-marker"
        JobRun.objects.filter(pk=job.pk).update(input_snapshot={"private": private}, output={"raw": private},
                                              config_snapshot={"secret": private}, error_category=private)
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("jobs.services.dispatch_pending", side_effect=AssertionError("dispatch")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")):
            result = self.submit(job_id=job.pk)
            self.assertEqual(self.submit(job_id=job.pk), result)
            detail = self.inspect(result["request"]["id"])
            self.assertEqual(detail, result)
            history = self.inspect()
        row = SupportRequest.objects.get()
        self.assertEqual(result["request"], dict(id=row.pk, category="job", job_id=job.pk,
            question="Why did my job stop?", status="received", created_at=row.created_at.isoformat(),
            revision=0, updates=[], updates_has_more=False))
        self.assertEqual(history["requests"], [{key: value for key, value in result["request"].items()
                                              if key not in {"question", "updates", "updates_has_more"}}])
        self.assertFalse(history["has_more"])
        self.assertFalse(any(field in query["sql"] for query in queries for field in
                             ('"input_snapshot"', '"config_snapshot"', '"output"', '"error_category"', '"dispatch_error"')))
        for value in (private, self.owner.email, self.project.canonical_origin, "requester_id", "request_key", "no_sensitive_data"):
            self.assertNotIn(value, json.dumps(result))
        for changes in ({"question": "Different question"}, {"job_id": None}, {"category": "other"}):
            with self.assertRaises(ValidationError): self.submit(**changes)
        self.assertEqual(SupportRequest.objects.count(), 1)
        # Later real job progress does not rewrite a historical request or block exact reconciliation.
        JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now())
        self.assertEqual(self.submit(job_id=job.pk), result)
        with transaction.atomic():
            JobRun.objects.filter(pk=job.pk).update(project=self.other_project, organization=self.other_org)
            with self.assertRaises(ValidationError): self.inspect(row.pk)
            with self.assertRaises(ValidationError): self.submit(job_id=job.pk)
            transaction.set_rollback(True)
        row.question = "Rewrite"
        with self.assertRaises(ValidationError): row.save()
        with self.assertRaises(ValidationError): SupportRequest(pk=row.pk, project=self.project,
            requester=self.owner, **self.command()).save()

    def test_exact_scalar_text_category_declaration_and_database_constraints(self):
        invalid = [{"question": value} for value in (None, True, [], "", " \n\t", "x" * 2001, "bad\x00text", "bad\rtext",
                   "bad\u202etext", "bad\ud800text", "Authorization: Bearer hidden", "password=hidden", "api_key: hidden")]
        invalid += [{"no_sensitive_data": value} for value in (False, 1, "true", None)]
        invalid += [{"category": value} for value in (True, [], "unknown")]
        invalid += [{"job_id": value} for value in (True, "1", 0, -1, 2**53, 1.5)]
        invalid += [{"request_key": value} for value in (True, "short", "x" * 65, "invalid key", "x\n" * 4)]
        for changes in invalid:
            with self.subTest(changes=repr(changes)), self.assertRaises(ValidationError): self.submit(**changes)
        for command in ([], {**self.command(), "recipient_id": self.outsider.pk}, {key: value for key, value in self.command().items() if key != "job_id"}):
            with self.assertRaises(ValidationError): support.validate_support_command(command)
        self.assertFalse(SupportRequest.objects.exists())
        self.submit(question="<script>inert customer text</script>\nTürkçe\t" + "😀" * 1900)
        row = SupportRequest.objects.get()
        for values in ({"category": "unknown"}, {"request_key": "bad"}, {"no_sensitive_data": False}, {"question": ""}):
            with self.assertRaises(IntegrityError), transaction.atomic(): SupportRequest.objects.filter(pk=row.pk).update(**values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SupportRequest.objects.bulk_create([SupportRequest(project=self.project, requester=self.owner, **self.command())])

    def test_own_requester_foreign_missing_restricted_and_retained_read_only_scope(self):
        row_id = self.submit()["request"]["id"]
        viewer = get_user_model().objects.create_user("support-viewer@example.invalid")
        membership = OrganizationMembership.objects.create(organization=self.organization, user=viewer, role="viewer")
        self.assertIsNone(self.inspect(row_id, actor=viewer)["request"])
        own = support.create_support_request(project=self.project, actor=viewer, command=self.command())
        self.assertNotEqual(own["request"]["id"], row_id)
        self.assertEqual([item["id"] for item in self.inspect(actor=viewer)["requests"]], [own["request"]["id"]])
        self.assertIsNone(self.inspect(row_id + 99999)["request"])
        for operation in (lambda: self.inspect(row_id, project=self.other_project),
                          lambda: self.inspect(row_id, actor=self.outsider),
                          lambda: support.create_support_request(project=self.project, actor=self.outsider, command=self.command())):
            with self.assertRaises(PermissionDenied): operation()
        # Support stays available inside the real retained window; costly eligibility is not a role.
        OrganizationTrial.objects.filter(organization=self.organization).update(
            started_at=timezone.now() - timedelta(days=31), ends_at=timezone.now() - timedelta(days=1))
        self.assertEqual(self.inspect(row_id)["request"]["id"], row_id)
        self.submit(request_key="after-trial-expiry")
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        with self.assertRaises(PermissionDenied): self.inspect(actor=viewer)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(self.inspect(actor=viewer)["requests"][0]["id"], own["request"]["id"])
        OrganizationTrial.objects.filter(organization=self.organization).update(
            started_at=timezone.now() - timedelta(days=122), ends_at=timezone.now() - timedelta(days=92))
        with self.assertRaises(PermissionDenied): self.inspect()

    def test_insert_final_reader_job_loss_and_failure_roll_back_without_partial_request(self):
        job = run_diagnostic(self.queue())
        create = SupportRequest.objects.create
        mutations = [(lambda: OrganizationMembership.objects.filter(user=self.owner, organization=self.organization).delete(), PermissionDenied),
                     (lambda: get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False), PermissionDenied),
                     (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), PermissionDenied),
                     (lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now()), PermissionDenied),
                     (lambda: JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now()), ValidationError),
                     (lambda: JobRun.objects.filter(pk=job.pk).update(organization_id=self.other_org.pk), ValidationError)]
        for mutate, error in mutations:
            def changed(**kwargs):
                row = create(**kwargs); mutate(); return row
            with patch("tenancy.support_requests.SupportRequest.objects.create", side_effect=changed), self.assertRaises(error):
                self.submit(job_id=job.pk)
            self.assertFalse(SupportRequest.objects.exists())
        for identity in (job.pk + 99999,):
            with self.assertRaises(ValidationError): self.submit(job_id=identity)
        with self.assertRaises(ValidationError): support.create_support_request(project=self.other_project,
            actor=self.outsider, command=self.command(job_id=job.pk))
        with patch("tenancy.support_requests.SupportRequest.objects.create", side_effect=RuntimeError("fixture storage failure")), self.assertRaises(RuntimeError):
            self.submit()
        self.assertEqual(self.submit()["request"]["status"], "received")

    def test_original_history_full_selection_and_final_reader_loss_denies_no_writes(self):
        request_id = self.submit()["request"]["id"]
        original = support._row
        for mutate, error in ((lambda: SupportRequest.objects.filter(pk=request_id).update(question="Changed original"), ValidationError),
                              (lambda: SupportRequest.objects.filter(pk=request_id).update(created_at=timezone.now()), ValidationError),
                              (lambda: OrganizationMembership.objects.filter(user=self.owner, organization=self.organization).delete(), PermissionDenied)):
            with transaction.atomic():
                def changed(row, assessed, **kwargs):
                    result = original(row, assessed, **kwargs); mutate(); return result
                with patch("tenancy.support_requests._row", side_effect=changed), self.assertRaises(error): self.inspect(request_id)
                transaction.set_rollback(True)
        with CaptureQueriesContext(connection) as queries: self.inspect(request_id); self.inspect()
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries))
        with transaction.atomic():
            SupportRequest.objects.filter(pk=request_id).update(created_at=timezone.now() + timedelta(seconds=1))
            with self.assertRaises(ValidationError): self.inspect()
            transaction.set_rollback(True)
        for identity in (True, 0, "1", 2**53):
            with self.assertRaises(ValidationError): self.inspect(identity)

    def test_explicit_synthetic_history_cap_orders_and_checks_twenty_first_row(self):
        stamp = timezone.now()
        SupportRequest.objects.bulk_create([SupportRequest(project=self.project, requester=self.owner,
            **self.command(request_key=f"synthetic-{index:08d}"), created_at=stamp) for index in range(21)])
        ids = list(SupportRequest.objects.order_by("-pk").values_list("pk", flat=True))
        result = self.inspect()
        self.assertTrue(result["has_more"])
        self.assertEqual([row["id"] for row in result["requests"]], ids[:20])
        original = support._row
        def changed(row, assessed, **kwargs):
            result = original(row, assessed, **kwargs)
            SupportRequest.objects.filter(pk=ids[-1]).update(question="Changed overflow original")
            return result
        with patch("tenancy.support_requests._row", side_effect=changed), self.assertRaises(ValidationError): self.inspect()

    def test_actual_customer_export_source_parts_erasure_and_personal_close(self):
        from accounts.closure import close_personal_access
        from config.artifacts import read_private_artifact
        from .customer_export import project_customer_rows, complete_bounded_customer_archive, _reviewed_fields
        from .customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot
        from .customer_source_parts import capture_source_stage, FORMAT
        from .deletion import _customer_deletion_order, prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        job = run_diagnostic(self.queue()); settle_usage(job=job, actual_units=0)
        request_id = self.submit(job_id=job.pk)["request"]["id"]
        foreign = support.create_support_request(project=self.other_project, actor=self.outsider, command=self.command())["request"]["id"]
        _reviewed_fields("tenancy.SupportRequest")
        order = [model._meta.label for model, _ in _customer_deletion_order()]
        for parent in ("tenancy.Project", "jobs.JobRun"):
            self.assertLess(order.index("tenancy.SupportRequest"), order.index(parent))
        rows = project_customer_rows(organization=self.organization, actor=self.owner,
                                    model_label="tenancy.SupportRequest", after_id=0, through_id=foreign)
        self.assertEqual([row["id"] for row in rows["rows"]], [request_id])
        self.assertEqual(rows["rows"][0]["question"], "Why did my job stop?")
        self.assertNotIn("request_key", rows["rows"][0])
        with ZipFile(BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            self.assertIn(b"Why did my job stop?", archive.read("records/tenancy/SupportRequest.json"))
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            stored = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="b" * 32)
            self.assertTrue(capture_reserved_customer_snapshot(stored.pk))
            stored.refresh_from_db(); self.assertEqual(stored.state, stored.State.READY)
            with ZipFile(BytesIO(b"".join(read_private_artifact(part.storage_key) for part in stored.parts.order_by("position")))) as archive:
                self.assertEqual(json.loads(archive.read("records/tenancy/SupportRequest.json"))[0]["id"], request_id)
            snapshot = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner,
                                                         request_key="d" * 32, format=FORMAT)
            for _ in range(200):
                snapshot.refresh_from_db()
                if snapshot.state != snapshot.State.PREPARING: break
                self.assertTrue(capture_source_stage(snapshot.pk, snapshot.progress.get("step", 0)))
        snapshot.refresh_from_db(); self.assertEqual(snapshot.state, snapshot.State.READY)
        part = snapshot.parts.get(source__model="tenancy.SupportRequest")
        with ZipFile(BytesIO(read_private_artifact(part.storage_key))) as archive:
            self.assertEqual(json.loads(archive.read("data"))[0]["id"], request_id)
            self.assertNotIn(b"support-request-001", archive.read("data"))
        with project_artifact_barrier(self.organization.pk, shared=True), transaction.atomic():
            Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())
            run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
            delete_customer_database_records(run=run)
            self.assertFalse(SupportRequest.objects.filter(pk=request_id).exists())
            self.assertTrue(SupportRequest.objects.filter(pk=foreign).exists())
            transaction.set_rollback(True)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=timezone.now())
        request = RequestFactory().post("/api/account/close/"); request.user = self.owner
        with patch("tenancy.services.did_recently_authenticate", return_value=True):
            close_personal_access(actor=self.owner, request=request)
        self.assertFalse(SupportRequest.objects.filter(pk=request_id).exists())
        self.assertTrue(SupportRequest.objects.filter(pk=foreign).exists())


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES)
class ConcurrentSupportRequestTests(TransactionTestCase):
    setUp = fixtures.JobFoundationTests.setUp

    def test_two_postgresql_sessions_create_same_original_once_and_changed_command_conflicts(self):
        def submit(question):
            connections.close_all()
            try:
                return support.create_support_request(project=self.project, actor=self.owner,
                    command=SupportRequestTests.command(self, question=question))["request"]["id"]
            except ValidationError:
                return "conflict"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            same = list(executor.map(submit, ["Original question"] * 2))
        self.assertEqual(same[0], same[1]); self.assertEqual(SupportRequest.objects.count(), 1)
        SupportRequest.objects.all().delete()
        with ThreadPoolExecutor(max_workers=2) as executor:
            changed = list(executor.map(submit, ["Question one", "Question two"]))
        self.assertEqual(changed.count("conflict"), 1)
        self.assertEqual(SupportRequest.objects.count(), 1)
