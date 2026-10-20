import json
from datetime import timedelta, timezone as utc
from hashlib import sha256
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import read_project_artifact
from tenancy.models import Organization, OrganizationMembership, Project, ProjectConfiguration, ProjectMembership
from .action_review import record_action
from .findings import record_csv_findings
from .models import IntentClusterReview, ProjectReportSnapshot
from .reporting import create_project_report, read_project_report
from . import test_findings as finding_fixtures
from .weekly_summary import retained_weekly_report_source


@override_settings(STORAGES=TEST_STORAGES,
                   ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv", "application/json"}),
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                       "LOCATION": "weekly-source-fixtures"}})
class WeeklyReportSourceTests(TransactionTestCase):
    def setUp(self):
        self.assessed = timezone.now().astimezone(utc.utc)
        self.week_end = self.assessed.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=self.assessed.weekday())
        self.report_time = self.week_end - timedelta(days=2)
        with patch("jobs.weekly_summary.timezone.now", return_value=self.week_end - timedelta(days=8)):
            finding_fixtures.FindingEvidenceTests.setUp(self)
            self.finding = record_csv_findings(project=self.project, actor=self.owner,
                connection=self.connection, import_id=self.run.pk)[0][0]
            ProjectConfiguration.objects.create(project=self.project, target_country="Turkey", target_languages=["en"],
                                                seed_topics=["service questions"])
            source = IntentClusterReview.objects.create(project=self.project, actor=self.owner,
                request_key="weekly-intent-001", label="Manual intent", manual_topics=["service questions"],
                market="Turkey", language="en", page_kind="existing_unverified",
                preferred_page="https://finding.example/services", reason="Human source-poor review.",
                proposed_action="refresh", action_reason="Review a page manually.")
            self.action = record_action(project=self.project, actor=self.owner, request_key="weekly-action-001",
                source_id=source.pk, state="proposed", assignee_id=self.owner.pk,
                acceptance_criteria="Review exact customer-private criteria.", reason="Manual proposal.")
        with patch("jobs.weekly_summary.timezone.now", return_value=self.report_time):
            self.report = self.create_report("weekly-report-001")

    def create_report(self, key, **changes):
        return create_project_report(**{**dict(project=self.project, actor=self.owner, request_key=key,
            content_format="json", finding_ids=[self.finding.pk], action_review_ids=[self.action.pk], outcome_ids=[]), **changes})

    def source(self, **changes):
        with patch("jobs.weekly_summary.timezone.now", return_value=self.assessed):
            return retained_weekly_report_source(**{**dict(project=self.project, recipient=self.owner), **changes})

    def test_genuine_import_action_report_original_dates_coverage_minimization_no_writes_or_network(self):
        with CaptureQueriesContext(connection) as queries, patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("mail")):
            result = self.source()
        self.assertFalse(any(query["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for query in queries))
        self.assertEqual(result["state"], "available_selected_snapshot")
        self.assertEqual(result["report_id"], self.report.pk)
        self.assertEqual(result["week_end"], self.week_end.isoformat())
        self.assertEqual(result["week_start"], (self.week_end - timedelta(days=7)).isoformat())
        self.assertEqual(result["source_sha256"], self.report.content_sha256)
        self.assertEqual(result["source_counts"], {"findings": 1, "actions": 1, "outcomes": 0})
        self.assertEqual(result["rows"][0]["recorded_at"], self.finding.detected_at.isoformat())
        self.assertEqual(result["rows"][0]["coverage"]["provider_top_rows"], "incomplete_unknown")
        self.assertEqual(result["rows"][1]["state"], "proposed")
        serialized = json.dumps(result)
        for private in (self.owner.email, self.report.artifact_key, self.finding.subject, self.action.acceptance_criteria,
                        "https://finding.example/services", '"summary"', '"search_metrics"', '"criteria"'):
            self.assertNotIn(private, serialized)
        self.assertIn("not_complete_provider_coverage_or_causal_uplift", serialized)
        self.assertEqual(self.source(), result)

    def test_latest_json_and_half_open_week_no_older_fallback_and_unavailable_not_zero(self):
        for moment, key, fmt in ((self.week_end - timedelta(days=7, microseconds=1), "weekly-old-001", "json"),
                                 (self.week_end, "weekly-future-001", "json"),
                                 (self.report_time + timedelta(hours=1), "weekly-csv-001", "csv")):
            with patch("jobs.weekly_summary.timezone.now", return_value=moment):
                self.create_report(key, content_format=fmt)
        self.assertEqual(self.source()["report_id"], self.report.pk)
        with patch("jobs.weekly_summary.timezone.now", return_value=self.report_time):
            tied = self.create_report("weekly-tied-001")
        self.assertEqual(self.source()["report_id"], tied.pk)
        with patch("jobs.reporting.read_project_artifact", return_value=b"corrupt"):
            with self.assertRaises(ValidationError): self.source()
        ProjectReportSnapshot.objects.filter(pk__in=[self.report.pk, tied.pk]).delete()
        result = self.source()
        self.assertEqual(result["state"], "unavailable_no_report")
        self.assertIsNone(result["source_counts"])
        self.assertIsNone(result["source_sha256"])
        self.assertEqual(result["rows"], [])
        # Exact week start is eligible; row dates genuinely predate this separately created report.
        ProjectReportSnapshot.objects.all().delete()
        start = self.week_end - timedelta(days=7)
        with patch("jobs.weekly_summary.timezone.now", return_value=start):
            boundary = self.create_report("weekly-start-001")
        self.assertEqual(self.source()["report_id"], boundary.pk)
        self.assertEqual(boundary.created_at, start)

    def test_recipient_current_verification_scope_restriction_and_retained_history(self):
        with self.assertRaises(PermissionDenied): self.source(recipient=self.other)
        membership = OrganizationMembership.objects.create(organization=self.project.organization, user=self.other, role="viewer")
        self.assertEqual(self.source(recipient=self.other)["report_id"], self.report.pk)
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        with self.assertRaises(PermissionDenied): self.source(recipient=self.other)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(self.source(recipient=self.other)["report_id"], self.report.pk)
        EmailAddress.objects.filter(user=self.other).update(verified=False)
        with self.assertRaises(PermissionDenied): self.source(recipient=self.other)
        # A creator's lost role does not erase a retained snapshot for another current verified reader.
        EmailAddress.objects.filter(user=self.other).update(verified=True)
        OrganizationMembership.objects.filter(organization=self.project.organization, user=self.owner).delete()
        self.assertEqual(self.source(recipient=self.other)["report_id"], self.report.pk)

    def test_mid_read_recipient_or_original_metadata_loss_never_returns_projection(self):
        changes = [lambda: OrganizationMembership.objects.filter(organization=self.project.organization, user=self.owner).delete(),
                   lambda: EmailAddress.objects.filter(user=self.owner).update(verified=False),
                   lambda: EmailAddress.objects.filter(user=self.owner).update(primary=False),
                   lambda: get_user_model().objects.filter(pk=self.owner.pk).update(email="changed@example.invalid"),
                   lambda: get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False),
                   lambda: Organization.objects.filter(pk=self.project.organization_id).update(is_suspended=True),
                   lambda: Organization.objects.filter(pk=self.project.organization_id).update(closed_at=self.assessed, is_suspended=True),
                   lambda: ProjectReportSnapshot.objects.filter(pk=self.report.pk).delete(),
                   lambda: ProjectReportSnapshot.objects.filter(pk=self.report.pk).update(created_at=self.report_time + timedelta(seconds=1)),
                   lambda: ProjectReportSnapshot.objects.filter(pk=self.report.pk).update(action_review_ids=[])]
        for change in changes:
            def mutate(**kwargs):
                data = read_project_artifact(**kwargs)
                change()
                return data
            with self.subTest(change=change), transaction.atomic():
                with patch("jobs.reporting.read_project_artifact", side_effect=mutate), self.assertRaises(PermissionDenied):
                    self.source()
                transaction.set_rollback(True)

    def test_actual_private_body_size_sha_schema_binding_and_dates_fail_closed(self):
        original = json.loads(read_project_report(project=self.project, actor=self.owner, snapshot=self.report))
        invalid = []
        for update in ({"project_id": True}, {"project_id": self.project.pk + 999}, {"limits": "complete"},
                       {"version": "other"}, {"rows": []}, {"rows": original["rows"] * 31},
                       {"created_at": self.assessed.isoformat()}, {"created_at": "2026-01-01"}, {"extra": "private"}):
            invalid.append(json.dumps({**original, **update}).encode())
        for field, value in (("id", True), ("id", self.finding.pk + 999), ("source_id", 0),
                             ("source_id", self.finding.source_metric_id + 999),
                             ("kind", "unknown"), ("recorded_at", self.assessed.isoformat()),
                             ("coverage", ["invalid"]), ("confidence", "x" * 41)):
            rows = [dict(row) for row in original["rows"]]
            rows[0][field] = value
            invalid.append(json.dumps({**original, "rows": rows}).encode())
        invalid.extend([b'{"version":"project-report-v1","version":"duplicate"}', b'\xff',
                        b'{"x":NaN}', b'[' * 1500 + b']' * 1500])
        for data in invalid:
            # Digest-consistent malformed stored bodies still cannot supply source authority.
            with self.subTest(data=data[:40]), transaction.atomic():
                ProjectReportSnapshot.objects.filter(pk=self.report.pk).update(size_bytes=len(data), content_sha256=sha256(data).hexdigest())
                with patch("jobs.reporting.read_project_artifact", return_value=data), self.assertRaises(ValidationError):
                    self.source()
                transaction.set_rollback(True)
        with patch("jobs.reporting.read_project_artifact", return_value=b"x" * 131073), self.assertRaises(ValidationError):
            self.source()
        with transaction.atomic():
            ProjectReportSnapshot.objects.filter(pk=self.report.pk).update(finding_ids=[self.finding.pk + 999])
            with self.assertRaises(ValidationError): self.source()
            transaction.set_rollback(True)

    def test_genuine_maximum_finding_selection_and_scope_rejection(self):
        from integrations.models import ImportRun
        from integrations.search_console import queue_search_console_csv_import
        from .services import execute_job
        day = self.run.date_end
        data = b"Top queries,Clicks,Impressions,CTR,Position\n" + b"".join(
            f"bounded query {index},2,200,1%,10\n".encode() for index in range(10))
        with patch("jobs.weekly_summary.timezone.now", return_value=self.report_time):
            job = queue_search_console_csv_import(connection=self.connection, user=self.owner, content=data,
                date_start=day - timedelta(days=6), date_end=day)
            self.assertTrue(execute_job(job.pk))
            findings, _ = record_csv_findings(project=self.project, actor=self.owner,
                connection=self.connection, import_id=ImportRun.objects.get(job=job).pk)
            self.assertEqual(len(findings), 20)
            report = self.create_report("weekly-bounded-001", finding_ids=[row.pk for row in findings])
        result = self.source()
        self.assertEqual(result["report_id"], report.pk)
        self.assertEqual(result["source_counts"]["findings"], 20)
        self.assertEqual(len(result["rows"]), 21)
        with self.assertRaises(ValidationError):
            self.create_report("weekly-too-many-001", finding_ids=[row.pk for row in findings] + [self.finding.pk])
        from tenancy.services import create_organization, create_project
        foreign = create_project(organization=create_organization(user=self.other, name="Foreign source org"),
            user=self.other, name="Foreign source project", canonical_origin="https://weekly-foreign.example.invalid")
        with self.assertRaises(PermissionDenied): self.source(project=foreign)
        with transaction.atomic():
            ProjectReportSnapshot.objects.filter(pk=report.pk).update(project=foreign)
            with self.assertRaises(ValidationError): self.source(project=foreign, recipient=self.other)
            transaction.set_rollback(True)

    def test_genuine_page_outcome_preserves_manual_dates_without_metrics_or_regression_claim(self):
        from integrations.models import ImportRun
        from . import test_action_outcome as outcome_fixtures
        from .outcome_comparison import record_page_outcome
        # Reuse the owning genuine service/import fixture without importing a TestCase into discovery.
        self.import_page = lambda *args: outcome_fixtures.ActionPageOutcomeTests.import_page(self, *args)
        with patch("jobs.weekly_summary.timezone.now", return_value=self.report_time):
            outcome_fixtures.ActionPageOutcomeTests.setUp(self)
            ImportRun.objects.filter(pk=self.before.pk).update(created_at=self.implemented_at - timedelta(days=2))
            outcome = record_page_outcome(project=self.project, actor=self.actor, action_id=self.action.action_id,
                connection_id=self.connection.pk, previous_import_id=self.before.pk, current_import_id=self.after.pk)
            report = create_project_report(project=self.project, actor=self.actor, request_key="weekly-outcome-001",
                content_format="json", finding_ids=[], action_review_ids=[self.action.pk], outcome_ids=[outcome.pk])
        with patch("jobs.weekly_summary.timezone.now", return_value=self.assessed):
            result = retained_weekly_report_source(project=self.project, recipient=self.actor)
        self.assertEqual(result["report_id"], report.pk)
        self.assertEqual(result["source_counts"], {"findings": 0, "actions": 1, "outcomes": 1})
        self.assertEqual(result["rows"][0]["implementation_at"], self.implemented_at.isoformat())
        self.assertIsNone(result["rows"][0]["verification_at"])
        self.assertEqual(result["rows"][1]["method_version"], outcome.method_version)
        self.assertIn("provider_top_rows_unknown", result["rows"][1]["coverage"])
        self.assertNotIn("search_metrics", json.dumps(result))
        self.assertNotIn("conversion", json.dumps(result))

    def test_frozen_assessment_and_final_projection_authority_source_fence(self):
        from .weekly_summary import _rows
        def project_then_revoke(*args):
            result = _rows(*args)
            EmailAddress.objects.filter(user=self.owner).update(verified=False)
            return result
        with transaction.atomic():
            with patch("jobs.weekly_summary._rows", side_effect=project_then_revoke), self.assertRaises(PermissionDenied):
                self.source()
            transaction.set_rollback(True)
        boundary = self.week_end + timedelta(days=7)
        calls = 0
        def clock():
            nonlocal calls
            calls += 1
            return boundary - timedelta(microseconds=1) if calls == 1 else boundary
        with patch("jobs.weekly_summary.timezone.now", side_effect=clock):
            result = retained_weekly_report_source(project=self.project, recipient=self.owner)
        self.assertEqual(result["report_id"], self.report.pk)
        self.assertEqual(result["week_end"], self.week_end.isoformat())
        self.assertEqual(result["assessed_at"], (boundary - timedelta(microseconds=1)).isoformat())
