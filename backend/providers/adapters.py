import http.client
import json
import math
import re
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import ValidationError

from jobs.crawling import (
    FetchDenied,
    FetchError,
    FetchLimitExceeded,
    _connection_factory,
    _host_header,
    _read_body,
    _remaining,
    _resolve_public_addresses,
    _set_socket_timeout,
    _system_resolver,
)

from .models import AIModelCapability, AIProvider, AIProviderAccount, normalize_compatible_endpoint
from .services import require_model_capabilities, resolve_provider_secret


MAX_REQUEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_safe_request_id = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_safe_bearer_token = re.compile(r"[A-Za-z0-9._~+/-]{1,4096}=*")


class ProviderRequestError(Exception):
    def __init__(self, category, *, retryable=False, request_id="", input_tokens=None, output_tokens=None,
                 answer_text="", response_id="", response_model=""):
        self.category = category
        self.retryable = retryable
        self.request_id = request_id if _safe_request_id.fullmatch(request_id or "") else ""
        self.input_tokens = _token_count(input_tokens)
        self.output_tokens = _token_count(output_tokens)
        self.answer_text = answer_text if type(answer_text) is str and len(answer_text) <= 4000 else ""
        self.response_id = _clean_request_id(response_id)
        self.response_model = _clean_request_id(response_model)
        super().__init__(category)


@dataclass(frozen=True)
class ProviderCitation:
    url: str
    title: str
    start_index: int
    end_index: int


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    structured: dict | None
    citations: tuple[ProviderCitation, ...]
    request_id: str
    response_id: str
    input_tokens: int | None
    output_tokens: int | None
    response_model: str = ""


def create_response(
    *, account, model, prompt, max_output_tokens, output_schema=None, web_search=False, timeout=30,
    transport=None, organization=None, expected_revision=None, expected_model_revision=None, preserve_answer=False,
    checkpoint=None,
):
    if checkpoint is not None and not callable(checkpoint):
        raise ValidationError("Provider checkpoint must be callable.")
    if not isinstance(prompt, str) or not prompt or len(prompt) > 100_000:
        raise ValidationError("Prompt must contain between 1 and 100000 characters.")
    if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 1_000_000:
        raise ValidationError("Output token limit must be a positive bounded integer.")
    if type(timeout) not in {int, float} or not 1 <= timeout <= 120:
        raise ValidationError("Provider timeout must be between 1 and 120 seconds.")
    if type(web_search) is not bool:
        raise ValidationError("Web search must be a boolean.")
    if type(preserve_answer) is not bool or preserve_answer and (web_search or output_schema is not None):
        raise ValidationError("Answer evidence is available only for no-tool text requests.")
    required = {AIModelCapability.TEXT_GENERATION}
    if output_schema is not None:
        if not isinstance(output_schema, dict) or output_schema.get("type") != "object":
            raise ValidationError("Structured output requires an object JSON schema.")
        try:
            _check_schema(output_schema)
        except ValueError as error:
            raise ValidationError(str(error)) from None
        required.add(AIModelCapability.STRUCTURED_OUTPUT)
    if web_search:
        required.add(AIModelCapability.WEB_SEARCH)

    model = require_model_capabilities(model, required)
    if expected_model_revision is not None and model.updated_at.isoformat() != expected_model_revision:
        raise ValidationError("The selected model configuration changed.")
    if model.max_output_tokens is not None and max_output_tokens > model.max_output_tokens:
        raise ValidationError("Output token limit exceeds the selected model limit.")
    account = AIProviderAccount.objects.select_related("provider").filter(pk=getattr(account, "pk", None)).first()
    if account is None or account.provider_id != model.provider_id:
        raise ValidationError("Provider account and model must belong to the same provider.")
    if account.organization_id is not None and account.organization_id != getattr(organization, "pk", None):
        raise ValidationError("Provider account is unavailable for this organization.")

    payload = {
        "model": model.identifier,
        "input": prompt,
        "max_output_tokens": max_output_tokens,
        "store": False,
    }
    if output_schema is not None:
        payload["text"] = {
            "format": {
                "type": "json_schema",
                "name": "organicseoops_response",
                "strict": True,
                "schema": output_schema,
            },
        }
    if web_search:
        payload["tools"] = [{"type": "web_search"}]
    try:
        encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError):
        raise ValidationError("Provider request must be JSON serializable.") from None
    if len(encoded) > MAX_REQUEST_BYTES:
        raise ValidationError("Provider request is too large.")

    provider = model.provider
    endpoint = (
        "https://api.openai.com/v1/responses"
        if provider.kind == AIProvider.Kind.OPENAI
        else f"{provider.base_url}/responses"
    )
    if checkpoint is not None:
        checkpoint()
    secret = resolve_provider_secret(account, organization=organization, expected_revision=expected_revision)
    result = (transport or post_json)(
        endpoint=endpoint,
        body=encoded,
        secret=secret,
        timeout=timeout,
        egress_policy=provider.egress_policy,
        **({"checkpoint": checkpoint} if checkpoint is not None else {}),
    )
    response = _parse_response(result, output_schema=output_schema, include_citations=web_search,
                               preserve_answer=preserve_answer)
    if checkpoint is not None:
        checkpoint()
    return response


