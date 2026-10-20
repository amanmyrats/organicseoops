import json
from io import BytesIO
from datetime import timedelta
from zipfile import ZipFile
from zoneinfo import ZoneInfo
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from integrations.models import ImportRun, SearchMetricObservation
from integrations.search_console import queue_search_console_csv_import
from integrations.services import create_connection
from tenancy.models import MembershipRole, OrganizationMembership, Project
from tenancy.services import create_organization, create_project, update_project

from .findings import record_csv_findings, record_page_change_findings, record_query_change_findings
from .models import Finding, Opportunity, ProjectReportSnapshot, Recommendation
from .reporting import create_project_report, read_project_report
from .services import execute_job


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv"}),
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                       "LOCATION": "finding-evidence-fixtures"}})
class FindingEvidenceTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending")
        dispatch.start()
        self.addCleanup(dispatch.stop)
        cache.clear()
        users = get_user_model().objects
        self.owner = users.create_user("finding-owner@example.com", password="test-password")
        self.other = users.create_user("finding-other@example.com", password="test-password")
        for actor in (self.owner, self.other):
            EmailAddress.objects.create(user=actor, email=actor.email, primary=True, verified=True)
        organization = create_organization(user=self.owner, name="Finding organization")
        self.project = create_project(organization=organization, user=self.owner, name="Finding site",
                                      canonical_origin="https://finding.example")
        self.connection = create_connection(project=self.project, user=self.owner, provider="google_search_console",
            external_property_id="https://finding.example/", capabilities=["csv_import", "query_metrics"],
            available_dimensions=["query"], source_semantics="search_console_performance",
            source_semantics_version="csv-v1", timezone="America/Los_Angeles")
        end = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=3)
        job = queue_search_console_csv_import(connection=self.connection, user=self.owner,
            content=b"Top queries,Clicks,Impressions,CTR,Position\nmiddle query,2,200,1%,10\n"
                    b"zero row,0,200,0%,8\n",
            date_start=end - timedelta(days=6), date_end=end)
        self.assertTrue(execute_job(job.pk))
        self.run = ImportRun.objects.get(job=job)

    def test_source_bound_immutable_findings_replay_without_creating_opportunity_or_recommendation(self):
        findings, truncated = record_csv_findings(project=self.project, actor=self.owner,
            connection=self.connection, import_id=self.run.pk)
        self.assertFalse(truncated)
        self.assertEqual(len(findings), 2)
        self.assertEqual({item.detector for item in findings}, {
            "web_position_4_to_20_candidate", "web_high_impressions_low_ctr_candidate"})
        self.assertEqual({item.source_metric_id for item in findings},
                         {self.run.search_metrics.get(query="middle query").pk})
        self.assertEqual((Opportunity.objects.count(), Recommendation.objects.count()), (0, 0))
        again, truncated = record_csv_findings(project=self.project, actor=self.owner,
            connection=self.connection, import_id=self.run.pk)
        self.assertEqual([item.pk for item in findings], [item.pk for item in again])
        self.assertEqual(Finding.objects.count(), 2)
        self.assertIn("incomplete_unknown", json.dumps(findings[0].evidence))
        self.assertNotIn("zero row", json.dumps([item.evidence for item in findings]))
        with self.assertRaises(ValidationError):
            findings[0].save()

    @override_settings(ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv", "application/json"}))
    def test_private_report_snapshots_scope_auth_and_csv_formula_cells(self):
        finding = record_csv_findings(project=self.project, actor=self.owner,
                                      connection=self.connection, import_id=self.run.pk)[0][0]
        Finding.objects.filter(pk=finding.pk).update(subject='=HYPERLINK("https://outside.invalid")')
        csv_request = dict(project=self.project, actor=self.owner, request_key="report-fixture-001",
                           content_format="csv", finding_ids=[finding.pk], action_review_ids=[], outcome_ids=[])
        report = create_project_report(**csv_request)
        self.assertEqual(create_project_report(**csv_request).pk, report.pk)
        self.assertEqual(ProjectReportSnapshot.objects.count(), 1)
        data = read_project_report(project=self.project, actor=self.owner, snapshot=report)
        self.assertIn(b"'=HYPERLINK", data)
        self.assertNotIn(b"\r\n=HYPERLINK", data)
        self.assertNotIn(b"access_token", data)
        self.assertTrue(report.artifact_key.startswith(f"organizations/{self.project.organization_id}/projects/{self.project.pk}/"))
        json_report = create_project_report(**{**csv_request, "request_key": "report-fixture-002",
                                               "content_format": "json"})
        parsed = json.loads(read_project_report(project=self.project, actor=self.owner, snapshot=json_report))
        self.assertEqual(parsed["rows"][0]["method_version"], finding.method_version)
        self.assertEqual(parsed["rows"][0]["source_id"], finding.source_metric_id)
        self.assertIn("not_complete_provider_coverage", parsed["limits"])
        with self.assertRaises(PermissionDenied):
            read_project_report(project=self.project, actor=self.other, snapshot=report)
        with self.assertRaises(ValidationError):
            create_project_report(**{**csv_request, "finding_ids": [finding.pk, finding.pk]})
        with self.assertRaises(ValidationError):
            report.save()

    def test_authenticated_report_download_rechecks_current_project_access(self):
        finding = record_csv_findings(project=self.project, actor=self.owner,
                                      connection=self.connection, import_id=self.run.pk)[0][0]
        url = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/reports/"
        payload = {"request_key": "report-api-001", "format": "csv", "finding_ids": [finding.pk],
                   "action_review_ids": [], "outcome_ids": []}
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        self.assertEqual(owner.post(url, data=json.dumps(payload), content_type="application/json").status_code, 403)
        owner.get("/_allauth/browser/v1/auth/session")
        created = owner.post(url, data=json.dumps(payload), content_type="application/json",
                             HTTP_X_CSRFTOKEN=owner.cookies["csrftoken"].value)
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["report"]["source_counts"]["findings"], 1)
        report_id = created.json()["report"]["id"]
        download = url + f"{report_id}/download/"
        self.assertEqual(Client().get(download).status_code, 401)
        response = owner.get(download)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"gsc-csv-opportunity-v1", response.content)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        member = get_user_model().objects.create_user("report-member@example.invalid", "Test passphrase 99!")
        EmailAddress.objects.create(user=member, email=member.email, verified=True, primary=True)
        membership = OrganizationMembership.objects.create(organization=self.project.organization,
                                                            user=member, role=MembershipRole.VIEWER)
        reader = Client()
        reader.force_login(member)
        self.assertEqual(reader.get(download).status_code, 200)
        membership.delete()
        self.assertEqual(reader.get(download).status_code, 404)
        other = Client()
        other.force_login(self.other)
        self.assertEqual(other.get(download).status_code, 404)

    def test_report_download_and_owner_bundle_deny_current_authority_or_original_source_loss_during_private_read(self):
        from tenancy.artifacts import read_project_artifact
        from tenancy.models import Organization
        from tenancy.report_bundle import selected_report_bundle
        finding = record_csv_findings(project=self.project, actor=self.owner, connection=self.connection, import_id=self.run.pk)[0][0]
        report = create_project_report(project=self.project, actor=self.owner, request_key="final-report-read-001",
            content_format="csv", finding_ids=[finding.pk], action_review_ids=[], outcome_ids=[])
        client = Client(); client.force_login(self.owner)
        path = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/reports/{report.pk}/download/"
        for change in (lambda: OrganizationMembership.objects.filter(organization=self.project.organization, user=self.owner).delete(),
                       lambda: Organization.objects.filter(pk=self.project.organization_id).update(is_suspended=True),
                       lambda: get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False),
                       lambda: ProjectReportSnapshot.objects.filter(pk=report.pk).delete(),
                       lambda: ProjectReportSnapshot.objects.filter(pk=report.pk).update(content_sha256="0" * 64)):
            def read_then_change(**kwargs):
                data = read_project_artifact(**kwargs)
                change()
                return data
            with transaction.atomic():
                with patch("jobs.reporting.read_project_artifact", side_effect=read_then_change):
                    response = client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(b"gsc-csv-opportunity-v1", response.content)
                transaction.set_rollback(True)
            with transaction.atomic():
                with patch("jobs.reporting.read_project_artifact", side_effect=read_then_change), self.assertRaises(PermissionDenied):
                    selected_report_bundle(organization=self.project.organization, actor=self.owner, report_ids=[report.pk])
                transaction.set_rollback(True)
        def read_then_demote(**kwargs):
            data = read_project_artifact(**kwargs)
            OrganizationMembership.objects.filter(organization=self.project.organization, user=self.owner).update(role="viewer")
            return data
        # A viewer can still read a project report, but cannot receive an owner organization archive.
        with transaction.atomic():
            with patch("jobs.reporting.read_project_artifact", side_effect=read_then_demote), self.assertRaises(PermissionDenied):
                selected_report_bundle(organization=self.project.organization, actor=self.owner, report_ids=[report.pk])
            self.assertIn(b"gsc-csv-opportunity-v1", read_project_report(project=self.project, actor=self.owner, snapshot=report))
            transaction.set_rollback(True)

    def test_shared_report_does_not_deliver_after_mid_read_revoke_expiry_creator_share_role_or_entitlement_loss(self):
        from tenancy.artifacts import read_project_artifact
        from tenancy.models import OrganizationTrial
        from .models import ProjectReportShare
        from .report_shares import create_report_share, read_shared_report
        finding = record_csv_findings(project=self.project, actor=self.owner, connection=self.connection, import_id=self.run.pk)[0][0]
        report = create_project_report(project=self.project, actor=self.owner, request_key="final-share-report-001",
            content_format="csv", finding_ids=[finding.pk], action_review_ids=[], outcome_ids=[])
        share, token = create_report_share(project=self.project, actor=self.owner, report_id=report.pk,
            request_key="final-share-read-001", recipient_email="reader@example.invalid", expires_hours=24, acknowledge_link_access=True)
        for change in (lambda: ProjectReportShare.objects.filter(pk=share.pk).update(revoked_at=timezone.now()),
                       lambda: ProjectReportShare.objects.filter(pk=share.pk).update(expires_at=timezone.now() - timedelta(microseconds=1)),
                       lambda: OrganizationMembership.objects.filter(organization=self.project.organization, user=self.owner).update(role="viewer"),
                       lambda: OrganizationTrial.objects.filter(organization=self.project.organization).update(
                           state="expired", ends_at=self.project.organization.trial.started_at + timedelta(microseconds=1))):
            def read_then_change(**kwargs):
                data = read_project_artifact(**kwargs)
                change()
                return data
            with transaction.atomic():
                with patch("jobs.reporting.read_project_artifact", side_effect=read_then_change), self.assertRaises(PermissionDenied):
                    read_shared_report(token)
                transaction.set_rollback(True)
            with transaction.atomic():
                with patch("jobs.reporting.read_project_artifact", side_effect=read_then_change):
                    response = Client().get(f"/api/reports/shared/{token}/")
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(b"gsc-csv-opportunity-v1", response.content)
                transaction.set_rollback(True)
        # Natural expiry while the storage call is outstanding, without editing expiry metadata.
        finished = False
        def slow_read(**kwargs):
            nonlocal finished
            data = read_project_artifact(**kwargs)
            finished = True
            return data
        def clock():
            return share.expires_at if finished else share.expires_at - timedelta(microseconds=1)
        # Existing initial entitlement must still be valid at the original share deadline.
        with patch("jobs.report_shares.timezone.now", side_effect=clock), patch("jobs.reporting.read_project_artifact", side_effect=slow_read):
            with self.assertRaises(PermissionDenied): read_shared_report(token)
        self.assertTrue(finished)
        # Retained authenticated reading is allowed after trial expiry; only live sharing loses entitlement.
        OrganizationTrial.objects.filter(organization=self.project.organization).update(
            state="expired", ends_at=self.project.organization.trial.started_at + timedelta(microseconds=1))
        self.assertIn(b"gsc-csv-opportunity-v1", read_project_report(project=self.project, actor=self.owner, snapshot=report))
        with self.assertRaises(PermissionDenied): read_shared_report(token)

    def test_report_share_one_time_link_expiry_revoke_and_creator_role_recheck(self):
        from datetime import timedelta
        from unittest.mock import patch

        from jobs.models import ProjectReportShare
        from tenancy.models import AuditEvent, AuditEventType

        finding = record_csv_findings(project=self.project, actor=self.owner,
                                      connection=self.connection, import_id=self.run.pk)[0][0]
        base = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/"
        owner = Client()
        owner.force_login(self.owner)
        created = owner.post(base + "reports/", data=json.dumps({"request_key": "share-report-001",
            "format": "csv", "finding_ids": [finding.pk], "action_review_ids": [], "outcome_ids": []}),
            content_type="application/json")
        self.assertEqual(created.status_code, 201, created.content)
        report_id = created.json()["report"]["id"]
        share_url = base + "report-shares/"
        payload = {"report_id": report_id, "request_key": "share-link-001",
                   "intended_recipient": "recipient@example.invalid", "expires_hours": 1,
                   "acknowledge_link_access": True}
        self.assertEqual(owner.post(share_url, data=json.dumps({**payload, "acknowledge_link_access": False}),
                                    content_type="application/json").status_code, 409)
        issued = owner.post(share_url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(issued.status_code, 201, issued.content)
        link = issued.json()["link_path"]
        self.assertIn("Anyone holding a link", issued.json()["disclosure"])
        token = link.split("/")[-2]
        share = ProjectReportShare.objects.get(pk=issued.json()["share"]["id"])
        self.assertNotEqual(share.token_digest, token)
        self.assertNotIn(token, str(share.__dict__))
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.REPORT_SHARE_CREATED,
                                                    project=self.project).count(), 1)
        self.assertEqual(Client().get(link).status_code, 200)
        self.assertEqual(Client().get(link)["Cache-Control"], "private, no-store")
        wrong_token = ("A" if token[0] != "A" else "B") + token[1:]
        self.assertEqual(Client().get(link.replace(token, wrong_token)).status_code, 404)
        replay = owner.post(share_url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertNotIn("link_path", replay.json())
        self.assertEqual(replay.json()["share"]["id"], share.pk)
        with patch("jobs.report_shares.timezone.now", return_value=share.expires_at + timedelta(seconds=1)):
            self.assertEqual(Client().get(link).status_code, 404)
        membership = OrganizationMembership.objects.get(organization=self.project.organization, user=self.owner)
        membership.role = MembershipRole.VIEWER
        membership.save(update_fields=["role"])
        self.assertEqual(Client().get(link).status_code, 404)
        membership.role = MembershipRole.OWNER
        membership.save(update_fields=["role"])
        self.assertEqual(Client().get(link).status_code, 200)
        revoked = owner.post(share_url + f"{share.pk}/revoke/", data="{}", content_type="application/json")
        self.assertEqual(revoked.status_code, 200, revoked.content)
        self.assertEqual(Client().get(link).status_code, 404)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.REPORT_SHARE_REVOKED,
                                                    project=self.project).count(), 1)
        self.assertEqual(owner.post(share_url + f"{share.pk}/revoke/", data="{}",
                                    content_type="application/json").status_code, 200)
        self.assertEqual(AuditEvent.objects.filter(event_type=AuditEventType.REPORT_SHARE_REVOKED,
                                                    project=self.project).count(), 1)
        self.assertEqual(owner.get(share_url).json()["shares"][0]["state"], "revoked")
        live = owner.post(share_url, data=json.dumps({**payload, "request_key": "share-link-002"}),
                          content_type="application/json")
        self.assertEqual(live.status_code, 201, live.content)
        self.assertEqual(Client().get(live.json()["link_path"]).status_code, 200)
        from tenancy.closure import close_organization_locally
        from django.test import RequestFactory

        closure_request = RequestFactory().post("/api/organizations/close/")
        closure_request.user = self.owner
        with patch("tenancy.services.did_recently_authenticate", return_value=True):
            close_organization_locally(organization=self.project.organization, actor=self.owner,
                                       request=closure_request)
        self.assertIsNotNone(ProjectReportShare.objects.get(pk=live.json()["share"]["id"]).revoked_at)
        self.assertEqual(Client().get(live.json()["link_path"]).status_code, 404)
        self.assertEqual(owner.get(base + f"reports/{report_id}/download/").status_code, 404)
        self.assertEqual(owner.get(share_url).status_code, 404)

    def test_report_shares_reject_foreign_sources_lost_entitlement_and_tampered_storage(self):
        from unittest.mock import patch

        finding = record_csv_findings(project=self.project, actor=self.owner,
                                      connection=self.connection, import_id=self.run.pk)[0][0]
        other_organization = create_organization(user=self.other, name="Outside report organization")
        foreign_project = create_project(organization=other_organization, user=self.other,
                                         name="Outside site", canonical_origin="https://report-outside.example")
        base = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/"
        owner = Client()
        owner.force_login(self.owner)
        invalid = owner.post(base + "reports/", data=json.dumps({"request_key": "foreign-source-001",
            "format": "csv", "finding_ids": [finding.pk + 50000], "action_review_ids": [], "outcome_ids": []}),
            content_type="application/json")
        self.assertEqual(invalid.status_code, 404)
        self.assertEqual(ProjectReportSnapshot.objects.count(), 0)
        created = owner.post(base + "reports/", data=json.dumps({"request_key": "current-source-001",
            "format": "csv", "finding_ids": [finding.pk], "action_review_ids": [], "outcome_ids": []}),
            content_type="application/json")
        self.assertEqual(created.status_code, 201, created.content)
        report_id = created.json()["report"]["id"]
        share_payload = {"report_id": report_id, "request_key": "share-scope-001",
                         "intended_recipient": "intended@example.invalid", "expires_hours": 24,
                         "acknowledge_link_access": True}
        foreign = owner.post(base + "report-shares/", data=json.dumps({**share_payload, "report_id": report_id + 50000}),
                             content_type="application/json")
        self.assertEqual(foreign.status_code, 403)
        viewer = get_user_model().objects.create_user("report-viewer@example.invalid", password="pass-for-test")
        OrganizationMembership.objects.create(organization=self.project.organization,
                                              user=viewer, role=MembershipRole.VIEWER)
        reader = Client()
        reader.force_login(viewer)
        self.assertEqual(reader.post(base + "report-shares/", data=json.dumps(share_payload),
                                     content_type="application/json").status_code, 403)
        issued = owner.post(base + "report-shares/", data=json.dumps(share_payload), content_type="application/json")
        self.assertEqual(issued.status_code, 201, issued.content)
        link = issued.json()["link_path"]
        self.assertEqual(owner.get(f"/api/organizations/{foreign_project.organization_id}/projects/"
                                   f"{foreign_project.pk}/reports/{report_id}/download/").status_code, 404)
        self.assertEqual(owner.get(f"/api/organizations/{foreign_project.organization_id}/projects/"
                                   f"{foreign_project.pk}/report-shares/").status_code, 404)
        with patch("jobs.report_shares.timezone.now", return_value=timezone.now() + timedelta(days=40)):
            self.assertEqual(Client().get(link).status_code, 404)
        self.assertEqual(Client().get(link).status_code, 200)
        ProjectReportSnapshot.objects.filter(pk=report_id).update(content_sha256="0" * 64)
        self.assertEqual(owner.get(base + f"reports/{report_id}/download/").status_code, 503)
        self.assertEqual(Client().get(link).status_code, 503)

    def test_report_share_revocation_stays_available_after_creation_limit(self):
        finding = record_csv_findings(project=self.project, actor=self.owner,
                                      connection=self.connection, import_id=self.run.pk)[0][0]
        report = create_project_report(project=self.project, actor=self.owner,
            request_key="share-rate-report-001", content_format="csv", finding_ids=[finding.pk],
            action_review_ids=[], outcome_ids=[])
        url = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/report-shares/"
        owner = Client()
        owner.force_login(self.owner)
        for number in range(10):
            issued = owner.post(url, data=json.dumps({"report_id": report.pk,
                "request_key": f"share-rate-{number:03d}", "intended_recipient": "reader@example.invalid",
                "expires_hours": 1, "acknowledge_link_access": True}), content_type="application/json")
            self.assertEqual(issued.status_code, 201, issued.content)
            if number == 0:
                first_link = issued.json()["link_path"]
                first_share_id = issued.json()["share"]["id"]
        self.assertEqual(owner.post(url, data=json.dumps({"report_id": report.pk,
            "request_key": "share-rate-011", "intended_recipient": "reader@example.invalid",
            "expires_hours": 1, "acknowledge_link_access": True}), content_type="application/json").status_code, 429)
        self.assertEqual(Client().get(first_link).status_code, 200)
        self.assertEqual(owner.post(url + f"{first_share_id}/revoke/", data="{}",
                                    content_type="application/json").status_code, 200)
        self.assertEqual(Client().get(first_link).status_code, 404)

    def test_organization_selected_reports_bundle_is_owner_only_and_explicitly_partial(self):
        finding = record_csv_findings(project=self.project, actor=self.owner,
                                      connection=self.connection, import_id=self.run.pk)[0][0]
        report = create_project_report(project=self.project, actor=self.owner,
            request_key="organization-bundle-report", content_format="csv", finding_ids=[finding.pk],
            action_review_ids=[], outcome_ids=[])
        url = f"/api/organizations/{self.project.organization_id}/reports/bundle/"
        payload = json.dumps({"report_ids": [report.pk]})
        self.assertEqual(Client().post(url, payload, content_type="application/json").status_code, 401)
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        self.assertEqual(owner.post(url, payload, content_type="application/json").status_code, 403)
        owner.get("/_allauth/browser/v1/auth/session")
        headers = {"HTTP_X_CSRFTOKEN": owner.cookies["csrftoken"].value}
        response = owner.post(url, payload, content_type="application/json", **headers)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertNotIn(report.artifact_key.encode(), response.content)
        with ZipFile(BytesIO(response.content)) as archive:
            self.assertCountEqual(archive.namelist(), [
                "manifest.json", f"project-{self.project.pk}/report-{report.pk}.csv"])
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["scope"], "selected_project_reports_only_not_complete_organization_export")
            self.assertEqual(manifest["reports"][0]["content_sha256"], report.content_sha256)
            self.assertIn(b"gsc-csv-opportunity-v1", archive.read(f"project-{self.project.pk}/report-{report.pk}.csv"))
        reader = get_user_model().objects.create_user("bundle-viewer@example.invalid", password="test-password")
        OrganizationMembership.objects.create(organization=self.project.organization, user=reader,
                                              role=MembershipRole.VIEWER)
        client = Client()
        client.force_login(reader)
        self.assertEqual(client.get(f"/api/organizations/{self.project.organization_id}/projects/"
                                    f"{self.project.pk}/reports/{report.pk}/download/").status_code, 200)
        self.assertEqual(client.post(url, payload, content_type="application/json").status_code, 404)
        self.assertEqual(owner.post(url, json.dumps({"report_ids": [report.pk, report.pk]}),
                                    content_type="application/json", **headers).status_code, 409)
        self.assertEqual(owner.post(url, json.dumps({"report_ids": [report.pk + 50000]}),
                                    content_type="application/json", **headers).status_code, 404)
        self.assertEqual(owner.post(f"/api/organizations/{self.project.organization_id + 50000}/reports/bundle/",
                                    payload, content_type="application/json", **headers).status_code, 404)
        ProjectReportSnapshot.objects.filter(pk=report.pk).update(content_sha256="0" * 64)
        self.assertEqual(owner.post(url, payload, content_type="application/json", **headers).status_code, 503)

    def test_retention_expiry_denies_project_download_and_owner_bundle(self):
        finding = record_csv_findings(project=self.project, actor=self.owner,
                                      connection=self.connection, import_id=self.run.pk)[0][0]
        report = create_project_report(project=self.project, actor=self.owner,
            request_key="retained-report-fixture", content_format="csv", finding_ids=[finding.pk],
            action_review_ids=[], outcome_ids=[])
        client = Client()
        client.force_login(self.owner)
        base = f"/api/organizations/{self.project.organization_id}/"
        download = base + f"projects/{self.project.pk}/reports/{report.pk}/download/"
        bundle = base + "reports/bundle/"
        archive = base + "export/archive/"
        rows = base + "export/rows/"
        payload = json.dumps({"report_ids": [report.pk]})
        trial = self.project.organization.trial
        trial.started_at = timezone.now() - timedelta(days=119)
        trial.ends_at = timezone.now() - timedelta(days=89)
        trial.save(update_fields=["started_at", "ends_at"])
        self.assertEqual(client.get(download).status_code, 200)
        self.assertEqual(client.post(bundle, payload, content_type="application/json").status_code, 200)
        self.assertEqual(client.post(archive, "{}", content_type="application/json").status_code, 200)
        trial.started_at -= timedelta(days=2)
        trial.ends_at -= timedelta(days=2)
        trial.save(update_fields=["started_at", "ends_at"])
        self.assertEqual(client.get(download).status_code, 404)
        self.assertEqual(client.post(bundle, payload, content_type="application/json").status_code, 404)
        self.assertEqual(client.post(archive, "{}", content_type="application/json").status_code, 403)
        self.assertEqual(client.post(rows, json.dumps({"model": "tenancy.Project", "after_id": 0,
            "through_id": self.project.pk}), content_type="application/json").status_code, 403)
        self.assertTrue(ProjectReportSnapshot.objects.filter(pk=report.pk).exists())  # Access cutoff is not deletion.

    def test_closed_tenant_deletion_removes_source_report_and_share_but_not_other_organization(self):
        from unittest.mock import patch
        from django.test import RequestFactory

        from integrations.models import IntegrationConnection, SearchMetricObservation
        from jobs.models import Artifact, ProjectReportShare
        from jobs.report_shares import create_report_share
        from tenancy.closure import close_organization_locally
        from tenancy.deletion import (delete_customer_database_records, prepare_customer_data_deletion,
                                      sweep_customer_artifact_versions)

        finding = record_csv_findings(project=self.project, actor=self.owner,
                                      connection=self.connection, import_id=self.run.pk)[0][0]
        report = create_project_report(project=self.project, actor=self.owner,
            request_key="delete-report-fixture", content_format="csv", finding_ids=[finding.pk],
            action_review_ids=[], outcome_ids=[])
        share, _token = create_report_share(project=self.project, actor=self.owner, report_id=report.pk,
            request_key="delete-share-fixture", recipient_email="reader@example.invalid", expires_hours=24,
            acknowledge_link_access=True)
        other_org = create_organization(user=self.other, name="Other retained customer")
        other_project = create_project(organization=other_org, user=self.other, name="Other retained project",
                                       canonical_origin="https://retained-elsewhere.example.invalid")
        request = RequestFactory().post("/api/organizations/close/")
        request.user = self.owner
        with patch("tenancy.services.did_recently_authenticate", return_value=True):
            close_organization_locally(organization=self.project.organization, actor=self.owner, request=request)
        run = prepare_customer_data_deletion(organization=self.project.organization)
        self.assertEqual(sweep_customer_artifact_versions(run=run).state, run.State.STORAGE_CLEARED)
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        owner_client = Client()
        owner_client.force_login(self.owner)
        status = owner_client.get(f"/api/organizations/{self.project.organization_id}/closure-status/")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["deletion"]["state"], run.State.COMPLETE)
        self.assertIn("hosted verification", status.json()["limitations"])
        self.assertFalse(ImportRun.objects.filter(pk=self.run.pk).exists())
        self.assertFalse(SearchMetricObservation.objects.filter(import_run_id=self.run.pk).exists())
        self.assertFalse(Artifact.objects.filter(project_id=self.project.pk).exists())
        self.assertFalse(IntegrationConnection.objects.filter(pk=self.connection.pk).exists())
        self.assertFalse(Finding.objects.filter(pk=finding.pk).exists())
        self.assertFalse(ProjectReportSnapshot.objects.filter(pk=report.pk).exists())
        self.assertFalse(ProjectReportShare.objects.filter(pk=share.pk).exists())
        self.assertTrue(Project.objects.filter(pk=other_project.pk, organization=other_org).exists())

    def test_foreign_actor_source_and_scope_revocation_fail_closed(self):
        with self.assertRaises(PermissionDenied):
            record_csv_findings(project=self.project, actor=self.other,
                                connection=self.connection, import_id=self.run.pk)
        other_project = Project.objects.create(organization=self.project.organization,
                                               name="Other", canonical_origin="https://other-finding.example")
        observation = SearchMetricObservation.objects.get(import_run=self.run, query="middle query")
        invalid = Finding(project=other_project, actor=self.owner, source_metric=observation,
                          detector="web_position_4_to_20_candidate", method_version="gsc-csv-opportunity-v1",
                          subject="middle query", fingerprint="a" * 64, evidence={"safe": True})
        with self.assertRaises(ValidationError):
            invalid.full_clean()
        update_project(project=self.project, user=self.owner, canonical_origin="https://changed.example")
        with self.assertRaises((PermissionDenied, ValidationError)):
            record_csv_findings(project=self.project, actor=self.owner,
                                connection=self.connection, import_id=self.run.pk)
        self.assertFalse(Finding.objects.exists())

    def test_explicit_review_and_draft_are_distinct_revisioned_records(self):
        finding = record_csv_findings(project=self.project, actor=self.owner,
                                      connection=self.connection, import_id=self.run.pk)[0][0]
        review = Opportunity.objects.create(project=self.project, finding=finding, actor=self.owner,
            priority=Opportunity.Priority.MEDIUM, estimated_effort="small", business_relevance="unknown",
            review_reason="Check the actual search intent before selecting work.")
        draft = Recommendation.objects.create(project=self.project, opportunity=review, actor=self.owner,
            revision=1, draft="Consider improving the existing relevant page after human review.")
        self.assertEqual((review.revision, draft.revision), (1, 1))
        self.assertEqual(review.finding.source_metric.import_run_id, self.run.pk)
        self.assertEqual(Recommendation.objects.filter(opportunity=review).count(), 1)
        with self.assertRaises(ValidationError):
            review.save()
        with self.assertRaises(ValidationError):
            draft.save()
        other_project = Project.objects.create(organization=self.project.organization, name="Foreign review",
                                               canonical_origin="https://review.example")
        with self.assertRaises(ValidationError):
            Opportunity(project=other_project, finding=finding, actor=self.owner,
                        review_reason="Different project", revision=2).full_clean()
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Finding.objects.filter(pk=finding.pk).update(source_metric=None)

    def test_project_api_requires_csrf_roles_and_explicit_review_revision(self):
        viewer_user = get_user_model().objects.create_user("finding-viewer@example.com", password="test-password")
        EmailAddress.objects.create(user=viewer_user, email=viewer_user.email, verified=True, primary=True)
        OrganizationMembership.objects.create(organization=self.project.organization, user=viewer_user,
                                              role=MembershipRole.VIEWER)
        def client_for(actor):
            client = Client(enforce_csrf_checks=True)
            client.force_login(actor)
            client.get("/_allauth/browser/v1/auth/session")
            return client
        owner, viewer, other = (client_for(actor) for actor in (self.owner, viewer_user, self.other))
        prefix = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/findings/"
        path = prefix + f"imports/{self.connection.pk}/{self.run.pk}/"
        def post(client, url, body, csrf=True):
            headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value} if csrf else {}
            return client.post(url, data=json.dumps(body), content_type="application/json", **headers)
        self.assertEqual(owner.get(prefix).json()["findings"], [])
        self.assertFalse(Finding.objects.exists())
        self.assertEqual(post(owner, path, {}, csrf=False).status_code, 403)
        self.assertEqual(post(viewer, path, {}).status_code, 403)
        self.assertEqual(post(other, path, {}).status_code, 404)
        result = post(owner, path, {})
        self.assertEqual(result.status_code, 201)
        ids = result.json()["finding_ids"]
        self.assertEqual(len(ids), 2)
        self.assertEqual(post(owner, path, {}).json()["finding_ids"], ids)
        visible = viewer.get(prefix)
        self.assertEqual(visible.status_code, 200)
        self.assertIn("no-store", visible["Cache-Control"])
        self.assertEqual(visible.json()["findings"][0]["review"], None)
        self.assertTrue(visible.json()["findings"][0]["source_current"])
        self.assertEqual(other.get(prefix).status_code, 404)
        review_url = prefix + f"{ids[0]}/reviews/"
        details = {"expected_revision": 0, "priority": "medium", "estimated_effort": "small",
                   "business_relevance": "unknown", "reason": "Check intent first"}
        self.assertEqual(post(viewer, review_url, details).status_code, 403)
        first = post(owner, review_url, details)
        self.assertEqual(first.status_code, 201)
        self.assertIsNone(first.json()["approved_action"])
        self.assertEqual(post(owner, review_url, details).json()["review"]["id"], first.json()["review"]["id"])
        self.assertEqual(post(owner, review_url, {**details, "priority": "high"}).status_code, 409)
        again = post(owner, review_url, {**details, "expected_revision": 1, "priority": "high"})
        self.assertEqual(again.json()["review"]["revision"], 2)
        self.assertEqual(Opportunity.objects.filter(project=self.project).count(), 2)
        update_project(project=self.project, user=self.owner, canonical_origin="https://changed.example")
        self.assertFalse(viewer.get(prefix).json()["findings"][0]["source_current"])
        self.assertEqual(post(owner, review_url, {**details, "expected_revision": 2}).status_code, 409)

    def test_comparable_query_changes_are_distinct_immutable_candidates(self):
        current = self.run
        job = queue_search_console_csv_import(connection=self.connection, user=self.owner,
            content=b"Top queries,Clicks,Impressions,CTR,Position\nmiddle query,3,150,2%,8\n"
                    b"new query,3,100,3%,4\n",
            date_start=current.date_start - timedelta(days=7), date_end=current.date_start - timedelta(days=1))
        self.assertTrue(execute_job(job.pk))
        previous = ImportRun.objects.get(job=job)
        records, truncated = record_query_change_findings(project=self.project, actor=self.owner,
            connection=self.connection, previous_import_id=previous.pk, current_import_id=current.pk)
        self.assertFalse(truncated)
        self.assertEqual({item.detector for item in records}, {
            "web_query_clicks_decreased_candidate", "web_query_impressions_increased_candidate",
            "web_query_average_position_worsened_candidate"})
        self.assertEqual({item.subject for item in records}, {"middle query"})
        self.assertEqual({item.evidence["previous_observation_id"] for item in records},
                         {previous.search_metrics.get(query="middle query").pk})
        self.assertEqual({item.source_metric_id for item in records},
                         {current.search_metrics.get(query="middle query").pk})
        self.assertEqual(records[0].evidence["coverage"]["hidden_queries"], "unknown")
        replay, _ = record_query_change_findings(project=self.project, actor=self.owner,
            connection=self.connection, previous_import_id=previous.pk, current_import_id=current.pk)
        self.assertEqual([item.pk for item in records], [item.pk for item in replay])
        self.assertFalse(Opportunity.objects.exists())
        with self.assertRaises(PermissionDenied):
            record_query_change_findings(project=self.project, actor=self.other,
                connection=self.connection, previous_import_id=previous.pk, current_import_id=current.pk)
        path = (f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}"
                f"/findings/query-changes/{self.connection.pk}/")
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        owner.get("/_allauth/browser/v1/auth/session")
        data = {"previous_import_id": previous.pk, "current_import_id": current.pk}
        self.assertEqual(owner.post(path, data=json.dumps(data), content_type="application/json").status_code, 403)
        result = owner.post(path, data=json.dumps(data), content_type="application/json",
                            HTTP_X_CSRFTOKEN=owner.cookies["csrftoken"].value)
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json()["finding_ids"], [item.pk for item in records])
        other = Client()
        other.force_login(self.other)
        self.assertEqual(other.post(path, data=json.dumps(data), content_type="application/json").status_code, 404)
        update_project(project=self.project, user=self.owner, canonical_origin="https://changed.example")
        self.assertEqual(owner.post(path, data=json.dumps(data), content_type="application/json",
                                    HTTP_X_CSRFTOKEN=owner.cookies["csrftoken"].value).status_code, 409)
        self.assertFalse(owner.get(path.rsplit("query-changes/", 1)[0]).json()["findings"][0]["source_current"])

    def test_page_windows_require_same_clean_observed_page_and_do_not_join_queries(self):
        project = Project.objects.create(organization=self.project.organization, name="Page comparison",
                                         canonical_origin="https://pages.example")
        connection = create_connection(project=project, user=self.owner, provider="google_search_console",
            external_property_id="https://pages.example/", capabilities=["csv_import", "page_metrics"],
            available_dimensions=["page"], source_semantics="search_console_performance",
            source_semantics_version="csv-v1", timezone="America/Los_Angeles")
        end = self.run.date_end
        def import_pages(content, start, finish):
            job = queue_search_console_csv_import(connection=connection, user=self.owner, content=content,
                date_start=start, date_end=finish)
            self.assertTrue(execute_job(job.pk))
            return ImportRun.objects.get(job=job)
        previous = import_pages(
            b"Top pages,Clicks,Impressions,CTR,Position\nhttps://pages.example/known,5,100,5%,6\n"
            b"https://pages.example/?token=secret,2,30,6.67%,5\n",
            end - timedelta(days=13), end - timedelta(days=7))
        current = import_pages(
            b"Top pages,Clicks,Impressions,CTR,Position\nhttps://pages.example/known,3,120,2.5%,9\n"
            b"https://pages.example/new,1,20,5%,2\nhttps://pages.example/?token=secret,3,40,7.5%,4\n",
            end - timedelta(days=6), end)
        records, truncated = record_page_change_findings(project=project, actor=self.owner,
            connection=connection, previous_import_id=previous.pk, current_import_id=current.pk)
        self.assertFalse(truncated)
        self.assertEqual({item.detector for item in records}, {
            "web_page_clicks_decreased_candidate", "web_page_impressions_increased_candidate",
            "web_page_average_position_worsened_candidate"})
        self.assertEqual({item.subject for item in records}, {"https://pages.example/known"})
        self.assertNotIn("secret", json.dumps([item.evidence for item in records]))
        self.assertEqual([row.pk for row in records], [row.pk for row in record_page_change_findings(
            project=project, actor=self.owner, connection=connection,
            previous_import_id=previous.pk, current_import_id=current.pk)[0]])
        with self.assertRaises(ValidationError):
            record_page_change_findings(project=project, actor=self.owner, connection=connection,
                previous_import_id=self.run.pk, current_import_id=current.pk)
        self.client.force_login(self.owner)
        path = (f"/api/organizations/{project.organization_id}/projects/{project.pk}"
                f"/findings/page-changes/{connection.pk}/")
        response = self.client.post(path, data=json.dumps({"previous_import_id": previous.pk,
            "current_import_id": current.pk}), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["finding_ids"], [item.pk for item in records])
