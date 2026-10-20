from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from providers.models import AIModel, AIProvider, AIProviderAccount
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_collection as collection, competitor_topics_source as source, competitor_topics_selection as selection
from . import competitor_synthesis_job as original, competitor_headings_synthesis_selection as paired
from . import test_competitor_headings_synthesis_selection as fixtures
from .models import AIUsageRecord, Artifact, JobCancellation, JobRun, UsageReservation
from .services import _snapshot
from .usage import UsageLimitError


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorTopicsSelectionTests(TransactionTestCase):
    setUp = fixtures.CompetitorHeadingsSynthesisSelectionTests.setUp
    queue = fixtures.CompetitorHeadingsSynthesisSelectionTests.queue
    transport = fixtures.CompetitorHeadingsSynthesisSelectionTests.transport
    collected = fixtures.CompetitorHeadingsSynthesisSelectionTests.collected

    def input_data(self, job, **changes):
        return {"job_id":job.pk, "ai_processing_permission":True, "model_id":self.model.pk,
            "account_id":self.account.pk, "max_output_tokens":512, "max_cost_usd":"0.010000", "allow_free":False, **changes}

    def select(self, job, **changes):
        return selection.selection_snapshot(self.project, self.admin, self.input_data(job, **changes))

    def test_one_genuine_source_compact_hashed_configuration_no_writes_keys_provider_or_reservation(self):
        job = self.collected("topic-model", '<h1>İlk topic</h1><p>private-contact@example.invalid</p>'.encode())
        reservations = list(UsageReservation.objects.values())
        connection.queries_log.clear()
        with (patch("providers.services.resolve_provider_secret", side_effect=AssertionError("No key")),
            patch("providers.adapters.create_response", side_effect=AssertionError("No provider")),
            patch("socket.getaddrinfo", side_effect=AssertionError("No DNS")),
            patch("socket.create_connection", side_effect=AssertionError("No egress")), CaptureQueriesContext(connection) as queries):
            model, account, config, packet = self.select(job)
        self.assertGreater(len(queries),0); self.assertLess(len(queries),connection.queries_log.maxlen)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT","UPDATE","DELETE")) for row in queries))
        self.assertEqual((model.pk, account.pk, config["method"], config["source_method"]),
            (self.model.pk,self.account.pk,selection.METHOD,source.METHOD))
        self.assertEqual(config["source_selection_digest"],packet["selection_digest"])
        self.assertEqual(config["prompt_sha256"],sha256(source.INSTRUCTIONS.encode()).hexdigest())
        self.assertEqual(config["output_schema_sha256"],sha256(collection._encode(source.OUTPUT_SCHEMA)).hexdigest())
        self.assertEqual(config["estimated_max_cost_usd"],"0.004480")
        self.assertEqual(_snapshot(config),config); self.assertLess(len(json.dumps(config).encode()),4096)
        for private in ("İlk topic", "private-contact", "secret_reference", "OPENAI_API_KEY", self.owner.email, '"prompt":'):
            self.assertNotIn(private,json.dumps(config))
        self.assertEqual(JobRun.objects.count(),1); self.assertFalse(AIUsageRecord.objects.exists())
        self.assertEqual(list(UsageReservation.objects.values()),reservations)
        owner_config = selection.selection_snapshot(self.project,self.owner,self.input_data(job))[2]
        self.assertEqual(config["source_selection_digest"],owner_config["source_selection_digest"])
        self.assertEqual(config["source_metadata_sha256"],owner_config["source_metadata_sha256"])
        self.assertNotEqual(config["caller_source_sha256"],owner_config["caller_source_sha256"])
        artifact = job.artifacts.get(); Artifact.objects.filter(pk=artifact.pk).update(created_at=artifact.created_at+timedelta(microseconds=1))
        self.assertNotEqual(self.select(job)[2]["source_metadata_sha256"],config["source_metadata_sha256"])
        packet["observation"]["collection"]["evidence"]["headings"][0]["text"] = "Changed"
        self.assertEqual(self.select(job)[3]["observation"]["collection"]["evidence"]["headings"][0]["text"],"İlk topic")

    def test_exact_single_input_and_fixed_family_before_source_or_model_selection(self):
        job = self.collected("topic-command")
        invalid = ({"ai_processing_permission":1},{"allow_free":1},{"max_output_tokens":True},{"max_output_tokens":127},
            {"max_output_tokens":2049},{"job_id":True},{"job_id":str(job.pk)},{"job_id":2**53},
            {"model_id":True},{"account_id":0},{"max_cost_usd":"NaN"},{"max_cost_usd":"0"},
            {"previous_job_id":job.pk},{"current_job_id":job.pk},{"handler":"synthesize_competitor_pair"})
        with patch.object(source,"read_competitor_topics_source",side_effect=AssertionError("No invalid source")):
            for changes in invalid:
                with self.subTest(changes=changes), self.assertRaises(ValidationError): self.select(job,**changes)
            with self.assertRaises(ValidationError): selection.selection_snapshot(self.project,self.admin,{"job_id":job.pk})
        pair = {**self.input_data(job),"previous_job_id":job.pk,"current_job_id":job.pk+1}
        pair.pop("job_id")
        with self.assertRaises(ValidationError): selection.selection_snapshot(self.project,self.admin,pair)
        for wrapper in (original,paired):
            with self.assertRaises(ValidationError): wrapper.selection_snapshot(self.project,self.admin,self.input_data(job))
        with transaction.atomic():
            wrong = collection.queue_competitor_collection(project=self.project,actor=self.owner,data=self.root_data,idempotency_key="topic-root")
            with patch.object(original,"_selection",side_effect=AssertionError("No wrong-family model")), self.assertRaises(PermissionDenied): self.select(wrong)
            transaction.set_rollback(True)
        with self.assertRaises(PermissionDenied): selection.selection_snapshot(self.project,self.foreign,self.input_data(job))
        unknown = self.collected("topic-uncitable",b"<h1>"+b"x"*81+b"</h1>")
        with patch.object(original,"_selection",side_effect=AssertionError("No uncitable model")), self.assertRaises(ValidationError): self.select(unknown)

    def test_current_capabilities_price_context_output_free_policy_and_account_scope(self):
        job = self.collected("topic-policy")
        with self.assertRaises(ValidationError): self.select(job,max_cost_usd="0.000001")
        fields = collection._row_pin(self.model)
        for changes in ({"context_window":None},{"context_window":original.INPUT_TOKEN_CEILING+511},
            {"max_output_tokens":256},{"capabilities":["text_generation","structured_output"]},
            {"pricing_verified_at":None},{"enabled":False},{"capabilities_verified_at":timezone.now()+timedelta(days=1)}):
            with self.subTest(changes=changes), transaction.atomic():
                AIModel.objects.filter(pk=self.model.pk).update(**changes)
                with self.assertRaises(ValidationError): self.select(job)
                transaction.set_rollback(True)
        AIModel.objects.filter(pk=self.model.pk).update(context_window=original.INPUT_TOKEN_CEILING+512)
        self.select(job)
        with self.assertRaises(ValidationError): self.select(job,allow_free=True)
        AIModel.objects.filter(pk=self.model.pk).update(access_tier="free",privacy_policy_url="https://provider.example.invalid/privacy")
        with self.assertRaises(ValidationError): self.select(job)
        self.assertEqual(self.select(job,allow_free=True)[2]["model_access_tier"],"free")
        AIModel.objects.filter(pk=self.model.pk).update(privacy_policy_url="")
        with self.assertRaises(ValidationError): self.select(job,allow_free=True)
        AIModel.objects.filter(pk=self.model.pk).update(**{key:fields[key] for key in ("access_tier","privacy_policy_url","context_window")})
        foreign_org = Organization.objects.create(name="Foreign topic fixture")
        with transaction.atomic():
            AIProviderAccount.objects.filter(pk=self.account.pk).update(organization_id=self.organization.pk,secret_reference="")
            self.assertEqual(self.select(job)[1].organization_id,self.organization.pk)
            transaction.set_rollback(True)
        for changes in ({"organization_id":foreign_org.pk,"secret_reference":""},{"state":"revoked","revoked_at":timezone.now()}):
            with self.subTest(changes=changes), transaction.atomic():
                AIProviderAccount.objects.filter(pk=self.account.pk).update(**changes)
                with self.assertRaises(ValidationError): self.select(job)
                transaction.set_rollback(True)
        priced = original._selection
        def drift(*args,**kwargs):
            model,account = priced(*args,**kwargs)
            AIModel.objects.filter(pk=model.pk).update(input_price_usd_per_million=Decimal("100.0000"))
            return model,account
        with patch.object(original,"_selection",side_effect=drift), self.assertRaises(PermissionDenied): self.select(job)

    def test_late_model_account_metadata_and_original_authority_withhold_selection(self):
        job = self.collected("topic-late")
        digest = original._digest
        for loss in ("model","account","artifact","actor","caller","revision","cancel","organization","expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                def late(value):
                    result = digest(value)
                    if type(value) is dict and "model" in value:
                        if loss == "model": AIModel.objects.filter(pk=self.model.pk).update(updated_at=timezone.now())
                        elif loss == "account": AIProviderAccount.objects.filter(pk=self.account.pk).update(rotated_at=timezone.now())
                        elif loss == "artifact": Artifact.objects.filter(job=job).update(size_bytes=1)
                        elif loss == "actor": OrganizationMembership.objects.filter(organization=self.organization,user=self.owner).update(role="viewer")
                        elif loss == "caller": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                        elif loss == "revision": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                        elif loss == "cancel": JobCancellation.objects.create(job=job,requested_by=self.owner)
                        elif loss == "organization": Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True)
                        else:
                            now=timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31),ends_at=now-timedelta(seconds=1))
                    return result
                with patch.object(original,"_digest",side_effect=late), self.assertRaises((PermissionDenied,ValidationError,UsageLimitError)): self.select(job)
                transaction.set_rollback(True)

    def test_final_model_row_return_rechecks_single_original_actor_caller_cancel_and_commercial(self):
        job = self.collected("topic-final"); rows = original._model_rows
        for loss in ("actor","caller-role","revision","cancel","organization","expiry"):
            with self.subTest(loss=loss), transaction.atomic():
                now=[timezone.now()]; ends=now[0]+timedelta(seconds=20)
                OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends-timedelta(days=30),ends_at=ends)
                def last(model,account):
                    result=rows(model,account)
                    if loss == "actor": OrganizationMembership.objects.filter(organization=self.organization,user=self.owner).update(role="viewer")
                    elif loss == "caller-role": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="owner")
                    elif loss == "revision": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                    elif loss == "cancel": JobCancellation.objects.create(job=job,requested_by=self.owner)
                    elif loss == "organization": Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True)
                    else: now[0]=ends
                    return result
                with patch.object(original,"_model_rows",side_effect=last) as read, patch("jobs.usage.timezone.now",side_effect=lambda:now[0]):
                    with self.assertRaises((PermissionDenied,ValidationError,UsageLimitError)): self.select(job)
                    read.assert_called_once()
                transaction.set_rollback(True)

    def test_last_model_source_original_metadata_usage_cancel_and_model_provider_account_losses_withhold_selection(self):
        job = self.collected("terminal-topic-model"); reader = original._read_pair_sources
        expected = self.select(job)[2:]
        for loss in ("artifact", "status", "usage", "cancel", "model", "price", "provider", "account"):
            with self.subTest(loss=loss), transaction.atomic():
                calls = 0
                def last(*args):
                    nonlocal calls
                    result = reader(*args); calls += 1
                    if calls == 1:
                        if loss == "artifact": Artifact.objects.filter(job=job).update(size_bytes=1)
                        elif loss == "status": JobRun.objects.filter(pk=job.pk).update(status="failed")
                        elif loss == "usage": UsageReservation.objects.filter(job=job).update(actual_units=2)
                        elif loss == "cancel": JobCancellation.objects.create(job=job, requested_by=self.owner)
                        elif loss == "model": AIModel.objects.filter(pk=self.model.pk).update(enabled=False)
                        elif loss == "price": AIModel.objects.filter(pk=self.model.pk).update(input_price_usd_per_million=Decimal("100.0000"))
                        elif loss == "provider": AIProvider.objects.filter(pk=self.provider.pk).update(enabled=False)
                        else: AIProviderAccount.objects.filter(pk=self.account.pk).update(state="revoked", revoked_at=timezone.now())
                    return result
                with patch.object(original, "_read_pair_sources", side_effect=last), self.assertRaises(PermissionDenied):
                    self.select(job)
                self.assertEqual(calls, 1)
                transaction.set_rollback(True)
        self.assertEqual(self.select(job)[2:], expected)
