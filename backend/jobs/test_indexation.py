import json
from datetime import timedelta

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.utils import timezone

from tenancy.models import MembershipRole, OrganizationMembership, Project, ProjectOriginVerification
from tenancy.services import create_organization, create_project

from .diagnostics import build_technical_diagnostics
from .indexation import build_indexation_evidence, reconcile_indexation_reports
from .findings import record_indexation_findings
from .models import CrawlPageSnapshot, CrawlRun, Finding, IndexationEvidenceSnapshot, JobRun, JobStatus, Opportunity


class IndexationEvidenceTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("indexation@example.com", password="test-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        organization = create_organization(user=self.owner, name="Indexation org")
        self.project = create_project(
            organization=organization, user=self.owner, name="Indexation site",
            canonical_origin="https://indexation.example.com",
        )
        self.job = JobRun.objects.create(
            organization=organization, project=self.project, actor=self.owner, handler="crawl_site",
            input_snapshot={"seeds": ["https://indexation.example.com/", "https://indexation.example.com/blocked"], "page_limit": 4},
            method_version="crawl-http-v1",
        )
        self.job.status = JobStatus.RUNNING
        self.job.save(update_fields=["status"])
        self.run = CrawlRun.objects.create(
            job=self.job, organization=organization, project=self.project, page_limit=4,
            pages_attempted=2, pages_observed=2, robots_status="available",
            discovery={
                "urls": ["https://indexation.example.com/", "https://indexation.example.com/failed"],
                "sitemap_urls": ["https://indexation.example.com/", "https://indexation.example.com/failed"],
                "skipped_robots": 1, "queue_remaining": 1,
            },
            completed_at=timezone.now(),
        )

    def page(self, path, *, status=200, directives=None, canonical="", links=None, final_url=None):
        url = "https://indexation.example.com" + path
        return CrawlPageSnapshot.objects.create(
            crawl_run=self.run, project=self.project, requested_url=url, final_url=final_url or url,
            status_code=status, robots_directives=directives or [], canonical_url=canonical,
            links=links or [],
        )

    def finish(self):
        self.job.status = JobStatus.PARTIALLY_SUCCEEDED
        self.job.save(update_fields=["status", "updated_at"])
        build_technical_diagnostics(self.run.pk)

    def test_sitemap_and_crawl_conflicts_do_not_claim_engine_indexing(self):
        self.page("/", directives=[{"agent": "robots", "content": "noindex"}],
            canonical="https://indexation.example.com/other",
            links=[{"url": "https://indexation.example.com/path?private=secret-value", "internal": True},
                   {"url": "https://outside.example.com/", "internal": False}])
        self.page("/failed", status=404)
        self.finish()
        snapshot = build_indexation_evidence(self.run.pk)
        output = snapshot.output
        by_url = {item["url"]: item for item in output["urls"]}
        home = by_url["https://indexation.example.com/"]
        self.assertIn("sitemap", home["discovered_by"])
        self.assertIn("sitemap_http_or_noindex_candidate", home["indexability_signals"])
        self.assertEqual(home["fetch_observations"][0]["directive_state"], "noindex_observed")
        self.assertEqual(home["fetch_observations"][0]["declared_canonical"], "https://indexation.example.com/other")
        self.assertIsNone(home["engine_selected_canonical"])
        self.assertEqual(home["engine_indexed_state"], "unknown_no_engine_report")
        self.assertEqual(by_url["https://indexation.example.com/failed"]["fetch_observations"][0]["status_code"], 404)
        self.assertEqual(by_url["https://indexation.example.com/blocked"]["crawlability"], "unknown_not_checked")
        self.assertEqual(output["coverage"]["unattributed_robots_skips"], 1)
        self.assertEqual(output["coverage"]["analytics_inventory"], "unavailable")
        self.assertEqual(output["coverage"]["engine_indexing_reports"], "unavailable")
        self.assertEqual(output["coverage"]["omitted_parameterized_urls"], 1)
        self.assertNotIn("secret-value", json.dumps(output))
        self.assertNotIn("outside.example.com", json.dumps(output))
        self.assertEqual(build_indexation_evidence(self.run.pk).pk, snapshot.pk)
        with self.assertRaises(ValidationError):
            snapshot.save()

    def test_changed_or_cross_project_evidence_cannot_be_reused(self):
        self.page("/")
        self.finish()
        snapshot = build_indexation_evidence(self.run.pk)
        other = Project.objects.create(
            organization=self.project.organization, name="Other", canonical_origin="https://other.example.com",
        )
        snapshot.project = other
        snapshot._state.adding = True
        with self.assertRaisesMessage(ValidationError, "crawl project's scope"):
            snapshot.full_clean()
        self.page("/late", status=503)
        with self.assertRaises(ValidationError):
            build_indexation_evidence(self.run.pk)

    def test_redirected_sitemap_url_does_not_inherit_final_page_directives(self):
        self.run.discovery["sitemap_urls"] = ["https://indexation.example.com/"]
        self.run.save(update_fields=["discovery"])
        self.page("/", final_url="https://indexation.example.com/final",
                  directives=[{"agent": "robots", "content": "noindex"}],
                  canonical="https://indexation.example.com/final")
        self.finish()
        output = build_indexation_evidence(self.run.pk).output
        by_url = {item["url"]: item for item in output["urls"]}
        requested = by_url["https://indexation.example.com/"]
        final = by_url["https://indexation.example.com/final"]
        self.assertEqual(requested["fetch_observations"][0]["fetch_state"], "redirect_observed")
        self.assertEqual(requested["fetch_observations"][0]["directive_state"], "unknown_failed_or_unchecked")
        self.assertIsNone(requested["fetch_observations"][0]["declared_canonical"])
        self.assertEqual(requested["indexability_signals"], ["sitemap_redirect_candidate"])
        self.assertEqual(final["fetch_observations"][0]["directive_state"], "noindex_observed")

    def test_parameterized_canonicals_never_serialize_query_values(self):
        self.page("/", canonical="https://indexation.example.com/target?token=private-value")
        self.finish()
        output = build_indexation_evidence(self.run.pk).output
        visit = next(item for item in output["urls"] if item["url"] == "https://indexation.example.com/")["fetch_observations"][0]
        self.assertIsNone(visit["declared_canonical"])
        self.assertEqual(visit["declared_canonical_scope"], "redacted_parameterized_or_credentialed")
        self.assertNotIn("private-value", json.dumps(output))

    def test_revoked_crawl_actor_cannot_create_indexation_evidence(self):
        self.page("/")
        self.finish()
        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
        with self.assertRaises(ValidationError):
            build_indexation_evidence(self.run.pk)
        self.assertEqual(IndexationEvidenceSnapshot.objects.count(), 0)

    def inspection(self, url, *, verdict="PASS", canonical=None, crawled_at=None, property_id=None):
        from integrations.google_tokens import SCOPE
        from integrations.models import GoogleOAuthGrant, IntegrationConnection
        from integrations.search_console_coverage import record_coverage_observation

        property_id = property_id or "sc-domain:indexation.example.com"
        domain = property_id.startswith("sc-domain:")
        ProjectOriginVerification.objects.get_or_create(
            project=self.project, organization=self.project.organization, origin=self.project.canonical_origin,
            defaults={"challenge_digest": "a" * 64, "state": ProjectOriginVerification.State.VERIFIED,
                      "verified_at": timezone.now()},
        )
        grant = GoogleOAuthGrant.objects.create(
            project=self.project, organization=self.project.organization, actor=self.owner, scope=SCOPE,
            encrypted_refresh_token="v1:fixture-only", state=GoogleOAuthGrant.State.ACTIVE,
            selected_property_id=property_id, selected_site_url=property_id if domain else property_id + "/",
            selected_origins=[self.project.canonical_origin] if domain else [], verified_at=timezone.now(),
        )
        connection = IntegrationConnection(
            project=self.project, provider="google_search_console", external_property_id=property_id,
            credential_reference=grant.credential_reference,
            capabilities=["api_sync", "page_metrics", "indexing_status", "sitemaps"],
            available_dimensions=["page"], source_semantics="search_console_domain_pages" if domain else "search_console_performance",
            source_semantics_version="gsc-domain-page-v1" if domain else "gsc-performance-v1", timezone="America/Los_Angeles",
        )
        connection.save()
        job = JobRun.objects.create(
            project=self.project, organization=self.project.organization, actor=self.owner,
            handler="collect_search_console_coverage", method_version="search-console-coverage-v1",
            input_snapshot={"connection_id": connection.pk, "grant_id": grant.pk, "inspection_url": url},
            config_snapshot={"grant_revision": grant.revision, "property_id": property_id,
                             "approved_origins": [self.project.canonical_origin]},
        )
        job.status = JobStatus.RUNNING
        job.save(update_fields=["status", "updated_at"])
        result = record_coverage_observation(job=job, connection=connection, grant=grant, source="inspection",
            response={"inspectionResult": {"indexStatusResult": {
                "verdict": verdict, "googleCanonical": canonical or url,
                "userCanonical": "https://indexation.example.com/?secret=hidden",
                "lastCrawlTime": (crawled_at or timezone.now()).isoformat(),
            }}})
        job.status = JobStatus.SUCCEEDED
        job.save(update_fields=["status", "updated_at"])
        return result, grant

    def test_current_google_indexed_version_is_source_identified_not_crawl_inference(self):
        page = self.page("/", directives=[{"agent": "robots", "content": "noindex"}],
                         canonical="https://indexation.example.com/declared")
        CrawlPageSnapshot.objects.filter(pk=page.pk).update(observed_at=timezone.now() - timedelta(days=2))
        self.finish()
        snapshot = build_indexation_evidence(self.run.pk)
        original = {row["url"]: row for row in snapshot.output["urls"]}
        self.assertEqual(original["https://indexation.example.com/"]["engine_indexed_state"], "unknown_no_engine_report")
        result, grant = self.inspection("https://indexation.example.com/", canonical="https://indexation.example.com/selected")
        report = reconcile_indexation_reports(project=self.project, user=self.owner, crawl_run_id=self.run.pk)
        self.assertEqual(report["diagnostics_id"], snapshot.diagnostics_id)
        url = next(row for row in report["urls"] if row["url"] == "https://indexation.example.com/")
        self.assertEqual(url["engine_indexed_state"], "unknown_no_engine_report")
        self.assertEqual(url["engine_reports"][0]["indexed_state"], "reported_indexed")
        self.assertEqual(url["engine_reports"][0]["observation_id"], result.pk)
        self.assertEqual(url["engine_reports"][0]["method"], "google_indexed_version_only")
        self.assertEqual(set(url["engine_reports"][0]["disagreement_candidates"]), {
            "local_noindex_vs_google_indexed_candidate", "declared_vs_google_selected_canonical_candidate",
        })
        self.assertIsNone(url["engine_reports"][0]["declared_canonical"])
        self.assertNotIn("secret=hidden", json.dumps(report))
        self.assertFalse(next(row for row in report["urls"] if row["url"].endswith("/blocked"))["engine_reports"])
        self.assertEqual(IndexationEvidenceSnapshot.objects.get(pk=snapshot.pk).output, snapshot.output)
        grant.state = grant.State.RECONNECT_REQUIRED
        grant.revision += 1
        grant.save()
        unavailable = reconcile_indexation_reports(project=self.project, user=self.owner, crawl_run_id=self.run.pk)
        self.assertEqual(unavailable["coverage"]["engine_indexing_reports"], "unavailable")

    def test_older_google_indexed_version_is_stale_not_current_conflict(self):
        self.page("/", directives=[{"agent": "robots", "content": "noindex"}])
        self.finish()
        build_indexation_evidence(self.run.pk)
        self.inspection("https://indexation.example.com/", crawled_at=timezone.now() - timedelta(days=2))
        row = next(row for row in reconcile_indexation_reports(project=self.project, user=self.owner,
            crawl_run_id=self.run.pk)["urls"] if row["url"] == "https://indexation.example.com/")
        self.assertTrue(row["engine_reports"][0]["stale_relative_to_local_crawl"])
        self.assertEqual(row["engine_reports"][0]["disagreement_candidates"], [])

    def test_foreign_crawl_and_removed_verified_origin_cannot_reuse_inspection(self):
        self.page("/")
        self.finish()
        build_indexation_evidence(self.run.pk)
        self.inspection("https://indexation.example.com/")
        other = Project.objects.create(organization=self.project.organization, name="Other",
                                       canonical_origin="https://different.example.com")
        with self.assertRaises(ValidationError):
            reconcile_indexation_reports(project=other, user=self.owner, crawl_run_id=self.run.pk)
        ProjectOriginVerification.objects.filter(project=self.project).update(
            state=ProjectOriginVerification.State.REVOKED, revoked_at=timezone.now())
        report = reconcile_indexation_reports(project=self.project, user=self.owner, crawl_run_id=self.run.pk)
        self.assertEqual(report["coverage"]["engine_indexing_reports"], "unavailable")
        self.assertFalse(next(row for row in report["urls"] if row["url"] == "https://indexation.example.com/")["engine_reports"])

    def test_reports_on_distinct_google_properties_keep_separate_verdicts(self):
        page = self.page("/")
        CrawlPageSnapshot.objects.filter(pk=page.pk).update(observed_at=timezone.now() - timedelta(days=2))
        self.finish()
        build_indexation_evidence(self.run.pk)
        self.inspection("https://indexation.example.com/", verdict="PASS")
        self.inspection("https://indexation.example.com/", verdict="FAIL",
                        property_id="https://indexation.example.com")
        row = next(row for row in reconcile_indexation_reports(project=self.project, user=self.owner,
            crawl_run_id=self.run.pk)["urls"] if row["url"] == "https://indexation.example.com/")
        self.assertEqual({(report["property"], report["indexed_state"]) for report in row["engine_reports"]}, {
            ("sc-domain:indexation.example.com", "reported_indexed"),
            ("https://indexation.example.com", "reported_not_indexed"),
        })

    def test_indexation_candidate_findings_keep_current_google_and_local_evidence_separate(self):
        page = self.page("/", directives=[{"agent": "robots", "content": "noindex"}])
        CrawlPageSnapshot.objects.filter(pk=page.pk).update(observed_at=timezone.now() - timedelta(days=2))
        self.finish()
        snapshot = build_indexation_evidence(self.run.pk)
        observed, grant = self.inspection("https://indexation.example.com/")
        findings, availability, truncated = record_indexation_findings(project=self.project, actor=self.owner,
                                                             crawl_run_id=self.run.pk)
        self.assertFalse(truncated)
        self.assertEqual(availability, "indexed_version_per_url_where_authorized")
        self.assertEqual({item.detector for item in findings}, {
            "sitemap_http_or_noindex_candidate", "local_noindex_vs_google_indexed_candidate"})
        self.assertTrue(all(item.source_indexation_id == snapshot.pk for item in findings))
        google = next(item for item in findings if item.evidence["provider"] is not None)
        self.assertEqual((google.evidence["provider"]["observation_id"], google.evidence["provider"]["property"]),
                         (observed.pk, "sc-domain:indexation.example.com"))
        again, _, _ = record_indexation_findings(project=self.project, actor=self.owner, crawl_run_id=self.run.pk)
        self.assertEqual([item.pk for item in findings], [item.pk for item in again])
        self.assertFalse(Opportunity.objects.exists())
        self.assertNotIn("secret=hidden", json.dumps([item.evidence for item in findings]))
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        browser.get("/_allauth/browser/v1/auth/session")
        prefix = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/findings/"
        path = prefix + f"indexation/{self.run.pk}/"
        self.assertEqual(browser.post(path, data="{}", content_type="application/json").status_code, 403)
        response = browser.post(path, data="{}", content_type="application/json",
                                HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.json()["finding_ids"]), {item.pk for item in findings})
        listed = browser.get(prefix).json()["findings"]
        self.assertTrue(all(item["source_current"] for item in listed))
        self.assertEqual({item["source_indexation_id"] for item in listed}, {snapshot.pk})
        grant.state = grant.State.RECONNECT_REQUIRED
        grant.revision += 1
        grant.save()
        current, availability, _ = record_indexation_findings(project=self.project, actor=self.owner,
                                                            crawl_run_id=self.run.pk)
        self.assertEqual(availability, "unavailable")
        self.assertEqual([item.detector for item in current], ["sitemap_http_or_noindex_candidate"])
        self.assertEqual(Finding.objects.filter(source_indexation=snapshot).count(), 2)
        listed = browser.get(prefix).json()["findings"]
        self.assertFalse(next(item for item in listed if item["id"] == google.pk)["source_current"])
        self.assertTrue(next(item for item in listed if item["id"] != google.pk)["source_current"])
        review_path = prefix + f"{google.pk}/reviews/"
        self.assertEqual(browser.post(review_path, data=json.dumps({"expected_revision": 0,
            "priority": "medium", "estimated_effort": "small", "business_relevance": "unknown",
            "reason": "Review the contradiction"}), content_type="application/json",
            HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value).status_code, 409)

    def test_stale_google_report_never_generates_indexed_disagreement_finding(self):
        self.page("/", directives=[{"agent": "robots", "content": "noindex"}])
        self.finish()
        build_indexation_evidence(self.run.pk)
        self.inspection("https://indexation.example.com/", crawled_at=timezone.now() - timedelta(days=2))
        findings, _, _ = record_indexation_findings(project=self.project, actor=self.owner, crawl_run_id=self.run.pk)
        self.assertEqual([item.detector for item in findings], ["sitemap_http_or_noindex_candidate"])

    def test_protected_no_fetch_api_builds_only_on_explicit_owner_post_and_viewers_read(self):
        self.page("/")
        self.finish()
        path = f"/api/organizations/{self.project.organization_id}/projects/{self.project.pk}/indexation/"
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        owner.get("/_allauth/browser/v1/auth/session")
        viewer_user = get_user_model().objects.create_user("indexation-viewer@example.com", password="test-password")
        OrganizationMembership.objects.create(organization=self.project.organization, user=viewer_user,
                                              role=MembershipRole.VIEWER)
        viewer = Client(enforce_csrf_checks=True)
        viewer.force_login(viewer_user)
        viewer.get("/_allauth/browser/v1/auth/session")
        outsider_user = get_user_model().objects.create_user("indexation-outsider@example.com", password="test-password")
        outsider = Client(enforce_csrf_checks=True)
        outsider.force_login(outsider_user)
        self.assertEqual(owner.get(path).json()["report"], None)
        self.assertFalse(IndexationEvidenceSnapshot.objects.exists())
        payload = json.dumps({"crawl_run_id": self.run.pk})
        self.assertEqual(owner.post(path, data=payload, content_type="application/json").status_code, 403)
        self.assertEqual(viewer.post(path, data=payload, content_type="application/json",
                                     HTTP_X_CSRFTOKEN=viewer.cookies["csrftoken"].value).status_code, 403)
        self.assertEqual(outsider.get(path).status_code, 404)
        response = owner.post(path, data=payload, content_type="application/json",
                              HTTP_X_CSRFTOKEN=owner.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(owner.post(path, data=payload, content_type="application/json",
                                    HTTP_X_CSRFTOKEN=owner.cookies["csrftoken"].value).status_code, 200)
        read = viewer.get(path, {"crawl_run_id": self.run.pk})
        self.assertEqual(read.status_code, 200)
        self.assertIn("no-store", read["Cache-Control"])
        self.assertEqual(read.json()["report"]["urls"][0]["engine_indexed_state"], "unknown_no_engine_report")
        self.assertEqual(viewer.get(path, {"crawl_run_id": 999999}).status_code, 404)
