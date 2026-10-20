import copy
import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.mfa.models import Authenticator
from django.contrib.auth import HASH_SESSION_KEY, get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import staff_cancellation_investigation as staff, test_paddle_cancellation as fixtures
from .models import AuditEvent, AuditEventType, Organization, OrganizationBillingCancellation
from .paddle_cancellation import execute_billing_cancellation, prepare_billing_cancellation, reconcile_billing_cancellation
from .paddle_transport import PaddleTransportError
from .test_paddle_seller import SANDBOX_KEY
from .test_trial_corrections import staff_trial_request


@override_settings(PADDLE_ENVIRONMENT="sandbox")
class StaffCancellationInvestigationTests(TestCase):
    _close_fixture = fixtures.ClosureBillingCancellationTests._close_fixture
    _observed = fixtures.ClosureBillingCancellationTests._observed

    def setUp(self):
        fixtures.ClosureBillingCancellationTests.setUp(self)
        self.inspector = get_user_model().objects.create_user("cancel-inspector@example.invalid", "fixture-password", is_staff=True)
        self.permissions = Permission.objects.filter(content_type__app_label="tenancy", codename__in=["view_organization", "view_organizationbillingcancellation"])
        self.inspector.user_permissions.add(*self.permissions)
        self.request = staff_trial_request(self.inspector)
        with patch("tenancy.paddle_cancellation.paddle_seller_secrets", return_value=(SANDBOX_KEY, "unused")):
            self.cancellation = prepare_billing_cancellation(organization=self.organization, actor=self.owner)

    def inspect(self, **changes):
        return staff.inspect_staff_cancellation(**{**dict(request=self.request, organization_id=self.organization.pk,
            cancellation_id=self.cancellation.pk, reason="investigation"), **changes})

    def events(self):
        return AuditEvent.objects.filter(event_type=AuditEventType.STAFF_CANCELLATION_INSPECTED)

    def test_genuine_reserved_sending_unknown_get_confirmed_provider_date_before_attempt_no_replay(self):
        self.assertEqual((len(self.inspect()["cancellation"]), self.inspect()["cancellation"]["state"]), (7, "reserved"))
        self._close_fixture()
        def timeout(**_):
            self.assertEqual(self.inspect()["cancellation"]["state"], "sending")
            raise PaddleTransportError("timeout")
        with patch("tenancy.paddle_cancellation.paddle_seller_secrets", return_value=(SANDBOX_KEY, "unused")):
            unknown = execute_billing_cancellation(self.cancellation, cancel=timeout)
            self.assertEqual(self.inspect()["cancellation"]["error_category"], "timeout")
            response = self._observed(); provider_date = self.cancellation.created_at - timedelta(days=2)
            response["data"]["canceled_at"] = provider_date.isoformat()
            confirmed = reconcile_billing_cancellation(unknown, subscription_get=lambda **_: response)
            self.assertEqual(confirmed.state, "confirmed")
            execute_billing_cancellation(confirmed, cancel=lambda **_: self.fail("no rePOST"))
            reconcile_billing_cancellation(confirmed, subscription_get=lambda **_: self.fail("no second GET"))
        result = self.inspect()["cancellation"]
        self.assertEqual(result["confirmed_at"], provider_date.isoformat())
        self.assertLess(result["confirmed_at"], result["created_at"])
        self.subscription.refresh_from_db(); self.assertEqual(self.subscription.status, "active")
        self.assertEqual(set(self.events().first().details), {"cancellation_id", "reason", "state"})

    def test_scalar_privacy_audit_only_retained_closed_old_other_environment_unknown_category(self):
        self._close_fixture()
        old = timezone.now() - timedelta(days=500)
        OrganizationBillingCancellation.objects.filter(pk=self.cancellation.pk).update(state="unknown", created_at=old,
            attempted_at=old + timedelta(seconds=1), error_category="private future provider category")
        with override_settings(PADDLE_ENVIRONMENT="live"), CaptureQueriesContext(connection) as queries, \
                patch("socket.create_connection", side_effect=AssertionError("network")), \
                patch("django.core.mail.send_mail", side_effect=AssertionError("SMTP")), \
                patch("tenancy.billing_state.paid_access_state", side_effect=AssertionError("effective paid")):
            result = self.inspect()
        self.assertEqual(result["cancellation"]["error_category"], "unclassified_failure")
        for private in (self.cancellation.customer_id, self.cancellation.provider_subscription_id, self.owner.email,
                self.organization.name, "private future provider category", "actor_id", "subscription_id", "closed_at"):
            self.assertNotIn(private, json.dumps(result)); self.assertNotIn(private, json.dumps(self.events().get().details))
        for query in queries:
            self.assertFalse(any(table in query["sql"] for table in ("paddlewebhookreceipt", "paddlecheckout", '"tenancy_paddlesubscription"', "organizationdeletionrun", "jobs_", "account_emailaddress")))
            if 'FROM "accounts_user"' in query["sql"]: self.assertIn(f'"accounts_user"."id" = {self.inspector.pk}', query["sql"])
        writes = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertEqual(len(writes), 1); self.assertIn("tenancy_auditevent", writes[0])

    def test_exact_inputs_current_pair_mfa_hash_and_full_hidden_source_session_rollback(self):
        for changes, error in (({"organization_id": self.organization.pk + 99999}, PermissionDenied),
                ({"cancellation_id": self.cancellation.pk + 99999}, PermissionDenied), ({"cancellation_id": True}, ValidationError),
                ({"cancellation_id": 2**53}, ValidationError), ({"reason": "private prose"}, ValidationError)):
            with self.assertRaises(error): self.inspect(**changes)
        for permission in self.permissions:
            self.inspector.user_permissions.remove(permission)
            with patch.object(staff, "_source", side_effect=AssertionError("source before authority")), self.assertRaises(PermissionDenied): self.inspect()
            self.inspector.user_permissions.add(permission)
        session_key = self.request.session.session_key
        for key, value in ((HASH_SESSION_KEY, "invalid"), (AUTHENTICATION_METHODS_SESSION_KEY, [{"method": "password"}])):
            with transaction.atomic():
                self.request.session[key] = value; self.request.session.save()
                with self.assertRaises(PermissionDenied): self.inspect()
                transaction.set_rollback(True)
            self.request.session = type(self.request.session)(session_key=session_key)
        create = AuditEvent.objects.create
        mutations = [(lambda key=key, value=value: OrganizationBillingCancellation.objects.filter(pk=self.cancellation.pk).update(**{key: value}), ValidationError)
            for key, value in (("customer_id", "ctm_" + "z" * 26), ("provider_subscription_id", "sub_" + "z" * 26),
                ("actor_id", self.inspector.pk), ("environment", "live"),
                ("created_at", self.cancellation.created_at - timedelta(microseconds=1)),
                ("error_category", "private marker"))]
        mutations += [(lambda: OrganizationBillingCancellation.objects.filter(pk=self.cancellation.pk).update(state="sending", attempted_at=timezone.now()), ValidationError)]
        mutations += [(lambda: Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True), ValidationError),
            (lambda: self.inspector.user_permissions.clear(), PermissionDenied),
            (lambda: Authenticator.objects.filter(user=self.inspector).delete(), PermissionDenied),
            (lambda: Session.objects.filter(session_key=session_key).delete(), PermissionDenied),
            (lambda: get_user_model().objects.filter(pk=self.inspector.pk).update(session_version="invalid"), PermissionDenied)]
        original = staff._source(self.organization.pk, self.cancellation.pk)
        for mutate, error in mutations:
            def changed(**kwargs):
                event = create(**kwargs); mutate(); return event
            with patch.object(staff.AuditEvent.objects, "create", side_effect=changed), self.assertRaises(error): self.inspect()
            self.assertFalse(self.events().exists()); self.assertEqual(staff._source(self.organization.pk, self.cancellation.pk), original)
            self.request.session = type(self.request.session)(session_key=session_key)
        with patch.object(staff.AuditEvent.objects, "create", side_effect=RuntimeError("audit unavailable")), self.assertRaises(RuntimeError): self.inspect()
        record = staff._record
        def changed(source, assessed):
            result = record(source, assessed)
            OrganizationBillingCancellation.objects.filter(pk=self.cancellation.pk).update(actor_id=self.inspector.pk)
            return result
        with patch.object(staff, "_record", side_effect=changed), self.assertRaises(ValidationError): self.inspect()
        self.assertFalse(self.events().exists())

    def test_state_date_shapes_provider_date_not_local_confirmation_and_unknown_not_zero(self):
        source = staff._source(self.organization.pk, self.cancellation.pk); assessed = timezone.now()
        for key, value in (("state", "invalid"), ("environment", "invalid"), ("customer_id", "private"),
                ("actor_id", True), ("created_at", assessed + timedelta(microseconds=1)),
                ("attempted_at", assessed), ("confirmed_at", assessed), ("error_category", "x" * 33)):
            invalid = copy.deepcopy(source); invalid["cancellation"][key] = value
            with self.subTest(field=key), self.assertRaises(ValidationError): staff._record(invalid, assessed)
        unknown = copy.deepcopy(source)
        unknown["cancellation"].update(state="unknown", attempted_at=assessed)
        self.assertEqual(staff._record(unknown, assessed)["error_category"], "unclassified_failure")
        for key, value in (("attempted_at", source["cancellation"]["created_at"] - timedelta(microseconds=1)),
                ("attempted_at", assessed.replace(tzinfo=None)), ("confirmed_at", assessed)):
            invalid = copy.deepcopy(unknown); invalid["cancellation"][key] = value
            with self.assertRaises(ValidationError): staff._record(invalid, assessed)
        confirmed = copy.deepcopy(unknown)
        confirmed["cancellation"].update(state="confirmed", confirmed_at=source["cancellation"]["created_at"] - timedelta(days=2))
        self.assertIsNone(staff._record(confirmed, assessed)["error_category"])
