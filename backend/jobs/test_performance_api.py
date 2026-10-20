import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import MembershipRole, OrganizationMembership
from tenancy.services import create_organization, create_project

from .models import JobRun, PerformanceObservationSnapshot
from .findings import record_performance_findings
from .performance_job import execute_performance_audit


@override_settings(STORAGES=TEST_STORAGES, ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                        "LOCATION": "performance-api-fixtures"}})
class PerformanceAPITests(TransactionTestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("performance-api-owner@example.com", password="test-password")
        self.viewer = users.create_user("performance-api-viewer@example.com", password="test-password")
        self.other = users.create_user("performance-api-other@example.com", password="test-password")
        for actor in (self.owner, self.viewer, self.other):
            EmailAddress.objects.create(user=actor, email=actor.email, verified=True, primary=True)
        self.org = create_organization(user=self.owner, name="Performance API")
        OrganizationMembership.objects.create(organization=self.org, user=self.viewer, role=MembershipRole.VIEWER)
        self.project = create_project(organization=self.org, user=self.owner, name="Measured",
                                      canonical_origin="https://measured.example")
        self.target = "https://measured.example/page"
        self.path = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/performance/"

    def client_for(self, user):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        client.get("/_allauth/browser/v1/auth/session")
        return client

    def post(self, client, path, data, *, csrf=True):
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value} if csrf else {}
        with patch("jobs.services.dispatch_pending"):
            return client.post(path, data=json.dumps(data), content_type="application/json", **headers)

    @override_settings(GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
    def test_private_queue_and_parsed_lab_field_detail_never_return_raw_or_key(self):
        owner, viewer, other = (self.client_for(user) for user in (self.owner, self.viewer, self.other))
        payload = {"target": self.target, "grain": "page", "strategy": "mobile",
                   "sources": ["psi_lab", "crux_current"], "idempotency_key": "audit-one"}
        self.assertEqual(self.post(owner, self.path, payload, csrf=False).status_code, 403)
        self.assertEqual(self.post(viewer, self.path, payload).status_code, 403)
        self.assertEqual(other.get(self.path).status_code, 404)
        self.assertEqual(owner.get(self.path).json()["jobs"], [])
        response = self.post(owner, self.path, payload)
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()["max_requests"], 2)
        self.assertIn("no-store", response["Cache-Control"])
        job_id = response.json()["job"]["id"]
        self.assertEqual(self.post(owner, self.path, payload).json()["job"]["id"], job_id)
        self.assertEqual(self.post(owner, self.path, {**payload, "target": "https://other.example/"}).status_code, 409)
        self.assertEqual(self.post(owner, self.path, payload).status_code, 429)
        end = timezone.now().date() - timedelta(days=2)
        lab = {"lighthouseResult": {"requestedUrl": self.target, "finalUrl": self.target,
               "fetchTime": timezone.now().isoformat(), "lighthouseVersion": "12.5.0",
               "configSettings": {"formFactor": "mobile"}, "categories": {"performance": {"score": .7}},
               "audits": {}}, "raw_private": "PRIVATE_PROVIDER_BODY"}
        field = {"record": {"key": {"url": self.target, "formFactor": "PHONE"},
            "collectionPeriod": {"firstDate": {"year": end.year, "month": end.month, "day": 1},
                                 "lastDate": {"year": end.year, "month": end.month, "day": end.day}},
            "metrics": {"largest_contentful_paint": {"percentiles": {"p75": 2500}}}}}
        with patch("jobs.performance_job.google_performance_key", return_value="fixture_key_with_32_placeholder_chars"):
            self.assertTrue(execute_performance_audit(job_id, fetch=lambda *, kind, **_kw: lab if kind == "psi_lab" else field))
        detail_path = self.path + f"{job_id}/"
        detail = viewer.get(detail_path)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["job"]["status"], "partially_succeeded")
        self.assertEqual({item["source"] for item in detail.json()["observations"]}, {"psi_lab", "crux_current"})
        self.assertEqual(next(item for item in detail.json()["observations"] if item["source"] == "psi_lab")
                         ["result"]["field_data"], "not_used")
        self.assertEqual(next(item for item in detail.json()["observations"] if item["source"] == "crux_current")
                         ["result"]["metrics"][0]["method"], "field_p75_not_a_lab_score")
        self.assertNotIn("PRIVATE_PROVIDER_BODY", detail.content.decode())
        self.assertNotIn("fixture_key_with_32_placeholder_chars", detail.content.decode())
        self.assertNotIn("raw_artifact", detail.content.decode())
        self.assertEqual(PerformanceObservationSnapshot.objects.filter(job_id=job_id).count(), 2)
        self.assertEqual(other.get(detail_path).status_code, 404)
        lab_snapshot = PerformanceObservationSnapshot.objects.get(job_id=job_id, source="psi_lab")
        finding_path = (f"/api/organizations/{self.org.pk}/projects/{self.project.pk}"
                        f"/findings/performance/{lab_snapshot.pk}/")
        self.assertEqual(self.post(owner, finding_path, {}, csrf=False).status_code, 403)
        self.assertEqual(self.post(viewer, finding_path, {}).status_code, 403)
        finding_response = self.post(owner, finding_path, {})
        self.assertEqual(finding_response.status_code, 201)
        self.assertEqual(finding_response.json()["finding_ids"], [])  # Observed .7 lab is not low.

    def test_missing_key_fails_before_queue_and_cancel_is_scoped_and_csrf_protected(self):
        owner, viewer = self.client_for(self.owner), self.client_for(self.viewer)
        payload = {"target": self.target, "grain": "page", "strategy": "mobile",
                   "sources": ["psi_lab"], "idempotency_key": "missing-key"}
        self.assertEqual(self.post(owner, self.path, payload).status_code, 503)
        self.assertFalse(JobRun.objects.filter(handler="audit_performance").exists())
        with override_settings(GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars"):
            job_id = self.post(owner, self.path, payload).json()["job"]["id"]
        cancel_path = self.path + f"{job_id}/cancel/"
        self.assertEqual(self.post(owner, cancel_path, {}, csrf=False).status_code, 403)
        self.assertEqual(self.post(viewer, cancel_path, {}).status_code, 403)
        self.assertEqual(self.post(owner, cancel_path, {}).json()["job"]["status"], "cancelled")

    @override_settings(GOOGLE_PERFORMANCE_API_KEY="fixture_key_with_32_placeholder_chars")
    def test_history_exposes_threshold_regression_candidate_without_blending_lab(self):
        owner = self.client_for(self.owner)
        payload = {"target": self.target, "grain": "page", "strategy": "mobile",
                   "sources": ["crux_history"], "idempotency_key": "history-only"}
        job_id = self.post(owner, self.path, payload).json()["job"]["id"]
        end = timezone.now().date() - timedelta(days=2)
        def period(last):
            first = last - timedelta(days=27)
            return {"firstDate": {"year": first.year, "month": first.month, "day": first.day},
                    "lastDate": {"year": last.year, "month": last.month, "day": last.day}}
        history = {"record": {"key": {"url": self.target, "formFactor": "PHONE"},
            "collectionPeriods": [period(end - timedelta(days=7)), period(end)],
            "metrics": {"largest_contentful_paint": {"percentilesTimeseries": {"p75s": [2000, 4500]}}}}}
        self.assertTrue(execute_performance_audit(job_id, fetch=lambda **_kw: history))
        detail = owner.get(self.path + f"{job_id}/").json()
        self.assertEqual(detail["job"]["lab"], "unavailable")
        output = detail["observations"][0]["result"]
        self.assertEqual((output["source"], output["rolling_windows_overlap"]), ("crux_history_api", True))
        self.assertEqual(output["regressions"][0]["state"], "regression_candidate")
        self.assertEqual(output["regressions"][1]["state"], "unknown_insufficient_eligible_periods")
        findings, truncated = record_performance_findings(project=self.project, actor=self.owner,
            observation_id=PerformanceObservationSnapshot.objects.get(job_id=job_id).pk)
        self.assertFalse(truncated)
        self.assertEqual({item.detector for item in findings}, {
            "poor_crux_field_lcp_candidate", "crux_field_threshold_regression_candidate"})
        self.assertTrue(all(item.source_performance.job_id == job_id for item in findings))
        self.assertFalse(any(item.evidence.get("source") == "psi_lab" for item in findings))
        observation_id = PerformanceObservationSnapshot.objects.get(job_id=job_id).pk
        path = (f"/api/organizations/{self.org.pk}/projects/{self.project.pk}"
                f"/findings/performance/{observation_id}/")
        result = self.post(owner, path, {})
        self.assertEqual(result.status_code, 201)
        self.assertEqual(set(result.json()["finding_ids"]), {item.pk for item in findings})
        listed = owner.get(f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/findings/").json()["findings"]
        self.assertEqual({item["source_performance_id"] for item in listed}, {observation_id})
        self.assertTrue(all(item["source_current"] for item in listed))
