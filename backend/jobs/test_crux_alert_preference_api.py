import json
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from tenancy.models import OrganizationMembership, Project, ProjectMembership
from . import test_alert_preferences as fixtures
from .models import ProjectCruxAlertPreference, ProjectAlertPreference, ProjectSummaryPreference, ProjectAlertDelivery, ProjectAlertEpisodeClaim, JobRun


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "crux-intent-api"}})
class CruxAlertPreferenceApiTests(TestCase):
    setUp = fixtures.AlertPreferenceTests.setUp

    def browser(self, user=None):
        client = Client(enforce_csrf_checks=True); client.force_login(user or self.owner)
        client.get("/_allauth/browser/v1/auth/session")
        return client, {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value}

    def endpoint(self, org=None, project=None):
        return f"/api/organizations/{self.org.pk if org is None else org}/projects/{self.project.pk if project is None else project}/crux-alert-preference/"

    def test_actual_private_own_get_csrf_strict_json_methods_scope_and_no_other_intent_or_delivery(self):
        path = self.endpoint()
        self.assertEqual(Client().get(path).status_code, 401)
        client, csrf = self.browser()
        result = client.get(path)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result["Cache-Control"], "private, no-store")
        self.assertEqual(result["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(result.json(), {"project_id": self.project.pk, "preference": {"channel": "email",
            "source_family": "crux_material", "frequency": "off", "revision": 0, "delivery_state": "rollout_off"}})
        with override_settings(CRUX_ALERT_DELIVERY_ENABLED=True):
            self.assertEqual(client.get(path).json()["preference"]["delivery_state"], "enabled_optional")
        self.assertFalse(ProjectCruxAlertPreference.objects.exists())
        payload = {"frequency": "daily", "expected_revision": 0}
        self.assertEqual(client.post(path, json.dumps(payload), content_type="application/json").status_code, 403)
        invalid = [json.dumps({**payload, key: value}) for key, value in (
            ("user_id", self.other.pk), ("email", self.other.email), ("source_families", ["crux_material"]),
            ("minimum_absolute_increase", 1), ("intent_at", "2026-10-04"), ("material_crux", False))]
        invalid += ['{"frequency":"off","frequency":"daily","expected_revision":0}',
                    '{"frequency":"daily","expected_revision":NaN}', '{"frequency":"daily","expected_revision":true}',
                    '[0]', '{' * 1100, '"' + 'x' * 1025 + '"', '{"frequency":"weekly","expected_revision":0}']
        for raw in invalid:
            with self.subTest(raw=raw[:40]):
                denied = client.post(path, raw, content_type="application/json", **csrf)
                self.assertEqual(denied.status_code, 409)
                self.assertNotIn(self.other.email, denied.content.decode())
        self.assertEqual(client.get(path + "?source_family=crux_material").status_code, 400)
        self.assertEqual(client.generic("GET", path, data="{}", content_type="application/json").status_code, 409)
        for method in ("PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
            denied = client.generic(method, path, data="{}", content_type="application/json", **csrf)
            self.assertEqual(denied.status_code, 405); self.assertEqual(denied["Allow"], "GET, POST")
        for invalid_id in (0, 2**53):
            self.assertEqual(client.get(self.endpoint(org=invalid_id)).status_code, 400)
            self.assertEqual(client.get(self.endpoint(project=invalid_id)).status_code, 400)
        self.assertEqual(client.get(self.endpoint(org=self.org.pk + 10000)).status_code, 404)
        other, _ = self.browser(self.other)
        self.assertEqual(other.get(path).status_code, 404)
        membership = OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        self.assertEqual(other.get(path).json()["preference"]["revision"], 0)
        Project.objects.filter(pk=self.project.pk).update(access_restricted=True)
        self.assertEqual(other.get(path).status_code, 404)
        ProjectMembership.objects.create(project=self.project, organization_membership=membership)
        self.assertEqual(other.get(path).status_code, 200)
        with patch("jobs.crux_episode_source.current_material_crux_episodes", side_effect=AssertionError("source")), \
                patch("http.client.HTTPSConnection.request", side_effect=AssertionError("network")), \
                patch("jobs.tasks.scan_daily_alert_digests_task.apply_async", side_effect=AssertionError("dispatch")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")):
            saved = client.post(path, json.dumps(payload), content_type="application/json", **csrf)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["preference"]["revision"], 1)
        self.assertFalse(any(model.objects.exists() for model in (ProjectAlertPreference, ProjectSummaryPreference, ProjectAlertDelivery, ProjectAlertEpisodeClaim, JobRun)))

    def test_actual_revision_idempotency_verified_enable_off_and_final_loss_is_private_no_commit(self):
        client, csrf = self.browser(); path = self.endpoint()
        def save(frequency, revision):
            return client.post(path, json.dumps({"frequency": frequency, "expected_revision": revision}), content_type="application/json", **csrf)
        self.assertEqual(save("daily", 0).status_code, 200)
        row = ProjectCruxAlertPreference.objects.get(); original = row.updated_at
        self.assertEqual(save("daily", 1).json()["preference"]["revision"], 1)
        row.refresh_from_db(); self.assertEqual(row.updated_at, original)
        self.assertEqual(save("daily", 0).status_code, 409)
        EmailAddress.objects.filter(user=self.owner).update(verified=False)
        self.assertEqual(save("daily", 1).status_code, 403)
        self.assertEqual(save("off", 1).json()["preference"]["revision"], 2)
        ProjectCruxAlertPreference.objects.all().delete()
        EmailAddress.objects.filter(user=self.owner).update(verified=True)
        create = ProjectCruxAlertPreference.objects.create
        def changed(**kwargs):
            result = create(**kwargs); EmailAddress.objects.filter(user=self.owner).update(verified=False); return result
        with patch("jobs.crux_alert_preferences.ProjectCruxAlertPreference.objects.create", side_effect=changed):
            denied = save("daily", 0)
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(ProjectCruxAlertPreference.objects.exists())
        self.assertTrue(EmailAddress.objects.get(user=self.owner).verified)
        from .crux_alert_preferences import _preference
        def changed_projection(row):
            result = _preference(row); OrganizationMembership.objects.filter(user=self.owner, organization=self.org).delete(); return result
        with patch("jobs.crux_alert_preferences._preference", side_effect=changed_projection):
            denied = client.get(path)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied["Cache-Control"], "private, no-store")
        self.assertNotIn(self.owner.email, denied.content.decode())

    @override_settings(ACCOUNT_RATE_LIMITS={"crux_preference_read": "1/m/user,100/m/ip", "crux_preference_write": "1/m/user,100/m/ip",
                                           "summary_preference_read": "1/m/user,100/m/ip", "alert_preference_read": "1/m/user,100/m/ip"})
    def test_actual_independent_maintained_get_post_user_and_shared_ip_limits(self):
        client, csrf = self.browser(); path = self.endpoint()
        self.assertEqual(client.get(path).status_code, 200)
        limited = client.get(path)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited["Cache-Control"], "private, no-store")
        self.assertEqual(client.get(path.replace("crux-alert", "summary")).status_code, 200)
        self.assertEqual(client.get(path.replace("crux-alert", "alert")).status_code, 200)
        payload = json.dumps({"frequency": "off", "expected_revision": 0})
        self.assertEqual(client.post(path, payload, content_type="application/json", **csrf).status_code, 200)
        self.assertEqual(client.post(path, payload, content_type="application/json", **csrf).status_code, 429)
        cache.clear()
        OrganizationMembership.objects.create(organization=self.org, user=self.other, role="viewer")
        other, other_csrf = self.browser(self.other)
        with override_settings(ACCOUNT_RATE_LIMITS={"crux_preference_read": "100/m/user,1/m/ip", "crux_preference_write": "100/m/user,1/m/ip"}):
            self.assertEqual(client.get(path).status_code, 200)
            self.assertEqual(other.get(path).status_code, 429)
            self.assertEqual(other.get(path, REMOTE_ADDR="192.0.2.10").status_code, 200)
            self.assertEqual(client.post(path, payload, content_type="application/json", **csrf).status_code, 200)
            self.assertEqual(other.post(path, payload, content_type="application/json", **other_csrf).status_code, 429)
            self.assertEqual(other.post(path, payload, content_type="application/json", REMOTE_ADDR="192.0.2.10", **other_csrf).status_code, 200)
        self.assertFalse(ProjectCruxAlertPreference.objects.exists())
