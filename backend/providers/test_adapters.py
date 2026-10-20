import json
import os
import ssl
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from . import adapters
from .adapters import ProviderRequestError, create_response, post_json
from .models import AIModelCapability, AIProvider, AIProviderAccount
from .services import configure_model, create_provider, create_provider_account, require_model_capabilities, revoke_provider_account


class FakeHTTPResponse:
    def __init__(self, status, payload, headers=None):
        self.status = status
        self.data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.headers = headers or {}
        self.offset = 0

    def read(self, amount):
        chunk = self.data[self.offset:self.offset + amount]
        self.offset += len(chunk)
        return chunk

    def getheaders(self):
        return list(self.headers.items())


class FakeConnection:
    def __init__(self, response, calls, scheme, address, hostname, port, deadline, clock):
        calls.append(("connection", scheme, address, hostname, port, deadline))
        self.response = response
        self.calls = calls
        self.closed = False

    def request(self, method, target, **options):
        self.calls.append(("request", method, target, options))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class GuardedConnection(FakeConnection):
    def connect(self):
        self.calls.append(("connect",))


class ProviderAdapterTests(TestCase):
    def setUp(self):
        self.operator = get_user_model().objects.create_superuser("adapter-operator@example.com", "test-password")
        self.provider = create_provider(
            actor=self.operator,
            key="openai",
            name="OpenAI",
            kind=AIProvider.Kind.OPENAI,
            enabled=True,
        )
        self.account = create_provider_account(
            actor=self.operator,
            provider=self.provider,
            label="Platform",
            secret_reference="env:OPENAI_API_KEY",
        )
        self.model = configure_model(
            actor=self.operator,
            provider=self.provider,
            identifier="configured-model",
            name="Configured model",
            capabilities=[
                AIModelCapability.TEXT_GENERATION,
                AIModelCapability.STRUCTURED_OUTPUT,
                AIModelCapability.WEB_SEARCH,
            ],
            context_window=16_000,
            max_output_tokens=2_000,
            capability_source="https://platform.openai.com/docs/models/configured-model",
            capabilities_verified_at=timezone.now(),
            enabled=True,
        )

    def test_owning_guard_prevents_secret_resolution_and_post_parse_delivery_on_current_loss(self):
        options = {"account": self.account, "model": self.model, "prompt": "Original bounded evidence.",
            "max_output_tokens": 100}
        with patch("providers.adapters.resolve_provider_secret") as secret:
            for invalid in (False, 1, "guard", {}):
                with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                    create_response(**options, checkpoint=invalid)
            with self.assertRaises(PermissionDenied):
                create_response(**options, checkpoint=Mock(side_effect=PermissionDenied))
            secret.assert_not_called()

        payload = {"id": "resp_guarded", "status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": '{"title":"Original"}'}]}],
            "usage": {"input_tokens": 12, "output_tokens": 3}}
        schema = {"type": "object", "properties": {"title": {"type": "string"}},
            "required": ["title"], "additionalProperties": False}
        events, guards, connections = [], [], []

        def current():
            guards.append("guard")
            require_model_capabilities(self.model, {AIModelCapability.TEXT_GENERATION, AIModelCapability.STRUCTURED_OUTPUT})
            if not AIProviderAccount.objects.filter(pk=self.account.pk, state=AIProviderAccount.State.ACTIVE).exists():
                raise PermissionDenied

        def transport(**request):
            self.assertIs(request["checkpoint"], current)
            body = json.loads(request["body"])
            self.assertEqual(body["text"]["format"]["schema"], schema)
            self.assertFalse(body["store"])
            self.assertNotIn("runtime-secret", request["body"].decode())

            def factory(*args):
                connection = GuardedConnection(FakeHTTPResponse(200, payload), events, *args)
                connections.append(connection)
                return connection

            return post_json(**request, resolver=lambda *_args: ["8.8.8.8"], connection_factory=factory)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "runtime-secret"}):
            result = create_response(**options, output_schema=schema, transport=transport, checkpoint=current)
            self.assertEqual(result.structured, {"title": "Original"})
            self.assertEqual(len(guards), 6)
            self.assertTrue(connections[-1].closed)

            def parse_then_revoke(*args, **kwargs):
                result = original_parse(*args, **kwargs)
                revoke_provider_account(actor=self.operator, account=self.account)
                return result

            original_parse = adapters._parse_response
            with patch("providers.adapters._parse_response", side_effect=parse_then_revoke), self.assertRaises(PermissionDenied):
                create_response(**options, output_schema=schema, transport=transport, checkpoint=current)
            self.assertTrue(connections[-1].closed)
            self.assertEqual(sum(event[0] == "request" for event in events), 2)

    def test_native_response_uses_catalog_model_and_returns_safe_metadata(self):
        captured = {}

        def transport(**request):
            captured.update(request)
            return 200, "req_header", json.dumps({
                "id": "resp_safe",
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "answer"}]}],
                "usage": {"input_tokens": 12, "output_tokens": 3},
            }).encode()

        with patch.dict(os.environ, {"OPENAI_API_KEY": "runtime-secret"}, clear=False):
            response = create_response(
                account=self.account,
                model=self.model,
                prompt="Summarize this evidence.",
                max_output_tokens=100,
                transport=transport,
            )
        payload = json.loads(captured["body"])
        self.assertEqual(payload["model"], "configured-model")
        self.assertFalse(payload["store"])
        self.assertNotIn("runtime-secret", captured["body"].decode())
        self.assertEqual(captured["endpoint"], "https://api.openai.com/v1/responses")
        self.assertEqual((response.text, response.request_id, response.response_id), ("answer", "req_header", "resp_safe"))
        self.assertEqual((response.input_tokens, response.output_tokens), (12, 3))
        self.assertEqual(response.citations, ())

    def test_web_search_is_capability_gated_and_returns_only_safe_citations(self):
        captured = {}
        text = "A cited answer."

        def transport(**request):
            captured.update(request)
            return 200, "req_search", json.dumps({
                "id": "resp_search",
                "status": "completed",
                "output": [{"type": "message", "content": [{
                    "type": "output_text",
                    "text": text,
                    "annotations": [
                        {"type": "url_citation", "url": "https://source.example/article?id=1", "title": "Source", "start_index": 0, "end_index": 7},
                        {"type": "url_citation", "url": "https://127.0.0.1/private", "title": "Private", "start_index": 0, "end_index": 7},
                        {"type": "url_citation", "url": "javascript:alert(1)", "title": "Unsafe", "start_index": 0, "end_index": 7},
                    ],
                }]}],
            }).encode()

        with patch.dict(os.environ, {"OPENAI_API_KEY": "runtime-secret"}, clear=False):
            response = create_response(
                account=self.account,
                model=self.model,
                prompt="Search for evidence.",
                max_output_tokens=100,
                web_search=True,
                transport=transport,
            )
        self.assertEqual(json.loads(captured["body"])["tools"], [{"type": "web_search"}])
        self.assertEqual(len(response.citations), 1)
        self.assertEqual(response.citations[0].url, "https://source.example/article?id=1")

        self.model.capabilities = [AIModelCapability.TEXT_GENERATION]
        self.model.save()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "runtime-secret"}, clear=False):
            with self.assertRaises(ValidationError):
                create_response(
                    account=self.account,
                    model=self.model,
                    prompt="Search for evidence.",
                    max_output_tokens=100,
                    web_search=True,
                    transport=lambda **_request: self.fail("unsupported search must not run"),
                )

    def test_structured_request_is_capability_gated_and_malformed_output_fails(self):
        schema = {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
            "additionalProperties": False,
        }
        requests = []

        def transport(**request):
            requests.append(json.loads(request["body"]))
            return 200, "req_structured", json.dumps({
                "id": "resp_structured",
                "status": "completed",
                "text": {"format": {"type": "json_schema"}},
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "{not-json"}]}],
            }).encode()

        with patch.dict(os.environ, {"OPENAI_API_KEY": "runtime-secret"}, clear=False):
            with self.assertRaisesRegex(ProviderRequestError, "malformed_response"):
                create_response(
                    account=self.account,
                    model=self.model,
                    prompt="Return a title.",
                    max_output_tokens=100,
                    output_schema=schema,
                    transport=transport,
                )
        self.assertEqual(requests[0]["text"]["format"]["schema"], schema)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "runtime-secret"}, clear=False):
            valid = create_response(
                account=self.account,
                model=self.model,
                prompt="Return a title.",
                max_output_tokens=100,
                output_schema=schema,
                transport=lambda **_request: (200, "req_valid", json.dumps({
                    "id": "resp_valid",
                    "status": "completed",
                    "output": [{"type": "message", "content": [{
                        "type": "output_text", "text": json.dumps({"title": "Valid"}),
                    }]}],
                }).encode()),
            )
        self.assertEqual(valid.structured, {"title": "Valid"})

        with patch.dict(os.environ, {"OPENAI_API_KEY": "runtime-secret"}, clear=False):
            with self.assertRaisesRegex(ProviderRequestError, "malformed_response"):
                create_response(
                    account=self.account,
                    model=self.model,
                    prompt="Return a title.",
                    max_output_tokens=100,
                    output_schema=schema,
                    transport=lambda **_request: (200, "req_shape", json.dumps({
                        "id": "resp_shape",
                        "status": "completed",
                        "output": [{"type": "message", "content": [{
                            "type": "output_text", "text": json.dumps({"unexpected": True}),
                        }]}],
                    }).encode()),
                )
        with self.assertRaises(ValidationError):
            create_response(
                account=self.account,
                model=self.model,
                prompt="Return a title.",
                max_output_tokens=100,
                output_schema={"type": "object", "$ref": "https://schemas.example/secret.json"},
                transport=lambda **_request: self.fail("transport must not run"),
            )
        with self.assertRaises(ValidationError):
            create_response(
                account=self.account,
                model=self.model,
                prompt="Return a title.",
                max_output_tokens=100,
                output_schema={
                    "type": "object",
                    "properties": {"score": {"type": "number", "enum": [float("nan")]}},
                    "required": ["score"],
                    "additionalProperties": False,
                },
                transport=lambda **_request: self.fail("invalid schema must not run"),
            )

        self.model.capabilities = [AIModelCapability.TEXT_GENERATION]
        self.model.save()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "runtime-secret"}, clear=False):
            with self.assertRaises(ValidationError):
                create_response(
                    account=self.account,
                    model=self.model,
                    prompt="Return a title.",
                    max_output_tokens=100,
                    output_schema=schema,
                    transport=lambda **_request: self.fail("transport must not run"),
                )

    def test_compatible_transport_pins_public_dns_and_does_not_follow_redirects(self):
        response = FakeHTTPResponse(200, {"status": "completed"}, {"x-request-id": "req_safe"})
        calls = []
        connections = []

        def factory(*args):
            connection = FakeConnection(response, calls, *args)
            connections.append(connection)
            return connection

        result = post_json(
            endpoint="https://compatible.example/v1/responses",
            body=b"{}",
            secret="runtime-secret",
            timeout=10,
            egress_policy=AIProvider.EgressPolicy.PUBLIC_HTTPS,
            resolver=lambda hostname, port, timeout: ["93.184.216.34"],
            connection_factory=factory,
        )
        self.assertEqual(result[:2], (200, "req_safe"))
        self.assertEqual(calls[0][2:4], ("93.184.216.34", "compatible.example"))
        request = calls[1]
        self.assertEqual((request[1], request[2]), ("POST", "/v1/responses"))
        self.assertEqual(request[3]["headers"]["Host"], "compatible.example")
        self.assertEqual(request[3]["headers"]["Authorization"], "Bearer runtime-secret")
        self.assertTrue(connections[0].closed)

        with self.assertRaisesRegex(ProviderRequestError, "egress_denied"):
            post_json(
                endpoint="https://compatible.example/v1/responses",
                body=b"{}",
                secret="runtime-secret",
                timeout=10,
                egress_policy=AIProvider.EgressPolicy.PUBLIC_HTTPS,
                resolver=lambda hostname, port, timeout: ["169.254.169.254"],
                connection_factory=lambda *_args: self.fail("private address must not connect"),
            )

    def test_compatible_adapter_uses_configured_endpoint_and_revocation_blocks_use(self):
        provider = create_provider(
            actor=self.operator,
            key="compatible",
            name="Compatible",
            kind=AIProvider.Kind.OPENAI_COMPATIBLE,
            base_url="https://compatible.example/v1",
            enabled=True,
        )
        account = create_provider_account(
            actor=self.operator,
            provider=provider,
            label="Compatible platform",
            secret_reference="env:OPENAI_COMPATIBLE_API_KEY",
        )
        model = configure_model(
            actor=self.operator,
            provider=provider,
            identifier="compatible-model",
            name="Compatible model",
            capabilities=[AIModelCapability.TEXT_GENERATION],
            capability_source="https://compatible.example/docs/models",
            capabilities_verified_at=timezone.now(),
            enabled=True,
        )
        calls = []
        with patch.dict(os.environ, {"OPENAI_COMPATIBLE_API_KEY": "runtime-secret"}, clear=False):
            create_response(
                account=account,
                model=model,
                prompt="Generate text.",
                max_output_tokens=100,
                transport=lambda **request: calls.append(request) or (200, "req_compatible", json.dumps({
                    "id": "resp_compatible",
                    "status": "completed",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
                }).encode()),
            )
        self.assertEqual(calls[0]["endpoint"], "https://compatible.example/v1/responses")
        revoke_provider_account(actor=self.operator, account=account)
        with patch.dict(os.environ, {"OPENAI_COMPATIBLE_API_KEY": "runtime-secret"}, clear=False):
            with self.assertRaises(PermissionDenied):
                create_response(
                    account=account,
                    model=model,
                    prompt="Generate text.",
                    max_output_tokens=100,
                    transport=lambda **_request: self.fail("revoked account must not call the provider"),
                )

    def test_rate_limit_refusal_and_hostile_request_ids_are_redacted(self):
        response = FakeHTTPResponse(
            429,
            {"error": {"message": "secret provider body"}},
            {"x-request-id": "unsafe\nsecret"},
        )
        with self.assertRaises(ProviderRequestError) as raised:
            post_json(
                endpoint="https://compatible.example/v1/responses",
                body=b"{}",
                secret="runtime-secret",
                timeout=10,
                egress_policy=AIProvider.EgressPolicy.PUBLIC_HTTPS,
                resolver=lambda hostname, port, timeout: ["93.184.216.34"],
                connection_factory=lambda *args: FakeConnection(response, [], *args),
            )
        self.assertEqual((raised.exception.category, raised.exception.retryable), ("rate_limited", True))
        self.assertEqual(raised.exception.request_id, "")
        self.assertNotIn("secret", str(raised.exception))

        with patch.dict(os.environ, {"OPENAI_API_KEY": "runtime-secret"}, clear=False):
            with self.assertRaisesRegex(ProviderRequestError, "refused") as refused:
                create_response(
                    account=self.account,
                    model=self.model,
                    prompt="Unsafe request.",
                    max_output_tokens=100,
                    transport=lambda **_request: (200, "req_refusal", json.dumps({
                        "id": "resp_refusal",
                        "status": "completed",
                        "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "details"}]}],
                        "usage": {"input_tokens": 10, "output_tokens": 1},
                    }).encode()),
                )
        self.assertEqual((refused.exception.request_id, refused.exception.input_tokens,
                          refused.exception.output_tokens), ("req_refusal", 10, 1))

    def test_transport_uses_one_deadline_and_redacts_invalid_credentials(self):
        now = [0]
        response = FakeHTTPResponse(200, {"status": "completed"})
        connections = []

        def resolver(hostname, port, timeout):
            self.assertEqual((hostname, port, timeout), ("api.openai.com", 443, 10))
            now[0] = 4
            return ["8.8.8.8"]

        def factory(*args):
            connection = FakeConnection(response, [], *args)
            original_request = connection.request

            def delayed_request(*request_args, **request_kwargs):
                original_request(*request_args, **request_kwargs)
                now[0] = 11

            connection.request = delayed_request
            connections.append(connection)
            return connection

        with self.assertRaises(ProviderRequestError) as raised:
            post_json(
                endpoint="https://api.openai.com/v1/responses",
                body=b"{}",
                secret="safe-token",
                timeout=10,
                egress_policy=AIProvider.EgressPolicy.OFFICIAL_OPENAI,
                resolver=resolver,
                connection_factory=factory,
                clock=lambda: now[0],
            )
        self.assertEqual((raised.exception.category, raised.exception.retryable), ("timeout", True))
        self.assertTrue(connections[0].closed)

        sentinel = "secret\nheader"
        with self.assertRaises(ProviderRequestError) as raised:
            post_json(
                endpoint="https://api.openai.com/v1/responses",
                body=b"{}",
                secret=sentinel,
                timeout=10,
                egress_policy=AIProvider.EgressPolicy.OFFICIAL_OPENAI,
                resolver=lambda *_args: self.fail("invalid credential must fail before DNS"),
            )
        self.assertEqual(raised.exception.category, "invalid_credential")
        self.assertNotIn(sentinel, str(raised.exception))
        self.assertNotIn(sentinel, repr(raised.exception))

    def test_transport_categories_bounds_and_non_finite_json_are_fixed(self):
        def request(response, connection_class=FakeConnection):
            return post_json(
                endpoint="https://compatible.example/v1/responses",
                body=b"{}",
                secret="safe-token",
                timeout=10,
                egress_policy=AIProvider.EgressPolicy.PUBLIC_HTTPS,
                resolver=lambda *_args: ["8.8.8.8"],
                connection_factory=lambda *args: connection_class(response, [], *args),
            )

        for status, category, retryable in (
            (400, "invalid_request", False),
            (408, "timeout", True),
            (429, "rate_limited", True),
            (500, "provider_unavailable", True),
        ):
            with self.subTest(status=status), self.assertRaises(ProviderRequestError) as raised:
                request(FakeHTTPResponse(status, {"error": "untrusted"}))
            self.assertEqual((raised.exception.category, raised.exception.retryable), (category, retryable))

        oversized = FakeHTTPResponse(200, b"", {"content-length": str(2 * 1024 * 1024 + 1)})
        with self.assertRaisesRegex(ProviderRequestError, "response_too_large"):
            request(oversized)
        encoded = FakeHTTPResponse(200, b"{}", {"content-encoding": "br"})
        with self.assertRaisesRegex(ProviderRequestError, "unsupported_content_encoding"):
            request(encoded)

        class TLSFailureConnection(FakeConnection):
            def request(self, *_args, **_kwargs):
                raise ssl.SSLCertVerificationError(1, "certificate verify failed")

        with self.assertRaises(ProviderRequestError) as raised:
            request(FakeHTTPResponse(200, {}), TLSFailureConnection)
        self.assertEqual((raised.exception.category, raised.exception.retryable), ("tls_verification_failed", False))

        number_schema = {
            "type": "object",
            "properties": {"score": {"type": "number"}},
            "required": ["score"],
            "additionalProperties": False,
        }
        with patch.dict(os.environ, {"OPENAI_API_KEY": "runtime-secret"}, clear=False):
            with self.assertRaisesRegex(ProviderRequestError, "malformed_response"):
                create_response(
                    account=self.account,
                    model=self.model,
                    prompt="Return a score.",
                    max_output_tokens=100,
                    output_schema=number_schema,
                    transport=lambda **_request: (200, "req_number", json.dumps({
                        "id": "resp_number",
                        "status": "completed",
                        "output": [{"type": "message", "content": [{
                            "type": "output_text", "text": '{"score": NaN}',
                        }]}],
                    }).encode()),
                )
