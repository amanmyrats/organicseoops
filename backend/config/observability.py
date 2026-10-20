import json
import logging
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4


_request_id = ContextVar("request_id", default=None)
_valid_request_id = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,63}").fullmatch
_sensitive_key = (
    r"authorization|proxy[-_]?authorization|cookie|set[-_]?cookie|api[-_]?key|"
    r"access[-_]?token|refresh[-_]?token|id[-_]?token|token|client[-_]?secret|"
    r"password|secret|sessionid|csrf(?:middleware)?token|authorization[-_]?code|"
    r"oauth[-_]?code|code|state|sig|receipt[-_]?proof|proof|x[-_]?amz[-_]?(?:credential|security[-_]?token|signature)|signature"
)
_header_secret = re.compile(
    rf"(?i)\b(authorization|proxy[-_]?authorization|cookie|set[-_]?cookie)\b"
    r"(\s*[:=]\s*)[^\r\n]*"
)
_value_secret = re.compile(
    rf"(?i)([\"']?(?:{_sensitive_key})[\"']?)(\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;&}\]]+)"
)
_bearer_secret = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_report_link_secret = re.compile(r"(/api/reports/shared/)[A-Za-z0-9_-]{43}(?=[/?#\s\"'])")
_extra_fields = (
    "duration_ms", "error_type", "job_id", "method", "provider",
    "provider_request_id", "status_code",
)


def redact(value):
    text = str(value)
    text = _report_link_secret.sub(r"\1[REDACTED]", text)
    text = _value_secret.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    text = _bearer_secret.sub("Bearer [REDACTED]", text)
    return _header_secret.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": redact(record.getMessage()),
            "request_id": getattr(record, "request_id", None) or _request_id.get(),
        }
        for field in _extra_fields:
            if hasattr(record, field):
                value = getattr(record, field)
                payload[field] = redact(value) if isinstance(value, str) else value
        if record.exc_info:
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps({key: value for key, value in payload.items() if value is not None}, separators=(",", ":"))


class SafeRequestLogFilter(logging.Filter):
    def filter(self, record):
        request = getattr(record, "request", None)
        if request is not None:
            record.request_id = getattr(request, "_organicseoops_request_id", None)
            message = record.getMessage()
            paths = {getattr(request, "path", "")}
            get_full_path = getattr(request, "get_full_path", None)
            if callable(get_full_path):
                paths.add(get_full_path())
            if not any(paths) and record.name == "django.server":
                request_line = str(record.args[0]) if record.args else ""
                method = request_line.partition(" ")[0]
                record.msg = f"{method if re.fullmatch(r'[A-Z]{1,16}', method) else 'request'} [PATH]"
                record.args = ()
                return True
            for path in sorted(filter(None, paths), key=len, reverse=True):
                if path:
                    message = message.replace(path, "[PATH]")
            record.msg = message
            record.args = ()
        return True


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = logging.getLogger("organicseoops.request")

    def __call__(self, request):
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if _valid_request_id(supplied) else uuid4().hex
        request._organicseoops_request_id = request_id
        token = _request_id.set(request_id)
        started = monotonic()
        try:
            response = self.get_response(request)
            response.headers["X-Request-ID"] = request_id
            self.logger.info(
                "request.complete",
                extra={
                    "duration_ms": round((monotonic() - started) * 1000),
                    "method": request.method,
                    "status_code": response.status_code,
                },
            )
            return response
        except Exception as error:
            self.logger.error(
                "request.failed",
                extra={"error_type": type(error).__name__, "method": request.method},
            )
            raise
        finally:
            _request_id.reset(token)
