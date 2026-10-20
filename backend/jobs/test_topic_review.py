from datetime import timedelta
import json
import os
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from integrations.models import ImportRun, IntegrationConnection
from integrations.search_console import queue_search_console_csv_import
from integrations.services import create_connection
from tenancy.models import Organization, ProjectConfiguration
from tenancy.services import update_project_configuration
from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
from .crawling import FetchResponse
from .models import JobRun, TopicReview, UsageReservation
from .research import execute_research, queue_research
from .services import execute_job
from .topic_discovery import execute_topic_discovery, queue_topic_discovery
from .topic_review import HUMAN_COMPONENTS, current_topic_candidate, current_topic_review, review_topic, score_topic_components


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json", "text/csv"}), DEBUG=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "topic-review-fixtures"}})
class TopicReviewTests(TransactionTestCase):
    def setUp(self):
        from .test_research import ResearchTests
        self.url = ResearchTests.url
        ResearchTests.setUp(self)
        self.feed = "https://research-source.example.invalid/rss.xml"
        update_project_configuration(project=self.project, user=self.owner, expected_revision=1, changes={"rss_feed_urls": [self.feed]})
        self.body = b'<rss><channel><item><title>Source topic</title><link>https://research-source.example.invalid/article</link></item></channel></rss>'
        with patch("jobs.services.dispatch_pending"):
            job = queue_topic_discovery(project=self.project, actor=self.owner, feeds=[self.feed], idempotency_key="topic-review-source")
        body = self.body
        class Fetcher:
            def fetch(inner, url, *, before_request):
                before_request(url)
                return FetchResponse(url=url, status=200, headers={"content-type": "application/rss+xml"}, body=body)
        self.assertTrue(execute_topic_discovery(job.pk, fetcher_factory=lambda _: Fetcher()))
        self.snapshot = job.topic_candidates
        self.judgments = {name: {"score": None, "note": ""} for name in HUMAN_COMPONENTS}
        self.judgments["relevance"] = {"score": 2, "note": "Human judgment of offer/audience fit, not demand."}

    def review(self, **changes):
        fields = dict(project=self.project, actor=self.owner, snapshot_id=self.snapshot.pk, candidate_index=0,
            expected_revision=0, request_key="topic-review-first", label="Human-reviewed topic", classification="unknown",
            language="en", intent_review_id=None, judgments=self.judgments, reason="Review actual source and unknown coverage before research.")
        return review_topic(**{**fields, **changes})

    def test_inspectable_unknown_components_immutable_corrections_and_exact_scoped_api(self):
        first = self.review()
        self.assertEqual(first.report["assessed_points"], 3)
        self.assertEqual(first.report["demand_volume"], "unavailable_not_zero")
        self.assertIn("competition", first.report["unknown_components"])
        self.assertIn("freshness", first.report["unknown_components"])
        self.assertEqual(self.review().pk, first.pk)
        report = score_topic_components(snapshot=self.snapshot, candidate_index=0,
            candidate=self.snapshot.output["candidates"][0], judgments=dict(reversed(list(self.judgments.items()))), mapping=None)
        self.assertEqual(report, first.report)
        revised = self.review(expected_revision=1, request_key="topic-review-correction", classification="evergreen",
                              reason="Human evergreen hypothesis, not proven long-term demand.")
        with self.assertRaises(ValidationError):
            self.review(request_key="stale-topic-review")
        with self.assertRaises(ValidationError):
            first.save()
        with self.assertRaises(ValidationError):
            self.review(expected_revision=2, request_key="unsupported-coverage", judgments={**self.judgments,
                "existing_coverage": {"score": 3, "note": "Missing mapping cannot establish a gap."}})
        path = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/topics/{self.snapshot.pk}/0/"
        client = Client(enforce_csrf_checks=True); client.force_login(self.owner)
        payload = dict(expected_revision=2, request_key="topic-api-correction", label="Human-reviewed topic",
            classification="trending", language="en", intent_review_id=None, judgments=self.judgments, reason="Human hypothesis only.")
        self.assertEqual(client.post(path, json.dumps(payload), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        response = client.post(path, json.dumps(payload), content_type="application/json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual([row["revision"] for row in client.get(path).json()["history"]], [3, 2, 1])
        other = Client(); other.force_login(self.other)
        self.assertEqual(other.get(path).status_code, 404)
        viewer = Client(); viewer.force_login(self.viewer)
        self.assertEqual(viewer.get(path).status_code, 200)
        self.assertEqual(viewer.post(path, json.dumps(payload), content_type="application/json").status_code, 403)
        self.assertEqual(revised.classification, "evergreen")

    def test_reviewed_topic_research_handoff_rejects_changed_judgments_and_source_scope(self):
        from .test_research import ResearchTests
        review = self.review()
        with patch("jobs.services.dispatch_pending"):
            research = queue_research(project=self.project, actor=self.owner, idempotency_key="reviewed-topic-research",
                data={**self.data, "topic": review.label, "topic_review_id": review.pk})
        self.assertEqual(research.config_snapshot["research_context"]["topic_review"]["id"], review.pk)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-not-real"}):
            self.assertTrue(execute_research(research.pk, fetcher=ResearchTests.fetcher(self), request=ResearchTests.response.__get__(self)))
        with patch("jobs.services.dispatch_pending"):
            stale = queue_research(project=self.project, actor=self.owner, idempotency_key="stale-reviewed-research",
                data={**self.data, "topic": review.label, "topic_review_id": review.pk})
        self.review(expected_revision=1, request_key="review-corrected-later", label="Corrected human topic")
        self.assertTrue(execute_research(stale.pk, request=lambda **_: self.fail("No stale topic AI")))
        stale.refresh_from_db()
        self.assertEqual(stale.error_category, "research_scope_changed")
        ProjectConfiguration.objects.filter(project=self.project).update(research_blocked_origins=["https://research-source.example.invalid"])
        with self.assertRaises(ValidationError):
            current_topic_candidate(project=self.project, actor=self.owner, snapshot_id=self.snapshot.pk, candidate_index=0)

    def test_first_party_growth_is_measured_but_not_demand_and_registered_review_is_deleted(self):
        connection = create_connection(project=self.project, user=self.owner, provider="google_search_console",
            external_property_id=self.project.canonical_origin, capabilities=["csv_import", "query_metrics"],
            available_dimensions=["query"], source_semantics="search_console_performance",
            source_semantics_version="csv-v1", timezone="America/Los_Angeles")
        end = timezone.now().date() - timedelta(days=3)
        imports = []
        with patch("jobs.services.dispatch_pending"):
            for start, last, clicks in ((end - timedelta(days=13), end - timedelta(days=7), 2), (end - timedelta(days=6), end, 5)):
                job = queue_search_console_csv_import(connection=connection, user=self.owner,
                    content=f"Top queries,Clicks,Impressions,CTR,Position\nobserved topic,{clicks},20,10%,3\n".encode(), date_start=start, date_end=last)
                self.assertTrue(execute_job(job.pk)); imports.append(ImportRun.objects.get(job=job))
            topic = queue_topic_discovery(project=self.project, actor=self.owner, feeds=[], connection=connection,
                previous_import_id=imports[0].pk, current_import_id=imports[1].pk, idempotency_key="review-query-source")
        self.assertTrue(execute_topic_discovery(topic.pk))
        row = self.review(snapshot_id=topic.topic_candidates.pk, request_key="review-query-001")
        growth = next(value for value in row.report["components"] if value["name"] == "growth")
        self.assertEqual((growth["score"], growth["click_change"]), (1, 3))
        self.assertEqual(row.report["demand_volume"], "unavailable_not_zero")
        IntegrationConnection.objects.filter(pk=connection.pk).update(state="disconnected")
        with self.assertRaises(ValidationError):
            current_topic_candidate(project=self.project, actor=self.owner, snapshot_id=topic.topic_candidates.pk, candidate_index=0)
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        run = prepare_customer_data_deletion(organization=self.org)
        while run.state == run.State.PENDING:
            run = sweep_customer_artifact_versions(run=run)
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(TopicReview.objects.exists())

    def test_exact_current_mapping_coverage_and_authenticated_review_handoff(self):
        from .intent_mapping import review_intent_cluster
        from tenancy.services import create_organization, create_project
        # Current configured manual seed is explicitly unmeasured, not observed demand.
        ProjectConfiguration.objects.filter(project=self.project).update(seed_topics=["manual seed"], target_languages=["en", "tr"])
        # Match the discovery language snapshot for this synthetic source.
        JobRun.objects.filter(pk=self.snapshot.job_id).update(config_snapshot={
            **self.snapshot.job.config_snapshot, "languages": ["en", "tr"]})
        def mapping(project, actor, **changes):
            return review_intent_cluster(project=project, actor=actor, **{**dict(request_key="topic-map-first",
                label="Human coverage", source_finding_ids=[], manual_topics=["manual seed"], intent="informational",
                page_kind="existing_unverified", preferred_page=project.canonical_origin + "/guide", language="en",
                reason="Human choice; actual coverage is unverified.", proposed_action="refresh", action_reason="Review existing page first."), **changes})
        selected = mapping(self.project, self.owner)
        judgments = {**self.judgments, "existing_coverage": {"score": 2, "note": "Human coverage review of possible existing page."}}
        row = self.review(intent_review_id=selected.pk, judgments=judgments)
        self.assertEqual(row.report["existing_mapping"]["preferred_page"], selected.preferred_page)
        path = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/topics/reviews/{row.pk}/"
        client = Client(); client.force_login(self.owner)
        response = client.get(path)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["review"]["id"], row.pk)
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertIn("no-store", response["Cache-Control"])
        other = Client(); other.force_login(self.other)
        self.assertEqual(other.get(path).status_code, 404)
        self.assertEqual(Client().get(path).status_code, 401)
        mismatched = mapping(self.project, self.owner, request_key="topic-map-language", language="tr")
        with self.assertRaises(ValidationError):
            self.review(expected_revision=1, request_key="topic-map-wronglang", intent_review_id=mismatched.pk)
        foreign_org = create_organization(user=self.other, name="Foreign topic fixture")
        foreign = create_project(organization=foreign_org, user=self.other, name="Foreign topic project", canonical_origin="https://foreign-topic.example.invalid")
        update_project_configuration(project=foreign, user=self.other, expected_revision=0,
            changes={"target_country": "Türkiye", "target_languages": ["en"], "seed_topics": ["manual seed"]})
        foreign_mapping = mapping(foreign, self.other)
        with self.assertRaises(PermissionDenied):
            self.review(expected_revision=1, request_key="topic-map-foreign", intent_review_id=foreign_mapping.pk)
        for field, value in (("topic", "Changed label"), ("language", "tr"), ("mapping_id", None)):
            with self.subTest(field=field), self.assertRaises(ValidationError), patch("jobs.services.dispatch_pending"):
                queue_research(project=self.project, actor=self.owner, idempotency_key="topic-mismatch-" + field,
                    data={**self.data, "topic": row.label, "mapping_id": selected.pk, "topic_review_id": row.pk, field: value})
        mapping(self.project, self.owner, request_key="topic-map-corrected", cluster_id=selected.cluster_id, expected_revision=1)
        with self.assertRaises(ValidationError):
            current_topic_review(project=self.project, actor=self.owner, review_id=row.pk)
        self.assertEqual(client.get(path).status_code, 409)

    def test_discovery_job_api_scope_csrf_cancellation_allowance_and_bad_sources(self):
        root = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/topics/"
        client = Client(enforce_csrf_checks=True); client.force_login(self.owner)
        payload = dict(feeds=[self.feed], connection_id=None, previous_import_id=None, current_import_id=None,
            idempotency_key="topic-api-launch")
        self.assertEqual(client.post(root, json.dumps(payload), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        def post(path, data):
            return client.post(path, json.dumps(data), content_type="application/json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        with patch("jobs.services.dispatch_pending"):
            response = post(root, payload)
        self.assertEqual(response.status_code, 202, response.content)
        job = JobRun.objects.get(pk=response.json()["job_id"])
        self.assertEqual(job.usage.reserved_units, 1)
        detail = root + f"jobs/{job.pk}/"
        self.assertEqual(client.get(detail).json()["job"]["estimated_units"], 1)
        other = Client(); other.force_login(self.other)
        viewer = Client(); viewer.force_login(self.viewer)
        self.assertEqual(other.get(detail).status_code, 404)
        self.assertEqual(viewer.get(detail).status_code, 200)
        self.assertEqual(viewer.post(detail, "{}", content_type="application/json").status_code, 403)
        self.assertEqual(client.get(root + "jobs/999999/").status_code, 404)
        self.assertEqual(post(detail, {}).status_code, 200)
        self.assertEqual(client.get(detail).json()["job"]["status"], "cancelled")
        self.assertTrue(client.get(detail).json()["job"]["cancel_requested"])
        job.usage.refresh_from_db(); self.assertEqual(job.usage.state, UsageReservation.State.RELEASED)
        self.assertEqual(post(root, {**payload, "feeds": ["https://outside.example.invalid/rss"], "idempotency_key": "topic-bad-feed"}).status_code, 409)
        self.assertEqual(post(root, {**payload, "previous_import_id": 1, "idempotency_key": "topic-bad-pair"}).status_code, 409)
        trial = self.org.trial
        trial.started_at = timezone.now() - timedelta(days=31); trial.ends_at = timezone.now() - timedelta(days=1)
        trial.save(update_fields=["started_at", "ends_at"])
        response = post(root, {**payload, "idempotency_key": "topic-expired-test"})
        self.assertEqual(response.status_code, 429, response.content)
        self.assertEqual(response.json()["code"], "trial_unavailable")
