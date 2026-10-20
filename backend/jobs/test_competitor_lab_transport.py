import gzip
import json
import ssl
from hashlib import sha256
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase

from . import competitor_lab_transport as transport, competitor_lab as evidence
from . import test_competitor_lab as lab_fixtures, test_passive_resource_transport as wire_fixtures
from .performance_transport import PerformanceTransportError


class CompetitorLabTransportTests(SimpleTestCase):
    transport = wire_fixtures.PassiveResourceTransportTests.transport
    URL = lab_fixtures.URL
    KEY = "fixture_provider_key_with_32_chars"

    def setup_wire(self, body=None, *, fields=None, status="200 OK", clock=None):
        body = json.dumps(lab_fixtures.CompetitorLabTests().payload()).encode() if body is None else body
        fields = fields if fields is not None else f"Content-Length: {len(body)}\r\nContent-Type: application/json\r\n".encode()
        _fetcher, conn, response, factory, resolver = self.transport(body, fields=fields, status=status)
        checkpoint, send = Mock(), Mock()
        options = {"clock":clock} if clock else {}
        def call(**changes):
            return transport.request_competitor_lab(**({"url":self.URL,"strategy":"mobile","api_key":self.KEY,
                "checkpoint":checkpoint,"before_send":send,"resolver":resolver,"connection_factory":factory, **options} | changes))
        return call,conn,response,factory,resolver,checkpoint,send

    def test_exact_public_target_fixed_google_tls_header_only_key_one_send_complete_original_minimized_no_sql_io(self):
        body=json.dumps(lab_fixtures.CompetitorLabTests().payload()).encode()
        for encoding in ("identity","gzip"):
            wire=body if encoding=="identity" else gzip.compress(body)
            fields=f"Content-Length: {len(wire)}\r\nContent-Type: application/json; charset=utf-8\r\nContent-Encoding: {encoding}\r\nSet-Cookie: private=secret\r\n".encode()
            call,conn,response,factory,resolver,checkpoint,send=self.setup_wire(wire,fields=fields)
            with patch("socket.create_connection",side_effect=AssertionError("No real network")), patch("providers.performance_key.google_performance_key",side_effect=AssertionError("Supplied transient key only")):
                result=call()
            self.assertEqual(result["response_sha256"],sha256(body).hexdigest());self.assertEqual(result["response_size_bytes"],len(body))
            self.assertEqual((result["method_version"],result["url"],result["strategy"]),(evidence.METHOD,self.URL,"mobile"))
            self.assertEqual([args.args[:2] for args in resolver.call_args_list],[("competitor.example.invalid",443),("pagespeedonline.googleapis.com",443)])
            self.assertEqual(factory.call_args.args[:4],("https","93.184.216.34","pagespeedonline.googleapis.com",443))
            conn.connect.assert_called_once();send.assert_called_once_with();self.assertEqual(checkpoint.call_count,8)
            method,path=conn.request.call_args.args;headers=conn.request.call_args.kwargs["headers"]
            self.assertEqual(method,"GET");self.assertEqual(urlsplit(path).path,"/pagespeedonline/v5/runPagespeed")
            self.assertEqual(parse_qs(urlsplit(path).query),{"url":[self.URL],"strategy":["mobile"],"category":["PERFORMANCE"]})
            self.assertIsNone(conn.request.call_args.kwargs["body"]);self.assertEqual(headers["X-goog-api-key"],self.KEY)
            self.assertEqual(headers["Host"],"pagespeedonline.googleapis.com");self.assertNotIn(self.KEY,path)
            for private in (self.KEY,"private","secret","Set-Cookie","userAgent","loadingExperience"):
                self.assertNotIn(private,json.dumps(result))
            self.assertGreater(response.read1.call_count,2);conn.close.assert_called_once()

    def test_invalid_exact_uri_device_key_timeout_and_mandatory_gates_deny_before_dns(self):
        for changes in ({"url":self.URL+"?secret=x"},{"url":self.URL+"#"},{"url":"https://competitor.example.invalid/"},
            {"url":"https://user:secret@competitor.example.invalid/a"},{"url":"https://competitor.example.invalid:443/a"},
            {"strategy":[]},{"strategy":"tablet"},{"timeout":True},{"timeout":0},{"timeout":31},
            {"api_key":"bad\nkey"},{"api_key":None},{"checkpoint":None},{"before_send":None}):
            call,conn,_response,factory,resolver,_checkpoint,send=self.setup_wire()
            with self.subTest(changes=changes),self.assertRaises((PermissionDenied,ValidationError,PerformanceTransportError)):call(**changes)
            resolver.assert_not_called();factory.assert_not_called();conn.request.assert_not_called();send.assert_not_called()

    def test_every_current_boundary_and_distinct_send_loss_stops_and_closes_without_replay(self):
        for boundary in range(1,9):
            call,conn,_response,factory,resolver,checkpoint,send=self.setup_wire()
            checkpoint.side_effect=[None]*(boundary-1)+[PermissionDenied]
            with self.subTest(boundary=boundary),self.assertRaises(PermissionDenied):call()
            if boundary<=4:factory.assert_not_called()
            else:conn.close.assert_called_once()
            if boundary<=5:conn.request.assert_not_called();send.assert_not_called()
            else:conn.request.assert_called_once();send.assert_called_once()
            self.assertLessEqual(resolver.call_count,2)
        call,conn,_response,_factory,_resolver,_checkpoint,send=self.setup_wire();send.side_effect=PermissionDenied
        with self.assertRaises(PermissionDenied):call()
        conn.request.assert_not_called();conn.close.assert_called_once();send.assert_called_once()

    def test_all_target_and_provider_addresses_must_be_public_before_connected_or_send(self):
        for side_effect in ([['127.0.0.1']],[['93.184.216.34','10.0.0.1']], [['93.184.216.34'],['93.184.216.34','169.254.169.254']]):
            call,conn,_response,factory,resolver,_checkpoint,send=self.setup_wire();resolver.side_effect=side_effect
            with self.assertRaises(PerformanceTransportError) as raised:call()
            self.assertEqual(raised.exception.category,"egress_denied");factory.assert_not_called();send.assert_not_called();conn.request.assert_not_called()

    def test_strict_complete_json_headers_length_utf8_single_gzip_and_limits(self):
        body=json.dumps(lab_fixtures.CompetitorLabTests().payload()).encode()
        base=f"Content-Length: {len(body)}\r\nContent-Type: application/json\r\n".encode()
        for fields in (base+b"Content-Length: 0\r\n",base+b"Content-Type: application/json\r\n",base+b"Transfer-Encoding: chunked\r\n",
            base+b"Trailer: other\r\n",base+b"Content-Range: bytes 0-1/9\r\n",base+b"Content-Encoding: br\r\n",
            b"Content-Type: application/json\r\n", f"Content-Length: {len(body)}\r\nContent-Type: application/json; charset=latin-1\r\n".encode()):
            call,conn,response,*_=self.setup_wire(body,fields=fields)
            with self.subTest(fields=fields),self.assertRaises(PerformanceTransportError):call()
            response.read1.assert_not_called();conn.close.assert_called_once()
        compressed=gzip.compress(body)
        for raw,length,encoding in ((body,len(body)+1,"identity"),(compressed[:-1],len(compressed)-1,"gzip"),
            (compressed+gzip.compress(b"tail"),len(compressed+gzip.compress(b"tail")),"gzip"),
            (compressed+b"tail",len(compressed)+4,"gzip"),(gzip.compress(b"x"*(evidence.MAX_BODY_BYTES+1)),len(gzip.compress(b"x"*(evidence.MAX_BODY_BYTES+1))),"gzip"),
            (b"\xff",1,"identity"),(b'{"id":"a","id":"b"}',19,"identity"),(b'{"ignored":NaN}',15,"identity")):
            fields=f"Content-Length: {length}\r\nContent-Type: application/json\r\nContent-Encoding: {encoding}\r\n".encode()
            call,conn,*_=self.setup_wire(raw,fields=fields)
            with self.subTest(raw_size=len(raw)),self.assertRaises(PerformanceTransportError):call()
            conn.close.assert_called_once()

    def test_status_tls_network_errors_are_categorical_private_closed_and_never_retried(self):
        for status,category in (("302 Found","redirect_denied"),("429 Limited","quota_limited"),("503 Error","provider_unavailable"),("403 Forbidden","provider_request_rejected")):
            call,conn,response,*_=self.setup_wire(b"private provider secret",status=status)
            with self.subTest(status=status),self.assertRaises(PerformanceTransportError) as raised:call()
            self.assertEqual(str(raised.exception),category);conn.request.assert_called_once();response.read1.assert_not_called();conn.close.assert_called_once()
        for error,category in ((ssl.SSLCertVerificationError("private tls"),"tls_verification_failed"),(TimeoutError("private timeout"),"timeout"),(OSError("private network"),"network_error")):
            call,conn,_response,_factory,_resolver,_checkpoint,send=self.setup_wire();conn.connect.side_effect=error
            with self.subTest(category=category),self.assertRaises(PerformanceTransportError) as raised:call()
            self.assertEqual(str(raised.exception),category);conn.request.assert_not_called();send.assert_not_called();conn.close.assert_called_once()

    def test_total_deadline_survives_target_dns_connected_read_and_projection(self):
        for boundary in range(1,9):
            now=[0];call,conn,_response,_factory,_resolver,checkpoint,send=self.setup_wire(clock=lambda:now[0]);seen=[0]
            def expired():
                seen[0]+=1
                if seen[0]==boundary:now[0]=31
            checkpoint.side_effect=expired
            with self.subTest(boundary=boundary),self.assertRaises(PerformanceTransportError) as raised:call()
            self.assertEqual(raised.exception.category,"timeout")
            if boundary<=5:conn.request.assert_not_called();send.assert_not_called()
            else:conn.request.assert_called_once();conn.close.assert_called_once()

        now=[0];call,conn,_response,factory,_resolver,checkpoint,send=self.setup_wire(clock=lambda:now[0])
        def target_time():
            if checkpoint.call_count==2:now[0]=6
        checkpoint.side_effect=target_time
        with self.assertRaises(PerformanceTransportError) as raised:call(_deadline=5)
        self.assertEqual(raised.exception.category,"timeout");factory.assert_not_called();send.assert_not_called()

    def test_returned_exact_uri_device_and_runtime_failure_never_fallback_to_old_or_field_data(self):
        for key in ("id","requestedUrl","finalUrl"):
            payload=lab_fixtures.CompetitorLabTests().payload()
            target=payload if key=="id" else payload["lighthouseResult"];target[key]="https://other.example.invalid/a"
            call,conn,*_=self.setup_wire(json.dumps(payload).encode())
            with self.assertRaises(PerformanceTransportError) as raised:call()
            self.assertEqual(raised.exception.category,"malformed_response");conn.request.assert_called_once();conn.close.assert_called_once()
        payload=lab_fixtures.CompetitorLabTests().payload();payload["lighthouseResult"]["runtimeError"]={"code":"private","message":"private"}
        call,conn,*_=self.setup_wire(json.dumps(payload).encode());result=call()
        self.assertEqual((result["state"],result["lab"]),("unavailable",None));self.assertNotIn("private",json.dumps(result));conn.close.assert_called_once()
