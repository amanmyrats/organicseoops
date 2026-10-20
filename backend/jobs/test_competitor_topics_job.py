import io
import json
from datetime import timedelta
from unittest.mock import patch
from zipfile import ZipFile

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from providers.adapters import ProviderRequestError, ProviderResponse
from tenancy.models import Organization, OrganizationMembership, OrganizationTrial, ProjectConfiguration
from tenancy.customer_export import _row
from . import competitor_topics_job as topics, competitor_synthesis_job as original
from . import test_competitor_topics_selection as fixtures
from .ai_usage import record_ai_attempt
from .api import _job_payload
from .models import AIUsageRecord, Artifact, JobCancellation, JobRun, JobStep
from .recovery import reconcile_stuck_competitor_synthesis
from .services import queue_job, retry_job
from .usage import UsageLimitError, reconcile_usage


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True,
    ARTIFACT_ALLOWED_CONTENT_TYPES=frozenset({"text/html", "text/plain", "application/json", "application/zip"}))
class CompetitorTopicsJobTests(TransactionTestCase):
    setUp = fixtures.CompetitorTopicsSelectionTests.setUp
    queue = fixtures.CompetitorTopicsSelectionTests.queue
    transport = fixtures.CompetitorTopicsSelectionTests.transport
    collected = fixtures.CompetitorTopicsSelectionTests.collected
    input_data = fixtures.CompetitorTopicsSelectionTests.input_data

    def queued(self, source, key="topics-request", **changes):
        with patch("jobs.tasks.execute_competitor_topics_task.apply_async") as task:
            job = topics.queue_competitor_topics(project=self.project,actor=self.admin,
                data=self.input_data(source,**changes),idempotency_key=key)
        self.dispatch=task
        return job

    def response(self, structured=None):
        return ProviderResponse(text="PRIVATE RAW PROVIDER TEXT",structured=structured if structured is not None else
            {"topics":[{"label":"Unverified topic label","reference":"heading_0","quote":"Selected"}]},
            citations=(),request_id="fixture-request",response_id="fixture-response",input_tokens=40,output_tokens=20)

    def request(self, **kwargs):
        self.assertFalse(connection.in_atomic_block)
        job=JobRun.objects.get(handler=topics.HANDLER,status="running")
        self.assertEqual(job.steps.get().output,{"method":topics.METHOD,"state":"attempted"})
        self.assertEqual(job.ai_usage_record.status,"attempted")
        self.assertEqual(kwargs["output_schema"],topics.synthesis.OUTPUT_SCHEMA)
        self.assertIs(kwargs["web_search"],False); self.assertEqual(kwargs["timeout"],30)
        self.assertIn("untrusted source data",kwargs["prompt"]); kwargs["checkpoint"]()
        return self.response()

    def read(self, job, actor=None):
        return topics.read_competitor_topics(project=self.project,actor=actor or self.owner,job_id=job.pk)

    def execute(self, job, request=None):
        with patch("socket.create_connection",side_effect=AssertionError("No actual provider")):
            result=topics.execute_competitor_topics(job.pk,request=request or self.request)
        job.refresh_from_db(); return result

    def test_committed_single_original_hypotheses_private_readback_one_citation_usage_hidden_and_historical(self):
        source=self.collected("single-original")
        job=self.queued(source)
        self.dispatch.assert_called_once_with(args=[job.pk],queue="ai",task_id=f"job-{job.pk}",retry=False)
        self.assertEqual((job.usage.provider,job.usage.reserved_units),("ai",1))
        self.assertEqual(self.queued(source).pk,job.pk); self.dispatch.assert_not_called()
        self.assertTrue(self.execute(job)); self.assertEqual(job.status,"succeeded",job.error_category)
        result=self.read(job); self.assertEqual(self.read(job,self.admin),result)
        stored=result["synthesis"]
        self.assertEqual(stored["observation"]["job_id"],source.pk)
        self.assertEqual(stored["observation"]["collection"]["evidence"],source.output["evidence"])
        self.assertEqual(stored["topics"],self.response().structured["topics"])
        self.assertEqual(stored["state"],topics.STATE)
        self.assertNotIn("PRIVATE RAW",json.dumps(stored)); self.assertNotIn("comparison",stored)
        self.assertEqual(job.citations.count(),1)
        citation=job.citations.get()
        self.assertEqual((citation.source_url,citation.observed_at),(source.output["url"],original._date(source.output["observed_at"])))
        self.assertLess(citation.observed_at,original._date(stored["generated_at"]))
        self.assertEqual((job.usage.actual_units,job.usage.state),(1,"settled"))
        self.assertEqual((job.ai_usage_record.status,job.ai_usage_record.operation_version),("completed",topics.METHOD))
        self.assertFalse(self.execute(job,lambda **kwargs:self.fail("No replay")))
        for private in ("output","steps","artifacts","citations"):
            self.assertNotIn(private,_job_payload(job,detailed=True))
        fields=job._meta.concrete_fields
        self.assertIn("unverified_topic_hypotheses",_row(job,fields)["scope"])
        stored["topics"][0]["label"]="Changed"
        self.assertEqual(self.read(job)["synthesis"]["topics"][0]["label"],"Unverified topic label")
        self.assertEqual(AIUsageRecord.objects.filter(job=job).count(),1)

    def test_direct_queue_original_family_manager_budget_retry_and_schedule_fail_closed(self):
        source=self.collected("single-policy"); data=self.input_data(source)
        model,account,config,_=topics.selection_snapshot(self.project,self.admin,data)
        for changes in ({"config_snapshot":{}},{"input_snapshot":{**data,"current_job_id":source.pk}},
            {"config_snapshot":{**config,"method":"competitor-static-synthesis-v1"}},{"actor":self.foreign}):
            with self.subTest(changes=changes),self.assertRaises((PermissionDenied,ValidationError)):
                queue_job(**{**dict(project=self.project,actor=self.admin,handler=topics.HANDLER,input_snapshot=data,
                    config_snapshot=config,idempotency_key="invalid-direct"),**changes})
        for changes in ({"ai_processing_permission":False},{"max_cost_usd":"0.000001"},{"allow_free":True}):
            with self.subTest(changes=changes),self.assertRaises(ValidationError): self.queued(source,**changes)
        fake=JobRun(project=self.project,organization=self.organization,actor=self.admin,handler=topics.HANDLER,
            method_version=topics.METHOD,input_snapshot=data,config_snapshot=config,retry_of=source)
        with self.assertRaises(ValidationError): fake.full_clean()
        fake.retry_of=None; fake.scheduled_for=timezone.now()
        with self.assertRaises(ValidationError): fake.full_clean()
        job=self.queued(source)
        OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
        self.assertTrue(self.execute(job,lambda **kwargs:self.fail("No revoked attempt")))
        self.assertEqual((job.status,job.usage.actual_units),("cancelled",0))
        self.assertFalse(job.steps.exists()); self.assertFalse(job.artifacts.exists())
        OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="admin")
        with self.assertRaises(ValidationError): retry_job(job=job,actor=self.admin,idempotency_key="retry-topics")

    def test_committed_unknown_recovery_never_replays_and_settles_exactly_once(self):
        source=self.collected("single-unknown"); job=self.queued(source)
        job.status="running"; job.save(update_fields=["status","updated_at"])
        step=JobStep.objects.create(job=job,sequence=1,name=topics.STAGE,status="running",output={"method":topics.METHOD,"state":"attempted"})
        record_ai_attempt(job=job,step=step)
        JobRun.objects.filter(pk=job.pk).update(updated_at=timezone.now()-timedelta(seconds=160))
        with patch("providers.adapters.create_response",side_effect=AssertionError("No replay")):
            self.assertEqual(reconcile_stuck_competitor_synthesis(),1)
            self.assertEqual(reconcile_stuck_competitor_synthesis(),0)
            self.assertFalse(self.execute(job,lambda **kwargs:self.fail("No replay")))
        self.assertEqual((job.status,job.error_category,job.usage.actual_units),("failed","request_outcome_unknown",1))
        self.assertEqual(job.ai_usage_record.status,"unknown"); self.assertFalse(job.artifacts.exists())
        self.assertEqual(reconcile_usage(),0)
        self.assertEqual(AIUsageRecord.objects.filter(job=job).count(),1)

    def test_invalid_unquoted_topics_and_untrusted_provider_error_discard_raw_answer(self):
        source=self.collected("single-invalid")
        values=({"topics":[{"label":"Claim","reference":"heading_0","quote":"Fabricated"}]},
            {"topics":[{"label":"Claim","reference":"heading_0","quote":"Selected","approved":True}]})
        for index,value in enumerate(values):
            job=self.queued(source,"invalid-topics-"+str(index))
            self.assertTrue(self.execute(job,lambda **kwargs:self.response(value)))
            self.assertEqual(job.status,"failed"); self.assertEqual(job.output,{})
            self.assertFalse(job.artifacts.exists()); self.assertFalse(job.citations.exists())
            self.assertEqual(job.usage.actual_units,1)
        job=self.queued(source,"provider-error")
        def error(**kwargs): raise ProviderRequestError("raw_private_provider_text")
        self.assertTrue(self.execute(job,error))
        self.assertEqual(job.error_category,"provider_unavailable")
        self.assertNotIn("raw_private",json.dumps(job.output)); self.assertFalse(job.artifacts.exists())
        self.assertFalse(self.execute(job,lambda **kwargs:self.fail("No replay")))

    def test_private_byte_metadata_actor_caller_source_cancel_and_natural_expiry_losses_withhold(self):
        source=self.collected("single-private"); job=self.queued(source)
        self.assertTrue(self.execute(job)); self.assertEqual(job.status,"succeeded",job.error_category)
        expected=self.read(job); read=original.read_project_artifact
        for loss in ("artifact","actor","caller","configuration","source-cancel","result-cancel","expiry","corrupt-bytes"):
            with self.subTest(loss=loss),transaction.atomic():
                def late(**kwargs):
                    content=read(**kwargs)
                    if loss=="artifact": Artifact.objects.filter(job=job).update(size_bytes=1)
                    elif loss=="actor": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                    elif loss=="caller": OrganizationMembership.objects.filter(organization=self.organization,user=self.owner).update(role="viewer")
                    elif loss=="configuration": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                    elif loss=="source-cancel": JobCancellation.objects.create(job=source,requested_by=self.owner)
                    elif loss=="result-cancel": JobCancellation.objects.create(job=job,requested_by=self.owner)
                    elif loss=="expiry":
                        now=timezone.now(); OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now-timedelta(days=31),ends_at=now-timedelta(seconds=1))
                    else: return content+b" "
                    return content
                with patch.object(original,"read_project_artifact",side_effect=late),self.assertRaises((PermissionDenied,ValidationError,UsageLimitError)): self.read(job)
                transaction.set_rollback(True)
        self.assertEqual(self.read(job),expected)

    def test_last_fresh_source_own_metadata_status_usage_and_all_cancellation_losses_withhold_private_result(self):
        source=self.collected("single-final-reader"); job=self.queued(source)
        self.assertTrue(self.execute(job)); self.assertEqual(job.status,"succeeded",job.error_category)
        expected=self.read(job); reader=original._reader_source
        for loss in ("artifact","status","usage","own-cancel","source-cancel"):
            with self.subTest(loss=loss),transaction.atomic():
                calls=0
                def late(current,project,actor):
                    nonlocal calls
                    result=reader(current,project,actor); calls+=1
                    if calls==2:
                        if loss=="artifact": Artifact.objects.filter(job=job).update(size_bytes=1)
                        elif loss=="status": JobRun.objects.filter(pk=job.pk).update(status="failed")
                        elif loss=="usage": AIUsageRecord.objects.filter(job=job).update(status="unknown")
                        else: JobCancellation.objects.create(job=job if loss=="own-cancel" else source,requested_by=self.owner)
                    return result
                with patch.object(original,"_reader_source",side_effect=late),self.assertRaises(PermissionDenied): self.read(job)
                self.assertEqual(calls,2); transaction.set_rollback(True)
        self.assertEqual(self.read(job),expected)

    def test_late_scope_loss_after_provider_and_storage_never_publishes_private_result(self):
        source=self.collected("single-races")
        for loss in ("provider-cancel","storage-revision"):
            job=self.queued(source,"race-"+loss)
            save=original.save_project_artifact
            def request(**kwargs):
                response=self.request(**kwargs)
                if loss=="provider-cancel": JobCancellation.objects.create(job=source,requested_by=self.owner)
                return response
            def store(**kwargs):
                key=save(**kwargs)
                if loss=="storage-revision": ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2)
                return key
            with patch.object(original,"save_project_artifact",side_effect=store): self.assertTrue(self.execute(job,request))
            self.assertEqual(job.status,"cancelled"); self.assertEqual(job.output,{})
            self.assertFalse(job.artifacts.exists()); self.assertFalse(job.citations.exists())
            self.assertEqual(job.usage.actual_units,1)
            JobCancellation.objects.filter(job=source).delete()
            ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=1)

    def test_historical_topic_archive_retained_copies_sequential_parts_and_child_first_erasure(self):
        from tenancy.artifacts import read_project_artifact
        from tenancy.customer_export import complete_bounded_customer_archive
        from tenancy.customer_inventory import CUSTOMER
        from tenancy.customer_snapshot import reserve_bounded_customer_snapshot, capture_reserved_customer_snapshot, private_snapshot_part
        from tenancy.customer_source_parts import capture_source_stage
        from tenancy.deletion import prepare_customer_data_deletion, sweep_customer_artifact_versions, delete_customer_database_records
        source = self.collected("single-historical"); job = self.queued(source)
        self.assertTrue(self.execute(job)); self.assertEqual(job.status, "succeeded", job.error_category)
        artifact = job.artifacts.get(); content = read_project_artifact(project=self.project, key=artifact.key)
        with ZipFile(io.BytesIO(complete_bounded_customer_archive(organization=self.organization, actor=self.owner))) as archive:
            row = next(row for row in json.loads(archive.read("records/jobs/JobRun.json")) if row["id"] == job.pk)
            self.assertEqual(row["scope"], "historical_original_single_heading_facts_and_unverified_topic_hypotheses_not_current_use_semantic_truth_page_topics_gaps_intent_freshness_rankings_whole_site_or_human_approval")
            self.assertEqual(row["output"], job.output); self.assertIn(content, [archive.read(name) for name in archive.namelist()])
            self.assertNotIn("records/jobs/AIUsageRecord.json", archive.namelist())
        bounded = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="a" * 32)
        self.assertTrue(capture_reserved_customer_snapshot(bounded.pk))
        retained, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[])
        with self.assertRaises((PermissionDenied, ValidationError)): self.read(job)
        self.assertEqual(private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)[0], retained)
        sequential = reserve_bounded_customer_snapshot(organization=self.organization, actor=self.owner, request_key="b" * 32, format="source-parts-v2")
        for _ in range(len(CUSTOMER) * 2 + 10):
            sequential.refresh_from_db()
            if sequential.state != sequential.State.PREPARING: break
            self.assertTrue(capture_source_stage(sequential.pk, sequential.progress.get("step", 0)))
        sequential.refresh_from_db(); self.assertEqual(sequential.state, sequential.State.READY)
        part = sequential.parts.filter(source__model="jobs.JobRun").first()
        data, _ = private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=sequential.pk, position=part.position)
        with ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(next(row for row in json.loads(archive.read("data")) if row["id"] == job.pk)["output"], job.output)
        now = timezone.now()
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=now - timedelta(days=121), ends_at=now - timedelta(days=91))
        with self.assertRaises(PermissionDenied): private_snapshot_part(organization=self.organization, actor=self.owner, snapshot_id=bounded.pk, position=0)
        Organization.objects.filter(pk=self.organization.pk).update(is_suspended=True, closed_at=now)
        run = sweep_customer_artifact_versions(run=prepare_customer_data_deletion(organization=self.organization))
        self.assertEqual(delete_customer_database_records(run=run).state, run.State.COMPLETE)
        self.assertFalse(JobRun.objects.filter(pk=job.pk).exists()); self.assertFalse(AIUsageRecord.objects.filter(job_id=job.pk).exists())
        self.assertFalse(Artifact.objects.filter(pk=artifact.pk).exists())
