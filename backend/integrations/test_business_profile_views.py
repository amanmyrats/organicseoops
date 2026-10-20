from functools import partial
import json
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from jobs.models import JobRun
from tenancy.models import MembershipRole, OrganizationMembership
from . import test_business_profile_oauth as oauth_fixtures
from . import test_business_profile_read as read_fixtures
from .business_profile import POLICY_VERSION
from .business_profile_oauth import revoke_business_grant
from .business_profile_read import _begin, complete_business_consent, read_business_profile
from .models import BusinessProfileOAuthGrant


@override_settings(PROVIDER_ENCRYPTION_KEYS=(oauth_fixtures.KEY,), STAFF_MFA_REQUIRED=False,
    SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["app.example.invalid", "wrong.example.invalid"],
    FRONTEND_ORIGIN="https://app.example.invalid", CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class BusinessViewsTests(TestCase):
    review = oauth_fixtures.BusinessConsentTests.review
    collector = read_fixtures.BusinessReadTests.collector
    refresh = read_fixtures.BusinessReadTests.refresh

    def setUp(self):
        oauth_fixtures.BusinessConsentTests.setUp(self)
        cache.clear()
        self.path = f"/api/organizations/{self.org.pk}/projects/{self.project.pk}/business-profile/"
        self.browser = self.client_for(self.owner)

    def client_for(self, user):
        client = Client(enforce_csrf_checks=True, HTTP_HOST="app.example.invalid")
        client.force_login(user)
        client.get("/_allauth/browser/v1/auth/session", secure=True)
        return client

    def post(self, body, *, browser=None, path=None, csrf=True):
        browser = browser or self.browser
        return browser.post(path or self.path, data=body if type(body) is str else json.dumps(body),
            content_type="application/json", secure=True, HTTP_REFERER="https://app.example.invalid/",
            **({"HTTP_X_CSRFTOKEN": browser.cookies["csrftoken"].value} if csrf else {}))

    def start(self):
        result = self.post({"action": "consent", "selection": self.selection, "policy_version": POLICY_VERSION})
        self.assertEqual(result.status_code, 201)
        url = urlsplit(result.json()["authorization_url"])
        self.assertEqual((url.scheme, url.hostname, url.path), ("https", "accounts.google.com", "/o/oauth2/v2/auth"))
        params = parse_qs(url.query)
        self.assertEqual(params["scope"], ["https://www.googleapis.com/auth/business.manage"])
        self.assertNotIn("SECRET", result.content.decode())
        return params["state"][0]

    def test_authenticated_consent_actual_protected_read_status_no_replay_and_revoke_journey(self):
        state = self.start()
        from django.utils import timezone
        from datetime import timedelta
        from .google_tokens import GoogleTokens
        exchange = Mock(return_value=GoogleTokens("ACCESS_SECRET", "REFRESH_SECRET", timezone.now() + timedelta(hours=1)))
        callback = urlsplit(oauth_fixtures.CALLBACK).path
        with patch("integrations.business_profile_views.complete_business_consent",
                   side_effect=partial(complete_business_consent, exchange=exchange)):
            response = self.browser.get(callback, {"state": state, "code": "CODE_SECRET"}, secure=True)
            self.assertEqual(response.status_code, 303)
            self.assertNotIn("SECRET", response["Location"])
            self.assertEqual(self.browser.get(callback, {"state": state, "code": "CODE_SECRET"}, secure=True).status_code, 303)
        self.assertEqual(exchange.call_count, 1)
        grant = BusinessProfileOAuthGrant.objects.get()
        collect, seen = self.collector()
        body = {"action": "read", "grant_id": grant.pk, "grant_revision": 0, "policy_version": POLICY_VERSION,
                "accepted": True, "request_key": "fixture-private-read"}
        with patch("integrations.business_profile_views.read_business_profile",
                   side_effect=partial(read_business_profile, refresh=self.refresh, collect=collect)):
            response = self.post(body)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["result"]["reviews"], read_fixtures.source_fixtures.reviews())
            self.assertEqual(self.post(body).json()["code"], "request_already_attempted")
        self.assertEqual(len(seen), 3)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        status = self.browser.get(self.path, {"request_key": "fixture-private-read"}, secure=True)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["attempts"][0]["actual_units"], 4)
        self.assertEqual(status.json()["returned_content"], "not_stored_not_replayable")
        for value in ("ACCESS_SECRET", "REFRESH_SECRET", "review_1", "Untrusted", "SIBLING_CANARY"):
            self.assertNotIn(value, status.content.decode())
        with patch("integrations.business_profile_views.revoke_business_grant",
                   side_effect=partial(revoke_business_grant, revoke=lambda **_kwargs: True)):
            response = self.post({"action": "revoke", "grant_id": grant.pk})
        self.assertEqual(response.json()["state"], "revoked")
        with patch("integrations.business_profile_views.read_business_profile") as transport:
            foreign = self.post({**body, "grant_id": grant.pk + 999})
            self.assertEqual(foreign.status_code, 403)
            transport.assert_not_called()

    def test_unauthorized_csrf_member_foreign_origin_duplicate_json_and_oversize_fail_without_exchange(self):
        self.assertEqual(Client(HTTP_HOST="app.example.invalid").get(self.path, secure=True).status_code, 401)
        self.assertEqual(self.post({"action": "consent"}, csrf=False).status_code, 403)
        member = get_user_model().objects.create_user("gbp-member@example.invalid", "test-password")
        OrganizationMembership.objects.create(organization=self.org, user=member, role=MembershipRole.MEMBER)
        self.assertEqual(self.post({"action": "consent"}, browser=self.client_for(member)).status_code, 403)
        self.assertEqual(self.browser.get(self.path.replace(f"organizations/{self.org.pk}", "organizations/999999"), secure=True).status_code, 404)
        with patch("integrations.business_profile_views.read_business_profile") as read:
            for payload in ('{"action":"read","action":"revoke"}', '[]', '{"action":NaN}',
                            "x" * 4097, '{"action":"read","grant_id":true}', '{"action":{"secret":"x"}}'):
                self.assertEqual(self.post(payload).status_code, 409)
            read.assert_not_called()
        state = self.start()
        callback = urlsplit(oauth_fixtures.CALLBACK).path
        with patch("integrations.business_profile_views.complete_business_consent") as exchange:
            response = self.browser.get(callback, {"state": state, "code": "CODE_SECRET"}, secure=True,
                                        HTTP_HOST="wrong.example.invalid")
            self.assertEqual(response.status_code, 303)
            exchange.assert_not_called()
        self.assertFalse(JobRun.objects.exists())

    def test_scoped_pending_attempt_cancel_and_unknown_key_status_never_returns_content(self):
        # Use checked fixture completion to stage only an operational attempt for the API cancel boundary.
        from .business_profile_oauth import complete_business_oauth
        from .google_tokens import GoogleTokens
        from django.utils import timezone
        from datetime import timedelta
        # The opaque state is read only from this browser response.
        state = self.start()
        grant = complete_business_oauth(actor=self.owner, session_key=self.browser.session.session_key, state=state,
            callback_url=oauth_fixtures.CALLBACK, code="CODE_SECRET", exchange=lambda **_kwargs: GoogleTokens(
                "ACCESS_SECRET", "REFRESH_SECRET", timezone.now() + timedelta(hours=1)))
        job = _begin(project=self.project, actor=self.owner, request_key="fixture-cancel-read", data={"operation": "read",
            "grant_id": grant.pk, "grant_revision": 0, "policy_version": POLICY_VERSION, "accepted": True})
        self.assertEqual(self.post({"action": "cancel", "job_id": job.pk + 999}).status_code, 403)
        self.assertEqual(self.post({"action": "cancel", "job_id": job.pk}).status_code, 200)
        self.assertTrue(job.cancellation.pk)
        status = self.browser.get(self.path, {"request_key": "fixture-cancel-read"}, secure=True)
        self.assertTrue(status.json()["attempts"][0]["cancel_requested"])
        self.assertEqual(self.browser.get(self.path, {"request_key": "unseen-key"}, secure=True).json()["attempts"], [])
        self.assertEqual(self.browser.get(self.path, {"before_id": "bad"}, secure=True).status_code, 409)
