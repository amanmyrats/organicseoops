from datetime import timedelta
from decimal import Decimal
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from providers.models import AIModel, AIModelCapability, AIProvider, AIProviderAccount
from providers.services import configure_model, create_provider, create_provider_account
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_collection as collection
from . import competitor_synthesis_job as selection
from . import test_competitor_comparison as fixtures
from .models import UsageReservation, Artifact, JobCancellation, JobRun
from .services import _snapshot
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorSynthesisSelectionTests(TransactionTestCase):
    queue = fixtures.CompetitorComparisonTests.queue
    transport = fixtures.CompetitorComparisonTests.transport
    collected = fixtures.CompetitorComparisonTests.collected

    def setUp(self):
        fixtures.CompetitorComparisonTests.setUp(self)
        self.operator = get_user_model().objects.create_superuser("synthesis-operator@example.invalid", "test-password")
        self.provider = create_provider(actor=self.operator, key="synthesis-model", name="Configured provider", kind="openai", enabled=True)
        self.account = create_provider_account(actor=self.operator, provider=self.provider,
            label="Platform fixture", secret_reference="env:OPENAI_API_KEY")
        self.model = configure_model(actor=self.operator, provider=self.provider, identifier="selected-model", name="Selected model",
            capabilities=[AIModelCapability.TEXT_GENERATION, AIModelCapability.STRUCTURED_OUTPUT, AIModelCapability.REASONING],
            context_window=32768, max_output_tokens=2048, capability_source="https://provider.example.invalid/models",
            capabilities_verified_at=timezone.now(), enabled=True, input_price_usd_per_million=Decimal("0.1250"),
            output_price_usd_per_million=Decimal("2.5000"), pricing_source="https://provider.example.invalid/prices",
            pricing_verified_at=timezone.now(), access_tier="standard")

    def input_data(self, before, after, **changes):
        return {"previous_job_id": before.pk, "current_job_id": after.pk, "ai_processing_permission": True,
            "model_id": self.model.pk, "account_id": self.account.pk, "max_output_tokens": 512,
            "max_cost_usd": "0.010000", "allow_free": False, **changes}

    def select(self, before, after, **changes):
        return selection.selection_snapshot(self.project, self.admin, self.input_data(before, after, **changes))

    def test_genuine_source_compact_default_ascii_snapshot_full_hidden_microseconds_and_no_write_key_or_provider(self):
        before = self.collected("model-before", '<title>İlk</title><p>private-contact@example.invalid</p>'.encode())
        after = self.collected("model-after", '<title>İkinci</title><h2>New</h2>'.encode())
        with patch("providers.services.resolve_provider_secret", side_effect=AssertionError("No secret")), \
             patch("providers.adapters.create_response", side_effect=AssertionError("No provider")), \
             patch("socket.create_connection", side_effect=AssertionError("No egress")), CaptureQueriesContext(connection) as queries:
            model, account, config, source = self.select(before, after)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual((model.pk, account.pk), (self.model.pk, self.account.pk))
        self.assertEqual(config["source_selection_digest"], source["selection_digest"])
        self.assertEqual(_snapshot(config), config)
        self.assertLess(len(json.dumps(config).encode()), 4096)
        self.assertEqual(config["estimated_max_cost_usd"], "0.004480")
        for private in ("İlk", "İkinci", "private-contact", "secret_reference", "OPENAI_API_KEY", self.owner.email, "prompt\":"):
            self.assertNotIn(private, json.dumps(config))
        self.assertEqual(source["comparison"]["source_sha256"], before.config_snapshot["binding"]["source_sha256"])
        original_config = dict(config)
        artifact = before.artifacts.get()
        Artifact.objects.filter(pk=artifact.pk).update(created_at=artifact.created_at + timedelta(microseconds=1))
        changed = self.select(before, after)[2]
        self.assertEqual(changed["source_selection_digest"], original_config["source_selection_digest"])
        self.assertNotEqual(changed["source_metadata_sha256"], original_config["source_metadata_sha256"])
        self.assertEqual(changed["caller_source_sha256"], original_config["caller_source_sha256"])
        config["method"] = "changed"
        self.assertEqual(self.select(before, after)[2]["method"], selection.METHOD)

    def test_strict_input_rejects_before_source_read_and_cost_context_capabilities_and_free_policy_fail_closed(self):
        before = self.collected("strict-before"); after = self.collected("strict-after")
        invalid = ({"ai_processing_permission": 1}, {"allow_free": 1}, {"max_output_tokens": True}, {"max_output_tokens": 127},
            {"max_output_tokens": 2049}, {"model_id": True}, {"account_id": 2**53}, {"previous_job_id": str(before.pk)},
            {"current_job_id": before.pk}, {"max_cost_usd": "0"}, {"max_cost_usd": "NaN"}, {"extra": "untrusted"})
        with patch.object(selection.synthesis, "read_competitor_synthesis_source", side_effect=AssertionError("No invalid source read")):
            for changes in invalid:
                with self.subTest(changes=changes), self.assertRaises(ValidationError):
                    self.select(before, after, **changes)
        with self.assertRaises(ValidationError): self.select(before, after, max_cost_usd="0.000001")
        with self.assertRaises(ValidationError): self.select(before, after, allow_free=True)
        original = collection._row_pin(self.model)
        for changes in ({"context_window": None}, {"context_window": selection.INPUT_TOKEN_CEILING + 511},
            {"max_output_tokens": 256}, {"capabilities": ["text_generation", "structured_output"]},
            {"pricing_verified_at": None}, {"enabled": False}, {"capabilities_verified_at": timezone.now() + timedelta(days=1)}):
            AIModel.objects.filter(pk=self.model.pk).update(**changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError): self.select(before, after)
            AIModel.objects.filter(pk=self.model.pk).update(**{key: original[key] for key in changes})
        AIModel.objects.filter(pk=self.model.pk).update(access_tier="free", privacy_policy_url="https://provider.example.invalid/privacy")
        with self.assertRaises(ValidationError): self.select(before, after)
        self.assertEqual(self.select(before, after, allow_free=True)[2]["model_access_tier"], "free")
        AIModel.objects.filter(pk=self.model.pk).update(privacy_policy_url="")
        with self.assertRaises(ValidationError): self.select(before, after, allow_free=True)
        self.assertEqual(JobRun.objects.count(), 2)

    def test_foreign_scope_and_current_account_revocation_or_late_model_and_original_source_loss_withhold_selection(self):
        before = self.collected("late-model-before"); after = self.collected("late-model-after")
        with self.assertRaises(PermissionDenied):
            selection.selection_snapshot(self.project, self.foreign, self.input_data(before, after))
        account_fields = collection._row_pin(self.account)
        AIProviderAccount.objects.filter(pk=self.account.pk).update(state="revoked", revoked_at=timezone.now())
        with self.assertRaises(ValidationError): self.select(before, after)
        AIProviderAccount.objects.filter(pk=self.account.pk).update(state=account_fields["state"], revoked_at=account_fields["revoked_at"])
        digest = selection._digest
        for kind in ("model", "account", "caller", "configuration", "cancellation", "expiry"):
            def late_digest(value):
                result = digest(value)
                if type(value) is dict and "model" in value:
                    if kind == "model": AIModel.objects.filter(pk=self.model.pk).update(updated_at=self.model.updated_at + timedelta(microseconds=1))
                    if kind == "account": AIProviderAccount.objects.filter(pk=self.account.pk).update(rotated_at=timezone.now())
                    if kind == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                    if kind == "configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                    if kind == "cancellation": JobCancellation.objects.create(job=before, requested_by=self.owner)
                    if kind == "expiry":
                        now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(
                            started_at=now - timedelta(days=31), ends_at=now - timedelta(days=1))
                return result
            with self.subTest(kind=kind), patch.object(selection, "_digest", side_effect=late_digest), \
                 self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                self.select(before, after)
            AIModel.objects.filter(pk=self.model.pk).update(updated_at=self.model.updated_at)
            AIProviderAccount.objects.filter(pk=self.account.pk).update(rotated_at=account_fields["rotated_at"])
            OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="admin")
            ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=1)
            JobCancellation.objects.filter(job=before).delete()
            now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(
                started_at=now - timedelta(days=1), ends_at=now + timedelta(days=1))

    def test_priced_model_reload_drift_and_exact_context_floor_preserve_independent_caller_and_original_actor(self):
        before = self.collected("priced-before"); after = self.collected("priced-after")
        AIModel.objects.filter(pk=self.model.pk).update(context_window=selection.INPUT_TOKEN_CEILING + 512)
        admin_config = self.select(before, after)[2]
        owner_config = selection.selection_snapshot(self.project, self.owner, self.input_data(before, after))[2]
        self.assertEqual(admin_config["source_selection_digest"], owner_config["source_selection_digest"])
        self.assertEqual(admin_config["source_metadata_sha256"], owner_config["source_metadata_sha256"])
        self.assertNotEqual(admin_config["caller_source_sha256"], owner_config["caller_source_sha256"])
        priced_selection = selection._selection

        def priced_then_changed(*args, **kwargs):
            model, account = priced_selection(*args, **kwargs)
            AIModel.objects.filter(pk=model.pk).update(input_price_usd_per_million=Decimal("100.0000"))
            return model, account

        with patch.object(selection, "_selection", side_effect=priced_then_changed), self.assertRaises(PermissionDenied):
            self.select(before, after)

    def test_final_model_rows_return_fences_original_pair_and_independent_caller_authority(self):
        before = self.collected("final-selection-before"); after = self.collected("final-selection-after")
        expected = self.select(before, after)[2:]
        original = selection._model_rows
        for loss in ("actor", "caller", "caller-role", "revision", "approval-list", "first-cancel", "organization", "expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                now = [timezone.now()]
                ends = now[0] + timedelta(seconds=20)
                OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends - timedelta(days=30), ends_at=ends)
                def last_rows(model, account):
                    result = original(model, account)
                    if loss == "actor": OrganizationMembership.objects.filter(organization=self.organization, user=self.owner).update(role="viewer")
                    elif loss == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                    elif loss == "caller-role": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="owner")
                    elif loss == "revision": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                    elif loss == "approval-list": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[self.data["origin"]])
                    elif loss == "first-cancel": JobCancellation.objects.create(job=before, requested_by=self.owner)
                    elif loss == "organization": Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True)
                    else: now[0] = ends
                    return result
                with patch.object(selection, "_model_rows", side_effect=last_rows) as rows, patch("jobs.usage.timezone.now", side_effect=lambda: now[0]):
                    with self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)): self.select(before, after)
                    rows.assert_called_once()
                transaction.set_rollback(True)
        self.assertEqual(self.select(before, after)[2:], expected)

    def test_first_original_cancellation_during_last_second_source_read_withholds_model_selection(self):
        before = self.collected("selection-cancel-before"); after = self.collected("selection-cancel-after")
        source, rows = selection.collection._read_source, selection._model_rows
        completed, injected = [False], [False]
        def final_rows(*args, **kwargs):
            result = rows(*args, **kwargs); completed[0] = True; return result
        def final_source(job, *args, **kwargs):
            result = source(job, *args, **kwargs)
            if completed[0] and job.pk == after.pk and not injected[0]:
                JobCancellation.objects.create(job=before, requested_by=self.owner)
                injected[0] = True
            return result
        denied = False
        with patch.object(selection, "_model_rows", side_effect=final_rows), patch.object(selection.collection, "_read_source", side_effect=final_source):
            try: self.select(before, after)
            except PermissionDenied: denied = True
        self.assertTrue(injected[0])
        self.assertTrue(denied, "A model selection was returned after its first original source was cancelled during the final second read.")

    def test_last_model_pair_source_first_metadata_usage_both_cancels_and_model_provider_account_losses_withhold(self):
        before = self.collected("terminal-root-model-before"); after = self.collected("terminal-root-model-after")
        reader = selection._read_pair_sources; expected = self.select(before, after)[2:]
        for loss in ("artifact", "status", "usage", "first-cancel", "second-cancel", "model", "price", "provider", "account"):
            with self.subTest(loss=loss), transaction.atomic():
                calls = 0
                def last(*args):
                    nonlocal calls
                    result = reader(*args); calls += 1
                    if calls == 2:
                        if loss == "artifact": Artifact.objects.filter(job=before).update(size_bytes=1)
                        elif loss == "status": JobRun.objects.filter(pk=before.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=before).update(actual_units=2)
                        elif loss in ("first-cancel", "second-cancel"):
                            JobCancellation.objects.create(job=before if loss == "first-cancel" else after, requested_by=self.owner)
                        elif loss == "model": AIModel.objects.filter(pk=self.model.pk).update(enabled=False)
                        elif loss == "price": AIModel.objects.filter(pk=self.model.pk).update(input_price_usd_per_million=Decimal("100.0000"))
                        elif loss == "provider": AIProvider.objects.filter(pk=self.provider.pk).update(enabled=False)
                        else: AIProviderAccount.objects.filter(pk=self.account.pk).update(state="revoked", revoked_at=timezone.now())
                    return result
                with patch.object(selection, "_read_pair_sources", side_effect=last), self.assertRaises(PermissionDenied):
                    self.select(before, after)
                self.assertEqual(calls, 2)
                transaction.set_rollback(True)
        self.assertEqual(self.select(before, after)[2:], expected)
