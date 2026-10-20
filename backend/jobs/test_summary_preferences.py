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
from .models import ProjectSummaryPreference
from .summary_preferences import project_summary_preference, set_project_summary_preference


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, WEEKLY_SUMMARY_DELIVERY_ENABLED=False,
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "summary-prefs"}})
class SummaryPreferenceTests(TransactionTestCase):
    def setUp(self):
        dispatch = patch("jobs.services.dispatch_pending", return_value=False)
        self.addCleanup(dispatch.stop)
        dispatch.start()
        cache.clear()
        self.owner = get_user_model().objects.create_user("summary-owner@example.invalid", "Test passphrase 99!")
        self.other = get_user_model().objects.create_user("summary-viewer@example.invalid", "Test passphrase 99!")
        for user in (self.owner, self.other):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        self.org = create_organization(user=self.owner, name="Summary preferences")
        self.project = create_project(organization=self.org, user=self.owner, name="Summary site",
                                      canonical_origin="https://summary.example.invalid")
        self.path = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/summary-preference/"

    def save(self, frequency="weekly", revision=0, actor=None):
        return set_project_summary_preference(project=self.project, actor=actor or self.owner,
            frequency=frequency, expected_revision=revision)

    def test_default_reads_and_off_are_write_free_then_revision_fences_prevent_stale_reenable(self):
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(project_summary_preference(project=self.project, actor=self.owner),
                             {"channel": "email", "frequency": "off", "revision": 0, "delivery_state": "rollout_off"})
            self.assertEqual(self.save("off")["revision"], 0)
        self.assertFalse(any(query["sql"].lstrip().split()[0] in {"INSERT", "UPDATE", "DELETE"} for query in queries))
        self.assertEqual(self.save()["revision"], 1)
        self.assertEqual(self.save(revision=1)["revision"], 1)
        self.assertEqual(self.save("off", 1)["revision"], 2)
        with self.assertRaises(ValidationError): self.save(revision=1)
        self.assertEqual(ProjectSummaryPreference.objects.get().frequency, "off")
        for frequency, revision in ((True, 2), ("daily", 2), ("weekly", True), ("off", -1)):
            with self.assertRaises(ValidationError): self.save(frequency, revision)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ProjectSummaryPreference.objects.create(project=self.project, user=self.owner)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ProjectSummaryPreference.objects.filter(user=self.owner).update(frequency="spam")
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ProjectSummaryPreference.objects.filter(user=self.owner).update(revision=0)

    def test_configured_rollout_is_not_recipient_eligibility_or_a_direct_send_on_get_or_save(self):
        from .models import ProjectSummaryDelivery
        client = Client(); client.force_login(self.owner)
        with patch("jobs.summary_delivery.send_mail", side_effect=AssertionError("SMTP")), \
                patch("jobs.tasks.send_weekly_summary_task.delay", side_effect=AssertionError("dispatch")):
            for enabled, state in ((False, "rollout_off"), (True, "enabled_optional"), (False, "rollout_off")):
                with override_settings(WEEKLY_SUMMARY_DELIVERY_ENABLED=enabled):
                    self.assertEqual(client.get(self.path).json()["preference"]["delivery_state"], state)
                    result = client.post(self.path, json.dumps({"frequency": "weekly", "expected_revision":
                        1 if ProjectSummaryPreference.objects.exists() else 0}), content_type="application/json")
                    self.assertEqual(result.status_code, 200)
                    self.assertEqual(result.json()["preference"], {"channel": "email", "frequency": "weekly",
                        "revision": 1, "delivery_state": state})
            EmailAddress.objects.filter(user=self.owner).update(verified=False)
            with override_settings(WEEKLY_SUMMARY_DELIVERY_ENABLED=True):
                self.assertEqual(client.get(self.path).json()["preference"]["delivery_state"], "enabled_optional")
        self.assertEqual(ProjectSummaryDelivery.objects.count(), 0)

    def test_only_current_own_project_reader_and_verification_required_to_enable_not_disable(self):
        with self.assertRaises(PermissionDenied): self.save(actor=self.other)
        membership = OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        self.assertEqual(self.save(actor=self.other)["frequency"], "weekly")
        self.assertEqual(ProjectSummaryPreference.objects.get().user_id, self.other.pk)
        EmailAddress.objects.filter(user=self.other).update(verified=False)
        with self.assertRaises(PermissionDenied): self.save(revision=1, actor=self.other)
        self.assertEqual(self.save("off", 1, actor=self.other)["frequency"], "off")
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        with self.assertRaises(PermissionDenied): self.save("off", 2, actor=self.other)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(self.save("off", 2, actor=self.other)["revision"], 2)
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True)
        with self.assertRaises(PermissionDenied): self.save("off", 2, actor=self.other)

    def test_final_verification_role_loss_rolls_back_insert_without_mail_or_job(self):
        original = ProjectSummaryPreference.objects.create
        for change in (lambda: EmailAddress.objects.filter(user=self.owner).update(verified=False),
                       lambda: OrganizationMembership.objects.filter(organization=self.org, user=self.owner).delete()):
            def create_then_change(**kwargs):
                row = original(**kwargs)
                change()
                return row
            with patch("jobs.summary_preferences.ProjectSummaryPreference.objects.create", side_effect=create_then_change), \
                    patch("django.core.mail.send_mail", side_effect=AssertionError("mail")), self.assertRaises(PermissionDenied):
                self.save()
            self.assertEqual(ProjectSummaryPreference.objects.count(), 0)
            self.assertTrue(EmailAddress.objects.get(user=self.owner).verified)
            self.assertTrue(OrganizationMembership.objects.filter(user=self.owner).exists())

    def test_actual_private_api_csrf_exact_fields_foreign_authority_and_no_recipient_copy(self):
        self.assertEqual(Client().get(self.path).status_code, 401)
        client = Client(enforce_csrf_checks=True); client.force_login(self.owner)
        result = client.get(self.path)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        payload = {"frequency": "weekly", "expected_revision": 0}
        self.assertEqual(client.post(self.path, json.dumps(payload), content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session")
        csrf = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}
        for raw in (json.dumps({**payload, "user_id": self.other.pk}), json.dumps({**payload, "email": self.other.email}),
                    '{"frequency":"off","frequency":"weekly","expected_revision":0}', '{"frequency":"weekly","expected_revision":NaN}'):
            self.assertEqual(client.post(self.path, raw, content_type="application/json", **csrf).status_code, 409)
        self.assertEqual(client.get(self.path + "?user_id=1").status_code, 400)
        self.assertEqual(client.put(self.path, "{}", content_type="application/json", **csrf).status_code, 405)
        result = client.post(self.path, json.dumps(payload), content_type="application/json", **csrf)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["preference"]["frequency"], "weekly")
        self.assertNotIn(self.owner.email, result.content.decode())
        self.assertNotIn("user_id", result.content.decode())
        other = Client(); other.force_login(self.other)
        self.assertEqual(other.get(self.path).status_code, 404)
        OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        self.assertEqual(other.get(self.path).json()["preference"]["frequency"], "off")
        self.assertEqual(client.post(self.path, json.dumps({"frequency": "off", "expected_revision": 1}),
                                    content_type="application/json", **csrf).json()["preference"]["revision"], 2)
        self.assertEqual(client.post(self.path, json.dumps(payload), content_type="application/json", **csrf).status_code, 409)

    def test_actual_customer_export_organization_erasure_and_personal_close_are_scoped(self):
        from accounts.closure import close_personal_access
        from tenancy.customer_inventory import require_complete_ownership_map
        from tenancy.customer_export import project_customer_rows
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        self.save()
        other_org = create_organization(user=self.other, name="Other preferences")
        other_project = create_project(organization=other_org, user=self.other, name="Other summary",
                                       canonical_origin="https://other-summary.example.invalid")
        set_project_summary_preference(project=other_project, actor=self.other, frequency="weekly", expected_revision=0)
        require_complete_ownership_map()
        row = ProjectSummaryPreference.objects.get(project=self.project)
        exported = project_customer_rows(organization=self.org, actor=self.owner,
            model_label="jobs.ProjectSummaryPreference", after_id=0, through_id=row.pk)
        self.assertEqual([item["user_id"] for item in exported["rows"]], [self.owner.pk])
        self.assertEqual(exported["rows"][0]["frequency"], "weekly")
        Organization.objects.filter(pk=self.org.pk).update(is_suspended=True, closed_at=timezone.now())
        request = RequestFactory().post("/api/account/close/"); request.user = self.owner
        with transaction.atomic():
            with patch("tenancy.services.did_recently_authenticate", return_value=True):
                close_personal_access(actor=self.owner, request=request)
            self.assertFalse(ProjectSummaryPreference.objects.filter(user=self.owner).exists())
            self.assertTrue(ProjectSummaryPreference.objects.filter(user=self.other).exists())
            transaction.set_rollback(True)
        self.assertTrue(ProjectSummaryPreference.objects.filter(project_id=self.project.pk).exists())
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.org))
        delete_customer_database_records(run=run)
        self.assertFalse(ProjectSummaryPreference.objects.filter(project_id=self.project.pk).exists())
        self.assertTrue(ProjectSummaryPreference.objects.filter(project=other_project).exists())
        self.assertFalse(ProjectSummaryPreference.objects.filter(user=self.owner).exists())
        self.assertTrue(ProjectSummaryPreference.objects.filter(user=self.other).exists())

    @override_settings(ACCOUNT_RATE_LIMITS={"summary_preference_read": "1/m/user,100/m/ip",
                                          "summary_preference_write": "2/m/user,100/m/ip"})
    def test_actual_get_user_and_ip_limits_are_enforced_without_using_post_budget_or_writing(self):
        client = Client(enforce_csrf_checks=True); client.force_login(self.owner)
        self.assertEqual(client.get(self.path).status_code, 200)
        limited = client.get(self.path)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited["Cache-Control"], "private, no-store")
        self.assertEqual(limited["X-Robots-Tag"], "noindex, nofollow")
        self.assertFalse(ProjectSummaryPreference.objects.exists())
        client.get("/_allauth/browser/v1/auth/session")
        result = client.post(self.path, json.dumps({"frequency": "off", "expected_revision": 0}),
            content_type="application/json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(result.status_code, 200)
        cache.clear()
        OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        other = Client(); other.force_login(self.other)
        with override_settings(ACCOUNT_RATE_LIMITS={"summary_preference_read": "100/m/user,1/m/ip"}):
            self.assertEqual(client.get(self.path).status_code, 200)
            self.assertEqual(other.get(self.path).status_code, 429)
            self.assertEqual(other.get(self.path, REMOTE_ADDR="192.0.2.10").status_code, 200)
        self.assertFalse(ProjectSummaryPreference.objects.exists())
