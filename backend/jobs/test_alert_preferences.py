from django.test import TransactionTestCase
import json
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, IntegrityError, transaction
from django.test import Client, RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from tenancy.models import Organization, OrganizationMembership, Project, ProjectMembership
from tenancy.services import create_organization, create_project
from .alert_preferences import project_alert_preference, set_project_alert_preference
from .models import ProjectAlertPreference, ProjectSummaryPreference
from .summary_preferences import set_project_summary_preference


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, ALERT_DIGEST_DELIVERY_ENABLED=False,
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "alert-prefs"}})
class AlertPreferenceTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        cache.clear()
        self.owner = get_user_model().objects.create_user("alert-owner@example.invalid", "Test passphrase 99!")
        self.other = get_user_model().objects.create_user("alert-viewer@example.invalid", "Test passphrase 99!")
        for user in (self.owner, self.other):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        self.org = create_organization(user=self.owner, name="Alert preferences")
        self.project = create_project(organization=self.org, user=self.owner, name="Alert site",
                                      canonical_origin="https://alerts.example.invalid")
        self.path = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/alert-preference/"

    def save(self, frequency="daily", families=None, revision=0, actor=None):
        return set_project_alert_preference(project=self.project, actor=actor or self.owner,
            frequency=frequency, source_families=["crawl_failure"] if families is None else families,
            expected_revision=revision)

    def test_write_free_defaults_weekly_independence_and_family_revision_idempotency(self):
        set_project_summary_preference(project=self.project, actor=self.owner, frequency="weekly", expected_revision=0)
        with patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")), \
                patch("jobs.tasks.send_weekly_summary_task.delay", side_effect=AssertionError("dispatch")), \
                CaptureQueriesContext(connection) as queries:
            self.assertEqual(project_alert_preference(project=self.project, actor=self.owner),
                {"channel": "email", "frequency": "off", "source_families": [], "revision": 0,
                  "delivery_state": "rollout_off"})
            self.assertEqual(self.save("off", [])["revision"], 0)
        self.assertFalse(any(q["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for q in queries))
        self.assertEqual(self.save()["revision"], 1)
        self.assertEqual(self.save(revision=1)["revision"], 1)
        both = self.save(families=["integration_health", "crawl_failure"], revision=1)
        self.assertEqual(both["source_families"], ["crawl_failure", "integration_health"])
        self.assertEqual(both["revision"], 2)
        self.assertEqual(self.save(families=both["source_families"], revision=2)["revision"], 2)
        self.assertEqual(self.save("off", both["source_families"], 2)["revision"], 3)
        with self.assertRaises(ValidationError): self.save(revision=2)
        self.assertEqual(self.save("off", [], 3)["revision"], 4)
        self.assertEqual(ProjectSummaryPreference.objects.get().frequency, "weekly")
        from .models import ProjectSummaryDelivery, JobRun
        self.assertEqual(ProjectSummaryDelivery.objects.count(), 0)
        self.assertEqual(JobRun.objects.count(), 0)

    def test_exact_family_frequency_revision_validation_and_sql_constraints(self):
        invalid = [("daily", [], 0), (True, [], 0), ("weekly", [], 0), ("off", "crawl_failure", 0),
                   ("daily", [True], 0), ("daily", [["crawl_failure"]], 0), ("daily", ["regression"], 0),
                   ("daily", ["crawl_failure", "crawl_failure"], 0), ("off", [], True), ("off", [], -1),
                   ("off", [], 2**31 - 1)]
        for frequency, families, revision in invalid:
            with self.assertRaises(ValidationError): self.save(frequency, families, revision)
        self.save()
        for fields in ({"frequency": "spam"}, {"revision": 0}, {"crawl_failure": False}):
            with transaction.atomic(), self.assertRaises(IntegrityError):
                ProjectAlertPreference.objects.filter(user=self.owner).update(**fields)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ProjectAlertPreference.objects.create(project=self.project, user=self.owner)

    def test_actual_configured_rollout_get_and_post_never_send_or_dispatch(self):
        from .models import ProjectAlertDelivery, ProjectAlertEpisodeClaim, JobRun
        client = Client(enforce_csrf_checks=True); client.force_login(self.owner)
        client.get("/_allauth/browser/v1/auth/session")
        csrf = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        for enabled, state in ((False, "rollout_off"), (True, "enabled_optional")):
            with override_settings(ALERT_DIGEST_DELIVERY_ENABLED=enabled), \
                    patch("jobs.alert_digest_delivery.send_mail", side_effect=AssertionError("SMTP")), \
                    patch("jobs.tasks.send_daily_alert_digest_task.apply_async", side_effect=AssertionError("dispatch")), \
                    patch("jobs.tasks.scan_daily_alert_digests_task.apply_async", side_effect=AssertionError("discovery")):
                current = client.get(self.path).json()["preference"]
                self.assertEqual(current["delivery_state"], state)
                result = client.post(self.path, json.dumps({"frequency": "daily", "source_families": ["crawl_failure"],
                    "expected_revision": current["revision"]}), content_type="application/json", **csrf)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["preference"]["delivery_state"], state)
        self.assertFalse(any(model.objects.exists() for model in (ProjectAlertDelivery, ProjectAlertEpisodeClaim, JobRun)))

    def test_current_own_reader_verified_enable_only_and_retained_off_selection(self):
        with self.assertRaises(PermissionDenied): self.save(actor=self.other)
        membership = OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        self.assertEqual(self.save(actor=self.other)["frequency"], "daily")
        EmailAddress.objects.filter(user=self.other).update(verified=False)
        with self.assertRaises(PermissionDenied): self.save(revision=1, actor=self.other)
        self.assertEqual(self.save("off", ["crawl_failure"], 1, self.other)["revision"], 2)
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        with self.assertRaises(PermissionDenied): self.save("off", [], 2, self.other)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(self.save("off", [], 2, self.other)["revision"], 3)
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True)
        with self.assertRaises(PermissionDenied): self.save("off", [], 3, self.other)

    def test_final_insert_and_read_authority_loss_rollback_or_deny(self):
        original = ProjectAlertPreference.objects.create
        for change in (lambda: EmailAddress.objects.filter(user=self.owner).update(verified=False),
                       lambda: OrganizationMembership.objects.filter(organization=self.org, user=self.owner).delete()):
            def create_then_change(**kwargs):
                row = original(**kwargs); change(); return row
            with patch("jobs.alert_preferences.ProjectAlertPreference.objects.create", side_effect=create_then_change), \
                    self.assertRaises(PermissionDenied):
                self.save()
            self.assertFalse(ProjectAlertPreference.objects.exists())
            self.assertTrue(EmailAddress.objects.get(user=self.owner).verified)
            self.assertTrue(OrganizationMembership.objects.filter(user=self.owner).exists())
        from .alert_preferences import _preference
        def project_then_suspend(row):
            result = _preference(row)
            get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
            return result
        with patch("jobs.alert_preferences._preference", side_effect=project_then_suspend), self.assertRaises(PermissionDenied):
            project_alert_preference(project=self.project, actor=self.owner)

    def test_actual_private_api_csrf_strict_input_scope_own_user_and_no_delivery(self):
        self.assertEqual(Client().get(self.path).status_code, 401)
        client = Client(enforce_csrf_checks=True); client.force_login(self.owner)
        result = client.get(self.path)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        payload = {"frequency": "daily", "source_families": ["crawl_failure"], "expected_revision": 0}
        self.assertEqual(client.post(self.path, json.dumps(payload), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        csrf = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        invalid = [json.dumps({**payload, "user_id": self.other.pk}), json.dumps({**payload, "email": self.other.email}),
                   '{"frequency":"off","frequency":"daily","source_families":["crawl_failure"],"expected_revision":0}',
                   '{"frequency":"daily","source_families":["crawl_failure"],"expected_revision":NaN}',
                   json.dumps({**payload, "source_families": ["crawl_failure", "crawl_failure"]}), "[0]", "{" * 1100]
        for raw in invalid:
            self.assertEqual(client.post(self.path, raw, content_type="application/json", **csrf).status_code, 409)
        self.assertEqual(client.get(self.path + "?source_family=crawl_failure").status_code, 400)
        self.assertEqual(client.generic("GET", self.path, data="{}", content_type="application/json").status_code, 409)
        denied = client.put(self.path, "{}", content_type="application/json", **csrf)
        self.assertEqual(denied.status_code, 405); self.assertEqual(denied["Allow"], "GET, POST")
        with patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")), \
                patch("jobs.tasks.send_weekly_summary_task.delay", side_effect=AssertionError("dispatch")):
            result = client.post(self.path, json.dumps(payload), content_type="application/json", **csrf)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["preference"]["delivery_state"], "rollout_off")
        self.assertNotIn(self.owner.email, result.content.decode()); self.assertNotIn("user_id", result.content.decode())
        self.assertEqual(client.post(self.path, json.dumps(payload), content_type="application/json", **csrf).status_code, 409)
        other = Client(); other.force_login(self.other)
        self.assertEqual(other.get(self.path).status_code, 404)
        OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        self.assertEqual(other.get(self.path).json()["preference"]["revision"], 0)
        self.assertEqual(client.get(f"/api/organizations/{self.org.pk + 100}/projects/{self.project.pk}/alert-preference/").status_code, 404)
        from .models import ProjectSummaryDelivery
        self.assertFalse(ProjectSummaryDelivery.objects.exists()); self.assertFalse(ProjectSummaryPreference.objects.exists())

    @override_settings(ACCOUNT_RATE_LIMITS={"alert_preference_read": "1/m/user,100/m/ip",
                                           "alert_preference_write": "1/m/user,100/m/ip"})
    def test_actual_separate_get_post_user_ip_limits_and_weekly_independence(self):
        client = Client(enforce_csrf_checks=True); client.force_login(self.owner)
        self.assertEqual(client.get(self.path).status_code, 200)
        limited = client.get(self.path)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited["Cache-Control"], "private, no-store")
        self.assertEqual(limited["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(client.get(self.path.replace("alert-preference", "summary-preference")).status_code, 200)
        client.get("/_allauth/browser/v1/auth/session")
        csrf = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        payload = json.dumps({"frequency": "off", "source_families": [], "expected_revision": 0})
        self.assertEqual(client.post(self.path, payload, content_type="application/json", **csrf).status_code, 200)
        self.assertEqual(client.post(self.path, payload, content_type="application/json", **csrf).status_code, 429)
        cache.clear()
        OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        other = Client(); other.force_login(self.other)
        with override_settings(ACCOUNT_RATE_LIMITS={"alert_preference_read": "100/m/user,1/m/ip"}):
            self.assertEqual(client.get(self.path).status_code, 200)
            self.assertEqual(other.get(self.path).status_code, 429)
            self.assertEqual(other.get(self.path, REMOTE_ADDR="192.0.2.10").status_code, 200)
        self.assertFalse(ProjectAlertPreference.objects.exists())

    def test_actual_customer_export_organization_erasure_and_personal_close_are_scoped(self):
        from accounts.closure import close_personal_access
        from tenancy.customer_inventory import require_complete_ownership_map
        from tenancy.customer_export import project_customer_rows
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        self.save()
        other_org = create_organization(user=self.other, name="Other alerts")
        other_project = create_project(organization=other_org, user=self.other, name="Other site",
                                       canonical_origin="https://other-alerts.example.invalid")
        set_project_alert_preference(project=other_project, actor=self.other, frequency="daily",
                                    source_families=["integration_health"], expected_revision=0)
        require_complete_ownership_map()
        row = ProjectAlertPreference.objects.get(project=self.project)
        exported = project_customer_rows(organization=self.org, actor=self.owner,
            model_label="jobs.ProjectAlertPreference", after_id=0, through_id=row.pk)
        self.assertEqual([item["user_id"] for item in exported["rows"]], [self.owner.pk])
        self.assertTrue(exported["rows"][0]["crawl_failure"])
        self.assertFalse(exported["rows"][0]["integration_health"])
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        request = RequestFactory().post("/api/account/close/"); request.user = self.owner
        with transaction.atomic():
            with patch("tenancy.services.did_recently_authenticate", return_value=True):
                close_personal_access(actor=self.owner, request=request)
            self.assertFalse(ProjectAlertPreference.objects.filter(user=self.owner).exists())
            self.assertTrue(ProjectAlertPreference.objects.filter(user=self.other).exists())
            transaction.set_rollback(True)
        self.assertTrue(ProjectAlertPreference.objects.filter(project_id=self.project.pk).exists())
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.org))
        delete_customer_database_records(run=run)
        self.assertFalse(ProjectAlertPreference.objects.filter(project_id=self.project.pk).exists())
        self.assertTrue(ProjectAlertPreference.objects.filter(project=other_project).exists())
        self.assertFalse(ProjectAlertPreference.objects.filter(user=self.owner).exists())
        self.assertTrue(ProjectAlertPreference.objects.filter(user=self.other).exists())
