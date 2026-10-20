from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.observability import redact
from .customer_inventory import GLOBAL, require_complete_ownership_map
from .models import PublicAnalyticsConsentEpoch, PublicAnalyticsObservation
from .public_analytics import (issue_public_analytics_epoch, purge_expired_public_analytics_epochs,
                               record_public_observation, withdraw_public_analytics_epoch)
from .public_analytics_policy import parse_public_analytics_policy
from .public_analytics_source import CONSENT_VERSION
from .test_public_analytics_policy import policy
from .test_public_analytics_source import candidate

CONTENT = json.dumps(policy()).encode()
PIN = parse_public_analytics_policy(CONTENT)[1]
CONFIG = {"PUBLIC_ANALYTICS_ENABLED": True, "PUBLIC_ANALYTICS_POLICY_SHA256": PIN,
          "FRONTEND_ORIGIN": "https://product.example.invalid"}


def configure_policy(test):
    directory = TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    test.policy_path = Path(directory.name) / "policy.json"
    test.policy_path.write_bytes(CONTENT)
    configuration = override_settings(PUBLIC_ANALYTICS_POLICY_FILE=str(test.policy_path))
    configuration.enable()
    test.addCleanup(configuration.disable)


@override_settings(**CONFIG)
class PublicAnalyticsKernelTests(TestCase):
    def setUp(self):
        configure_policy(self)

    def issue(self):
        return issue_public_analytics_epoch(allowed=True, consent_version=CONSENT_VERSION)

    def record(self, grant, value=None):
        return record_public_observation(receipt_proof=grant["receipt_proof"], candidate=candidate() if value is None else value)

    def test_real_explicit_epoch_original_server_receipt_dedupe_minimization_and_global_ownership(self):
        grant = self.issue(); epoch = PublicAnalyticsConsentEpoch.objects.get()
        self.assertEqual(epoch.proof_digest, sha256(grant["receipt_proof"].encode()).hexdigest())
        self.assertEqual(epoch.expires_at - epoch.created_at, timedelta(minutes=15))
        first = self.record(grant); second = self.record(grant)
        self.assertEqual(first, second); self.assertEqual(PublicAnalyticsObservation.objects.count(), 1)
        cta = {**candidate(), "event_id": "public_cta_selected", "cta_id": "public_trial_cta"}
        self.record(grant, cta); self.record(grant, cta)
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 2)
        newer = self.issue(); self.record(newer)
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 3)
        self.assertNotRegex(json.dumps(first), "epoch|proof|policy|origin|path|account|organization|visitor|customer")
        self.assertNotIn(grant["receipt_proof"], redact(json.dumps(grant)))
        require_complete_ownership_map()
        for model in (PublicAnalyticsConsentEpoch, PublicAnalyticsObservation):
            self.assertIn(model._meta.label, GLOBAL)
            self.assertFalse(any(field.name in {"user", "actor", "organization", "project", "ip", "user_agent", "url", "referrer"} for field in model._meta.fields))
            self.assertNotIn("proof_digest", admin.site._registry[model].fields)
        observation = PublicAnalyticsObservation.objects.first()
        observation.route_id = "OTHER"
        with self.assertRaises(ValidationError): observation.save()
        with self.assertRaises(ValidationError):
            PublicAnalyticsConsentEpoch(pk=epoch.pk, proof_digest=epoch.proof_digest, policy_digest=PIN,
                created_at=epoch.created_at, expires_at=epoch.expires_at + timedelta(minutes=15)).save()

    def test_false_malformed_missing_stale_policy_proof_scope_and_extra_properties_fail_without_records(self):
        for value in [False, None, 1, "true"]:
            with self.assertRaises(ValidationError): issue_public_analytics_epoch(allowed=value, consent_version=CONSENT_VERSION)
        with self.assertRaises(ValidationError): issue_public_analytics_epoch(allowed=True, consent_version="old")
        with override_settings(PUBLIC_ANALYTICS_POLICY_FILE=""), self.assertRaises(ValidationError): self.issue()
        self.assertEqual(PublicAnalyticsConsentEpoch.objects.count(), 0)
        grant = self.issue()
        for proof in [None, True, "", "x" * 43, grant["receipt_proof"] + "extra"]:
            with self.assertRaises(ValidationError): record_public_observation(receipt_proof=proof, candidate=candidate())
        for value in [{}, {**candidate(), "route_id": "OTHER"}, {**candidate(), "customer_export": "private"},
                      {**candidate(), "consent_state": "denied"}]:
            with self.assertRaises(ValidationError): self.record(grant, value)
        with override_settings(PUBLIC_ANALYTICS_POLICY_SHA256="f" * 64), self.assertRaises(ValidationError): self.record(grant)
        changed = policy(); changed["routes"][0]["html_sha256"] = "c" * 64
        content = json.dumps(changed).encode(); pin = parse_public_analytics_policy(content)[1]
        self.policy_path.write_bytes(content)
        with override_settings(PUBLIC_ANALYTICS_POLICY_SHA256=pin):
            with self.assertRaises(ValidationError): self.record(grant)
            replacement = self.issue()
            self.assertEqual(self.record(replacement)["state"], "recorded")
            withdraw_public_analytics_epoch(receipt_proof=replacement["receipt_proof"])
        self.policy_path.write_bytes(CONTENT)
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 0)

    def test_withdrawal_erases_only_its_epoch_without_current_policy_and_replay_or_renewal(self):
        grant, other = self.issue(), self.issue(); self.record(grant); self.record(other)
        with override_settings(PUBLIC_ANALYTICS_POLICY_FILE=""):
            withdraw_public_analytics_epoch(receipt_proof=grant["receipt_proof"])
        epoch = PublicAnalyticsConsentEpoch.objects.get(proof_digest=sha256(grant["receipt_proof"].encode()).hexdigest())
        original = epoch.revoked_at
        withdraw_public_analytics_epoch(receipt_proof=grant["receipt_proof"]); epoch.refresh_from_db()
        self.assertEqual(epoch.revoked_at, original)
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 1)
        with self.assertRaises(ValidationError): self.record(grant)
        self.assertEqual(self.record(other)["state"], "recorded")

    def test_original_expiry_purge_bounds_and_insert_or_final_policy_loss_roll_back(self):
        grant = self.issue(); self.record(grant); epoch = PublicAnalyticsConsentEpoch.objects.get()
        with patch("tenancy.public_analytics.timezone.now", return_value=epoch.expires_at):
            with self.assertRaises(ValidationError): self.record(grant)
            self.assertEqual(purge_expired_public_analytics_epochs(limit=1), 1)
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 0)
        self.assertEqual(withdraw_public_analytics_epoch(receipt_proof=grant["receipt_proof"])["state"], "withdrawn")
        for limit in [False, 0, 1001, "1"]:
            with self.assertRaises(ValidationError): purge_expired_public_analytics_epochs(limit=limit)
        with patch("tenancy.public_analytics._current_policy", side_effect=[(CONTENT, PIN), ValidationError("Fixture policy loss")]):
            with self.assertRaises(ValidationError): self.issue()
        self.assertEqual(PublicAnalyticsConsentEpoch.objects.count(), 0)
        fresh = self.issue()
        with patch("tenancy.models.PublicAnalyticsObservation.save", side_effect=RuntimeError("Fixture insert crash")):
            with self.assertRaises(RuntimeError): self.record(fresh)
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 0)
        with patch("tenancy.public_analytics._current_policy", side_effect=[(CONTENT, PIN), ValidationError("Fixture policy loss")]):
            with self.assertRaises(ValidationError): self.record(fresh)
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 0)
        self.assertEqual(self.record(fresh)["state"], "recorded")

    def test_expiry_crossing_after_actual_insert_rolls_back_without_backdated_receipt(self):
        grant = self.issue(); epoch = PublicAnalyticsConsentEpoch.objects.get()
        before = epoch.expires_at - timedelta(seconds=1)
        original = PublicAnalyticsObservation.save
        clock = patch("tenancy.public_analytics.timezone.now", return_value=before)
        with clock as now:
            def cross_deadline(observation, *args, **kwargs):
                result = original(observation, *args, **kwargs)
                now.return_value = epoch.expires_at
                return result
            with patch.object(PublicAnalyticsObservation, "save", cross_deadline):
                with self.assertRaises(ValidationError): self.record(grant)
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 0)


@override_settings(**CONFIG)
class PublicAnalyticsRaceTests(TransactionTestCase):
    def setUp(self):
        configure_policy(self)

    def test_actual_postgresql_duplicate_and_withdrawal_receipt_races_have_no_replayed_or_remaining_event(self):
        self.assertEqual(connection.vendor, "postgresql")
        grant = issue_public_analytics_epoch(allowed=True, consent_version=CONSENT_VERSION)
        barrier = Barrier(2)
        def act(withdraw=False):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                if withdraw:
                    return withdraw_public_analytics_epoch(receipt_proof=grant["receipt_proof"])
                try:
                    return record_public_observation(receipt_proof=grant["receipt_proof"], candidate=candidate())
                except ValidationError:
                    return {"state": "denied"}
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(act, [False, False]))
        self.assertEqual(outcomes[0], outcomes[1]); self.assertEqual(PublicAnalyticsObservation.objects.count(), 1)
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(act, [False, True]))
        self.assertEqual(PublicAnalyticsObservation.objects.count(), 0)
        self.assertIsNotNone(PublicAnalyticsConsentEpoch.objects.get().revoked_at)
