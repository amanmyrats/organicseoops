import json
from hashlib import sha256
from tempfile import TemporaryFile
from unittest.mock import patch
from urllib.parse import urlencode

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.models import EmailAddress
from allauth.usersessions.models import UserSession
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from tenancy.models import AuditEvent, AuditEventType, Organization, OrganizationMembership
from tenancy.services import create_organization
from .auth import AccountAdapter
from .models import AccountEmailDelivery


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                      "LOCATION": "personal-export-fixtures"}}, SECURE_SSL_REDIRECT=False)
class PersonalExportTests(TestCase):
    def test_reauthenticated_personal_export_is_private_without_session_or_other_user_secrets(self):
        private_files = []
        def private_file(**kwargs):
            output = TemporaryFile(**kwargs)
            self.addCleanup(output.close)
            private_files.append(output)
            return output
        self.enterContext(patch("accounts.api.TemporaryFile", side_effect=private_file))
        users = get_user_model().objects
        user = users.create_user(email="self-export@example.invalid", password="Test-password-2026!")
        other = users.create_user(email="other-export@example.invalid", password="Test-password-2026!")
        for actor in (user, other):
            EmailAddress.objects.create(user=actor, email=actor.email, primary=True, verified=True)
            with patch.object(DefaultAccountAdapter, "send_mail", return_value=None):
                AccountAdapter().send_mail(f"account/email/{'own_export_fixture' if actor == user else 'other_export_fixture'}",
                                           actor.email, {"key": "MAIL-TOKEN-SECRET"})
        organization = create_organization(user=user, name="Self-owned organization")
        create_organization(user=other, name="Other-owned organization")
        UserSession.objects.create(user=user, session_key="s" * 40, ip="127.0.0.1",
                                   user_agent="Bearer SESSION-SECRET", data={"refresh_token": "DATA-SECRET"})
        url = "/api/account/export/"
        self.assertEqual(Client().post(url, "{}", content_type="application/json").status_code, 401)
        for path in ("/api/account/change-password/", "/api/account/logout-all/"):
            self.assertEqual(Client().post(path, "{}", content_type="application/json").status_code, 401)
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        self.assertEqual(client.post(url, "{}", content_type="application/json").status_code, 403)
        client.get("/_allauth/browser/v1/auth/session", secure=True)
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value,
                   "HTTP_REFERER": "https://testserver/"}
        self.assertEqual(client.post(url, "{}", content_type="application/json",
                                     secure=True, **headers).status_code, 403)
        verified = client.post("/_allauth/browser/v1/auth/reauthenticate",
            data=json.dumps({"password": "Test-password-2026!"}), content_type="application/json",
            secure=True, **headers)
        self.assertEqual(verified.status_code, 200, verified.content)
        response = client.post(url, "{}", content_type="application/json", secure=True, **headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.streaming)
        content = b"".join(response.streaming_content)
        self.assertTrue(private_files[-1].closed)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-SHA256"], sha256(content).hexdigest())
        payload = json.loads(content)
        self.assertEqual(payload["scope"], "own_account_not_organization_content")
        self.assertEqual(payload["account"]["email"], user.email)
        self.assertEqual(payload["memberships"][0]["organization_id"], organization.pk)
        self.assertEqual(payload["mail_diagnostics"], [{"purpose": "own_export_fixture", "state": "transport_returned",
            "attempted_at": AccountEmailDelivery.objects.get(address__user=user).attempted_at.isoformat()}])
        for forbidden in (other.email, "Other-owned organization", "SESSION-SECRET", "DATA-SECRET",
                          "refresh_token", "session_key", user.password, "other_export_fixture", "MAIL-TOKEN-SECRET"):
            self.assertNotIn(forbidden, content.decode())
        self.assertEqual(AuditEvent.objects.filter(actor=user, event_type=AuditEventType.ACCOUNT_EXPORTED).count(), 1)
        address = EmailAddress.objects.get(user=user, primary=True)
        AccountEmailDelivery.objects.bulk_create([AccountEmailDelivery(address=address, purpose=f"growth_{index:04d}",
            state="transport_returned", finished_at=timezone.now()) for index in range(1600)])
        EmailAddress.objects.bulk_create([EmailAddress(user=user, email=f"alias-{index}@example.invalid")
                                         for index in range(101)])
        UserSession.objects.bulk_create([UserSession(user=user, session_key=f"{index:040d}", ip="127.0.0.1",
            user_agent="Bearer SESSION-SECRET", data={"refresh_token": "DATA-SECRET"}) for index in range(101)])
        organizations = Organization.objects.bulk_create([Organization(name=f"Membership {index}")
                                                          for index in range(101)])
        OrganizationMembership.objects.bulk_create([OrganizationMembership(user=user, organization=org, role="member")
                                                   for org in organizations])
        native_headers = {"HTTP_REFERER": "https://testserver/"}
        self.assertEqual(client.post(url, "csrfmiddlewaretoken=wrong",
            content_type="application/x-www-form-urlencoded", secure=True, **native_headers).status_code, 403)
        grown = client.post(url, urlencode({"csrfmiddlewaretoken": client.cookies["csrftoken"].value}),
                            content_type="application/x-www-form-urlencoded", secure=True, **native_headers)
        self.assertEqual(grown.status_code, 200)
        grown_content = b"".join(grown.streaming_content)
        self.assertTrue(private_files[-1].closed)
        self.assertGreater(len(grown_content), 128 * 1024)
        self.assertEqual(int(grown["Content-Length"]), len(grown_content))
        self.assertEqual(grown["X-Content-SHA256"], sha256(grown_content).hexdigest())
        grown_payload = json.loads(grown_content)
        for name, queryset in (("emails", EmailAddress.objects.filter(user=user)),
                               ("memberships", OrganizationMembership.objects.filter(user=user)),
                               ("mail_diagnostics", AccountEmailDelivery.objects.filter(address__user=user)),
                               ("sessions", UserSession.objects.filter(user=user))):
            self.assertGreater(len(grown_payload[name]), 100)
            self.assertEqual(len(grown_payload[name]), queryset.count())
        self.assertEqual(grown_payload["mail_diagnostics"][-1]["purpose"], "growth_1599")
        for forbidden in (other.email, "Other-owned organization", "SESSION-SECRET", "DATA-SECRET",
                          "refresh_token", "session_key", user.password, "other_export_fixture", "MAIL-TOKEN-SECRET"):
            self.assertNotIn(forbidden, grown_content.decode())
        self.assertEqual(AuditEvent.objects.filter(actor=user, event_type=AuditEventType.ACCOUNT_EXPORTED)
                         .order_by("pk").last().details["size_bytes"], len(grown_content))
        with patch("accounts.api.ratelimit.consume", return_value=True):
            for request_body in ("{\"user_id\":1}", "[]", "x" * 129):
                self.assertEqual(client.post(url, request_body, content_type="application/json", secure=True,
                                             **headers).status_code, 400)
            self.assertEqual(client.post(url, urlencode({"csrfmiddlewaretoken": client.cookies["csrftoken"].value,
                                              "user_id": other.pk}), content_type="application/x-www-form-urlencoded",
                                         secure=True, **headers).status_code, 400)
            with TemporaryFile() as private_file, patch("accounts.api.TemporaryFile", return_value=private_file), \
                    patch("accounts.api._write_personal_account_export", side_effect=OSError("PRIVATE-PATH")):
                failed = client.post(url, "{}", content_type="application/json", secure=True, **headers)
                self.assertEqual(failed.status_code, 503)
                self.assertTrue(private_file.closed)
                self.assertNotIn("PRIVATE-PATH", failed.content.decode())
                self.assertEqual(failed["Cache-Control"], "private, no-store")
            with patch("accounts.api.TemporaryFile", side_effect=OSError("PRIVATE-PATH")):
                self.assertEqual(client.post(url, "{}", content_type="application/json", secure=True,
                                             **headers).status_code, 503)
        self.assertEqual(AuditEvent.objects.filter(actor=user, event_type=AuditEventType.ACCOUNT_EXPORTED).count(), 2)
        close_url = "/api/account/close/"
        with override_settings(SELF_SERVICE_ACCOUNT_CLOSURE_ENABLED=False):
            self.assertEqual(client.post(close_url, '{"acknowledge_restricted_identity_retention":true}',
                content_type="application/json", secure=True, **headers).status_code, 503)
        with override_settings(SELF_SERVICE_ACCOUNT_CLOSURE_ENABLED=True):
            self.assertFalse(client.get("/api/account/closure-status/", secure=True).json()["action_available"])
            self.assertEqual(client.post(close_url, '{"acknowledge_restricted_identity_retention":true}',
                content_type="application/json", secure=True, **headers).status_code, 409)
            Organization.objects.filter(memberships__user=user).update(is_suspended=True, closed_at=timezone.now())
            self.assertTrue(client.get("/api/account/closure-status/", secure=True).json()["action_available"])
            self.assertEqual(client.post(close_url, '{"acknowledge_restricted_identity_retention":false}',
                content_type="application/json", secure=True, **headers).status_code, 400)
            closed = client.post(close_url, '{"acknowledge_restricted_identity_retention":true}',
                                 content_type="application/json", secure=True, **headers)
        self.assertEqual(closed.status_code, 202, closed.content)
        self.assertEqual(closed.json()["state"], "access_closed")
        self.assertEqual(closed.json()["retained_identity"], "restricted_policy_review_not_erased")
        self.assertEqual(client.get("/_allauth/browser/v1/auth/session", secure=True).status_code, 401)
        user.refresh_from_db()
        self.assertIsNotNone(user.closed_at)
        self.assertTrue(Organization.objects.filter(name="Other-owned organization").exists())
