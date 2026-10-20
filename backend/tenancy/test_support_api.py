import json
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from config.test_foundations import TEST_STORAGES
from . import test_support_requests as fixtures
from .models import OrganizationMembership, SupportRequest


@override_settings(DEBUG=True, STORAGES=TEST_STORAGES,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "support-api"}})
class SupportApiTests(TestCase):
    def command(self, **changes):
        return {**fixtures.SupportRequestTests.command(self), "expected_actor_id": self.owner.pk, **changes}

    def setUp(self):
        cache.clear(); fixtures.SupportRequestTests.setUp(self)
        self.url = f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/support-requests/"
        self.client = Client(enforce_csrf_checks=True); self.client.force_login(self.owner)
        self.client.get("/_allauth/browser/v1/auth/session")
        self.csrf = {"HTTP_X_CSRFTOKEN": self.client.cookies["csrftoken"].value}

    def post(self, body=None, **changes):
        return self.client.post(self.url, json.dumps(body if body is not None else self.command(**changes)),
                                content_type="application/json", **self.csrf)

    def test_private_idempotent_create_list_detail_viewer_own_only_and_csrf(self):
        self.assertEqual(Client().get(self.url).status_code, 401)
        self.assertEqual(self.client.post(self.url, json.dumps(self.command()), content_type="application/json").status_code, 403)
        result = self.post(); self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(self.post().json(), result.json())
        identity = result.json()["request"]["id"]
        self.assertEqual(self.client.get(f"{self.url}{identity}/").json(), result.json())
        self.assertEqual(self.client.get(self.url).json()["requests"][0]["id"], identity)
        self.assertEqual(result["Cache-Control"], "private, no-store"); self.assertIn("noindex", result["X-Robots-Tag"])
        viewer = get_user_model().objects.create_user("support-api-viewer@example.invalid")
        OrganizationMembership.objects.create(organization=self.organization, user=viewer, role="viewer")
        client = Client(); client.force_login(viewer)
        missing = client.get(f"{self.url}{identity}/")
        self.assertEqual(missing.json()["request"], None)
        self.assertEqual(client.get(self.url).json()["requests"], [])
        self.assertEqual(client.post(self.url, json.dumps(self.command(expected_actor_id=viewer.pk)), content_type="application/json").status_code, 200)
        self.assertEqual(client.post(self.url, json.dumps(self.command()), content_type="application/json").status_code, 403)
        self.assertEqual(self.client.get(self.url).json()["requests"][0]["id"], identity)
        foreign = f"/api/organizations/{self.other_org.pk}/projects/{self.other_project.pk}/support-requests/"
        self.assertEqual(self.client.get(foreign).status_code, 404)
        self.assertEqual(SupportRequest.objects.count(), 2)

    def test_strict_input_no_error_echo_no_extra_authority_methods_or_get_body(self):
        for raw in ('{"request_key":"good-key","request_key":"duplicate"}', '{"value":NaN}', '[]', '"bad"', '{', '"' + 'x' * 17000 + '"'):
            response = self.client.post(self.url, raw, content_type="application/json", **self.csrf)
            self.assertEqual(response.status_code, 409)
            self.assertNotIn("duplicate", response.content.decode())
        for changes in ({"requester_id": self.outsider.pk}, {"no_sensitive_data": 1}, {"question": "Authorization: Bearer hidden-secret-marker"}):
            response = self.post(**changes); self.assertEqual(response.status_code, 409)
            self.assertNotIn("hidden-secret-marker", response.content.decode())
        self.assertEqual(self.client.get(self.url, {"recipient": "1"}).status_code, 400)
        self.assertEqual(self.client.generic("GET", self.url, "{}", content_type="application/json").status_code, 409)
        self.assertEqual(self.client.delete(self.url, **self.csrf).status_code, 405)
        self.assertEqual(self.client.post(self.url + "1/", "{}", content_type="application/json", **self.csrf).status_code, 405)
        self.assertEqual(self.client.get(self.url.replace(str(self.project.pk) + "/support", str(2**53) + "/support")).status_code, 400)
        self.assertFalse(SupportRequest.objects.exists())

    def test_actual_get_and_create_user_ip_budgets_are_independent(self):
        rates = {**settings.ACCOUNT_RATE_LIMITS, "support_request_read": "1/h/user,99/h/ip", "support_request_create": "1/h/user,99/h/ip"}
        with override_settings(ACCOUNT_RATE_LIMITS=rates):
            self.assertEqual(self.client.get(self.url).status_code, 200)
            denied = self.client.get(self.url); self.assertEqual(denied.status_code, 429)
            self.assertEqual(denied["Cache-Control"], "private, no-store")
            self.assertEqual(self.post().status_code, 200)
            self.assertEqual(self.post().status_code, 429)
        cache.clear()
        rates.update(support_request_read="99/h/user,1/h/ip")
        with override_settings(ACCOUNT_RATE_LIMITS=rates):
            self.assertEqual(self.client.get(self.url).status_code, 200)
            other = Client(); other.force_login(self.owner)
            self.assertEqual(other.get(self.url).status_code, 429)
            self.assertEqual(other.get(self.url, REMOTE_ADDR="127.0.0.2").status_code, 200)

    def test_final_insert_reader_loss_delivers_no_prose_or_partial_row(self):
        create = SupportRequest.objects.create
        def changed(**kwargs):
            result = create(**kwargs); OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).delete(); return result
        with patch("tenancy.support_requests.SupportRequest.objects.create", side_effect=changed):
            result = self.post()
        self.assertEqual(result.status_code, 403)
        self.assertNotIn("Why did my job stop?", result.content.decode())
        self.assertFalse(SupportRequest.objects.exists())