def post_json(
    *, endpoint, body, secret, timeout, egress_policy, resolver=_system_resolver,
    connection_factory=_connection_factory, clock=time.monotonic,
    checkpoint=None,
):
    """An opt-in owning guard raises on lost authority; it never receives secrets or response data."""
    if checkpoint is not None and not callable(checkpoint):
        raise ValidationError("Provider checkpoint must be callable.")
    parsed = urlsplit(endpoint)
    hostname = parsed.hostname
    request_id = ""
    connection = None
    deadline = clock() + timeout
    try:
        if (
            parsed.scheme != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or parsed.query
            or parsed.fragment
        ):
            raise FetchDenied("invalid_endpoint")
        if not isinstance(secret, str) or not _safe_bearer_token.fullmatch(secret):
            raise ProviderRequestError("invalid_credential")
        if egress_policy == AIProvider.EgressPolicy.OFFICIAL_OPENAI:
            if endpoint != "https://api.openai.com/v1/responses":
                raise FetchDenied("invalid_official_endpoint")
        elif egress_policy == AIProvider.EgressPolicy.PUBLIC_HTTPS and hostname:
            pass
        else:
            raise FetchDenied("invalid_egress_policy")
        if checkpoint is not None:
            checkpoint()
        addresses = _resolve_public_addresses(
            hostname,
            443,
            resolver=resolver,
            timeout=_remaining(deadline, clock),
        )
        if checkpoint is not None:
            checkpoint()
            _remaining(deadline, clock)
        connection = connection_factory("https", addresses[0], hostname, 443, deadline, clock)
        if checkpoint is not None:
            # No credentials or customer body bytes enter the socket before this
            # explicit pinned/default-validated TLS handshake and owning fence.
            connection.connect()
            _remaining(deadline, clock)
            checkpoint()
            _set_socket_timeout(connection, _remaining(deadline, clock))
        connection.request(
            "POST",
            parsed.path or "/",
            body=body,
            headers={
                "Authorization": f"Bearer {secret}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Host": _host_header(hostname, 443, "https"),
            },
        )
        _set_socket_timeout(connection, _remaining(deadline, clock))
        response = connection.getresponse()
        _set_socket_timeout(connection, _remaining(deadline, clock))
        headers = {name.lower(): value.strip() for name, value in response.getheaders()}
        request_id = _request_id(headers)
        data = _read_body(
            response,
            headers,
            max_bytes=MAX_RESPONSE_BYTES,
            deadline=deadline,
            clock=clock,
            connection=connection,
        )
        if checkpoint is not None:
            _remaining(deadline, clock)
            checkpoint()
            _remaining(deadline, clock)
        if not 200 <= response.status < 300:
            raise ProviderRequestError(
                _http_error_category(response.status),
                retryable=response.status in {408, 429} or response.status >= 500,
                request_id=request_id,
            )
        return response.status, request_id, data
    except ProviderRequestError:
        raise
    except FetchDenied:
        raise ProviderRequestError("egress_denied") from None
    except FetchLimitExceeded as error:
        raise ProviderRequestError(error.code, retryable=error.code == "timeout") from None
    except TimeoutError:
        raise ProviderRequestError("timeout", retryable=True) from None
    except ssl.SSLCertVerificationError:
        raise ProviderRequestError("tls_verification_failed") from None
    except FetchError as error:
        raise ProviderRequestError(error.code, retryable=error.code in {"dns_error", "network_error"}) from None
    except (ssl.SSLError, OSError, http.client.HTTPException):
        raise ProviderRequestError("network_error", retryable=True) from None
    except (TypeError, ValueError, UnicodeError):
        raise ProviderRequestError("invalid_request") from None
    finally:
        if connection is not None:
            connection.close()


