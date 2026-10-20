"""D122 offline JSONL parser. Returns minimized derived evidence only."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from tenancy.models import normalize_origin

METHOD = "bot-log-jsonl-v1"
MAX_BYTES = 1024 * 1024
MAX_ROWS = 1000
MAX_LINE_BYTES = 8192
MAX_GROUPS = 100
MAX_SUMMARY_BYTES = 24 * 1024  # Leaves room for scope/authorization in existing 32 KiB job snapshots.
AGENTS = ("OAI-SearchBot", "GPTBot", "ChatGPT-User")
LIMITS = "Unverified UA claims/request counts, not bot identity, analytics visits/users, indexing, citations or training membership. Partial absence is not never visited; overlapping imports cannot be summed as complete traffic."


class BotLogError(ValueError):
    """Categorical only: never includes a log line, path, identifier or UA."""


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BotLogError("duplicate_json_key")
        result[key] = value
    return result


def _nonfinite(_value):
    raise BotLogError("invalid_json_number")


def _safe_text(value, limit):
    return (type(value) is str and 0 < len(value) <= limit
        and not any(ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in value))


def parse_bot_logs(content, *, origin, window_start, window_end, known_urls=(), now=None):
    """Caller must authorize current verified origin and inventory before persistence."""
    now = now or datetime.now(timezone.utc)
    if (not all(isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
                for value in (window_start, window_end, now))
        or not window_start < window_end <= now or window_end - window_start > timedelta(days=7)):
        raise BotLogError("invalid_coverage_window")
    start, end = window_start.astimezone(timezone.utc), window_end.astimezone(timezone.utc)
    try:
        if not _safe_text(origin, 253) or normalize_origin(origin) != origin:
            raise BotLogError("invalid_origin")
    except (ValidationError, ValueError):
        raise BotLogError("invalid_origin") from None
    if type(content) is not bytes or not content or len(content) > MAX_BYTES:
        raise BotLogError("invalid_upload_size")
    if type(known_urls) not in {list, tuple, set, frozenset} or len(known_urls) > 200:
        raise BotLogError("invalid_inventory")
    inventory = {}
    for url in known_urls:
        if not _safe_text(url, 512):
            raise BotLogError("invalid_inventory")
        try:
            parsed = urlsplit(url)
        except ValueError:
            raise BotLogError("invalid_inventory") from None
        if (parsed.scheme + "://" + parsed.netloc != origin or parsed.query or parsed.fragment
            or parsed.username is not None or parsed.password is not None):
            raise BotLogError("invalid_inventory")
        inventory[parsed.path or "/"] = url
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise BotLogError("invalid_utf8") from None
    groups, rows = {}, 0
    for line in text.split("\n"):
        if not line.strip():
            continue
        if len(line.encode()) > MAX_LINE_BYTES:
            raise BotLogError("line_limit")
        rows += 1
        if rows > MAX_ROWS:
            raise BotLogError("row_limit")
        try:
            row = json.loads(line, object_pairs_hook=_json_object, parse_constant=_nonfinite)
        except BotLogError:
            raise
        except (ValueError, TypeError, RecursionError):
            raise BotLogError("invalid_json") from None
        if type(row) is not dict or not {"timestamp", "origin", "target", "status", "user_agent"} <= set(row):
            raise BotLogError("invalid_row_fields")
        if row["origin"] != origin:
            raise BotLogError("foreign_origin")
        if (not _safe_text(row["timestamp"], 40) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", row["timestamp"])):
            raise BotLogError("invalid_timestamp")
        try:
            observed = datetime.fromisoformat(row["timestamp"]).astimezone(timezone.utc)
        except (ValueError, OverflowError):
            raise BotLogError("invalid_timestamp") from None
        if not start <= observed < end:
            raise BotLogError("outside_coverage_window")
        target, ua, status = row["target"], row["user_agent"], row["status"]
        if (not _safe_text(target, 2048) or not target.startswith("/") or target.startswith("//") or "\\" in target
            or not _safe_text(ua, 500) or type(status) is not int or not 100 <= status <= 599):
            raise BotLogError("invalid_request_fields")
        # Never retain arbitrary log paths, query/fragment values or the full UA.
        url = inventory.get(urlsplit(target).path)
        matches = [agent for agent in AGENTS if re.search(r"(?<![\w-])" + re.escape(agent) + r"(?![\w-])", ua)]
        agent = matches[0] if len(matches) == 1 else "other_unclassified"
        key = (agent, url)
        if key not in groups:
            if len(groups) >= MAX_GROUPS:
                raise BotLogError("group_limit")
            groups[key] = {"agent": agent, "identity": "user_agent_only_unverified", "known_url": url,
                "url_scope": "authorized_existing_inventory" if url else "unmatched_path_not_retained",
                "request_count": 0, "status_counts": {}, "first_seen": observed, "last_seen": observed}
        group = groups[key]
        group["request_count"] += 1
        code = str(status)
        group["status_counts"][code] = group["status_counts"].get(code, 0) + 1
        group["first_seen"] = min(group["first_seen"], observed)
        group["last_seen"] = max(group["last_seen"], observed)
    if not rows:
        raise BotLogError("empty_log")
    output = {"method": METHOD, "origin": origin, "source_sha256": sha256(content).hexdigest(),
        "window": {"start": start.isoformat(), "end": end.isoformat(), "timezone": "UTC", "end_exclusive": True},
        "coverage": "partial_customer_supplied_logs", "rows_seen": rows,
        "groups": [{**row, "first_seen": row["first_seen"].isoformat(), "last_seen": row["last_seen"].isoformat()}
                   for _, row in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1] or ""))],
        "limits": LIMITS}
    if len(json.dumps(output, allow_nan=False).encode()) > MAX_SUMMARY_BYTES:
        raise BotLogError("summary_limit")
    return output


def validate_summary(value):
    """Allowlist every durable field; a direct job/model path cannot stage raw logs."""
    def reject():
        raise ValidationError("Only validated minimized bot-log evidence may be staged.")

    def utc(value):
        if not _safe_text(value, 40):
            reject()
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0) or parsed.isoformat() != value:
                reject()
            return parsed
        except (ValueError, OverflowError):
            reject()

    if type(value) is not dict or set(value) != {"method", "origin", "source_sha256", "window", "coverage", "rows_seen", "groups", "limits"}:
        reject()
    if (value["method"] != METHOD or value["coverage"] != "partial_customer_supplied_logs" or value["limits"] != LIMITS
        or not _safe_text(value["source_sha256"], 64) or not re.fullmatch(r"[0-9a-f]{64}", value["source_sha256"])
        or type(value["rows_seen"]) is not int or not 1 <= value["rows_seen"] <= MAX_ROWS):
        reject()
    try:
        if not _safe_text(value["origin"], 253) or normalize_origin(value["origin"]) != value["origin"]:
            reject()
    except (ValueError, ValidationError):
        reject()
    window = value["window"]
    if (type(window) is not dict or set(window) != {"start", "end", "timezone", "end_exclusive"}
        or window["timezone"] != "UTC" or window["end_exclusive"] is not True):
        reject()
    start, end = utc(window["start"]), utc(window["end"])
    if not start < end <= datetime.now(timezone.utc) or end - start > timedelta(days=7):
        reject()
    if type(value["groups"]) is not list or not 1 <= len(value["groups"]) <= MAX_GROUPS:
        reject()
    seen, count = set(), 0
    for row in value["groups"]:
        if type(row) is not dict or set(row) != {"agent", "identity", "known_url", "url_scope", "request_count", "status_counts", "first_seen", "last_seen"}:
            reject()
        if (type(row["agent"]) is not str or row["agent"] not in (*AGENTS, "other_unclassified")
            or row["identity"] != "user_agent_only_unverified" or type(row["request_count"]) is not int
            or not 1 <= row["request_count"] <= MAX_ROWS):
            reject()
        url = row["known_url"]
        if url is not None:
            if not _safe_text(url, 512):
                reject()
            try:
                parts = urlsplit(url)
                if (parts.scheme + "://" + parts.netloc != value["origin"] or parts.query or parts.fragment
                    or parts.username is not None or parts.password is not None or not parts.path.startswith("/")):
                    reject()
            except ValueError:
                reject()
        if row["url_scope"] != ("authorized_existing_inventory" if url else "unmatched_path_not_retained"):
            reject()
        identity = (row["agent"], url)
        if identity in seen:
            reject()
        seen.add(identity)
        first, last = utc(row["first_seen"]), utc(row["last_seen"])
        codes = row["status_counts"]
        if (not start <= first <= last < end or type(codes) is not dict or not codes
            or any(type(code) is not str or not re.fullmatch(r"[1-5][0-9]{2}", code)
                   or type(total) is not int or not 1 <= total <= MAX_ROWS for code, total in codes.items())
            or sum(codes.values()) != row["request_count"]):
            reject()
        count += row["request_count"]
    if count != value["rows_seen"]:
        reject()
    if len(json.dumps(value, allow_nan=False).encode()) > MAX_SUMMARY_BYTES:
        reject()
    return value
