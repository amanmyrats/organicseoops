from unittest.mock import patch
from django.test import TransactionTestCase
from tenancy.customer_artifact_barrier import project_artifact_barrier
import hashlib

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from config.artifacts import save_private_artifact
from config.test_foundations import TEST_STORAGES
from tenancy.artifacts import project_artifact_scope
from tenancy.models import MembershipRole, OrganizationMembership, Project
from tenancy.services import create_organization, create_project, update_project, update_project_configuration

from .diagnostics import METHOD_VERSION, RULESET_VERSION, build_technical_diagnostics
from .findings import record_technical_findings
from .models import (
    Artifact,
    CrawlPageSnapshot,
    CrawlRun,
    Finding,
    JobRun,
    JobStatus,
    RenderAttempt,
    RenderedPageSnapshot,
    TechnicalDiagnosticsSnapshot,
    Opportunity,
)
from .renderer import METHOD_VERSION as RENDER_METHOD_VERSION


@override_settings(
    STORAGES=TEST_STORAGES,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/csv", "text/html", "text/plain"}),
)
class TechnicalDiagnosticsTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.tasks.execute_job_task.apply_async", return_value=None)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        self.owner = get_user_model().objects.create_user("diagnostics@example.com", password="test-password")
        EmailAddress.objects.create(user=self.owner, email=self.owner.email, verified=True, primary=True)
        self.organization = create_organization(user=self.owner, name="Diagnostics org")
        self.project = create_project(
            organization=self.organization,
            user=self.owner,
            name="Diagnostics project",
            canonical_origin="https://diagnostics.example.com",
        )
        self.job = JobRun.objects.create(
            organization=self.organization,
            project=self.project,
            actor=self.owner,
            handler="crawl_site",
            input_snapshot={
                "seeds": [
                    "https://diagnostics.example.com/",
                    "https://diagnostics.example.com/entry-final",
                    "https://diagnostics.example.com/missing-entry",
                ],
                "page_limit": 6,
            },
            config_snapshot={
                "host_delay_seconds": 1,
                "url_parameter_policy": {
                    "ignored": ["utm_source"],
                    "pagination": ["page"],
                    "facet": ["color"],
                    "variant_limit": 5,
                },
            },
            method_version="crawl-http-v1",
        )
        self.job.status = JobStatus.RUNNING
        self.job.save(update_fields=["status"])
        self.run = CrawlRun.objects.create(
            job=self.job,
            organization=self.organization,
            project=self.project,
            page_limit=6,
            pages_attempted=6,
            pages_observed=6,
            discovery={
                "urls": [
                    "https://diagnostics.example.com/",
                    "https://diagnostics.example.com/section",
                    "https://diagnostics.example.com/target",
                    "https://diagnostics.example.com/orphan",
                    "https://diagnostics.example.com/conditional",
                    "https://diagnostics.example.com/entry-final",
                ],
                "sitemap_urls": [
                    "https://diagnostics.example.com/section",
                    "https://diagnostics.example.com/orphan",
                ],
                "queue_remaining": 1,
                "skipped_parameter_variants": 2,
            },
            completed_at=timezone.now(),
        )

    def page(self, path, html, **fields):
        url = f"https://diagnostics.example.com{path}"
        content_hash = hashlib.sha256(html).hexdigest()
        with project_artifact_barrier(self.project.organization_id, shared=True):
            key = save_private_artifact(
                scope=f"{project_artifact_scope(self.project)}/jobs/{self.job.pk}",
                content=html,
                content_type="text/html",
                key_stem=content_hash[:32],
            )
        artifact = Artifact.objects.create(
            job=self.job,
            project=self.project,
            key=key,
            content_type="text/html",
            size_bytes=len(html),
        )
        return CrawlPageSnapshot.objects.create(
            crawl_run=self.run,
            project=self.project,
            requested_url=url,
            final_url=fields.pop("final_url", url),
            status_code=fields.pop("status_code", 200),
            content_hash=content_hash,
            raw_artifact=artifact,
            **fields,
        )

    def render(self, page, html, *, canonical_url, completeness="unknown"):
        content_hash = hashlib.sha256(html).hexdigest()
        with project_artifact_barrier(self.project.organization_id, shared=True):
            key = save_private_artifact(
                scope=f"{project_artifact_scope(self.project)}/jobs/{self.job.pk}",
                content=html,
                content_type="text/html",
                key_stem=content_hash[:32],
            )
        artifact = Artifact.objects.create(
            job=self.job,
            project=self.project,
            key=key,
            content_type="text/html",
            size_bytes=len(html),
        )
        attempt = RenderAttempt.objects.create(
            crawl_page=page,
            project=self.project,
            token_hash=hashlib.sha256(b"diagnostic-token").hexdigest(),
            request_hash=hashlib.sha256(b"diagnostic-request").hexdigest(),
            source_hash=page.content_hash,
            method_version=RENDER_METHOD_VERSION,
        )
        return RenderedPageSnapshot.objects.create(
            attempt=attempt,
            crawl_page=page,
            project=self.project,
            rendered_artifact=artifact,
            content_hash=content_hash,
            text_hash=hashlib.sha256(b"Rendered product").hexdigest(),
            text_excerpt="Rendered product",
            title="Rendered",
            canonical_url=canonical_url,
            comparison={"completeness": completeness},
            duration_ms=10,
            method_version=RENDER_METHOD_VERSION,
        )

    def test_raw_metadata_http_and_exact_duplicate_candidates_skip_unchecked_pages(self):
        first = self.page("/one", b"<html><body>Same raw HTML</body></html>",
            links=[{"url": "https://diagnostics.example.com/error", "internal": True},
                   {"url": "https://diagnostics.example.com/unknown", "internal": True}],
            hreflang=[{"language": "en", "url": "https://diagnostics.example.com/one"},
                      {"language": "en", "url": "https://diagnostics.example.com/two"}])
        second = CrawlPageSnapshot.objects.create(crawl_run=self.run, project=self.project,
            requested_url="https://diagnostics.example.com/two", final_url="https://diagnostics.example.com/two",
            status_code=200, content_hash=first.content_hash, raw_artifact=first.raw_artifact)
        CrawlPageSnapshot.objects.create(crawl_run=self.run, project=self.project,
            requested_url="https://diagnostics.example.com/conditional",
            final_url="https://diagnostics.example.com/conditional", status_code=304,
            content_hash=first.content_hash, raw_artifact=first.raw_artifact)
        self.page("/error", b"error", status_code=500)
        self.run.discovery = {}
        self.run.pages_attempted = self.run.pages_observed = 4
        self.run.save(update_fields=["discovery", "pages_attempted", "pages_observed"])
        self.job.status = JobStatus.SUCCEEDED
        self.job.save(update_fields=["status"])
        snapshot = build_technical_diagnostics(self.run.pk)
        records, truncated = record_technical_findings(project=self.project, actor=self.owner,
                                                       diagnostics_id=snapshot.pk)
        self.assertFalse(truncated)
        detectors = {item.detector for item in records}
        self.assertIn("raw_title_missing_candidate", detectors)
        self.assertIn("raw_meta_description_missing_candidate", detectors)
        self.assertIn("observed_http_error_candidate", detectors)
        self.assertIn("observed_internal_link_http_error_candidate", detectors)
        self.assertIn("conflicting_raw_hreflang_candidate", detectors)
        self.assertEqual(len([item for item in records if item.detector == "observed_internal_link_http_error_candidate"]), 1)
        duplicates = [item for item in records if item.detector == "exact_raw_html_duplicate_candidate"]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0].evidence["details"]["crawl_page_ids"], [first.pk, second.pk])
        self.assertNotIn("Same raw HTML", str([item.evidence for item in records]))
        self.assertFalse(any(item.subject.endswith("/conditional") and item.detector.startswith("raw_")
                             for item in records))
        replay, _ = record_technical_findings(project=self.project, actor=self.owner, diagnostics_id=snapshot.pk)
        self.assertEqual([item.pk for item in replay], [item.pk for item in records])

    def test_partial_crawl_does_not_label_equal_html_as_a_complete_duplicate_pair(self):
        first = self.page("/one", b"<html><body>Shared</body></html>")
        CrawlPageSnapshot.objects.create(crawl_run=self.run, project=self.project,
            requested_url="https://diagnostics.example.com/two", final_url="https://diagnostics.example.com/two",
            status_code=200, content_hash=first.content_hash, raw_artifact=first.raw_artifact)
        self.run.discovery = {"queue_remaining": 1}
        self.run.pages_attempted = self.run.pages_observed = 2
        self.run.save(update_fields=["discovery", "pages_attempted", "pages_observed"])
        self.job.status = JobStatus.PARTIALLY_SUCCEEDED
        self.job.save(update_fields=["status"])
        source = build_technical_diagnostics(self.run.pk)
        findings, _ = record_technical_findings(project=self.project, actor=self.owner, diagnostics_id=source.pk)
        self.assertNotIn("exact_raw_html_duplicate_candidate", {item.detector for item in findings})
        self.assertIn("raw_title_missing_candidate", {item.detector for item in findings})

    def test_diagnostics_preserve_coverage_unknowns_and_bounded_observations(self):
        variant_links = [
            {
                "url": f"https://diagnostics.example.com/products?page={number}&color=blue&utm_source=campaign",
                "internal": True,
            }
            for number in range(1, 6)
        ]
        root = self.page(
            "/",
            b'<h1>Visible product</h1><script type="application/ld+json">'
            b'{"@context":"https://schema.org","@type":"Product","name":"Visible product"}</script>',
            canonical_url="https://diagnostics.example.com/target",
            links=[{"url": "https://diagnostics.example.com/section", "internal": True}, *variant_links],
            structured_data=[{"@context": "https://schema.org", "@type": "Product", "name": "Visible product"}],
        )
        self.page(
            "/section",
            b"<h1>Section</h1>",
            canonical_url="https://diagnostics.example.com/conditional",
            links=[{"url": "https://diagnostics.example.com/target", "internal": True}],
        )
        self.page(
            "/target",
            b"<h1>Target</h1>",
            final_url="https://diagnostics.example.com/target-final",
            redirect_chain=[{"url": "https://diagnostics.example.com/target", "status": 301}],
            canonical_url="https://diagnostics.example.com/final",
            robots_directives=[{"agent": "robots", "content": "noindex,follow"}],
            structured_data=[{"name": "Target"}],
        )
        self.page(
            "/orphan",
            b"<h1>Orphan</h1>",
            canonical_url="https://diagnostics.example.com/target",
            structured_data_errors=[{"block": 1, "category": "invalid_json"}],
        )
        self.page(
            "/conditional",
            b"<h1>Conditional reuse</h1>",
            status_code=304,
            canonical_url="https://diagnostics.example.com/conditional",
            structured_data=[{
                "@id": "graph",
                "@graph": [
                    {"@type": "schema:Product", "name": "Conditional reuse"},
                    {"@type": "https://custom.example/Thing"},
                ],
            }],
        )
        self.page(
            "/entry-old",
            b"<h1>Redirected entry</h1>" + b"x" * 17000 + b"<p>Late name</p>",
            final_url="https://diagnostics.example.com/entry-final",
            redirect_chain=[{"url": "https://diagnostics.example.com/entry-old", "status": 301}],
            canonical_url="https://diagnostics.example.com/entry-final",
            structured_data=[{"@type": "Product", "name": "Late name"}],
            structured_data_errors=[{"block": 21, "category": "block_limit"}],
        )
        rendered_html = (
            b'<h1>Rendered product</h1><script type="application/ld+json">'
            b'{"@type":"Product","name":"Hidden product"}</script>'
        )
        self.render(root, rendered_html, canonical_url="https://outside.example/canonical")
        self.job.status = JobStatus.PARTIALLY_SUCCEEDED
        self.job.save(update_fields=["status"])
        update_project_configuration(
            project=self.project,
            user=self.owner,
            expected_revision=0,
            changes={
                "ignored_query_parameters": ["campaign"],
                "pagination_query_parameters": ["offset"],
                "facet_query_parameters": ["size"],
                "query_variant_limit": 2,
            },
        )

        snapshot = build_technical_diagnostics(self.run.pk)
        findings, truncated = record_technical_findings(project=self.project, actor=self.owner,
                                                       diagnostics_id=snapshot.pk)
        self.assertFalse(truncated)
        self.assertIn("canonical_canonical_chain", {item.detector for item in findings})
        self.assertIn("schema_invalid_syntax_candidate", {item.detector for item in findings})
        self.assertIn("pagination_variant_candidate", {item.detector for item in findings})
        self.assertNotIn("orphan_relative_to_complete_crawl_candidate", {item.detector for item in findings})
        self.assertTrue(all(item.source_diagnostics_id == snapshot.pk for item in findings))
        self.assertFalse(Opportunity.objects.exists())
        self.assertEqual([item.pk for item in findings], [item.pk for item in record_technical_findings(
            project=self.project, actor=self.owner, diagnostics_id=snapshot.pk)[0]])
        self.assertNotIn("color=blue", str([item.evidence for item in findings]))
        self.assertNotIn("campaign", str([item.evidence for item in findings]))
        self.assertEqual(Finding.objects.filter(source_diagnostics=snapshot).count(), len(findings))
        output = snapshot.output

        self.assertEqual((snapshot.method_version, snapshot.ruleset_version), (METHOD_VERSION, RULESET_VERSION))
        self.assertEqual(output["coverage"]["state"], "partial")
        self.assertIn("skipped_parameter_variants", output["coverage"]["reasons"])
        self.assertEqual(output["coverage"]["sitemap_inventory"], {"state": "available", "urls": 2})
        root_canonical = output["canonicals"]["observations"][0]
        self.assertEqual(
            set(root_canonical["conflicts"]),
            {"canonical_chain", "canonical_target_noindex", "canonical_target_redirects"},
        )
        self.assertEqual(root_canonical["browser_observations"], ["partial_raw_rendered_difference"])
        self.assertEqual(root_canonical["rendered"]["scope"], "outside_scope")
        self.assertEqual(output["canonicals"]["shared_targets"][0]["interpretation"], "review_candidate_not_conflict")
        conditional = next(
            item for item in output["canonicals"]["observations"]
            if item["url"] == "https://diagnostics.example.com/conditional"
        )
        self.assertEqual(conditional["raw"]["target_state"], "conditional_reuse")
        self.assertNotIn("canonical_target_non_200", conditional["conflicts"])
        final_target = next(
            item for item in output["canonicals"]["observations"]
            if item["url"] == "https://diagnostics.example.com/orphan"
        )
        self.assertEqual(final_target["raw"]["target_redirects"], 1)
        redirected_entry = next(
            item for item in output["canonicals"]["observations"]
            if item["url"] == "https://diagnostics.example.com/entry-final"
        )
        self.assertEqual(redirected_entry["raw"]["matched_as"], "final")
        self.assertEqual(redirected_entry["raw"]["target_redirects"], 0)
        nodes = {item["url"]: item for item in output["link_graph"]["nodes"]}
        self.assertEqual(nodes["https://diagnostics.example.com/"]["depth"], 0)
        self.assertEqual(nodes["https://diagnostics.example.com/section"]["depth"], 1)
        self.assertEqual(nodes["https://diagnostics.example.com/target"]["depth"], 2)
        self.assertEqual(
            nodes["https://diagnostics.example.com/orphan"]["orphan_status"], "unknown_partial_coverage",
        )
        self.assertTrue(nodes["https://diagnostics.example.com/orphan"]["in_sitemap_inventory"])
        entries = {item["configured_url"]: item for item in output["link_graph"]["entry_mappings"]}
        self.assertEqual(entries["https://diagnostics.example.com/entry-final"]["matched_as"], "final")
        self.assertEqual(entries["https://diagnostics.example.com/missing-entry"]["state"], "unobserved")
        variants = output["url_variants"]
        self.assertEqual(variants["policy"], "project_rules")
        self.assertTrue(variants["project_rules_available"])
        self.assertEqual(variants["configured_rules"], {
            "ignored": ["utm_source"], "pagination": ["page"], "facet": ["color"], "variant_limit": 5,
        })
        self.assertEqual(variants["skipped_parameter_variants"], 2)
        self.assertTrue(variants["groups"][0]["pagination_candidate"])
        self.assertTrue(variants["groups"][0]["high_variant_count_candidate"])
        self.assertEqual(variants["groups"][0]["ignored_parameters"], ["utm_source"])
        self.assertEqual(variants["groups"][0]["configured_pagination_parameters"], ["page"])
        self.assertEqual(variants["groups"][0]["configured_facet_parameters"], ["color"])
        self.assertTrue(variants["groups"][0]["observed_variant_count_at_or_above_limit"])
        self.assertNotIn("limit_reached", variants["groups"][0])
        self.assertNotIn("blue", str(variants))
        self.assertNotIn("campaign", str(variants))
        self.assertNotIn("variant_hash", str(variants))
        schema = {item["url"]: item for item in output["structured_data"]["observations"]}
        self.assertEqual(schema["https://diagnostics.example.com/"]["raw"]["state"], "syntax_type_observed")
        self.assertEqual(schema["https://diagnostics.example.com/"]["raw"]["visible_content_consistency"], "matched")
        self.assertEqual(schema["https://diagnostics.example.com/"]["rendered"]["visible_content_consistency"], "unknown")
        self.assertEqual(schema["https://diagnostics.example.com/target-final"]["raw"]["state"], "type_shape_issue_observed")
        self.assertEqual(schema["https://diagnostics.example.com/orphan"]["raw"]["state"], "invalid_syntax")
        conditional_schema = schema["https://diagnostics.example.com/conditional"]["raw"]
        self.assertEqual(conditional_schema["state"], "syntax_type_observed")
        self.assertEqual(
            [node["type_status"] for node in conditional_schema["nodes"]],
            ["unresolved_identifier", "unresolved_identifier"],
        )
        entry_schema = schema["https://diagnostics.example.com/entry-final"]["raw"]
        self.assertEqual(entry_schema["state"], "partial_limit")
        self.assertEqual(entry_schema["visible_content_consistency"], "unknown")
        self.assertEqual(build_technical_diagnostics(self.run.pk).pk, snapshot.pk)
        with self.assertRaises(ValidationError):
            snapshot.save()

    def test_diagnostics_reject_changed_or_cross_project_evidence(self):
        self.job.status = JobStatus.SUCCEEDED
        self.job.save(update_fields=["status"])
        snapshot = build_technical_diagnostics(self.run.pk)
        self.page("/later", b"<h1>Late</h1>")
        with self.assertRaisesMessage(ValidationError, "different crawl evidence"):
            build_technical_diagnostics(self.run.pk)

        other = Project.objects.create(
            organization=self.organization,
            name="Other diagnostics project",
            canonical_origin="https://other-diagnostics.example.com",
        )
        snapshot.project = other
        snapshot._state.adding = True
        with self.assertRaisesMessage(ValidationError, "crawl run's project"):
            snapshot.full_clean()

    def test_diagnostics_hash_binds_crawl_method_and_configuration(self):
        self.job.status = JobStatus.SUCCEEDED
        self.job.save(update_fields=["status"])
        build_technical_diagnostics(self.run.pk)
        JobRun.objects.filter(pk=self.job.pk).update(
            method_version="crawl-http-v2",
            config_snapshot={"host_delay_seconds": 1, "url_parameter_policy": {
                "ignored": ["campaign"], "pagination": [], "facet": [], "variant_limit": 2,
            }},
        )
        with self.assertRaisesMessage(ValidationError, "different crawl evidence"):
            build_technical_diagnostics(self.run.pk)

    def test_project_technical_candidate_api_requires_current_scope_and_owner_csrf(self):
        self.page("/", b"<h1>Page</h1>", canonical_url="https://diagnostics.example.com/target")
        self.page("/target", b"<h1>Error</h1>", status_code=404)
        self.job.status = JobStatus.SUCCEEDED
        self.job.save(update_fields=["status", "updated_at"])
        snapshot = build_technical_diagnostics(self.run.pk)
        path = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/findings/technical/{snapshot.pk}/"
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        owner.get("/_allauth/browser/v1/auth/session")
        viewer_user = get_user_model().objects.create_user("technical-viewer@example.com", password="test-password")
        OrganizationMembership.objects.create(organization=self.organization, user=viewer_user,
                                              role=MembershipRole.VIEWER)
        viewer = Client(enforce_csrf_checks=True)
        viewer.force_login(viewer_user)
        viewer.get("/_allauth/browser/v1/auth/session")
        self.assertEqual(owner.post(path, data="{}", content_type="application/json").status_code, 403)
        self.assertEqual(viewer.post(path, data="{}", content_type="application/json",
                                     HTTP_X_CSRFTOKEN=viewer.cookies["csrftoken"].value).status_code, 403)
        response = owner.post(path, data="{}", content_type="application/json",
                              HTTP_X_CSRFTOKEN=owner.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["finding_ids"])
        listed = owner.get(f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/findings/").json()["findings"]
        self.assertTrue(all(item["source_current"] for item in listed))
        self.assertEqual({item["source_diagnostics_id"] for item in listed}, {snapshot.pk})
        update_project(project=self.project, user=self.owner, canonical_origin="https://moved.example.com")
        listed = owner.get(f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/findings/").json()["findings"]
        self.assertTrue(all(not item["source_current"] for item in listed))
