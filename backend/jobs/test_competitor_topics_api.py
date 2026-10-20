import json
from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from config.test_foundations import TEST_STORAGES
from providers.models import AIModel, AIProviderAccount
from tenancy.models import OrganizationMembership, OrganizationTrial, ProjectConfiguration
from . import competitor_synthesis_api as api, competitor_topics_job as topics
from . import test_competitor_topics_job as fixtures
from .models import AIUsageRecord, Artifact, JobCancellation, JobRun, UsageReservation


@override_settings(STORAGES=TEST_STORAGES, DEBUG=True, SECURE_SSL_REDIRECT=False,
    CACHES={"default":{"BACKEND":"django.core.cache.backends.locmem.LocMemCache","LOCATION":"competitor-topics-api"}})
class CompetitorTopicsApiTests(TransactionTestCase):
    queue=fixtures.CompetitorTopicsJobTests.queue
    transport=fixtures.CompetitorTopicsJobTests.transport
    collected=fixtures.CompetitorTopicsJobTests.collected
    input_data=fixtures.CompetitorTopicsJobTests.input_data
    response=fixtures.CompetitorTopicsJobTests.response
    request=fixtures.CompetitorTopicsJobTests.request

    def setUp(self):
        fixtures.CompetitorTopicsJobTests.setUp(self)
        cache.clear()
        self.client=Client(enforce_csrf_checks=True); self.client.force_login(self.admin)
        self.client.get("/_allauth/browser/v1/auth/session",secure=True)
        self.csrf=self.client.cookies["csrftoken"].value
        self.base=f"/api/organizations/{self.organization.pk}/projects/{self.project.pk}/competitor-heading-topics/"

    def post(self,suffix="",data=None):
        return self.client.post(self.base+suffix,json.dumps(self.input if data is None else data),content_type="application/json",
            secure=True,HTTP_X_CSRFTOKEN=self.csrf,HTTP_REFERER="https://testserver/")

    def command(self,key="topics-api-request"):
        preview=self.post("selection/"); self.assertEqual(preview.status_code,200,preview.content)
        self.assertEqual(api._digest(preview.json()["selection"]),preview.json()["selection_digest"])
        return {**self.input,"idempotency_key":key,"selection_digest":preview.json()["selection_digest"]}

    def test_single_preview_queue_own_key_private_facts_hypotheses_nullable_usage_independent_reader_cancel(self):
        source=self.collected("topics-api-source"); self.input=self.input_data(source)
        with (patch("providers.services.resolve_provider_secret",side_effect=AssertionError("No preview key")),
            patch("providers.adapters.create_response",side_effect=AssertionError("No preview provider")),
            patch("socket.getaddrinfo",side_effect=AssertionError("No preview DNS"))):
            command=self.command()
            self.assertFalse(JobRun.objects.filter(handler=topics.HANDLER).exists())
            self.assertEqual(self.client.get(self.base+"?idempotency_key=topics-api-request",secure=True).json()["jobs"],[])
            queued=self.post(data=command); self.assertEqual(queued.status_code,202,queued.content)
            job_id=queued.json()["job"]["id"]
            self.assertEqual(self.post(data=command).json()["job"]["id"],job_id)
        waiting=self.client.get(self.base+f"{job_id}/",secure=True)
        self.assertEqual(waiting.status_code,200,waiting.content)
        self.assertIsNone(waiting.json()["evidence"]); self.assertIsNone(waiting.json()["usage"])
        self.assertEqual(waiting.json()["selection"]["input"],self.input)
        self.assertEqual(waiting.json()["selection_digest"],command["selection_digest"])
        self.assertTrue(topics.execute_competitor_topics(job_id,request=self.request))
        detail=self.client.get(self.base+f"{job_id}/",secure=True)
        self.assertEqual(detail.status_code,200,detail.content); body=detail.json()
        self.assertEqual(body["evidence"]["synthesis"]["observation"]["job_id"],source.pk)
        self.assertEqual(body["evidence"]["synthesis"]["observation"]["collection"]["evidence"],source.output["evidence"])
        self.assertEqual(body["evidence"]["synthesis"]["topics"],self.response().structured["topics"])
        self.assertEqual(body["evidence"]["synthesis"]["state"],topics.STATE)
        self.assertEqual(body["usage"]["status"],"completed"); self.assertIsNone(body["usage"]["reported_cost_usd"])
        self.assertNotIn("provider_request_id",body["usage"]); self.assertNotIn(b"PRIVATE RAW",detail.content)
        self.assertIn("no-store",detail["Cache-Control"]); self.assertEqual(detail["X-Robots-Tag"],"noindex, nofollow")
        other=Client(); other.force_login(self.owner)
        self.assertEqual(other.get(self.base+f"{job_id}/",secure=True).json()["evidence"],body["evidence"])
        self.assertEqual(other.get(self.base+"?idempotency_key=topics-api-request",secure=True).json()["jobs"],[])
        cancel_command=self.command("topics-api-cancel"); cancel_id=self.post(data=cancel_command).json()["job"]["id"]
        AIProviderAccount.objects.filter(pk=self.account.pk).update(state="revoked",revoked_at=timezone.now())
        self.assertEqual(self.post(f"{cancel_id}/",{}).status_code,202)
        self.assertEqual(JobRun.objects.get(pk=cancel_id).status,"cancelled")
        AIProviderAccount.objects.filter(pk=self.account.pk).update(state="active",revoked_at=None)
        self.assertEqual(self.post(data=cancel_command).json()["job"]["id"],cancel_id)

    def test_exact_single_digest_csrf_json_query_role_and_cross_pair_family_denials(self):
        source=self.collected("topics-api-strict"); self.input=self.input_data(source); command=self.command()
        self.assertEqual(self.client.post(self.base,json.dumps(command),content_type="application/json",secure=True).status_code,403)
        for change in ({"max_cost_usd":"0.020000"},{"max_output_tokens":513},{"ai_processing_permission":False},
            {"allow_free":1},{"job_id":True},{"job_id":str(source.pk)},{"model_id":True},{"previous_job_id":source.pk},
            {"current_job_id":source.pk},{"raw_prompt":"private"},{"selection_digest":"a"*64}):
            cache.clear()  # Independent validation cases; the dedicated budget test retains real limits.
            with self.subTest(change=change): self.assertIn(self.post(data={**command,**change}).status_code,(403,409))
        self.assertFalse(JobRun.objects.filter(handler=topics.HANDLER).exists())
        for body in ('{"model_id":1,"model_id":2}','{','[]','null','{"model_id":NaN}'," "*2049):
            cache.clear()
            result=self.client.post(self.base,body,content_type="application/json",secure=True,HTTP_X_CSRFTOKEN=self.csrf,HTTP_REFERER="https://testserver/")
            self.assertEqual(result.status_code,409)
        self.assertEqual(self.post("?posted=1",command).status_code,400)
        for query in ("?extra=1","?idempotency_key=key&idempotency_key=key"):
            self.assertEqual(self.client.get(self.base+query,secure=True).status_code,409)
        self.assertEqual(self.client.get(self.base+"selection/",secure=True).status_code,405)
        self.assertEqual(Client().get(self.base,secure=True).status_code,401)
        self.client.force_login(self.foreign); self.assertEqual(self.client.get(self.base,secure=True).status_code,404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.base+f"{source.pk}/",secure=True).status_code,403)
        job_id=self.post(data=command).json()["job"]["id"]
        for family in ("competitor-syntheses","competitor-heading-syntheses"):
            base=self.base.replace("competitor-heading-topics",family)
            self.assertEqual(self.client.get(base+f"{job_id}/",secure=True).status_code,403)
            self.assertEqual(self.client.post(base+"selection/",json.dumps(self.input),content_type="application/json",secure=True,
                HTTP_X_CSRFTOKEN=self.csrf,HTTP_REFERER="https://testserver/").status_code,409)
        EmailAddress.objects.filter(user=self.admin).update(verified=False)
        self.assertEqual(self.client.get(self.base,secure=True).status_code,403)

    def test_four_independent_topic_budgets_shared_ip_and_original_pair_read_separate(self):
        source=self.collected("topics-api-budget"); self.input=self.input_data(source)
        command=self.command(); job_id=self.post(data=command).json()["job"]["id"]
        other=Client(); other.force_login(self.owner); cache.clear()
        limits={"competitor_heading_topics_"+suffix:"1/h/ip" for suffix in ("read","selection","request","cancel")}
        with override_settings(ACCOUNT_RATE_LIMITS=limits):
            self.assertEqual(self.client.get(self.base,secure=True).status_code,200)
            self.assertEqual(other.get(self.base,secure=True).status_code,429)
            self.assertEqual(self.post("selection/").status_code,200); self.assertEqual(self.post("selection/").status_code,429)
            self.assertEqual(self.post(data=command).status_code,202); self.assertEqual(self.post(data=command).status_code,429)
            self.assertEqual(self.post(f"{job_id}/",{}).status_code,202); self.assertEqual(self.post(f"{job_id}/",{}).status_code,429)
            self.assertEqual(self.client.get(self.base.replace("competitor-heading-topics","competitor-heading-syntheses"),secure=True).status_code,200)

    def test_queue_after_serialization_original_source_model_caller_losses_roll_back_reservation_dispatch(self):
        source=self.collected("topics-api-queue"); self.input=self.input_data(source); command=self.command(); response=api._response
        for mutation in (lambda:OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer"),
            lambda:ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(revision=2),
            lambda:AIModel.objects.filter(pk=self.model.pk).update(enabled=False),
            lambda:Artifact.objects.filter(job=source).update(created_at=timezone.now()),
            lambda:JobCancellation.objects.create(job=source,requested_by=self.owner)):
            def changed(data,*args,**kwargs):
                result=response(data,*args,**kwargs)
                if "job" in data: mutation()
                return result
            with patch.object(api,"_response",side_effect=changed),patch("jobs.tasks.execute_competitor_topics_task.apply_async") as dispatch:
                result=self.post(data=command)
            self.assertIn(result.status_code,(403,409),result.content)
            self.assertFalse(JobRun.objects.filter(handler=topics.HANDLER).exists()); dispatch.assert_not_called()
            self.assertEqual(UsageReservation.objects.count(),1)

    def test_private_detail_after_serialization_metadata_source_model_caller_cancel_and_expiry_withhold(self):
        source=self.collected("topics-api-detail"); self.input=self.input_data(source)
        job_id=self.post(data=self.command()).json()["job"]["id"]
        self.assertTrue(topics.execute_competitor_topics(job_id,request=self.request)); response=api._response
        for mutation in (lambda:Artifact.objects.filter(job=source).update(created_at=timezone.now()),
            lambda:AIUsageRecord.objects.filter(job_id=job_id).update(duration_ms=1),
            lambda:AIModel.objects.filter(pk=self.model.pk).update(enabled=False),
            lambda:OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer"),
            lambda:JobCancellation.objects.create(job=source,requested_by=self.owner),
            lambda:JobCancellation.objects.create(job_id=job_id,requested_by=self.owner)):
            with transaction.atomic():
                def changed(data,*args,**kwargs):
                    result=response(data,*args,**kwargs)
                    if "evidence" in data: mutation()
                    return result
                with patch.object(api,"_response",side_effect=changed): result=self.client.get(self.base+f"{job_id}/",secure=True)
                self.assertIn(result.status_code,(403,409),result.content); self.assertNotIn(b"topics",result.content)
                transaction.set_rollback(True)
        now=[timezone.now()]; ends=now[0]+timedelta(seconds=10)
        OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends-timedelta(days=30),ends_at=ends)
        def expire(data,*args,**kwargs):
            result=response(data,*args,**kwargs)
            if "evidence" in data: now[0]=ends
            return result
        with patch("jobs.usage.timezone.now",side_effect=lambda:now[0]),patch.object(api,"_response",side_effect=expire):
            result=self.client.get(self.base+f"{job_id}/",secure=True)
        self.assertEqual(result.status_code,403); self.assertNotIn(b"topics",result.content)
        self.assertEqual(self.client.get(self.base,secure=True).status_code,200)

    def test_final_unchanged_api_metadata_rechecks_three_distinct_original_actor_job_actor_and_reader(self):
        source=self.collected("topics-api-final"); self.input=self.input_data(source)
        job_id=self.post(data=self.command()).json()["job"]["id"]
        self.assertTrue(topics.execute_competitor_topics(job_id,request=self.request))
        reader=get_user_model().objects.create_user("topics-independent-reader@example.invalid","test-password")
        EmailAddress.objects.create(user=reader,email=reader.email,primary=True,verified=True)
        membership=OrganizationMembership.objects.create(organization=self.organization,user=reader,role="admin")
        self.assertEqual(len({source.actor_id,self.admin.pk,reader.pk}),3)
        client=Client(); client.force_login(reader); url=self.base+f"{job_id}/"
        expected=client.get(url,secure=True).json()["evidence"]; metadata=api._metadata
        for phase in ("queue","detail"):
            losses=("collector","job-actor","source-cancel","account","expiry")+(("reader","reader-role") if phase=="detail" else ())
            for loss in losses:
                command=self.command("topics-final-"+loss) if phase=="queue" else None
                with self.subTest(phase=phase,loss=loss),transaction.atomic():
                    cache.clear(); now=[timezone.now()]; ends=now[0]+timedelta(seconds=20)
                    OrganizationTrial.objects.filter(organization=self.organization).update(started_at=ends-timedelta(days=30),ends_at=ends)
                    pins=[]
                    def last(job,**kwargs):
                        result=metadata(job,**kwargs); pins.append(result)
                        if len(pins)==2:
                            self.assertEqual(result,pins[0]); self.assertEqual(set(result["source"]),{source.pk})
                            if loss=="collector": OrganizationMembership.objects.filter(organization=self.organization,user=self.owner).update(role="viewer")
                            elif loss=="job-actor": OrganizationMembership.objects.filter(pk=self.membership.pk).update(role="viewer")
                            elif loss=="reader": OrganizationMembership.objects.filter(pk=membership.pk).update(role="viewer")
                            elif loss=="reader-role": OrganizationMembership.objects.filter(pk=membership.pk).update(role="owner")
                            elif loss=="source-cancel": JobCancellation.objects.create(job=source,requested_by=self.owner)
                            elif loss=="account": AIProviderAccount.objects.filter(pk=self.account.pk).update(state="revoked",revoked_at=now[0])
                            else: now[0]=ends
                        return result
                    with patch.object(api,"_metadata",side_effect=last),patch("jobs.usage.timezone.now",side_effect=lambda:now[0]),patch("jobs.tasks.execute_competitor_topics_task.apply_async") as dispatch:
                        result=self.post(data=command) if phase=="queue" else client.get(url,secure=True)
                        self.assertEqual(len(pins),2); self.assertIn(result.status_code,(403,409),result.content)
                        self.assertNotIn(b'"topics":',result.content); dispatch.assert_not_called()
                        if phase=="queue": self.assertFalse(JobRun.objects.filter(handler=topics.HANDLER,idempotency_key=command["idempotency_key"]).exists())
                    transaction.set_rollback(True)
        cache.clear(); self.assertEqual(client.get(url,secure=True).json()["evidence"],expected)

    def test_last_fresh_detail_source_own_metadata_status_usage_and_all_cancellation_losses_withhold(self):
        source=self.collected("topics-detail-last-source"); self.input=self.input_data(source)
        job_id=self.post(data=self.command()).json()["job"]["id"]
        self.assertTrue(topics.execute_competitor_topics(job_id,request=self.request))
        response=api._response; reader=api.synthesis._reader_source; url=self.base+f"{job_id}/"
        expected=self.client.get(url,secure=True).json()["evidence"]
        for loss in ("artifact","status","usage","own-cancel","source-cancel"):
            with self.subTest(loss=loss),transaction.atomic():
                cache.clear(); final=False; calls=0
                def serialized(data,*args,**kwargs):
                    nonlocal final
                    result=response(data,*args,**kwargs)
                    if "evidence" in data: final=True
                    return result
                def last(job,project,actor):
                    nonlocal calls
                    result=reader(job,project,actor)
                    if final:
                        calls+=1
                        if loss=="artifact": Artifact.objects.filter(job_id=job_id).update(size_bytes=1)
                        elif loss=="status": JobRun.objects.filter(pk=job_id).update(status="failed")
                        elif loss=="usage": AIUsageRecord.objects.filter(job_id=job_id).update(status="unknown")
                        else: JobCancellation.objects.create(job_id=job_id if loss=="own-cancel" else source.pk,requested_by=self.owner)
                    return result
                with patch.object(api,"_response",side_effect=serialized),patch.object(api.synthesis,"_reader_source",side_effect=last):
                    result=self.client.get(url,secure=True)
                self.assertEqual(calls,1); self.assertEqual(result.status_code,403,result.content); self.assertNotIn("evidence",result.json())
                transaction.set_rollback(True)
        cache.clear(); self.assertEqual(self.client.get(url,secure=True).json()["evidence"],expected)