def _parse_response(result, *, output_schema=None, include_citations=False, preserve_answer=False):
    _, header_request_id, body = result
    try:
        payload = json.loads(body, parse_constant=_reject_json_constant)
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ProviderRequestError("malformed_response", request_id=header_request_id) from None
    if not isinstance(payload, dict):
        raise ProviderRequestError("malformed_response", request_id=header_request_id)
    response_id = _clean_request_id(payload.get("id"))
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    input_tokens = _token_count(usage.get("input_tokens"))
    output_tokens = _token_count(usage.get("output_tokens"))
    evidence = {}
    if preserve_answer:
        # Only bounded answer message text, never arbitrary provider error bodies.
        output = payload.get("output")
        texts = []
        for item in output if isinstance(output, list) else []:
            if not isinstance(item, dict) or item.get("type") != "message" or not isinstance(item.get("content"), list):
                continue
            for content in item["content"]:
                if not isinstance(content, dict):
                    continue
                field = {"output_text": "text", "refusal": "refusal"}.get(content.get("type"))
                if field and type(content.get(field)) is str:
                    texts.append(content[field])
        text = "".join(texts)
        evidence = {"answer_text": text if len(text) <= 4000 else "", "response_id": response_id,
                    "response_model": _clean_request_id(payload.get("model"))}
    if payload.get("status") != "completed" or not isinstance(payload.get("output"), list):
        category = "refused" if _contains_refusal(payload.get("output")) else "incomplete_response"
        raise ProviderRequestError(category, request_id=header_request_id,
                                   input_tokens=input_tokens, output_tokens=output_tokens, **evidence)
    parts = []
    annotations = []
    text_length = 0
    for item in payload["output"]:
        if not isinstance(item, dict) or item.get("type") != "message" or not isinstance(item.get("content"), list):
            continue
        for content in item["content"]:
            if isinstance(content, dict) and content.get("type") == "refusal":
                raise ProviderRequestError("refused", request_id=header_request_id,
                                           input_tokens=input_tokens, output_tokens=output_tokens, **evidence)
            if isinstance(content, dict) and content.get("type") == "output_text" and isinstance(content.get("text"), str):
                parts.append(content["text"])
                if include_citations and isinstance(content.get("annotations"), list):
                    for annotation in content["annotations"]:
                        if isinstance(annotation, dict):
                            annotation = dict(annotation)
                            if type(annotation.get("start_index")) is int:
                                annotation["start_index"] += text_length
                            if type(annotation.get("end_index")) is int:
                                annotation["end_index"] += text_length
                        annotations.append(annotation)
                text_length += len(content["text"])
    if not parts:
        raise ProviderRequestError("malformed_response", request_id=header_request_id,
                                   input_tokens=input_tokens, output_tokens=output_tokens)
    text = "".join(parts)
    structured = None
    if output_schema is not None:
        try:
            structured = json.loads(text, parse_constant=_reject_json_constant)
        except (ValueError, json.JSONDecodeError, RecursionError):
            raise ProviderRequestError("malformed_response", request_id=header_request_id,
                                       input_tokens=input_tokens, output_tokens=output_tokens) from None
        if not _matches_schema(structured, output_schema):
            raise ProviderRequestError("malformed_response", request_id=header_request_id,
                                       input_tokens=input_tokens, output_tokens=output_tokens)
    citations = tuple(filter(None, (_citation(annotation, text) for annotation in annotations)))
    return ProviderResponse(
        text=text,
        structured=structured,
        citations=citations,
        request_id=header_request_id,
        response_id=response_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        response_model=_clean_request_id(payload.get("model")),
    )


