import json
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Event
from unittest.mock import patch
from zipfile import ZipFile

from cryptography.fernet import Fernet
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth import get_user_model
from allauth.account.models import EmailAddress
from django.db import connection as database_connection
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from jobs.models import JobCancellation, JobRun, JobStatus, JobStep
from tenancy.models import MembershipRole, Organization, OrganizationMembership, OrganizationTrial, Project

from .models import GoogleOAuthGrant, SearchAnalyticsPageSnapshot, SearchAnalyticsQueryPageSnapshot
from .search_console_analytics import validate_query_page_snapshot
from .search_console_sync import execute_search_console_sync, queue_search_console_sync, validate_sync_input
from . import test_search_console_sync as sync_fixtures


@override_settings(GOOGLE_OAUTH_CLIENT_ID="fixture-client", GOOGLE_OAUTH_CLIENT_SECRET="fixture-secret",
    GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),), STORAGES=TEST_STORAGES,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "application/zip"}),
    ARTIFACT_MAX_BYTES=32 * 1024 * 1024, DEBUG=True)
class QueryPageSourceTests(TransactionTestCase):
    setUp = sync_fixtures.SearchConsoleSyncTests.setUp

    def queue(self, key="paired-fixture", **changes):
        with patch("jobs.services.dispatch_pending"):
            return queue_search_console_sync(**{**dict(project=self.project, actor=self.user, connection=self.connection,
                grant=self.grant, day=self.day, dimensions=["query", "page"], report="query_page", idempotency_key=key), **changes})

    def response(self, offset=0, count=2):
        return {"responseAggregationType": "byPage", "rows": [
            {"keys": ["Actual query", f"https://sync.example/service-{index + offset}"], "clicks": 2,
             "impressions": 8, "ctr": .25, "position": 4.125} for index in range(count)]}

    def execute(self, job, query=None, **changes):
        with patch("socket.create_connection", side_effect=AssertionError("No actual provider network")):
            return execute_search_console_sync(**{**dict(job_id=job.pk, refresh=self.refresh, verify_site=self.site,
                query=lambda **_kwargs: self.fail("Never execute independent reports for a paired selection"),
                paired_query=query or (lambda **_kwargs: self.response())), **changes})

    def test_actual_queued_pair_paging_stage_digest_units_no_replay_and_independent_reports_stay_separate(self):
        job = self.queue()
        self.assertEqual(self.queue().pk, job.pk)
        self.assertEqual(job.usage.reserved_units, 3)
        calls = []
        def query(*, start_row, **kwargs):
            self.assertNotIn("dimension", kwargs)
            calls.append(start_row)
            return self.response(start_row, 100 if start_row == 0 else 1)
        self.assertTrue(self.execute(job, query))
        job.refresh_from_db()
        self.assertEqual((calls, job.status, job.usage.actual_units), ([0, 100], JobStatus.SUCCEEDED, 3))
        pages = list(SearchAnalyticsQueryPageSnapshot.objects.filter(job=job))
        self.assertEqual([page.start_row for page in pages], [0, 100])
        self.assertEqual(pages[0].grant_revision, self.grant.revision)
        for page in pages:
            validate_query_page_snapshot(page, current=False)
            step = JobStep.objects.get(job=job, sequence=2 + page.start_row // 100)
            self.assertEqual(step.output["result_sha256"], page.result_sha256)
            with self.assertRaises(ValidationError): page.save()
        self.assertEqual((job.output["source_coverage"], job.output["hidden_queries"], job.output["provider_completeness"]),
            ("bounded_query_page_top_rows_only", "unknown", "not_established"))
        self.assertFalse(self.execute(job, query))
        self.assertEqual(calls, [0, 100])
        self.assertFalse(SearchAnalyticsPageSnapshot.objects.filter(job=job).exists())
        independent = self.queue("independent", report=None)
        self.assertNotIn("report", independent.input_snapshot)
        self.assertEqual(independent.usage.reserved_units, 5)

    def test_pair_selection_foreign_grant_role_and_finalized_window_are_not_bypassed(self):
        data = {"connection_id": self.connection.pk, "grant_id": self.grant.pk,
                "day": self.day.isoformat(), "dimensions": ["query", "page"], "report": "query_page"}
        for change in ({"report": "page"}, {"dimensions": ["page", "query"]}, {"dimensions": ["query"]},
                       {"report": None}, {"day": timezone.now().date().isoformat()}, {"unexpected": True}):
            with self.subTest(change=change), self.assertRaises(ValidationError): validate_sync_input({**data, **change})
        foreign = Project.objects.create(organization=self.project.organization, name="Other", canonical_origin="https://other.example")
        grant = GoogleOAuthGrant.objects.create(organization=foreign.organization, project=foreign, actor=self.user,
            scope=self.grant.scope, verified_at=timezone.now(), encrypted_refresh_token="v1:fixture")
        with self.assertRaises(GoogleOAuthGrant.DoesNotExist): self.queue(grant=grant)
        OrganizationMembership.objects.filter(organization=self.project.organization, user=self.user).update(role=MembershipRole.VIEWER)
        with self.assertRaises(PermissionDenied): self.queue()
        self.assertFalse(SearchAnalyticsQueryPageSnapshot.objects.exists())

    def test_current_operator_oauth_configuration_is_required_before_costly_stages(self):
        job = self.queue()
        with override_settings(GOOGLE_OAUTH_CLIENT_SECRET=""):
            self.assertTrue(self.execute(job, lambda **_kwargs: self.fail("Disabled application must not call provider")))
        job.refresh_from_db()
        self.assertEqual((job.status, job.usage.actual_units), (JobStatus.CANCELLED, 0))
        self.assertFalse(JobStep.objects.filter(job=job).exists())

    def test_current_grant_revision_role_property_cancel_and_expiry_loss_discard_inflight_results(self):
        org = self.project.organization
        trial_end = OrganizationTrial.objects.get(organization=org).ends_at
        for kind in ("grant", "role", "property", "cancel", "expiry"):
            with self.subTest(kind=kind):
                job = self.queue(kind)
                def lost(**_kwargs):
                    if kind == "grant": GoogleOAuthGrant.objects.filter(pk=self.grant.pk).update(revision=1)
                    elif kind == "role": OrganizationMembership.objects.filter(organization=org, user=self.user).update(role=MembershipRole.VIEWER)
                    elif kind == "property": Project.objects.filter(pk=self.project.pk).update(canonical_origin="https://changed.example")
                    elif kind == "cancel": JobCancellation.objects.create(job=job, requested_by=self.user)
                    else: OrganizationTrial.objects.filter(organization=org).update(ends_at=timezone.now() - timedelta(seconds=1))
                    return self.response()
                self.assertTrue(self.execute(job, lost))
                job.refresh_from_db()
                self.assertEqual((job.status, job.usage.actual_units), (JobStatus.CANCELLED, 2))
                self.assertFalse(SearchAnalyticsQueryPageSnapshot.objects.filter(job=job).exists())
                GoogleOAuthGrant.objects.filter(pk=self.grant.pk).update(revision=0)
                OrganizationMembership.objects.filter(organization=org, user=self.user).update(role=MembershipRole.OWNER)
                Project.objects.filter(pk=self.project.pk).update(canonical_origin="https://sync.example")
                OrganizationTrial.objects.filter(organization=org).update(ends_at=trial_end)

    def test_lost_attempt_does_not_repeat_provider_or_ignore_billing_and_duplicate_cross_page_is_partial(self):
        job = self.queue("lost")
        def lost(**_kwargs): raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt): self.execute(job, lost)
        calls = []
        self.assertTrue(self.execute(job, lambda **kwargs: calls.append(kwargs)))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.usage.actual_units), (JobStatus.FAILED, "request_outcome_unknown", 2))
        self.assertFalse(calls)
        duplicate = self.queue("duplicate")
        self.assertTrue(self.execute(duplicate, lambda **kwargs: self.response(count=100 if kwargs["start_row"] == 0 else 1)))
        duplicate.refresh_from_db()
        self.assertEqual((duplicate.status, duplicate.usage.actual_units), (JobStatus.PARTIALLY_SUCCEEDED, 3))
        self.assertEqual(SearchAnalyticsQueryPageSnapshot.objects.filter(job=duplicate).count(), 1)

    def test_unsafe_omitted_keys_private_tamper_direct_creation_and_wrong_stage_fail_closed(self):
        job = self.queue()
        def response(**_kwargs):
            result = self.response()
            result["rows"].append({"keys": ["PRIVATE_QUERY", "https://foreign.example/?code=PRIVATE_SECRET"],
                "clicks": 1, "impressions": 2, "ctr": .5, "position": 1})
            return result
        self.assertTrue(self.execute(job, response))
        page = SearchAnalyticsQueryPageSnapshot.objects.get(job=job)
        self.assertEqual((page.result["omitted_pages"], page.result["rows_returned"]), (1, 3))
        self.assertNotIn("PRIVATE_", str(page.result))
        altered = deepcopy(page.result)
        altered["observations"][0]["clicks"] = 3
        SearchAnalyticsQueryPageSnapshot.objects.filter(pk=page.pk).update(result=altered)
        page.refresh_from_db()
        with self.assertRaises(ValidationError): validate_query_page_snapshot(page, current=False)
        pending = self.queue("wrong-stage")
        JobRun.objects.filter(pk=pending.pk).update(status=JobStatus.RUNNING)
        pending.refresh_from_db()
        page.pk = None
        page._state.adding = True
        page.job = pending
        with self.assertRaises(ValidationError): page.save()

    def test_actual_bounded_stored_sequential_exports_retain_history_and_closed_child_first_deletion(self):
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import _customer_deletion_order, prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        job = self.queue()
        self.assertTrue(self.execute(job))
        page = SearchAnalyticsQueryPageSnapshot.objects.get(job=job)
        org = self.project.organization
        label = "records/integrations/SearchAnalyticsQueryPageSnapshot.json"
        with ZipFile(BytesIO(complete_bounded_customer_archive(organization=org, actor=self.user))) as archive:
            row = json.loads(archive.read(label))[0]
            self.assertEqual(row["result"], page.result)
            self.assertIn("historical_bounded", row["scope"])
            self.assertNotIn("fixture-ciphertext", str(row))
        with patch("tenancy.tasks.capture_customer_snapshot_task.apply_async"):
            bounded = reserve_bounded_customer_snapshot(organization=org, actor=self.user, request_key="c" * 32)
            self.assertTrue(capture_reserved_customer_snapshot(bounded.pk))
            data, _ = private_snapshot_part(organization=org, actor=self.user, snapshot_id=bounded.pk, position=0)
            with ZipFile(BytesIO(data)) as archive: self.assertEqual(json.loads(archive.read(label))[0]["result"], page.result)
            GoogleOAuthGrant.objects.filter(pk=self.grant.pk).update(revision=1)
            self.assertEqual(private_snapshot_part(organization=org, actor=self.user, snapshot_id=bounded.pk, position=0)[0], data)
            sequential = reserve_bounded_customer_snapshot(organization=org, actor=self.user, request_key="d" * 32, format="source-parts-v2")
            for _ in range(len(CUSTOMER) * 2 + 10):
                sequential.refresh_from_db()
                if sequential.state != sequential.State.PREPARING: break
                self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
            sequential.refresh_from_db()
            self.assertEqual(sequential.state, sequential.State.READY)
            part = sequential.parts.get(source__model="integrations.SearchAnalyticsQueryPageSnapshot")
            data, _ = private_snapshot_part(organization=org, actor=self.user, snapshot_id=sequential.pk, position=part.position)
            with ZipFile(BytesIO(data)) as archive: self.assertEqual(json.loads(archive.read("data"))[0]["result"], page.result)
        order = [model._meta.label for model, _ in _customer_deletion_order()]
        for source in ("integrations.GoogleOAuthGrant", "integrations.IntegrationConnection", "jobs.JobRun", "tenancy.Project"):
            self.assertLess(order.index("integrations.SearchAnalyticsQueryPageSnapshot"), order.index(source))
        Organization.objects.filter(pk=org.pk).update(is_suspended=True, closed_at=timezone.now())
        with self.assertRaises(PermissionDenied): private_snapshot_part(organization=org, actor=self.user, snapshot_id=bounded.pk, position=0)
        GoogleOAuthGrant.objects.filter(pk=self.grant.pk).update(state="revoked", encrypted_refresh_token="",
            selected_property_id="", selected_site_url="", revoked_at=timezone.now())
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=org))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(SearchAnalyticsQueryPageSnapshot.objects.filter(project=self.project).exists())


