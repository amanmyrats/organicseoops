from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from providers.models import OrganizationPerformanceKey
from providers.performance_key import set_organization_performance_key, revoke_organization_performance_key
from tenancy.models import OrganizationMembership, ProjectConfiguration
from . import competitor_lab_fetch as producer, competitor_lab_selection as selection
from . import test_competitor_source as source_fixtures, test_competitor_lab as lab_fixtures, test_passive_resource_transport as wire_fixtures
from .competitor_collection import _encode, validate_result as root_result
from .competitor_page_dates_collection import validate_result as dates_result
from .crawling import FetchError
from .models import CrawlRun, JobRun, PerformanceObservationSnapshot, UsageReservation
from .performance_transport import PerformanceTransportError


KEY = Fernet.generate_key().decode()
SECRET = "fixture_org_key_with_32_characters"


@override_settings(PERFORMANCE_ENCRYPTION_KEYS=(KEY,), GOOGLE_PERFORMANCE_API_KEY="")
class CompetitorLabFetchTests(TestCase):
    transport = wire_fixtures.PassiveResourceTransportTests.transport

    def setUp(self):
        source_fixtures.CompetitorSourceTests.setUp(self)
        self.record=set_organization_performance_key(actor=self.owner,organization=self.organization,value=SECRET)

    def data(self):
        return {"origin":source_fixtures.COMPETITOR,"url":lab_fixtures.URL,"collection_permission":True,"provider_processing_permission":True,"strategy":"mobile"}

    def binding(self):
        return selection.selection_snapshot(project=self.project,actor=self.owner,data=self.data())

    def document(self,body,*,kind="application/json",status="200 OK",fields=None):
        fields=fields if fields is not None else f"Content-Length: {len(body)}\r\nContent-Type: {kind}\r\n".encode()
        _fetcher,conn,response,*_=self.transport(body,fields=fields,status=status)
        return conn,response

    def collect(self,*,binding=None,robots=b"User-agent: *\nDisallow:\n",robots_status="200 OK",provider_status="200 OK",
                connected=None,resolved=None,read=None,wait=None,before=None,send=None):
        original=self.binding() if binding is None else binding
        pending=[self.document(robots,kind="text/plain",status=robots_status),self.document(json.dumps(lab_fixtures.CompetitorLabTests().payload()).encode(),status=provider_status)]
        self.connections=[];self.resolutions=[];self.waits=[];self.now=0;self.sent=Mock(side_effect=send)
        def factory(*args):
            conn,response=pending.pop(0);self.connections.append((args[:4],conn))
            if connected:conn.connect.side_effect=lambda:connected(len(self.connections))
            if read:
                actual=response.read1
                response.read1=lambda amount:(read(len(self.connections)),actual(amount))[1]
            return conn
        def resolver(*args):
            self.resolutions.append(args[:2])
            if resolved:resolved(len(self.resolutions))
            return ["93.184.216.34"]
        def sleep(value):
            self.waits.append(value);self.now+=value
            if wait:wait()
        return producer.collect_competitor_lab(project=self.project,actor=self.owner,binding=original,before_request=before or (lambda:None),
            before_send=self.sent,resolver=resolver,connection_factory=factory,clock=lambda:self.now,sleep=sleep)

    def revoke(self):
        OrganizationMembership.objects.filter(organization=self.organization,user=self.owner).update(role="viewer")

    def test_actual_original_source_key_strict_robots_google_wire_provenance_privacy_no_write_and_fresh_roundtrip(self):
        original=self.binding()
        with patch("socket.create_connection",side_effect=AssertionError("No real I/O")),CaptureQueriesContext(connection) as queries:result=self.collect(binding=original)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT","UPDATE","DELETE")) for row in queries))
        self.assertEqual((result["method_version"],result["state"],result["selection_sha256"]),(producer.METHOD,"collected",original["selection_sha256"]))
        self.assertEqual((result["url"],result["strategy"],result["robots"]),(lab_fixtures.URL,"mobile","available"))
        self.assertEqual(self.waits,[1]);self.sent.assert_called_once_with()
        self.assertEqual(self.resolutions,[("competitor.example.invalid",443),("competitor.example.invalid",443),("pagespeedonline.googleapis.com",443)])
        self.assertEqual([args for args,_ in self.connections],[("https","93.184.216.34","competitor.example.invalid",443),("https","93.184.216.34","pagespeedonline.googleapis.com",443)])
        self.assertEqual(self.connections[0][1].request.call_args.args,("GET","/robots.txt"))
        self.assertEqual(self.connections[1][1].request.call_args.kwargs["headers"]["X-goog-api-key"],SECRET)
        for _,conn in self.connections:conn.close.assert_called_once()
        for private in (SECRET,"encrypted_secret","private","loadingExperience","robots.txt","User-agent:",self.owner.email):self.assertNotIn(private,json.dumps(result))
        stored=producer.parse_result(_encode(result),original);self.assertEqual(stored,result);stored["evidence"]["lab"]["scores"]["performance"]=0
        self.assertEqual(producer.parse_result(_encode(result),original),result)
        self.assertLessEqual(result["request_started_at"],result["evidence"]["received_at"])
        for model in (JobRun,CrawlRun,UsageReservation,PerformanceObservationSnapshot):self.assertFalse(model.objects.exists())
        for validator in (root_result,dates_result):
            with self.assertRaises(ValidationError):validator(result,original["source"]["page_source"])

    def test_strict_robots_denied_unknown_unsupported_no_follow_or_missing_and_original_pacing(self):
        for robots in (b"User-agent: *\nDisallow: /selected/", b"User-agent: OrganicSEOOpsBot\nDisallow:\n\nUser-agent: *\nDisallow: /selected/",b"unknown",b"User-agent: *\nDisallow: /*",b"User-agent: *\nDisallow:\nRequest-rate: 1/60",b"User-agent: *\nDisallow:\nCrawl-delay: 1.5",b"\xff"):
            result=self.collect(robots=robots);self.assertEqual(result["state"],"unavailable");self.assertEqual(len(self.connections),1);self.sent.assert_not_called();self.assertNotIn("evidence",result)
        for status in ("302 Found","403 Forbidden","503 Error"):
            result=self.collect(robots_status=status);self.assertEqual(result["state"],"unavailable");self.sent.assert_not_called()
        for status in ("404 Not Found","410 Gone"):
            self.assertEqual(self.collect(robots_status=status)["robots"],"missing_http_404_or_410")
        result=self.collect(robots=b"User-agent: *\nDisallow:\nCrawl-delay: 3");self.assertEqual(result["state"],"collected");self.assertEqual(self.waits,[3])

    def test_current_full_source_role_config_and_key_loss_dns_connected_body_pacing_and_projection_withhold(self):
        hooks=[{"resolved":lambda count:self.revoke() if count in (1,2,3) else None},
            {"connected":lambda count:self.revoke() if count==2 else None},{"read":lambda count:self.revoke() if count==2 else None},{"wait":self.revoke},
            {"connected":lambda count:revoke_organization_performance_key(actor=self.owner,organization=self.organization) if count==2 else None},
            {"connected":lambda count:OrganizationPerformanceKey.objects.filter(pk=self.record.pk).update(encrypted_secret="v1:corrupt") if count==2 else None},
            {"wait":lambda:ProjectConfiguration.objects.filter(pk=self.configuration.pk).update(competitor_origins=[source_fixtures.COMPETITOR,"https://changed.example.invalid"])}]
        for hook in hooks:
            with self.subTest(hook=hook),transaction.atomic():
                with self.assertRaises((PermissionDenied,ValidationError)):self.collect(**hook)
                transaction.set_rollback(True)
        actual=producer.validate_result
        def changed(*args):
            value=actual(*args);self.revoke();return value
        with patch.object(producer,"validate_result",side_effect=changed),self.assertRaises(PermissionDenied):self.collect()

    def test_current_read_and_owning_cancel_commercial_fences_are_mandatory_at_costly_and_final_boundaries(self):
        original=self.binding()
        for key in ("before_request","before_send"):
            values={"before_request":lambda:None,"before_send":lambda:None};values[key]=None
            with patch("jobs.crawling._system_resolver",side_effect=AssertionError("No DNS")),self.assertRaises(PermissionDenied):
                producer.collect_competitor_lab(project=self.project,actor=self.owner,binding=original,**values)
        for hook in ("connected","read","wait"):
            active=[True]
            def before():
                if not active[0]:raise PermissionDenied
            def change(*_):active[0]=False
            with self.subTest(hook=hook),self.assertRaises(PermissionDenied):self.collect(before=before,**{hook:change})
        with self.assertRaises(PermissionDenied):self.collect(send=self.revoke)
        self.connections[-1][1].request.assert_not_called()
        OrganizationMembership.objects.filter(organization=self.organization,user=self.owner).update(role="owner")
        reader=producer.selection_snapshot
        active=[True]
        def during_read(**kwargs):
            value=reader(**kwargs);active[0]=False;return value
        def before():
            if not active[0]:raise PermissionDenied
        with patch.object(producer,"selection_snapshot",side_effect=during_read),self.assertRaises(PermissionDenied):self.collect(before=before)
        self.assertEqual(self.connections,[])

    def test_frozen_binding_caller_mutation_and_wrong_method_device_or_foreign_original_selection_deny(self):
        original=self.binding();expected=deepcopy(original)
        result=self.collect(binding=original,resolved=lambda count:original["source"].update(strategy="desktop") if count==1 else None)
        self.assertEqual(result["state"],"collected");self.assertEqual(result["strategy"],"mobile");self.assertEqual(result["selection_sha256"],expected["selection_sha256"])
        with self.assertRaises(PermissionDenied):self.collect(binding=original)
        for changed in (None,{}, {**expected,"api_key":SECRET},{**expected,"selection_sha256":"0"*64}, {**expected,"method_version":"competitor-page-source-v1"}):
            with self.subTest(changed=changed),self.assertRaises(PermissionDenied):
                producer.collect_competitor_lab(project=self.project,actor=self.owner,binding=changed,before_request=lambda:None,before_send=lambda:None)

    def test_missing_key_quota_unknown_errors_and_deadline_are_categorical_no_provider_replay_or_private_details(self):
        self.record.delete();self.assertEqual(self.collect()["error_category"],"credential_unavailable");self.assertEqual(self.connections,[]);self.sent.assert_not_called()
        self.record=set_organization_performance_key(actor=self.owner,organization=self.organization,value=SECRET)
        result=self.collect(provider_status="429 Limited");self.assertEqual(result["error_category"],"quota_limited");self.sent.assert_called_once();self.assertEqual(len(self.connections),2)
        with patch.object(producer,"request_competitor_lab",side_effect=PerformanceTransportError("private_provider_secret")):
            self.assertEqual(self.collect()["error_category"],"lighthouse_failed")
        result=self.collect(wait=lambda:setattr(self,"now",31));self.assertEqual(result["error_category"],"timeout");self.sent.assert_not_called();self.assertEqual(len(self.connections),1)

    def test_strict_original_result_shape_dates_scope_bytes_duplicate_nonfinite_and_receipt_before_request_fail_closed(self):
        binding=self.binding();result=self.collect(binding=binding)
        changes=[{"api_key":SECRET},{"url":source_fixtures.COMPETITOR+"/other"},{"strategy":"desktop"},{"selection_sha256":"0"*64},{"robots":"unknown"},
            {"request_started_at":(timezone.now()+timedelta(days=1)).isoformat(timespec="microseconds")}, {"request_started_at":"2026-01-01T00:00:00.000000+00:00"}]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValidationError):producer.validate_result({**result,**change},binding)
        changed=deepcopy(result);changed["evidence"]["received_at"]=result["request_started_at"]
        changed["request_started_at"]=(timezone.now()+timedelta(microseconds=1)).isoformat(timespec="microseconds")
        with self.assertRaises(ValidationError):producer.validate_result(changed,binding)
        for raw in (b"",b"[]",b'{"state":"a","state":"b"}',b'{"ignored":NaN}',b"x"*8193,b"\xff"):
            with self.assertRaises(ValidationError):producer.parse_result(raw,binding)