def _contains_refusal(output):
    return isinstance(output, list) and any(
        isinstance(content, dict) and content.get("type") == "refusal"
        for item in output if isinstance(item, dict)
        for content in item.get("content", []) if isinstance(item.get("content"), list)
    )


def _check_schema(schema, *, depth=0, seen=None):
    if depth > 8 or not isinstance(schema, dict):
        raise ValueError("Structured output schema is invalid or too deeply nested.")
    seen = set() if seen is None else seen
    if id(schema) in seen:
        raise ValueError("Structured output schema cannot be recursive.")
    seen.add(id(schema))
    allowed = {"type", "description", "enum"}
    schema_type = schema.get("type")
    if schema_type == "object":
        allowed |= {"properties", "required", "additionalProperties"}
        properties = schema.get("properties")
        required = schema.get("required")
        if (
            not isinstance(properties, dict)
            or not properties
            or not all(isinstance(key, str) and key for key in properties)
            or required != list(properties)
            or schema.get("additionalProperties") is not False
        ):
            raise ValueError("Object schemas require every property and must reject additional properties.")
        for child in properties.values():
            _check_schema(child, depth=depth + 1, seen=seen)
    elif schema_type == "array":
        allowed.add("items")
        _check_schema(schema.get("items"), depth=depth + 1, seen=seen)
    elif schema_type not in {"string", "number", "integer", "boolean", "null"}:
        raise ValueError("Structured output schema uses an unsupported type.")
    if set(schema) - allowed:
        raise ValueError("Structured output schema uses unsupported keywords.")
    if "description" in schema and not isinstance(schema["description"], str):
        raise ValueError("Structured output schema descriptions must be strings.")
    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        raise ValueError("Structured output schema enums must be non-empty lists.")
    if "enum" in schema:
        typed_schema = {key: value for key, value in schema.items() if key != "enum"}
        if any(not _matches_schema(item, typed_schema) for item in schema["enum"]):
            raise ValueError("Structured output schema enum values must match their declared type.")
    seen.remove(id(schema))


def _matches_schema(value, schema):
    if "enum" in schema and value not in schema["enum"]:
        return False
    schema_type = schema["type"]
    if schema_type == "object":
        properties = schema["properties"]
        return (
            isinstance(value, dict)
            and set(value) == set(properties)
            and all(_matches_schema(value[key], child) for key, child in properties.items())
        )
    if schema_type == "array":
        return isinstance(value, list) and all(_matches_schema(item, schema["items"]) for item in value)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "number":
        return type(value) is int or type(value) is float and math.isfinite(value)
    if schema_type == "integer":
        return type(value) is int
    if schema_type == "boolean":
        return type(value) is bool
    return value is None


def _reject_json_constant(_value):
    raise ValueError("Non-finite JSON number")


def _citation(annotation, text):
    if not isinstance(annotation, dict) or annotation.get("type") != "url_citation":
        return None
    url = annotation.get("url")
    title = annotation.get("title")
    start = annotation.get("start_index")
    end = annotation.get("end_index")
    if (
        not isinstance(url, str)
        or len(url) > 2048
        or "\\" in url
        or any(ord(character) < 32 for character in url)
        or not isinstance(title, str)
        or not title
        or len(title) > 300
        or any(ord(character) < 32 for character in title)
        or type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(text)
    ):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.fragment:
            return None
        if parsed.query:
            normalize_compatible_endpoint(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")))
        else:
            normalize_compatible_endpoint(url)
    except (TypeError, ValidationError, ValueError):
        return None
    return ProviderCitation(url=url, title=title, start_index=start, end_index=end)


def _request_id(headers):
    return _clean_request_id(headers.get("x-request-id", ""))


def _clean_request_id(value):
    return value if isinstance(value, str) and _safe_request_id.fullmatch(value) else ""


def _token_count(value):
    return value if type(value) is int and 0 <= value <= 100_000_000 else None


def _http_error_category(status):
    return {
        400: "invalid_request",
        401: "authentication_failed",
        403: "permission_denied",
        408: "timeout",
        409: "provider_conflict",
        429: "rate_limited",
    }.get(status, "provider_unavailable" if status >= 500 else "provider_error")
