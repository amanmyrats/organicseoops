import json

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase, override_settings

from integrations.oauth_views import _origin_matches_callback


@override_settings(
    ALLOWED_HOSTS=["app.example.invalid", "api.example.invalid"],
    CSRF_TRUSTED_ORIGINS=["https://app.example.invalid"],
    FRONTEND_ORIGIN="https://app.example.invalid",
    SESSION_COOKIE_SECURE=True,
    CSRF_COOKIE_SECURE=True,
    SECURE_SSL_REDIRECT=False,
    STAFF_MFA_REQUIRED=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class SameOriginApiProxyTests(TestCase):
    def test_exact_root_host_is_required_for_browser_oauth_callback(self):
        path = "/api/integrations/google-search-console/oauth/callback/"
        callback = "https://app.example.invalid" + path
        viewer = RequestFactory().get(path, HTTP_HOST="app.example.invalid", HTTP_X_FORWARDED_PROTO="https")
        api_host = RequestFactory().get(path, HTTP_HOST="api.example.invalid", HTTP_X_FORWARDED_PROTO="https")
        self.assertTrue(_origin_matches_callback(viewer, callback))
        self.assertEqual(viewer.build_absolute_uri(viewer.path), callback)
        self.assertFalse(_origin_matches_callback(api_host, callback))

    def test_public_viewer_host_cookies_and_csrf_through_api_origin_host(self):
        user = get_user_model().objects.create_user("origin-owner@example.invalid", "Safe password 99!")
        EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        client = Client(enforce_csrf_checks=True)
        origin = "https://app.example.invalid"
        host = "app.example.invalid"  # CloudFront forwards the viewer Host for exact OAuth callback checks.
        headers = {"HTTP_HOST": host, "HTTP_X_FORWARDED_PROTO": "https", "HTTP_ORIGIN": origin,
                   "HTTP_REFERER": origin + "/account/login"}
        status = client.get("/_allauth/browser/v1/auth/session", **headers)
        self.assertEqual(status.status_code, 401)
        csrf = client.cookies["csrftoken"]
        self.assertTrue(csrf["secure"])
        self.assertFalse(csrf["domain"])
        headers["HTTP_X_CSRFTOKEN"] = csrf.value
        response = client.post("/_allauth/browser/v1/auth/login",
                               data=json.dumps({"email": user.email, "password": "Safe password 99!"}),
                               content_type="application/json", **headers)
        self.assertEqual(response.status_code, 200, response.content)
        session = client.cookies["sessionid"]
        self.assertTrue(session["secure"])
        self.assertTrue(session["httponly"])
        self.assertFalse(session["domain"])
        self.assertEqual(session["samesite"], "Lax")
        self.assertEqual(client.get("/api/organizations/", **headers).status_code, 200)
        blocked = client.post("/api/account/product-language/", data=json.dumps({"language": "tr"}),
                              content_type="application/json",
                              **{**headers, "HTTP_ORIGIN": "https://evil.example.invalid"})
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(client.get("/api/organizations/", HTTP_HOST="evil.example.invalid",
                                    HTTP_X_FORWARDED_PROTO="https").status_code, 400)
