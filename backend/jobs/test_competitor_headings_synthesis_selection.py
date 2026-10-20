from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from providers.models import AIModel, AIProviderAccount
from tenancy.models import OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_collection as collection, competitor_headings_synthesis as source
from . import competitor_synthesis_job as original, competitor_headings_synthesis_selection as selection
from . import test_competitor_synthesis_selection as model_fixtures, test_competitor_headings_comparison as heading_fixtures
from . import test_competitor_collection as root_fixtures
from .models import AIUsageRecord, Artifact, JobCancellation, JobRun
from .services import _snapshot
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorHeadingsSynthesisSelectionTests(TransactionTestCase):
    queue = heading_fixtures.CompetitorHeadingsComparisonTests.queue
    transport = heading_fixtures.CompetitorHeadingsComparisonTests.transport
    collected = heading_fixtures.CompetitorHeadingsComparisonTests.collected
    input_data = model_fixtures.CompetitorSynthesisSelectionTests.input_data

    def setUp(self):
        model_fixtures.CompetitorSynthesisSelectionTests.setUp(self)
        self.root_data = dict(self.data)
        self.data = {**self.data, "url": self.data["origin"] + "/selected/article"}

    def select(self, before, after, **changes):
        return selection.selection_snapshot(self.project, self.admin, self.input_data(before, after, **changes))

    def test_genuine_heading_source_compact_snapshot_exact_prompt_schema_metadata_no_write_key_provider_or_ai_attempt(self):
        before = self.collected("heading-model-before", '<h1>İlk</h1><p>private-contact@example.invalid</p>'.encode())
        after = self.collected("heading-model-after", '<h2>İkinci</h2><h2>İkinci</h2>'.encode())
        with patch("providers.services.resolve_provider_secret", side_effect=AssertionError("No secret")), \
             patch("providers.adapters.create_response", side_effect=AssertionError("No provider")), \
             patch("socket.create_connection", side_effect=AssertionError("No egress")), CaptureQueriesContext(connection) as queries:
            model, account, config, packet = self.select(before, after)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        self.assertEqual((model.pk, account.pk, config["method"], config["source_method"]), (self.model.pk, self.account.pk, selection.METHOD, source.METHOD))
        self.assertEqual(config["source_selection_digest"], packet["selection_digest"])
        self.assertEqual(config["prompt_sha256"], sha256(source.INSTRUCTIONS.encode()).hexdigest())
        self.assertEqual(config["output_schema_sha256"], sha256(collection._encode(source.OUTPUT_SCHEMA)).hexdigest())
        self.assertEqual(_snapshot(config), config); self.assertLess(len(json.dumps(config).encode()), 4096)
        self.assertEqual(config["estimated_max_cost_usd"], "0.004480")
        self.assertEqual(packet["comparison"]["source_sha256"], before.config_snapshot["binding"]["source_sha256"])
        for private in ("İlk", "İkinci", "private-contact", "secret_reference", "OPENAI_API_KEY", self.owner.email, '"prompt":'):
            self.assertNotIn(private, json.dumps(config))
        original_config = dict(config); artifact = before.artifacts.get()
        Artifact.objects.filter(pk=artifact.pk).update(created_at=artifact.created_at + timedelta(microseconds=1))
        changed = self.select(before, after)[2]
        self.assertEqual(changed["source_selection_digest"], original_config["source_selection_digest"])
        self.assertNotEqual(changed["source_metadata_sha256"], original_config["source_metadata_sha256"])
        self.assertEqual(changed["caller_source_sha256"], original_config["caller_source_sha256"])
        config["method"] = "changed"; self.assertEqual(self.select(before, after)[2]["method"], selection.METHOD)
        self.assertEqual(JobRun.objects.count(), 2); self.assertFalse(AIUsageRecord.objects.exists())

    def test_strict_input_before_heading_source_and_cost_capabilities_context_and_free_policy_fail_closed(self):
        before = self.collected("heading-strict-before"); after = self.collected("heading-strict-after")
        invalid = ({"ai_processing_permission": 1}, {"allow_free": 1}, {"max_output_tokens": True}, {"max_output_tokens": 127},
            {"max_output_tokens": 2049}, {"model_id": True}, {"account_id": 2**53}, {"previous_job_id": str(before.pk)},
            {"current_job_id": before.pk}, {"max_cost_usd": "0"}, {"max_cost_usd": "NaN"}, {"handler": "synthesize_competitor_pair"})
        with patch.object(source, "read_competitor_headings_synthesis_source", side_effect=AssertionError("No invalid source read")):
            for changes in invalid:
                with self.subTest(changes=changes), self.assertRaises(ValidationError): self.select(before, after, **changes)
        with self.assertRaises(ValidationError): self.select(before, after, max_cost_usd="0.000001")
        with self.assertRaises(ValidationError): self.select(before, after, allow_free=True)
        model_fields = collection._row_pin(self.model)
        for changes in ({"context_window": None}, {"context_window": original.INPUT_TOKEN_CEILING + 511},
            {"max_output_tokens": 256}, {"capabilities": ["text_generation", "structured_output"]},
            {"pricing_verified_at": None}, {"enabled": False}, {"capabilities_verified_at": timezone.now() + timedelta(days=1)}):
            AIModel.objects.filter(pk=self.model.pk).update(**changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError): self.select(before, after)
            AIModel.objects.filter(pk=self.model.pk).update(**{key: model_fields[key] for key in changes})
        AIModel.objects.filter(pk=self.model.pk).update(access_tier="free", privacy_policy_url="https://provider.example.invalid/privacy")
        with self.assertRaises(ValidationError): self.select(before, after)
        self.assertEqual(self.select(before, after, allow_free=True)[2]["model_access_tier"], "free")
        AIModel.objects.filter(pk=self.model.pk).update(privacy_policy_url="")
        with self.assertRaises(ValidationError): self.select(before, after, allow_free=True)
        self.assertFalse(AIUsageRecord.objects.exists())

    def test_foreign_current_account_and_late_model_source_caller_cancel_or_expiry_withhold_selection(self):
        before = self.collected("heading-late-model-before"); after = self.collected("heading-late-model-after")
        with self.assertRaises(PermissionDenied): selection.selection_snapshot(self.project, self.foreign, self.input_data(before, after))
        account_fields = collection._row_pin(self.account)
        AIProviderAccount.objects.filter(pk=self.account.pk).update(state="revoked", revoked_at=timezone.now())
        with self.assertRaises(ValidationError): self.select(before, after)
        AIProviderAccount.objects.filter(pk=self.account.pk).update(state=account_fields["state"], revoked_at=account_fields["revoked_at"])
        digest = original._digest
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
                        now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=31), ends_at=now + timedelta(days=-1))
                return result
            with self.subTest(kind=kind), patch.object(original, "_digest", side_effect=late_digest), self.assertRaises((PermissionDenied, ValidationError, UsageLimitError)):
                self.select(before, after)
            AIModel.objects.filter(pk=self.model.pk).update(updated_at=self.model.updated_at)
            AIProviderAccount.objects.filter(pk=self.account.pk).update(rotated_at=account_fields["rotated_at"])
            OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="admin")
            ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=1)
            JobCancellation.objects.filter(job=before).delete()
            now = timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=1), ends_at=now + timedelta(days=1))

    def test_exact_context_floor_priced_reload_drift_and_independent_reader_original_actor(self):
        before = self.collected("heading-priced-before"); after = self.collected("heading-priced-after")
        AIModel.objects.filter(pk=self.model.pk).update(context_window=original.INPUT_TOKEN_CEILING + 512)
        admin_config = self.select(before, after)[2]
        owner_config = selection.selection_snapshot(self.project, self.owner, self.input_data(before, after))[2]
        self.assertEqual(admin_config["source_selection_digest"], owner_config["source_selection_digest"])
        self.assertEqual(admin_config["source_metadata_sha256"], owner_config["source_metadata_sha256"])
        self.assertNotEqual(admin_config["caller_source_sha256"], owner_config["caller_source_sha256"])
        priced_selection = original._selection
        def priced_then_changed(*args, **kwargs):
            model, account = priced_selection(*args, **kwargs)
            AIModel.objects.filter(pk=model.pk).update(input_price_usd_per_million=Decimal("100.0000"))
            return model, account
        with patch.object(original, "_selection", side_effect=priced_then_changed), self.assertRaises(PermissionDenied): self.select(before, after)

    def test_actual_root_and_heading_sources_cannot_cross_fixed_model_families_and_unknowns_remain_null(self):
        before = self.collected("heading-family-before"); after = self.collected("heading-family-after")
        with patch.object(original, "_selection", side_effect=AssertionError("No wrong-family price selection")), self.assertRaises(PermissionDenied):
            original.selection_snapshot(self.project, self.admin, self.input_data(before, after))
        roots = []
        for key in ("heading-model-actual-root-before", "heading-model-actual-root-after"):
            root = collection.queue_competitor_collection(project=self.project, actor=self.owner, data=self.root_data, idempotency_key=key)
            with patch("socket.create_connection", side_effect=AssertionError("No actual egress")):
                self.assertTrue(collection.execute_competitor_collection(root.pk, fetcher=root_fixtures.CompetitorCollectionTests.fetcher(self)))
            roots.append(root)
        with patch.object(original, "_selection", side_effect=AssertionError("No wrong-family price selection")), self.assertRaises(PermissionDenied): self.select(*roots)
        for index, body in enumerate((b"<template>Unclosed", b"<h1>" + b"x" * 81 + b"</h1>")):
            unknown = self.collected("heading-model-unknown-" + str(index), body)
            config, packet = self.select(before, unknown)[2:]
            self.assertEqual(config["source_method"], source.METHOD)
            self.assertFalse(packet["comparison"]["comparable"])
            self.assertIsNone(packet["comparison"]["headings_changed"]); self.assertIsNone(packet["comparison"]["count_deltas"])
        self.assertFalse(AIUsageRecord.objects.exists())

    test_final_model_rows_return_fences_original_pair_and_independent_caller_authority = model_fixtures.CompetitorSynthesisSelectionTests.test_final_model_rows_return_fences_original_pair_and_independent_caller_authority
    test_first_original_cancellation_during_last_second_source_read_withholds_model_selection = model_fixtures.CompetitorSynthesisSelectionTests.test_first_original_cancellation_during_last_second_source_read_withholds_model_selection