@override_settings(GOOGLE_OAUTH_CLIENT_ID="fixture-client", GOOGLE_OAUTH_CLIENT_SECRET="fixture-secret",
    GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),), DEBUG=True)
class QueryPageConcurrencyTests(TransactionTestCase):
    setUp = sync_fixtures.SearchConsoleSyncTests.setUp
    queue = QueryPageSourceTests.queue
    response = QueryPageSourceTests.response
    execute = QueryPageSourceTests.execute

    def test_actual_postgresql_worker_overlap_cannot_duplicate_provider_stage_or_units(self):
        job = self.queue()
        entered, release = Event(), Event()
        calls = []
        def query(**kwargs):
            calls.append(kwargs["start_row"])
            entered.set()
            if not release.wait(timeout=20): raise AssertionError("Fixture release timed out")
            return self.response()
        def worker():
            close_old_connections()
            try: return self.execute(job, query)
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(worker)
            try:
                self.assertTrue(entered.wait(timeout=20))
                self.assertFalse(self.execute(job, lambda **_kwargs: self.fail("Contended worker must not call provider")))
            finally: release.set()
            self.assertTrue(first.result(timeout=20))
        job.refresh_from_db()
        self.assertEqual((calls, job.status, job.usage.actual_units), ([0], JobStatus.SUCCEEDED, 2))
        self.assertEqual(SearchAnalyticsQueryPageSnapshot.objects.filter(job=job).count(), 1)
        self.assertEqual(JobStep.objects.filter(job=job, name="Search Analytics page").count(), 1)


