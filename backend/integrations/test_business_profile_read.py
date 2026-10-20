from copy import deepcopy
from datetime import timedelta
from functools import partial
from io import BytesIO
import json
from unittest.mock import Mock, patch
from zipfile import ZipFile

from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from jobs.models import Artifact, JobCancellation, JobRun, JobStep, UsageReservation
from jobs.usage import reconcile_usage, UsageLimitError
from tenancy.models import OrganizationTrial, ProjectOriginVerification
from . import test_business_profile as source_fixtures
from . import test_business_profile_oauth as oauth_fixtures
from .business_profile import POLICY_VERSION
from .business_profile_read import (_before_request, _begin, BusinessRequestError, complete_business_consent,
    finish_business_attempt, read_business_profile, recover_business_attempts)
from .business_profile_transport import read_authorized_business_profile
from .google_tokens import GoogleTokens
from .models import BusinessProfileOAuthGrant
from .business_profile_tokens import decrypt_business_refresh_token, exchange_business_code
from .test_search_console_transport import FakeConnection, FakeResponse


@override_settings(PROVIDER_ENCRYPTION_KEYS=(oauth_fixtures.KEY,), STAFF_MFA_REQUIRED=False,
    SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["testserver"],
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class BusinessReadTests(TransactionTestCase):
    setUp = oauth_fixtures.BusinessConsentTests.setUp
    review = oauth_fixtures.BusinessConsentTests.review
    begin = oauth_fixtures.BusinessConsentTests.begin
    complete = oauth_fixtures.BusinessConsentTests.complete

    def grant(self):
        _, state = self.begin()
        return self.complete(state)

    def refresh(self, **_kwargs):
        return GoogleTokens("ACCESS_SECRET", None, timezone.now() + timedelta(hours=1))

    def collector(self, *, effect=None, status=200):
        responses = [{"accounts": [{"name": "accounts/123"}, {"name": "accounts/999", "accountName": "SIBLING_CANARY"}]},
            {"locations": [source_fixtures.profile(), {**source_fixtures.profile(), "name": "locations/999", "title": "SIBLING_CANARY"}]},
            source_fixtures.reviews()]
        seen = []
        def factory(*_args):
            if effect:
                effect(len(seen))
            transport = FakeConnection(FakeResponse(json.dumps(responses[len(seen)]).encode(), status if len(seen) == 2 else 200))
            seen.append(transport)
            return transport
        return partial(read_authorized_business_profile, resolver=lambda *_args, **_kwargs: ("8.8.8.8",),
                       connection_factory=factory), seen

    def read(self, grant, **changes):
        collect, seen = self.collector()
        kwargs = dict(project=self.project, actor=self.owner, grant_id=grant.pk, grant_revision=grant.revision,
            policy_version=POLICY_VERSION, accepted=True, request_key="fixture-business-read-1", refresh=self.refresh, collect=collect)
        return read_business_profile(**{**kwargs, **changes}), seen

    def test_actual_consent_and_protected_read_are_once_counted_unchanged_and_never_durable_content(self):
        _, state = self.begin()
        grant = complete_business_consent(actor=self.owner, session_key=self.session, state=state,
            callback_url=oauth_fixtures.CALLBACK, code="CODE_SECRET", exchange=lambda **_kwargs: GoogleTokens(
                "ACCESS_SECRET", "REFRESH_SECRET", timezone.now() + timedelta(hours=1)))
        consent = JobRun.objects.get(input_snapshot__operation="consent")
        self.assertEqual((consent.status, consent.usage.actual_units), ("succeeded", 1))
        result, seen = self.read(grant)
        self.assertEqual(len(seen), 3)
        self.assertEqual(result["result"]["profile"], source_fixtures.profile())
        self.assertEqual(result["result"]["reviews"], source_fixtures.reviews())
        self.assertNotIn("SIBLING_CANARY", json.dumps(result))
        grant.refresh_from_db()
        self.assertEqual((grant.state, grant.revision, result["grant_revision"]), ("active", 1, 1))
        job = JobRun.objects.get(pk=result["job_id"])
        self.assertEqual((job.status, job.output, job.usage.reserved_units, job.usage.actual_units), ("succeeded", {}, 4, 4))
        self.assertEqual(list(job.steps.values_list("name", flat=True)), ["token_refresh", "accounts_list", "locations_list", "reviews_list"])
        persisted = json.dumps(list(JobRun.objects.values()), default=str) + json.dumps(list(JobStep.objects.values()), default=str)
        # Datetimes are serialized separately; returned content never enters either snapshot/output.
        for value in ("SIBLING_CANARY", "review_1", "Untrusted", "ACCESS_SECRET", "REFRESH_SECRET"):
            self.assertNotIn(value, persisted)
        with self.assertRaises(BusinessRequestError) as error:
            self.read(grant, refresh=Mock(side_effect=AssertionError("duplicate must not refresh")))
        self.assertEqual(error.exception.category, "request_already_attempted")
        from tenancy.customer_export import complete_bounded_customer_archive
        with patch("tenancy.customer_export.iter_project_artifact_keys", return_value=iter(())):
            data = complete_bounded_customer_archive(organization=self.org, actor=self.owner)
        with ZipFile(BytesIO(data)) as archive:
            content = b"".join(archive.read(path) for path in archive.namelist())
        self.assertNotIn(b"review_1", content)
        self.assertNotIn(b"Untrusted", content)
        self.assertFalse(Artifact.objects.exists())

    def test_failure_and_mid_request_revocation_settle_only_attempted_units_and_never_deliver(self):
        grant = self.grant()
        collect, seen = self.collector(status=403)
        with self.assertRaises(BusinessRequestError) as error:
            self.read(grant, collect=collect)
        self.assertEqual(error.exception.category, "authorization_unavailable")
        job = JobRun.objects.get(handler="business_profile_request")
        self.assertEqual((job.status, job.usage.actual_units), ("failed", 4))
        self.assertEqual(grant.state, "pending_selection")
        def revoke(index):
            if index == 0:
                ProjectOriginVerification.objects.filter(pk=self.verification.pk).update(state="revoked", revoked_at=timezone.now())
        collect, seen = self.collector(effect=revoke)
        with self.assertRaises(BusinessRequestError) as error:
            self.read(grant, collect=collect, request_key="fixture-revoked-read")
        self.assertEqual(error.exception.category, "actor_or_source_revoked")
        self.assertEqual(len(seen), 1)
        job = JobRun.objects.get(idempotency_key="fixture-revoked-read")
        self.assertEqual(job.usage.actual_units, 2)
        self.assertEqual(job.output, {})

    def test_cancel_and_trial_expiry_before_refresh_send_no_network_and_release_estimate(self):
        grant = self.grant()
        def cancel(**_kwargs):
            job = JobRun.objects.get(handler="business_profile_request")
            JobCancellation.objects.create(job=job, requested_by=self.owner)
            return self.refresh()
        with self.assertRaises(BusinessRequestError) as error:
            self.read(grant, refresh=cancel, collect=Mock(side_effect=AssertionError("cancel must not collect")))
        self.assertEqual(error.exception.category, "cancelled")
        self.assertEqual(JobRun.objects.get(handler="business_profile_request").usage.actual_units, 1)
        OrganizationTrial.objects.filter(organization=self.org).update(
            started_at=timezone.now() - timedelta(days=31), ends_at=timezone.now() - timedelta(days=1))
        with self.assertRaises(UsageLimitError):
            self.read(grant, request_key="fixture-expired-read", refresh=Mock(side_effect=AssertionError("expiry must not refresh")))
        self.assertEqual(JobRun.objects.count(), 1)

    def test_unknown_recovery_uses_committed_steps_no_replay_and_fails_late_response(self):
        grant = self.grant()
        data = {"operation": "read", "grant_id": grant.pk, "grant_revision": 0,
                "policy_version": POLICY_VERSION, "accepted": True}
        job = _begin(project=self.project, actor=self.owner, data=data, request_key="fixture-lost-read")
        _before_request(job, "token_refresh")
        _before_request(job, "accounts_list")
        with self.assertRaises(BusinessRequestError) as error:
            _begin(project=self.project, actor=self.owner, data=data, request_key="fixture-concurrent-read")
        self.assertEqual(error.exception.category, "client_busy")
        JobRun.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(minutes=2),
                                               updated_at=timezone.now() - timedelta(minutes=2))
        self.assertEqual(recover_business_attempts(), 1)
        job.refresh_from_db()
        self.assertEqual((job.status, job.error_category, job.usage.actual_units), ("failed", "request_outcome_unknown", 2))
        self.assertFalse(finish_business_attempt(job))
        self.assertEqual(recover_business_attempts(), 0)
        self.assertEqual(reconcile_usage(), 0)
        with self.assertRaises(BusinessRequestError):
            _begin(project=self.project, actor=self.owner, data=data, request_key="fixture-lost-read")

    def test_direct_model_and_step_paths_forbid_content_scope_retry_and_artifact_persistence(self):
        grant = self.grant()
        result, _ = self.read(grant)
        job = JobRun.objects.get(pk=result["job_id"])
        job.output = {"reviews": source_fixtures.reviews()}
        with self.assertRaises(ValidationError):
            job.save()
        step = job.steps.first()
        step.output = source_fixtures.profile()
        with self.assertRaises(ValidationError):
            step.save()
        with self.assertRaises(ValidationError):
            Artifact.objects.create(job=job, project=self.project, key="invalid.json", content_type="application/json", size_bytes=10)
        data = deepcopy(job.input_snapshot)
        data["profile"] = source_fixtures.profile()
        with self.assertRaises(ValidationError):
            _begin(project=self.project, actor=self.owner, data=data, request_key="fixture-content-injection")
        with self.assertRaises(ValidationError):
            JobRun.objects.create(organization=self.org, project=self.project, actor=self.owner, handler=job.handler,
                method_version=POLICY_VERSION, input_snapshot=job.input_snapshot, retry_of=job, idempotency_key="fixture-retry")

    def test_overall_api_deadline_includes_refresh_and_suppresses_late_collection(self):
        grant = self.grant()
        elapsed = [0.0]
        def refresh(**_kwargs):
            elapsed[0] = 25.0
            return self.refresh()
        collect = Mock(side_effect=AssertionError("late refresh must not start another request"))
        with self.assertRaises(BusinessRequestError) as error:
            self.read(grant, refresh=refresh, collect=collect, clock=lambda: elapsed[0])
        self.assertEqual(error.exception.category, "timeout")
        collect.assert_not_called()
        self.assertEqual(JobRun.objects.get(handler="business_profile_request").usage.actual_units, 1)

    def test_rejected_scope_expiry_or_missing_refresh_captures_only_revocable_material_and_attempted_unit(self):
        from .business_profile import SCOPE
        from .business_profile_oauth import revoke_business_grant, require_business_grant
        from .google_tokens import GoogleTokenError
        from django.core.exceptions import PermissionDenied
        cases = ({"scope": SCOPE + " foreign.scope"}, {"expires_in": True}, {"refresh_token": None})
        for changes in cases:
            _, state = self.begin()
            payload = {"token_type": "Bearer", "scope": SCOPE, "expires_in": 3600,
                       "access_token": "ACCESS_SECRET", "refresh_token": "REFRESH_SECRET", **changes}
            with self.assertRaises(BusinessRequestError):
                complete_business_consent(actor=self.owner, session_key=self.session, state=state,
                    callback_url=oauth_fixtures.CALLBACK, code="CODE_SECRET",
                    exchange=partial(exchange_business_code, transport=lambda **_kwargs: payload))
            grant = BusinessProfileOAuthGrant.objects.latest("pk")
            self.assertEqual(grant.state, "revocation_pending")
            self.assertEqual(decrypt_business_refresh_token(grant.encrypted_refresh_token,
                organization_id=self.org.pk, project_id=self.project.pk), payload["refresh_token"] or "ACCESS_SECRET")
            with self.assertRaises(PermissionDenied):
                require_business_grant(grant=grant, actor=self.owner, expected_revision=grant.revision)
            job = JobRun.objects.latest("pk")
            self.assertEqual((job.status, job.steps.count(), job.usage.actual_units, job.output), ("failed", 1, 1, {}))
            with self.assertRaises(GoogleTokenError):
                revoke_business_grant(grant=grant, actor=self.owner, revoke=lambda **_kwargs: False)
            grant.refresh_from_db()
            self.assertEqual(grant.state, "revocation_pending")
            self.assertTrue(grant.encrypted_refresh_token)
            self.assertEqual(revoke_business_grant(grant=grant, actor=self.owner, revoke=lambda **_kwargs: True).state, "revoked")
        persisted = json.dumps(list(JobRun.objects.values()), default=str) + json.dumps(list(JobStep.objects.values()), default=str)
        self.assertNotIn("SECRET", persisted)
        self.assertNotIn("foreign.scope", persisted)

    def test_unexpected_replacement_disables_even_valid_refresh_and_confirms_each_token_without_abandonment(self):
        from .business_profile_oauth import revoke_business_grant, require_business_grant
        from .google_tokens import GoogleTokenError
        from django.core.exceptions import PermissionDenied
        grant = self.grant()
        collect = Mock(side_effect=AssertionError("replacement response cannot collect content"))
        with self.assertRaises(BusinessRequestError) as error:
            self.read(grant, collect=collect, refresh=lambda **_kwargs: GoogleTokens(
                "ACCESS_SECRET", "REPLACEMENT_SECRET", timezone.now() + timedelta(hours=1)))
        self.assertEqual(error.exception.category, "refresh_material_changed")
        collect.assert_not_called()
        grant.refresh_from_db()
        self.assertEqual(grant.state, "revocation_pending")
        self.assertEqual(decrypt_business_refresh_token(grant.encrypted_extra_token,
            organization_id=self.org.pk, project_id=self.project.pk), "REPLACEMENT_SECRET")
        with self.assertRaises(PermissionDenied):
            require_business_grant(grant=grant, actor=self.owner, expected_revision=0)
        seen = []
        def revoke(**kwargs):
            token = decrypt_business_refresh_token(kwargs["encrypted_refresh"], organization_id=self.org.pk, project_id=self.project.pk)
            seen.append(token)
            return token == "REFRESH_SECRET"
        with self.assertRaises(GoogleTokenError):
            revoke_business_grant(grant=grant, actor=self.owner, revoke=revoke)
        self.assertEqual(seen, ["REFRESH_SECRET", "REPLACEMENT_SECRET"])
        grant.refresh_from_db()
        self.assertEqual((grant.state, grant.encrypted_extra_token), ("revocation_pending", ""))
        self.assertEqual(decrypt_business_refresh_token(grant.encrypted_refresh_token,
            organization_id=self.org.pk, project_id=self.project.pk), "REPLACEMENT_SECRET")
        grant = revoke_business_grant(grant=grant, actor=self.owner, revoke=lambda **_kwargs: True)
        self.assertEqual((grant.state, grant.encrypted_refresh_token, grant.encrypted_extra_token), ("revoked", "", ""))
        self.assertEqual(JobRun.objects.get().usage.actual_units, 1)

    def test_replacement_returned_after_emergency_app_disable_remains_revocable(self):
        from providers.google_app import revoke_google_oauth_application
        from .business_profile_oauth import revoke_business_grant
        grant = self.grant()
        def refresh(**_kwargs):
            revoke_google_oauth_application(actor=self.staff, key="business_profile")
            return GoogleTokens("ACCESS_SECRET", "REPLACEMENT_SECRET", timezone.now() + timedelta(hours=1))
        with self.assertRaises(BusinessRequestError):
            self.read(grant, refresh=refresh, collect=Mock(side_effect=AssertionError("revoked app must not collect")))
        grant.refresh_from_db()
        self.assertEqual(grant.state, "revocation_pending")
        self.assertTrue(grant.encrypted_extra_token)
        self.assertEqual(revoke_business_grant(grant=grant, actor=self.owner, revoke=lambda **_kwargs: True).state, "revoked")

    def test_unconfirmed_original_cannot_block_replacement_revoke_and_retry_sends_only_remaining_material(self):
        from .business_profile_oauth import revoke_business_grant
        from .google_tokens import GoogleTokenError
        grant = self.grant()
        with self.assertRaises(BusinessRequestError):
            self.read(grant, refresh=lambda **_kwargs: GoogleTokens(
                "ACCESS_SECRET", "REPLACEMENT_SECRET", timezone.now() + timedelta(hours=1)))
        seen = []
        def revoke(**kwargs):
            token = decrypt_business_refresh_token(kwargs["encrypted_refresh"], organization_id=self.org.pk, project_id=self.project.pk)
            seen.append(token)
            if token == "REFRESH_SECRET":
                raise GoogleTokenError("network_error")
            return True
        with self.assertRaises(GoogleTokenError):
            revoke_business_grant(grant=grant, actor=self.owner, revoke=revoke)
        self.assertEqual(seen, ["REFRESH_SECRET", "REPLACEMENT_SECRET"])
        grant.refresh_from_db()
        self.assertEqual((grant.state, grant.encrypted_extra_token), ("revocation_pending", ""))
        self.assertEqual(decrypt_business_refresh_token(grant.encrypted_refresh_token,
            organization_id=self.org.pk, project_id=self.project.pk), "REFRESH_SECRET")
        def confirm(**kwargs):
            seen.append(decrypt_business_refresh_token(kwargs["encrypted_refresh"], organization_id=self.org.pk, project_id=self.project.pk))
            return True
        self.assertEqual(revoke_business_grant(grant=grant, actor=self.owner, revoke=confirm).state, "revoked")
        self.assertEqual(seen, ["REFRESH_SECRET", "REPLACEMENT_SECRET", "REFRESH_SECRET"])

    def test_late_replacement_after_closure_and_confirmed_old_revoke_reopens_only_disabled_cleanup(self):
        from django.test import RequestFactory
        from tenancy.closure import close_organization_locally
        from tenancy.closure_grants import revoke_closed_business_grant
        from tenancy.deletion import delete_customer_database_records, prepare_customer_data_deletion
        from tenancy.models import OrganizationDeletionRun
        grant = self.grant()
        def refresh(**_kwargs):
            request = RequestFactory().post("/")
            request.user = self.owner
            with patch("tenancy.services.did_recently_authenticate", return_value=True):
                closed = close_organization_locally(organization=self.org, actor=self.owner, request=request)
            self.assertEqual(revoke_closed_business_grant(grant_id=grant.pk, revoke=lambda **_kwargs: True).state, "revoked")
            prepare_customer_data_deletion(organization=closed)
            return GoogleTokens("ACCESS_SECRET", "REPLACEMENT_SECRET", timezone.now() + timedelta(hours=1))
        with self.assertRaises(BusinessRequestError):
            self.read(grant, refresh=refresh, collect=Mock(side_effect=AssertionError("closed source must not deliver")))
        grant.refresh_from_db()
        self.assertEqual((grant.state, grant.revoked_at, grant.encrypted_extra_token), ("revocation_pending", None, ""))
        self.assertEqual(decrypt_business_refresh_token(grant.encrypted_refresh_token,
            organization_id=self.org.pk, project_id=self.project.pk), "REPLACEMENT_SECRET")
        run = OrganizationDeletionRun.objects.get(organization=self.org)
        OrganizationDeletionRun.objects.filter(pk=run.pk).update(state="storage_cleared")
        with self.assertRaisesMessage(ValidationError, "Confirm provider grant revocation"):
            delete_customer_database_records(run=run)
        self.assertEqual(revoke_closed_business_grant(grant_id=grant.pk, revoke=lambda **_kwargs: True).state, "revoked")


@override_settings(PROVIDER_ENCRYPTION_KEYS=(oauth_fixtures.KEY,))
class BusinessConcurrentReadTests(TransactionTestCase):
    setUp = oauth_fixtures.BusinessConsentTests.setUp
    review = oauth_fixtures.BusinessConsentTests.review
    begin = oauth_fixtures.BusinessConsentTests.begin
    complete = oauth_fixtures.BusinessConsentTests.complete

    def test_two_postgresql_connections_competing_for_client_slot_reserve_only_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        _, state = self.begin()
        grant = self.complete(state)
        barrier = Barrier(2)
        data = {"operation": "read", "grant_id": grant.pk, "grant_revision": 0, "policy_version": POLICY_VERSION, "accepted": True}
        def reserve(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return _begin(project=self.project, actor=self.owner, data=data, request_key=f"race-{index}").pk
                except BusinessRequestError as error:
                    return error.category
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(reserve, (1, 2)))
        self.assertEqual(sum(type(value) is int for value in outcomes), 1)
        self.assertIn("client_busy", outcomes)
        self.assertEqual(JobRun.objects.filter(handler="business_profile_request").count(), 1)
        self.assertEqual(UsageReservation.objects.get().reserved_units, 4)
