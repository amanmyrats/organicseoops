import json
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from jobs.models import JobRun, JobStatus, PerformanceObservationSnapshot
from jobs.performance_job import execute_performance_audit, queue_performance_audit
from tenancy.models import AuditEvent, MembershipRole, OrganizationMembership
from tenancy.services import create_organization, create_project

from .models import OrganizationPerformanceKey
from .performance_key import google_performance_key, performance_key_reference, revoke_organization_performance_key


KEY = Fernet.generate_key().decode()
PLATFORM = "fixture_platform_key_with_32_chars"
OWNED = "fixture_org_key_with_32_characters"


@override_settings(PERFORMANCE_ENCRYPTION_KEYS=(KEY,), GOOGLE_PERFORMANCE_API_KEY=PLATFORM,
                   STAFF_MFA_REQUIRED=False, SECURE_SSL_REDIRECT=False, STORAGES=TEST_STORAGES,
                   ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"application/json"}),
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class OrganizationPerformanceTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.owner = get_user_model().objects.create_user("org-perf-owner@example.com", "test-password")
        self.other = get_user_model().objects.create_user("org-perf-other@example.com", "test-password")
        self.viewer = get_user_model().objects.create_user("org-perf-viewer@example.com", "test-password")
        for actor in (self.owner, self.other):
            EmailAddress.objects.create(user=actor, email=actor.email, primary=True, verified=True)
        self.organization = create_organization(user=self.owner, name="Org performance")
        self.foreign = create_organization(user=self.other, name="Other performance")
        OrganizationMembership.objects.create(user=self.viewer, organization=self.organization, role=MembershipRole.VIEWER)
        self.project = create_project(organization=self.organization, user=self.owner, name="Measured site",
                                      canonical_origin="https://perf.example.com")
        self.path = f"/api/organizations/{self.organization.pk}/performance-key/"

    def browser(self, user):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        client.get("/_allauth/browser/v1/auth/session", secure=True)
        return client

    def headers(self, browser):
        return {"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value,
                "HTTP_REFERER": "https://testserver/"}

    def set_key(self, browser, key=OWNED):
        return browser.post(self.path, data=json.dumps({"api_key": key}), content_type="application/json",
                            secure=True, **self.headers(browser))

    def test_scoped_write_only_key_and_revoke_never_fall_back_to_platform(self):
        self.assertEqual(google_performance_key(organization=self.organization), PLATFORM)
        self.assertEqual(self.browser(self.other).get(self.path, secure=True).status_code, 404)
        self.assertEqual(self.browser(self.viewer).get(self.path, secure=True).status_code, 403)
        browser = self.browser(self.owner)
        self.assertEqual(self.set_key(browser).status_code, 200)
        record = OrganizationPerformanceKey.objects.get(organization=self.organization)
        self.assertNotIn(OWNED, record.encrypted_secret)
        self.assertFalse(admin.site.is_registered(OrganizationPerformanceKey))
        self.assertEqual(google_performance_key(organization=self.organization), OWNED)
        self.assertEqual(google_performance_key(organization=self.foreign), PLATFORM)
        self.assertEqual(browser.get(self.path, secure=True).json(), {"state": "active"})
        self.assertNotIn(OWNED, json.dumps(list(AuditEvent.objects.values("details"))))
        self.assertEqual(AuditEvent.objects.get(organization=self.organization,
            event_type="integration_credential.updated").actor, self.owner)
        viewer = self.browser(self.viewer)
        self.assertEqual(viewer.post(self.path, data=json.dumps({"api_key": OWNED}),
                                     content_type="application/json", secure=True,
                                     **self.headers(viewer)).status_code, 403)
        self.assertEqual(browser.delete(self.path, secure=True, **self.headers(browser)).json(), {"revoked": True})
        with self.assertRaises(ValidationError):
            google_performance_key(organization=self.organization)
        record.refresh_from_db()
        self.assertEqual(record.encrypted_secret, "")

    def test_credential_revision_freezes_queued_audit_and_rechecks_after_request(self):
        browser = self.browser(self.owner)
        self.assertEqual(self.set_key(browser).status_code, 200)
        with patch("jobs.services.dispatch_pending"):
            job = queue_performance_audit(project=self.project, actor=self.owner,
                                          target="https://perf.example.com/page", grain="page",
                                          strategy="mobile", sources=["psi_lab"], idempotency_key="audit-1")
        self.assertEqual(job.config_snapshot["performance_credential"], performance_key_reference(
            organization=self.organization))

        def fetched(**kwargs):
            self.assertEqual(kwargs["api_key"], OWNED)
            revoke_organization_performance_key(actor=self.owner, organization=self.organization)
            return {"lighthouseResult": {
                "requestedUrl": "https://perf.example.com/page", "finalUrl": "https://perf.example.com/page",
                "fetchTime": timezone.now().isoformat(), "lighthouseVersion": "12.5.0",
                "configSettings": {"formFactor": "mobile"},
                "categories": {"performance": {"score": .8}}, "audits": {},
            }}

        self.assertTrue(execute_performance_audit(job.pk, fetch=fetched))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.usage.actual_units),
                         (JobStatus.CANCELLED, "credential_unavailable", 1))
        self.assertFalse(PerformanceObservationSnapshot.objects.filter(job=job).exists())
        self.assertEqual(google_performance_key(organization=self.foreign), PLATFORM)

        with patch("jobs.services.dispatch_pending"):
            unavailable = queue_performance_audit(project=self.project, actor=self.owner,
                target="https://perf.example.com/page", grain="page", strategy="mobile",
                sources=["psi_lab"], idempotency_key="audit-2")
        self.assertTrue(execute_performance_audit(unavailable.pk, fetch=lambda **_: self.fail("revoked key")))
        unavailable.refresh_from_db()
        self.assertEqual((unavailable.status, unavailable.error_category), (JobStatus.FAILED, "credential_unavailable"))

    def test_rotated_org_key_cannot_change_a_queued_audits_source(self):
        browser = self.browser(self.owner)
        self.assertEqual(self.set_key(browser).status_code, 200)
        with patch("jobs.services.dispatch_pending"):
            job = queue_performance_audit(project=self.project, actor=self.owner,
                                          target="https://perf.example.com/page", grain="page",
                                          strategy="mobile", sources=["psi_lab"], idempotency_key="rotation-test")
        self.assertEqual(self.set_key(browser, "fixture_new_org_key_with_32_chars").status_code, 200)
        self.assertTrue(execute_performance_audit(job.pk, fetch=lambda **_: self.fail("old job must not call provider")))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.usage.actual_units),
                         (JobStatus.CANCELLED, "credential_unavailable", 0))
