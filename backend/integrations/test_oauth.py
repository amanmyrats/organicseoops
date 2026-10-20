from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from tenancy.models import MembershipRole, OrganizationMembership
from tenancy.services import create_organization, create_project

from .models import GoogleOAuthIntent
from .oauth import CALLBACK_PATH, OAuthStateError, begin_google_oauth_intent, consume_google_oauth_intent


CALLBACK = f"https://callback.example.com{CALLBACK_PATH}"


@override_settings(GOOGLE_OAUTH_REDIRECT_URI=CALLBACK)
class GoogleOAuthStateTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("oauth-owner@example.com", password="test-password")
        self.admin = users.create_user("oauth-admin@example.com", password="test-password")
        self.outsider = users.create_user("oauth-other@example.com", password="test-password")
        for user in (self.owner, self.admin, self.outsider):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        organization = create_organization(user=self.owner, name="OAuth org")
        OrganizationMembership.objects.create(organization=organization, user=self.admin, role=MembershipRole.ADMIN)
        self.project = create_project(organization=organization, user=self.owner, name="OAuth site",
                                      canonical_origin="https://oauth-site.example")
        self.session_key = "a" * 32

    def test_one_time_state_binds_actor_project_session_and_exact_redirect(self):
        attempt, state = begin_google_oauth_intent(project=self.project, user=self.admin, session_key=self.session_key)
        self.assertEqual(attempt.organization_id, self.project.organization_id)
        self.assertEqual(attempt.redirect_uri, CALLBACK)
        self.assertEqual(attempt.status, GoogleOAuthIntent.Status.PENDING)
        self.assertNotIn(state, str(attempt.__dict__))
        self.assertNotEqual(attempt.session_digest, self.session_key)
        with self.assertRaises(PermissionDenied):
            consume_google_oauth_intent(user=self.admin, session_key="b" * 32, state=state, callback_url=CALLBACK)
        with self.assertRaises(PermissionDenied):
            consume_google_oauth_intent(user=self.outsider, session_key=self.session_key, state=state, callback_url=CALLBACK)
        with self.assertRaises(OAuthStateError):
            consume_google_oauth_intent(user=self.admin, session_key=self.session_key, state=state,
                                        callback_url=f"https://outside.example{CALLBACK_PATH}")
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, GoogleOAuthIntent.Status.PENDING)
        consumed = consume_google_oauth_intent(user=self.admin, session_key=self.session_key, state=state, callback_url=CALLBACK)
        self.assertEqual(consumed.status, GoogleOAuthIntent.Status.CONSUMED)
        with self.assertRaises(OAuthStateError):
            consume_google_oauth_intent(user=self.admin, session_key=self.session_key, state=state, callback_url=CALLBACK)
        with self.assertRaises(ValidationError):
            consumed.save()

    def test_revocation_expiry_and_replaced_flow_stay_terminal(self):
        attempt, old = begin_google_oauth_intent(project=self.project, user=self.admin, session_key=self.session_key)
        second, new = begin_google_oauth_intent(project=self.project, user=self.admin, session_key=self.session_key)
        attempt.refresh_from_db()
        self.assertEqual((attempt.status, second.status), (GoogleOAuthIntent.Status.DENIED, GoogleOAuthIntent.Status.PENDING))
        with self.assertRaises(OAuthStateError):
            consume_google_oauth_intent(user=self.admin, session_key=self.session_key, state=old, callback_url=CALLBACK)
        OrganizationMembership.objects.filter(organization=self.project.organization, user=self.admin).update(role=MembershipRole.VIEWER)
        with self.assertRaises(OAuthStateError):
            consume_google_oauth_intent(user=self.admin, session_key=self.session_key, state=new, callback_url=CALLBACK)
        second.refresh_from_db()
        self.assertEqual(second.status, GoogleOAuthIntent.Status.DENIED)
        OrganizationMembership.objects.filter(organization=self.project.organization, user=self.admin).update(role=MembershipRole.ADMIN)
        expired, token = begin_google_oauth_intent(project=self.project, user=self.admin, session_key=self.session_key)
        GoogleOAuthIntent.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(OAuthStateError):
            consume_google_oauth_intent(user=self.admin, session_key=self.session_key, state=token, callback_url=CALLBACK)
        expired.refresh_from_db()
        self.assertEqual((expired.status, expired.used_at is not None), (GoogleOAuthIntent.Status.DENIED, True))

    def test_unverified_actor_and_malformed_redirect_fail_before_intent(self):
        EmailAddress.objects.filter(user=self.admin).update(verified=False)
        with self.assertRaises(PermissionDenied):
            begin_google_oauth_intent(project=self.project, user=self.admin, session_key=self.session_key)
        EmailAddress.objects.filter(user=self.admin).update(verified=True)
        for callback in ("", "https://outside.example/callback", f"{CALLBACK}?secret=1",
                         f"http://outside.example{CALLBACK_PATH}"):
            with self.subTest(callback=callback), override_settings(GOOGLE_OAUTH_REDIRECT_URI=callback):
                with self.assertRaises(ValidationError):
                    begin_google_oauth_intent(project=self.project, user=self.admin, session_key=self.session_key)
        self.assertEqual(GoogleOAuthIntent.objects.count(), 0)
        with self.assertRaises(OAuthStateError):
            consume_google_oauth_intent(user=self.admin, session_key=self.session_key, state="wrong-state", callback_url=CALLBACK)


@override_settings(GOOGLE_OAUTH_REDIRECT_URI=CALLBACK)
class GoogleOAuthStateRaceTests(TransactionTestCase):
    def test_simultaneous_callbacks_consume_one_state_once(self):
        user = get_user_model().objects.create_user("oauth-race@example.com", password="test-password")
        EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        organization = create_organization(user=user, name="OAuth race org")
        project = create_project(organization=organization, user=user, name="Site",
                                 canonical_origin="https://oauth-race.example")
        intent, state = begin_google_oauth_intent(project=project, user=user, session_key="s" * 32)
        barrier = Barrier(2)

        def consume(_number):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                try:
                    consume_google_oauth_intent(user=user, session_key="s" * 32, state=state, callback_url=CALLBACK)
                    return "consumed"
                except OAuthStateError:
                    return "replayed"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual(list(executor.map(consume, (1, 2))), ["consumed", "replayed"])
        intent.refresh_from_db()
        self.assertEqual(intent.status, GoogleOAuthIntent.Status.CONSUMED)
