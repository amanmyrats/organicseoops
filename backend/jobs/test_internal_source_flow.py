"""Synthetic contract proof only: no real provider/site/paid operation."""
import json
import os
from datetime import timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from integrations.models import ImportRun
from integrations.search_console import queue_search_console_csv_import
from integrations.services import create_connection
from .action_review import record_action
from .content_brief import create_content_brief, read_content_brief
from .crawler import execute_crawl_job
from .findings import record_csv_findings, record_performance_findings
from .intent_mapping import review_intent_cluster
from .models import JobRun, JobStatus, PerformanceObservationSnapshot
from .performance_job import execute_performance_audit, queue_performance_audit
from .research import execute_research, queue_research
from .services import execute_job
from .local_assessment import review_local_business
from .technical_outcome import record_action_crawl_observations


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/csv", "application/json", "text/html", "text/plain"}),
    GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "internal-source-flow"}})
class InternalSourceFlowTests(TransactionTestCase):
    def test_one_project_import_crawl_performance_mapping_accepted_action_research_and_brief(self):
        from .test_research import ResearchTests
        from .test_crawler import FakeFetcher, response
        self.url = ResearchTests.url
        ResearchTests.setUp(self)
        from tenancy.services import update_project_configuration
        config = update_project_configuration(project=self.project, user=self.owner, expected_revision=1,
            changes={"business_locations": ["Synthetic fixture office"], "service_areas": ["Synthetic fixture service area"]})
        local = review_local_business(project=self.project, actor=self.owner, request_key="internal-local-001",
            expected_config_revision=config.revision, location_label="Synthetic fixture office",
            business_name="Synthetic fixture business", address_display="", phone="", hours="",
            services=["Synthetic fixture service"], service_areas=["Synthetic fixture service area"],
            profile_url="", eligibility="unknown", review_theme="", evidence_note="Synthetic human-entered data only.",
            suggested_action="Verify genuine service facts before drafting.")
        self.assertEqual(local.eligibility, "unknown")
        root = self.project.canonical_origin + "/"
        connection = create_connection(project=self.project, user=self.owner, provider="google_search_console",
            external_property_id=root, capabilities=["csv_import", "query_metrics"], available_dimensions=["query"],
            source_semantics="search_console_performance", source_semantics_version="csv-v1",
            timezone="America/Los_Angeles")
        end = timezone.now().astimezone(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=3)
        with patch("jobs.services.dispatch_pending"):
            source_job = queue_search_console_csv_import(connection=connection, user=self.owner,
                content=b"Top queries,Clicks,Impressions,CTR,Position\nservice questions,2,200,1%,10\n",
                date_start=end - timedelta(days=6), date_end=end)
        self.assertTrue(execute_job(source_job.pk))
        imported = ImportRun.objects.get(job=source_job)
        findings, _truncated = record_csv_findings(project=self.project, actor=self.owner,
                                                    connection=connection, import_id=imported.pk)
        client = Client(); client.force_login(self.owner)
        audit_path = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/first-audit/"
        with patch("jobs.services.dispatch_pending"):
            requested = client.post(audit_path, json.dumps({"page_limit": 1, "idempotency_key": "internal-first-crawl"}),
                                    content_type="application/json")
        self.assertEqual(requested.status_code, 202, requested.content)
        crawl = JobRun.objects.get(pk=requested.json()["job"]["id"])
        self.assertEqual(crawl.config_snapshot["first_audit_entrypoint"], "bounded-first-audit-request-v1")
        responses = {
            self.project.canonical_origin + "/robots.txt": [response(self.project.canonical_origin + "/robots.txt",
                body=b"User-agent: *\nAllow: /\n")],
            self.project.canonical_origin + "/sitemap.xml": [response(self.project.canonical_origin + "/sitemap.xml", status=404)],
            root: [response(root, body=b"<title>Synthetic service</title><h1>Service</h1>", headers={"content-type": "text/html"})],
        }
        def fetcher(scope):
            return FakeFetcher(scope, responses)
        self.assertTrue(execute_crawl_job(crawl.pk, fetcher_factory=fetcher, sleep=lambda _seconds: None))
        crawl.refresh_from_db()
        self.assertEqual(crawl.status, JobStatus.SUCCEEDED)
        self.assertEqual(crawl.usage.actual_units, 1)
        from tenancy.acquisition import acquisition_milestones
        self.assertEqual(acquisition_milestones()["milestones"]["first_audit_succeeded"], {"count": 0, "grain": "organization", "state": "derivable"})
        with patch("jobs.services.dispatch_pending"):
            performance = queue_performance_audit(project=self.project, actor=self.owner, target=root,
                grain="page", strategy="mobile", sources=["psi_lab"], idempotency_key="internal-performance")
        lab = {"lighthouseResult": {"requestedUrl": root, "finalUrl": root,
            "fetchTime": timezone.now().isoformat(), "lighthouseVersion": "12.5.0",
            "configSettings": {"formFactor": "mobile"}, "categories": {"performance": {"score": 0.4}}, "audits": {}}}
        self.assertTrue(execute_performance_audit(performance.pk, fetch=lambda **_kwargs: lab))
        observation = PerformanceObservationSnapshot.objects.get(job=performance)
        record_performance_findings(project=self.project, actor=self.owner, observation_id=observation.pk)
        mapping = review_intent_cluster(project=self.project, actor=self.owner, request_key="internal-intent-001",
            label="Human-selected service questions", source_finding_ids=[findings[0].pk], intent="informational",
            page_kind="existing_unverified", preferred_page=root, reason="Review existing page before new content.",
            language="en", proposed_action="refresh", action_reason="Human page proposal; not a query/page join.")
        proposal = record_action(project=self.project, actor=self.owner, request_key="internal-action-001",
            source_id=mapping.pk, state="proposed", assignee_id=self.owner.pk,
            acceptance_criteria="Review actual service facts before publishing.", reason="Human proposal.")
        accepted = record_action(project=self.project, actor=self.owner, request_key="internal-action-002",
            source_id=mapping.pk, state="accepted", assignee_id=self.owner.pk,
            acceptance_criteria=proposal.acceptance_criteria, reason="Owner approval.",
            action_id=proposal.action_id, expected_revision=1)
        with patch("jobs.services.dispatch_pending"):
            research = queue_research(project=self.project, actor=self.owner,
                data={**self.data, "mapping_id": mapping.pk}, idempotency_key="internal-research")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-not-real"}):
            self.assertTrue(execute_research(research.pk, fetcher=ResearchTests.fetcher(self),
                                              request=ResearchTests.response.__get__(self)))
        brief = create_content_brief(project=self.project, actor=self.owner, request_key="internal-brief-001",
            research_job_id=research.pk, action_id=accepted.action_id, title_options=["Human selected service question"],
            angle="Have a business expert review this evidence.", outline=["Useful service information"], questions=[])
        output = read_content_brief(project=self.project, actor=self.owner, brief=brief)
        self.assertEqual(output["action_review_id"], accepted.pk)
        self.assertEqual(output["research_job_id"], research.pk)
        self.assertEqual(output["sources"][0]["url"], self.url)
        self.assertEqual(output["claims_to_verify"][0]["quote"], "Evidence useful.")
        status = client.get(audit_path)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["crawl"][0]["status"], "succeeded")
        self.assertEqual(status.json()["performance"][0]["status"], "succeeded")
        self.assertEqual(status.json()["imports"][0]["state"], "succeeded")
        self.assertGreater(len(status.json()["candidates"]), 0)
        self.assertLessEqual(len(status.json()["candidates"]), 3)
        self.assertEqual(brief.action_review.state, "accepted")
        active = record_action(project=self.project, actor=self.owner, request_key="internal-action-003",
            source_id=mapping.pk, state="in_progress", assignee_id=self.owner.pk,
            acceptance_criteria=proposal.acceptance_criteria, reason="Synthetic manually assigned work.",
            action_id=proposal.action_id, expected_revision=2)
        implemented_at = timezone.now()
        implemented = record_action(project=self.project, actor=self.owner, request_key="internal-action-004",
            source_id=mapping.pk, state="implemented", assignee_id=self.owner.pk,
            acceptance_criteria=proposal.acceptance_criteria, reason="Synthetic manual change log; no site changed.",
            action_id=proposal.action_id, expected_revision=3, implemented_at=implemented_at,
            change_summary="Synthetic title fixture changed; no customer site was updated.")
        followup_responses = {url: list(items) for url, items in responses.items()}
        followup_responses[root] = [response(root, body=b"<title>After synthetic manual change</title><h1>Service</h1>",
                                               headers={"content-type": "text/html"})]
        with patch("jobs.services.dispatch_pending"):
            requested = client.post(audit_path, json.dumps({"page_limit": 1, "idempotency_key": "internal-followup-crawl"}),
                                    content_type="application/json")
        self.assertEqual(requested.status_code, 202)
        followup = JobRun.objects.get(pk=requested.json()["job"]["id"])
        self.assertTrue(execute_crawl_job(followup.pk,
            fetcher_factory=lambda scope: FakeFetcher(scope, followup_responses), sleep=lambda _seconds: None))
        technical = record_action_crawl_observations(project=self.project, actor=self.owner,
            action_id=proposal.action_id, previous_crawl_id=crawl.crawl_run.pk, current_crawl_id=followup.crawl_run.pk)
        self.assertIn("not_fix_proof", technical.report["urls"][0]["state"])
        verified = record_action(project=self.project, actor=self.owner, request_key="internal-action-005",
            source_id=mapping.pk, state="verified", assignee_id=self.owner.pk,
            acceptance_criteria=proposal.acceptance_criteria, reason="Human reviews a fixture observation only.",
            action_id=proposal.action_id, expected_revision=4, implemented_at=implemented_at,
            change_summary=implemented.change_summary, verification_note="Synthetic title observation; business facts still unverified.")
        outcome = record_action(project=self.project, actor=self.owner, request_key="internal-action-006",
            source_id=mapping.pk, state="outcome_reviewed", assignee_id=self.owner.pk,
            acceptance_criteria=proposal.acceptance_criteria, reason="Outcome reviewed without causal claims.",
            action_id=proposal.action_id, expected_revision=5, implemented_at=implemented_at,
            change_summary=implemented.change_summary, verification_note=verified.verification_note,
            outcome_note="Search and business impact remain unknown; fixture is not measured uplift.")
        self.assertEqual(outcome.state, "outcome_reviewed")
