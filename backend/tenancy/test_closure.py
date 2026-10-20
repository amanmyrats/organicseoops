import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from integrations.models import GA4OAuthGrant, GoogleOAuthGrant, IntegrationConnection
from integrations.ga4_oauth import encrypt_ga4_refresh_token
from integrations.google_tokens import encrypt_refresh_token
from integrations.services import create_connection
from jobs.models import JobRun, JobSchedule, JobStatus, UsageReservation
from jobs.services import create_job
from jobs.usage import reserve_usage
from providers.models import AIProvider, AIProviderAccount, AIProviderSecret, OrganizationPerformanceKey

from .closure import close_organization_locally
from .closure_grants import revoke_closed_analytics_grant, revoke_closed_search_console_grant
from .deletion import prepare_customer_data_deletion
from .models import (AuditEvent, AuditEventType, OrganizationBillingCancellation, OrganizationDeletionRun,
                     MembershipRole, OrganizationMembership, PaddleCheckoutAttempt, PaddleStatus,
                     PaddleSubscription, Project)
from .paddle_cancellation import (execute_billing_cancellation, prepare_billing_cancellation,
                                  reconcile_billing_cancellation)
from .paddle_transport import PaddleTransportError
from .services import create_organization, create_project
from .test_paddle_seller import SANDBOX_KEY


KEY = Fernet.generate_key().decode()


@override_settings(PADDLE_ENVIRONMENT="sandbox", DEBUG=True,
                   GOOGLE_OAUTH_ENCRYPTION_KEYS=(KEY,), GOOGLE_ANALYTICS_ENCRYPTION_KEYS=(KEY,),
                   CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                       "LOCATION": "closure-status-fixtures"}})