@override_settings(GOOGLE_OAUTH_CLIENT_ID="fixture-client", GOOGLE_OAUTH_CLIENT_SECRET="fixture-secret",
    GOOGLE_OAUTH_ENCRYPTION_KEYS=(Fernet.generate_key().decode(),), DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "paired-api"}})
class QueryPageAPITests(TestCase):
    setUp = sync_fixtures.SearchConsoleSyncTests.setUp
    queue = QueryPageSourceTests.queue
    response = QueryPageSourceTests.response
    execute = QueryPageSourceTests.execute

    def path(self):
        return f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/sources/{self.connection.pk}/query-page/"

    def test_actual_api_csrf_strict_pair_source_scoped_current_readback_and_positive_evidence_no_get_writes(self):
        path = self.path()
        self.assertEqual(Client().get(path).status_code, 401)
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.user)
        payload = {"day": self.day.isoformat(), "idempotency_key": "api-pair", "grant_id": self.grant.pk, "grant_revision": self.grant.revision}
        self.assertEqual(owner.post(path, json.dumps(payload), content_type="application/json").status_code, 403)
        owner.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": owner.cookies["csrftoken"].value}
        with patch("jobs.services.dispatch_pending"):
            queued = owner.post(path, json.dumps(payload), content_type="application/json", **headers)
        self.assertEqual((queued.status_code, queued.json()["report"], queued.json()["max_requests"]), (202, "query_page", 3))
        job = JobRun.objects.get(pk=queued.json()["job_id"])
        self.assertTrue(self.execute(job))
        with patch("socket.create_connection", side_effect=AssertionError("No network")), CaptureQueriesContext(database_connection) as queries:
            result = owner.get(path, {"job_id": job.pk})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertFalse(any(query["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for query in queries))
        body = result.json()
        self.assertEqual(body["job"]["id"], job.pk)
        self.assertEqual(body["candidate_state"], "positive_overlap_candidates")
        refs = body["candidates"][0]["evidence"]
        self.assertEqual([ref["row_index"] for ref in refs], [0, 1])
        self.assertEqual(refs[0]["result_sha256"], body["pages"][0]["result_sha256"])
        self.assertIn("not_proven_intent_conflict", body["interpretation"])
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        self.assertNotIn("fixture-ciphertext", result.content.decode())
        history = owner.get(path).json()
        self.assertEqual([item["id"] for item in history["jobs"]], [job.pk])
        self.assertNotIn("Actual query", str(history))
        reconciled = owner.get(path, {"request_key": "api-pair"}).json()
        self.assertEqual(reconciled["job"]["id"], job.pk)
        self.assertIsNone(owner.get(path, {"request_key": "missing"}).json()["job"])
        with patch("jobs.services.dispatch_pending"):
            self.assertEqual(owner.post(path, json.dumps({**payload, "grant_revision": 1}), content_type="application/json", **headers).status_code, 409)
        independent = owner.get(path.replace("/query-page/", "/sync/status/")).json()
        self.assertIsNone(independent["job"])
        for query in ("?job_id=1&job_id=2", "?job_id=01", "?job_id=true", "?job_id=9007199254740992", "?job_id=1&extra=1"):
            self.assertEqual(owner.get(path + query).status_code, 409)
        for raw in ('{"day":"2026-09-20","day":"2026-09-21","idempotency_key":"bad"}',
            '{"day":NaN,"idempotency_key":"bad"}', json.dumps({**payload, "dimensions": ["query"]})):
            self.assertEqual(owner.post(path, raw, content_type="application/json", **headers).status_code, 409)

    def test_private_latest_stage_tamper_and_scope_loss_during_stored_read_are_unusable(self):
        from . import search_console_query_page as reader
        job = self.queue()
        self.assertTrue(self.execute(job))
        self.client.force_login(self.user)
        path = self.path() + f"?job_id={job.pk}"
        original = reader._read_paired_pages
        def lost(current):
            pages = original(current)
            GoogleOAuthGrant.objects.filter(pk=self.grant.pk).update(revision=1)
            return pages
        with patch.object(reader, "_read_paired_pages", side_effect=lost):
            self.assertEqual(self.client.get(path).status_code, 403)
        GoogleOAuthGrant.objects.filter(pk=self.grant.pk).update(revision=0)
        page = SearchAnalyticsQueryPageSnapshot.objects.get(job=job)
        step = JobStep.objects.get(job=job, sequence=2)
        JobStep.objects.filter(pk=step.pk).update(output={"state": "recorded", "snapshot_id": page.pk, "next_start_row": None, "result_sha256": "a" * 64})
        self.assertEqual(self.client.get(path).status_code, 409)
        JobStep.objects.filter(pk=step.pk).update(output=step.output)
        self.queue("newer")
        self.assertEqual(self.client.get(path).status_code, 409)
        self.assertFalse(self.client.get(self.path()).json()["jobs"][-1]["source_current"])

    def test_foreign_viewer_original_source_actor_and_missing_positive_rows_do_not_gain_authority(self):
        admin = get_user_model().objects.create_user("paired-admin@example.invalid", password="test-password")
        EmailAddress.objects.create(user=admin, email=admin.email, verified=True, primary=True)
        OrganizationMembership.objects.create(organization=self.project.organization, user=admin, role=MembershipRole.ADMIN)
        job = self.queue(actor=admin)
        self.assertTrue(self.execute(job, lambda **_kwargs: {"rows": []}))
        self.client.force_login(admin)
        exact = self.path() + f"?job_id={job.pk}"
        body = self.client.get(exact).json()
        self.assertEqual(body["candidate_state"], "no_positive_overlap_in_bounded_rows_not_absence")
        self.assertEqual(body["candidates"], [])
        OrganizationMembership.objects.filter(organization=self.project.organization, user=self.user).update(role=MembershipRole.VIEWER)
        self.assertEqual(self.client.get(exact).status_code, 403)
        viewer = Client(); viewer.force_login(self.user)
        self.assertEqual(viewer.get(self.path()).status_code, 403)
        other = Project.objects.create(organization=self.project.organization, name="Other", canonical_origin="https://foreign.example")
        self.assertEqual(self.client.get(exact.replace(f"/projects/{self.project.pk}/", f"/projects/{other.pk}/")).status_code, 404)