class OrganizationClosureTests(TestCase):
    def setUp(self):
        cache.clear()
        users = get_user_model().objects
        self.owner = users.create_user("closure-owner@example.invalid", password="test-password")
        self.other = users.create_user("closure-outsider@example.invalid", password="test-password")
        for user in (self.owner, self.other):
            EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        self.org = create_organization(user=self.owner, name="Closure source")
        self.project = create_project(organization=self.org, user=self.owner,
                                      name="Closure project", canonical_origin="https://closure.example.invalid")
        self.other_org = create_organization(user=self.other, name="Independent source")
        self.other_project = create_project(organization=self.other_org, user=self.other,
            name="Independent project", canonical_origin="https://other-closure.example.invalid")
        self.request = RequestFactory().post("/api/organizations/close/")
        self.request.user = self.owner

    @patch("tenancy.services.did_recently_authenticate", return_value=True)
    def test_trial_close_stops_queued_running_schedules_sources_and_keys_without_cross_tenant_changes(self, _reauth):
        status_url = f"/api/organizations/{self.org.pk}/closure-status/"
        self.assertEqual(Client().get(status_url).status_code, 401)
        owner_client = Client()
        owner_client.force_login(self.owner)
        self.assertEqual(owner_client.get(status_url).json()["state"], "open")
        self.assertFalse(owner_client.get(status_url).json()["close_action_available"])
        other_client = Client()
        other_client.force_login(self.other)
        self.assertEqual(other_client.get(status_url).status_code, 404)
        viewer = get_user_model().objects.create_user("closure-viewer@example.invalid", password="test-password")
        OrganizationMembership.objects.create(organization=self.org, user=viewer, role=MembershipRole.VIEWER)
        viewer_client = Client()
        viewer_client.force_login(viewer)
        self.assertEqual(viewer_client.get(status_url).status_code, 403)
        queued = create_job(project=self.project, actor=self.owner, handler="diagnostic_probe",
                            input_snapshot={"sample": "closure", "simulate_partial": False})
        reserve_usage(job=queued, provider="diagnostic", units=0)
        running = create_job(project=self.project, actor=self.owner, handler="diagnostic_probe",
                             input_snapshot={"sample": "closure running", "simulate_partial": False})
        JobRun.objects.filter(pk=running.pk).update(status=JobStatus.RUNNING)
        schedule = JobSchedule.objects.create(organization=self.org, project=self.project, actor=self.owner,
            handler="diagnostic_probe", input_snapshot={"sample": "closure", "simulate_partial": False},
            enabled=True, next_run_at=timezone.now() + timedelta(hours=1))
        connection = create_connection(project=self.project, user=self.owner, provider="google_search_console",
            external_property_id="https://closure.example.invalid/", capabilities=["csv_import", "query_metrics"],
            available_dimensions=["query"], source_semantics="search_console_performance",
            source_semantics_version="csv-v1")
        google = GoogleOAuthGrant.objects.create(organization=self.org, project=self.project, actor=self.owner,
            encrypted_refresh_token=encrypt_refresh_token("CLOSE-GOOGLE"),
            scope="https://www.googleapis.com/auth/webmasters.readonly",
            verified_at=timezone.now())
        analytics = GA4OAuthGrant.objects.create(organization=self.org, project=self.project, actor=self.owner,
            encrypted_refresh_token=encrypt_ga4_refresh_token("CLOSE-GA4"),
            scope="https://www.googleapis.com/auth/analytics.readonly",
            verified_at=timezone.now())
        foreign = create_job(project=self.other_project, actor=self.other, handler="diagnostic_probe",
                             input_snapshot={"sample": "foreign", "simulate_partial": False})
        key = OrganizationPerformanceKey.objects.create(organization=self.org, state="active",
            encrypted_secret="v1:fixture-secret", rotated_at=timezone.now())
        provider = AIProvider.objects.create(key="fixture_ai", name="Synthetic only", kind="openai",
                                              egress_policy="official_openai", enabled=True)
        own_account = AIProviderAccount.objects.create(provider=provider, organization=self.org, label="own")
        other_account = AIProviderAccount.objects.create(provider=provider, organization=self.other_org, label="other")
        platform_account = AIProviderAccount.objects.create(provider=provider, label="platform")
        for account in (own_account, other_account, platform_account):
            AIProviderSecret.objects.create(account=account, ciphertext="v1:synthetic-only", rotated_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            close_organization_locally(organization=self.org, actor=self.other, request=self.request)
        closed = close_organization_locally(organization=self.org, actor=self.owner, request=self.request)
        self.assertIsNotNone(closed.closed_at)
        self.assertTrue(closed.is_suspended)
        queued.refresh_from_db()
        self.assertEqual((queued.status, queued.error_category), (JobStatus.CANCELLED, "organization_closed"))
        self.assertEqual(queued.usage.state, UsageReservation.State.RELEASED)
        self.assertIsNotNone(queued.usage.settled_at)
        self.assertTrue(running.cancellation.requested_by_id == self.owner.pk)
        schedule.refresh_from_db()
        self.assertFalse(schedule.enabled)
        self.assertIsNone(schedule.next_run_at)
        connection.refresh_from_db()
        self.assertEqual(connection.state, IntegrationConnection.State.DISCONNECTED)
        google.refresh_from_db()
        analytics.refresh_from_db()
        self.assertEqual((google.state, analytics.state), (google.State.REVOCATION_PENDING,
                                                         analytics.State.REVOCATION_PENDING))
        self.assertEqual((google.revision, analytics.revision), (1, 1))
        self.assertTrue(google.encrypted_refresh_token.startswith("v1:"))
        self.assertTrue(analytics.encrypted_refresh_token.startswith("v1:"))
        self.assertEqual(revoke_closed_search_console_grant(grant_id=google.pk,
            revoke=lambda **_: False).state, google.State.REVOCATION_PENDING)
        self.assertEqual(revoke_closed_analytics_grant(grant_id=analytics.pk,
            revoke=lambda **_: False).state, analytics.State.REVOCATION_PENDING)
        self.assertEqual(revoke_closed_search_console_grant(grant_id=google.pk,
            revoke=lambda *, encrypted_refresh: encrypted_refresh.startswith("v1:")).state, google.State.REVOKED)
        self.assertEqual(revoke_closed_analytics_grant(grant_id=analytics.pk,
            revoke=lambda *, token: token == "CLOSE-GA4").state, analytics.State.REVOKED)
        google.refresh_from_db(); analytics.refresh_from_db()
        self.assertEqual((google.encrypted_refresh_token, analytics.encrypted_refresh_token), ("", ""))
        self.assertEqual(revoke_closed_analytics_grant(grant_id=analytics.pk,
            revoke=lambda **_: self.fail("Already revoked: no remote call")).state, analytics.State.REVOKED)
        key.refresh_from_db()
        self.assertEqual((key.state, key.encrypted_secret), ("revoked", ""))
        own_account.refresh_from_db(); other_account.refresh_from_db(); platform_account.refresh_from_db()
        self.assertEqual(own_account.state, own_account.State.REVOKED)
        self.assertFalse(AIProviderSecret.objects.filter(account=own_account).exists())
        for untouched in (other_account, platform_account):
            self.assertEqual(untouched.state, untouched.State.ACTIVE)
            self.assertTrue(AIProviderSecret.objects.filter(account=untouched).exists())
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, JobStatus.QUEUED)
        self.assertTrue(Project.objects.for_user(self.other).filter(pk=self.other_project.pk).exists())
        self.assertFalse(Project.objects.for_user(self.owner).filter(pk=self.project.pk).exists())
        self.assertEqual(close_organization_locally(organization=self.org, actor=self.owner,
            request=self.request).closed_at, closed.closed_at)
        self.assertEqual(AuditEvent.objects.filter(organization=self.org,
            event_type=AuditEventType.ORGANIZATION_CLOSED).count(), 1)
        response = owner_client.get(status_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(response.json()["state"], "closed")
        self.assertEqual(response.json()["remote_revocation_pending"], {
            "search_console": 0, "analytics": 0, "business_profile": 0})

    @override_settings(SELF_SERVICE_CLOSURE_ENABLED=True)
    def test_owner_close_api_requires_csrf_recent_password_and_explicit_irreversible_ack(self):
        url = f"/api/organizations/{self.org.pk}/close/"
        other = Client()
        other.force_login(self.other)
        self.assertEqual(other.post(url, data='{"acknowledge_irreversible":true}',
                                    content_type="application/json").status_code, 404)
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        self.assertTrue(owner.get(f"/api/organizations/{self.org.pk}/closure-status/").json()["close_action_available"])
        data = '{"acknowledge_irreversible":true}'
        self.assertEqual(owner.post(url, data=data, content_type="application/json").status_code, 403)
        owner.get("/_allauth/browser/v1/auth/session", secure=True)
        headers = {"HTTP_X_CSRFTOKEN": owner.cookies["csrftoken"].value,
                   "HTTP_REFERER": "https://testserver/"}
        self.assertEqual(owner.post(url, data=data, content_type="application/json",
                                    secure=True, **headers).status_code, 403)
        verified = owner.post("/_allauth/browser/v1/auth/reauthenticate",
            data='{"password":"test-password"}', content_type="application/json", secure=True, **headers)
        self.assertEqual(verified.status_code, 200, verified.content)
        self.assertEqual(owner.post(url, data='{"acknowledge_irreversible":false}',
                                    content_type="application/json", secure=True, **headers).status_code, 409)
        response = owner.post(url, data=data, content_type="application/json", secure=True, **headers)
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response.json()["state"], "closed")
        self.assertEqual(response.json()["billing_state"], "not_required")
        self.assertEqual(response.json()["cleanup_state"], "prepared")
        self.assertTrue(OrganizationDeletionRun.objects.filter(organization=self.org, state="pending").exists())
        self.assertEqual(owner.post(url, data=data, content_type="application/json",
                                    secure=True, **headers).status_code, 200)
        self.assertEqual(AuditEvent.objects.filter(organization=self.org,
            event_type=AuditEventType.ORGANIZATION_CLOSED).count(), 1)

    def test_public_close_action_is_disabled_by_default(self):
        owner = Client()
        owner.force_login(self.owner)
        with override_settings(SELF_SERVICE_CLOSURE_ENABLED=False):
            response = owner.post(f"/api/organizations/{self.org.pk}/close/",
                data='{"acknowledge_irreversible":true}', content_type="application/json")
        self.assertEqual(response.status_code, 503)
        self.assertIsNone(self.org.__class__.objects.get(pk=self.org.pk).closed_at)

    @override_settings(SELF_SERVICE_CLOSURE_ENABLED=True)
    def test_closed_access_survives_failed_cleanup_preparation_and_daily_retry(self):
        owner = Client(enforce_csrf_checks=True)
        owner.force_login(self.owner)
        owner.get("/_allauth/browser/v1/auth/session", secure=True)
        headers = {"HTTP_X_CSRFTOKEN": owner.cookies["csrftoken"].value,
                   "HTTP_REFERER": "https://testserver/"}
        self.assertEqual(owner.post("/_allauth/browser/v1/auth/reauthenticate",
            data='{"password":"test-password"}', content_type="application/json",
            secure=True, **headers).status_code, 200)
        url = f"/api/organizations/{self.org.pk}/close/"
        with patch("tenancy.closure_api.prepare_customer_data_deletion", side_effect=ValidationError("transient")):
            response = owner.post(url, data='{"acknowledge_irreversible":true}',
                                  content_type="application/json", secure=True, **headers)
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual((response.json()["state"], response.json()["cleanup_state"]),
                         ("closed_cleanup_review", "needs_review"))
        self.assertTrue(self.org.__class__.objects.get(pk=self.org.pk).is_suspended)
        self.assertFalse(OrganizationDeletionRun.objects.filter(organization=self.org).exists())
        self.assertEqual(prepare_customer_data_deletion(organization=self.org).source,
                         OrganizationDeletionRun.Source.OWNER_CLOSED)
        self.assertEqual(owner.post(url, data='{"acknowledge_irreversible":true}',
                                    content_type="application/json", secure=True, **headers).status_code, 200)
        self.assertEqual(AuditEvent.objects.filter(organization=self.org,
            event_type=AuditEventType.ORGANIZATION_CLOSED).count(), 1)

    @override_settings(SELF_SERVICE_CLOSURE_ENABLED=True)
    @patch("tenancy.paddle_cancellation.paddle_seller_secrets", return_value=(SANDBOX_KEY, "unused"))
    def test_paid_close_response_stays_unknown_after_one_attempted_provider_timeout(self, _seller):
        now = timezone.now()
        subscription = PaddleSubscription.objects.create(organization=self.org, environment="sandbox",
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26,
            status=PaddleStatus.ACTIVE, verified_at=now - timedelta(days=1),
            period_starts_at=now - timedelta(days=1), period_ends_at=now + timedelta(days=29),
            currency_code="USD")
        PaddleCheckoutAttempt.objects.create(organization=self.org, actor=self.owner, environment="sandbox",
            offer_version="agency-launch-v1", product_id="pro_" + "c" * 26,
            price_id="pri_" + "d" * 26, request_key="api-close-paid", state=PaddleCheckoutAttempt.State.READY,
            transaction_id="txn_" + "e" * 26, sent_at=now - timedelta(days=1),
            paid_verified_at=now - timedelta(days=1), paid_customer_id=subscription.customer_id,
            paid_subscription_id=subscription.subscription_id)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        client.get("/_allauth/browser/v1/auth/session", secure=True)
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value,
                   "HTTP_REFERER": "https://testserver/"}
        url = f"/api/organizations/{self.org.pk}/close/"
        self.assertEqual(client.post(url, data='{"acknowledge_irreversible":true}',
                                     content_type="application/json", secure=True, **headers).status_code, 403)
        self.assertFalse(OrganizationBillingCancellation.objects.filter(organization=self.org).exists())
        self.assertFalse(AuditEvent.objects.filter(organization=self.org,
            event_type=AuditEventType.BILLING_CANCELLATION_PREPARED).exists())
        self.assertEqual(client.post("/_allauth/browser/v1/auth/reauthenticate",
            data='{"password":"test-password"}', content_type="application/json",
            secure=True, **headers).status_code, 200)
        called = []

        def uncertain(**kwargs):
            called.append(kwargs["attempt"].pk)
            raise PaddleTransportError("timeout")

        with patch("tenancy.closure_api.execute_billing_cancellation", side_effect=lambda attempt:
                   execute_billing_cancellation(attempt, cancel=uncertain)):
            response = client.post(url, data='{"acknowledge_irreversible":true}',
                                   content_type="application/json", secure=True, **headers)
            self.assertEqual(response.status_code, 202, response.content)
            self.assertEqual(response.json()["state"], "closed_billing_review")
            self.assertEqual(response.json()["billing_state"], "unknown")
            self.assertEqual(client.post(url, data='{"acknowledge_irreversible":true}',
                content_type="application/json", secure=True, **headers).status_code, 200)
        self.assertEqual(len(called), 1)
        self.assertEqual(PaddleSubscription.objects.get(pk=subscription.pk).status, PaddleStatus.ACTIVE)
        self.assertTrue(self.org.__class__.objects.get(pk=self.org.pk).is_suspended)
        seen = []

        def observed(**_):
            seen.append("provider_get")
            return {"data": {"id": subscription.subscription_id, "customer_id": subscription.customer_id,
                "status": "canceled", "canceled_at": timezone.now().isoformat()}}

        reconcile_path = f"/api/organizations/{self.org.pk}/closure/billing-reconcile/"
        with patch("tenancy.closure_api.reconcile_billing_cancellation", side_effect=lambda record:
                   reconcile_billing_cancellation(record, subscription_get=observed)):
            result = client.post(reconcile_path, "{}", content_type="application/json", secure=True, **headers)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()["state"], "confirmed")
        self.assertEqual(seen, ["provider_get"])
        with patch("tenancy.closure_api.reconcile_billing_cancellation", side_effect=lambda record:
                   reconcile_billing_cancellation(record, subscription_get=lambda **_: self.fail("No second GET"))):
            self.assertEqual(client.post(reconcile_path, "{}", content_type="application/json",
                                         secure=True, **headers).json()["state"], "confirmed")

    def test_scoped_grant_revoke_api_rechecks_closure_and_never_calls_foreign_provider_grant(self):
        grant = GoogleOAuthGrant.objects.create(organization=self.org, project=self.project, actor=self.owner,
            encrypted_refresh_token=encrypt_refresh_token("OWN-GRANT"),
            scope="https://www.googleapis.com/auth/webmasters.readonly", verified_at=timezone.now())
        foreign = GoogleOAuthGrant.objects.create(organization=self.other_org, project=self.other_project,
            actor=self.other, encrypted_refresh_token=encrypt_refresh_token("FOREIGN-GRANT"),
            scope="https://www.googleapis.com/auth/webmasters.readonly", verified_at=timezone.now())
        self.org.__class__.objects.filter(pk__in=[self.org.pk, self.other_org.pk]).update(
            is_suspended=True, closed_at=timezone.now())
        for record in (grant, foreign):
            type(record).objects.filter(pk=record.pk).update(state=record.State.REVOCATION_PENDING, revision=1)
        AuditEvent.objects.create(organization=self.org, actor=self.owner,
                                  event_type=AuditEventType.ORGANIZATION_CLOSED, details={})
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        client.get("/_allauth/browser/v1/auth/session", secure=True)
        headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value,
                   "HTTP_REFERER": "https://testserver/"}
        url = f"/api/organizations/{self.org.pk}/closure/grants/revoke/"
        body = {"provider": "search_console", "grant_id": grant.pk}
        self.assertEqual(client.post(url, data=json.dumps(body), content_type="application/json",
                                     secure=True, **headers).status_code, 403)
        self.assertEqual(client.post("/_allauth/browser/v1/auth/reauthenticate",
            data='{"password":"test-password"}', content_type="application/json",
            secure=True, **headers).status_code, 200)
        seen = []

        def verified_revoke(**kwargs):
            seen.append(kwargs["grant_id"])
            return revoke_closed_search_console_grant(grant_id=kwargs["grant_id"],
                invoked_by=kwargs["invoked_by"], revoke=lambda **_: True)

        with patch("tenancy.closure_api.revoke_closed_search_console_grant", side_effect=verified_revoke):
            denied = client.post(url, data=json.dumps({**body, "grant_id": foreign.pk}),
                                 content_type="application/json", secure=True, **headers)
            self.assertEqual(denied.status_code, 404)
            response = client.post(url, data=json.dumps(body), content_type="application/json",
                                   secure=True, **headers)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["state"], grant.State.REVOKED)
        self.assertEqual(seen, [grant.pk])
        foreign.refresh_from_db(); grant.refresh_from_db()
        self.assertEqual(foreign.state, foreign.State.REVOCATION_PENDING)
        self.assertTrue(foreign.encrypted_refresh_token)
        self.assertEqual(grant.encrypted_refresh_token, "")

    @patch("tenancy.services.did_recently_authenticate", return_value=True)
    def test_close_rolls_back_when_audit_fails(self, _reauth):
        job = create_job(project=self.project, actor=self.owner, handler="diagnostic_probe",
                         input_snapshot={"sample": "rollback", "simulate_partial": False})
        with patch("tenancy.closure.AuditEvent.objects.create", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                close_organization_locally(organization=self.org, actor=self.owner, request=self.request)
        self.org.refresh_from_db()
        job.refresh_from_db()
        self.assertIsNone(self.org.closed_at)
        self.assertEqual(job.status, JobStatus.QUEUED)

    @patch("tenancy.paddle_cancellation.paddle_seller_secrets", return_value=(SANDBOX_KEY, "unused"))
    @patch("tenancy.services.did_recently_authenticate", return_value=True)
    def test_paid_close_requires_prepared_current_cancellation_without_remote_call(self, _reauth, _seller):
        now = timezone.now()
        subscription = PaddleSubscription.objects.create(organization=self.org, environment="sandbox",
            customer_id="ctm_" + "a" * 26, subscription_id="sub_" + "b" * 26,
            status=PaddleStatus.ACTIVE, verified_at=now - timedelta(days=1),
            period_starts_at=now - timedelta(days=1), period_ends_at=now + timedelta(days=29),
            currency_code="USD")
        paid = PaddleCheckoutAttempt.objects.create(organization=self.org, actor=self.owner,
            environment="sandbox", offer_version="agency-launch-v1",
            product_id="pro_" + "c" * 26, price_id="pri_" + "d" * 26,
            request_key="paid-closure-fixture", state=PaddleCheckoutAttempt.State.READY,
            transaction_id="txn_" + "e" * 26, sent_at=now - timedelta(days=1),
            paid_verified_at=now - timedelta(days=1), paid_customer_id=subscription.customer_id,
            paid_subscription_id="sub_" + "f" * 26)
        with self.assertRaises(ValidationError):
            close_organization_locally(organization=self.org, actor=self.owner, request=self.request)
        paid.paid_subscription_id = subscription.subscription_id
        paid.save(update_fields=["paid_subscription_id"])
        with self.assertRaises(ValidationError):
            close_organization_locally(organization=self.org, actor=self.owner, request=self.request)
        attempt = prepare_billing_cancellation(organization=self.org, actor=self.owner)
        self.assertEqual(attempt.state, OrganizationBillingCancellation.State.RESERVED)
        closed = close_organization_locally(organization=self.org, actor=self.owner, request=self.request)
        self.assertTrue(closed.is_suspended)
        self.assertEqual(OrganizationBillingCancellation.objects.get(organization=self.org).state,
                         OrganizationBillingCancellation.State.RESERVED)
        self.assertEqual(PaddleSubscription.objects.get(pk=subscription.pk).status, PaddleStatus.ACTIVE)
        self.assertIn("pending", str(AuditEvent.objects.get(organization=self.org,
            event_type=AuditEventType.ORGANIZATION_CLOSED).details))
        def timeout(**_):
            raise PaddleTransportError("timeout")
        attempted = execute_billing_cancellation(attempt, cancel=timeout)
        self.assertEqual((attempted.state, attempted.error_category), (attempted.State.UNKNOWN, "timeout"))
        self.org.refresh_from_db()
        self.assertTrue(self.org.is_suspended)
        self.assertEqual(execute_billing_cancellation(attempted,
            cancel=lambda **_: self.fail("No duplicate provider cancellation")).state, attempted.State.UNKNOWN)
