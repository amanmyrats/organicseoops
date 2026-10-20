import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from config.artifacts import read_private_artifact, save_private_artifact
from tenancy.artifacts import project_artifact_scope
from tenancy.customer_artifact_barrier import project_artifact_barrier
from tenancy.services import Action, require_project_action

from .crawler import PageParser
from .crawling import CrawlScope
from .models import (
    Artifact,
    CrawlPageSnapshot,
    CrawlRun,
    JobCancellation,
    RenderAttempt,
    RenderedPageSnapshot,
)


PROTOCOL_VERSION = 1
METHOD_VERSION = "playwright-1.63.0-chromium-v1"
MAX_RENDER_PAGES = 3
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_SPOOL_BYTES = 3 * 1024 * 1024
MAX_BLOCKED_REQUESTS = 100
RENDER_TIMEOUT_SECONDS = 15
REQUEST_DIR = Path("/var/lib/organicseoops/render-requests")
RESULT_DIR = Path("/var/lib/organicseoops/render-results")


class RenderProtocolError(Exception):
    pass


class VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored = 0
        self.truncated = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "template", "noscript"}:
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "template", "noscript"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data):
        if self.ignored:
            return
        if sum(map(len, self.parts)) < 16000:
            self.parts.append(data)
            self.truncated = sum(map(len, self.parts)) > 16000
        elif data:
            self.truncated = True

    def text(self):
        return " ".join(" ".join(self.parts).split())[:16000]


def render_page_snapshot(snapshot_id, *, request_dir=REQUEST_DIR, result_dir=RESULT_DIR,
                         timeout=RENDER_TIMEOUT_SECONDS, clock=time.monotonic, sleep=time.sleep):
    page = CrawlPageSnapshot.objects.select_related(
        "project", "raw_artifact", "crawl_run__job__actor",
    ).get(pk=snapshot_id)
    if page.error_category or not page.raw_artifact_id:
        raise ValidationError("Only observed HTML crawl pages can be rendered.")
    with project_artifact_barrier(page.project.organization_id, shared=True):
        _require_current_access(page)
        if JobCancellation.objects.filter(job=page.crawl_run.job).exists():
            raise ValidationError("The crawl no longer permits rendering this page.")
        raw_html = read_private_artifact(page.raw_artifact.key)
        if len(raw_html) > MAX_HTML_BYTES or hashlib.sha256(raw_html).hexdigest() != page.content_hash:
            raise ValidationError("Raw crawl evidence cannot be rendered safely.")
        try:
            raw_html.decode("utf-8", errors="strict")
        except UnicodeError:
            raise ValidationError("Rendering currently requires UTF-8 crawl evidence.") from None

        request_id = uuid4()
        token = secrets.token_hex(32)
        deadline_ms = int((time.time() + timeout) * 1000)
        request = {
            "protocol": PROTOCOL_VERSION,
            "request_id": str(request_id),
            "token": token,
            "source_hash": page.content_hash,
            "method_version": METHOD_VERSION,
            "base_url": page.final_url or page.requested_url,
            "deadline_ms": deadline_ms,
            "html_b64": base64.b64encode(raw_html).decode("ascii"),
        }
        request_hash = _payload_hash(request)
        request["request_hash"] = request_hash

        with transaction.atomic():
            CrawlRun.objects.select_for_update().get(pk=page.crawl_run_id)
            if RenderAttempt.objects.filter(crawl_page__crawl_run_id=page.crawl_run_id).count() >= MAX_RENDER_PAGES:
                raise ValidationError(f"A crawl run can render at most {MAX_RENDER_PAGES} selected pages.")
            attempt = RenderAttempt.objects.create(
                request_id=request_id,
                crawl_page=page,
                project=page.project,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                request_hash=request_hash,
                source_hash=page.content_hash,
                method_version=METHOD_VERSION,
            )

        filename = f"{request_id}.json"
        try:
            _write_spool(request_dir, filename, request)
            attempt.status = RenderAttempt.Status.RUNNING
            attempt.save(update_fields=["status"])
            deadline = clock() + timeout
            while clock() < deadline:
                denial = _render_denial(page)
                if denial:
                    return _fail_attempt(attempt, denial)
                try:
                    result = _read_spool(result_dir, filename)
                except FileNotFoundError:
                    sleep(min(0.05, max(0, deadline - clock())))
                    continue
                return _persist_result(attempt, page, raw_html, result, token)
            return _fail_attempt(attempt, "render_timeout")
        except (OSError, RenderProtocolError, UnicodeError, ValueError):
            return _fail_attempt(attempt, "render_protocol_failed")
        except Exception:
            return _fail_attempt(attempt, "render_handler_failed")
        finally:
            _remove_spool(request_dir, filename)
            _remove_spool(result_dir, filename)


def _persist_result(attempt, page, raw_html, result, token):
    required = {
        "protocol", "request_id", "token", "request_hash", "source_hash", "method_version",
        "status", "error_category", "duration_ms", "blocked_requests", "html_b64",
    }
    if set(result) != required:
        raise RenderProtocolError("Unexpected renderer result fields")
    expected = {
        "protocol": PROTOCOL_VERSION,
        "request_id": str(attempt.request_id),
        "request_hash": attempt.request_hash,
        "source_hash": attempt.source_hash,
        "method_version": attempt.method_version,
    }
    if any(result.get(key) != value for key, value in expected.items()):
        raise RenderProtocolError("Renderer result identity mismatch")
    if not hmac.compare_digest(result.get("token", ""), token):
        raise RenderProtocolError("Renderer result token mismatch")
    if hashlib.sha256(result["token"].encode()).hexdigest() != attempt.token_hash:
        raise RenderProtocolError("Renderer result token hash mismatch")
    if result["status"] not in {"succeeded", "partial", "failed"}:
        raise RenderProtocolError("Invalid renderer status")
    if type(result["duration_ms"]) is not int or not 0 <= result["duration_ms"] <= 60000:
        raise RenderProtocolError("Invalid renderer duration")
    blocked = result["blocked_requests"]
    if not isinstance(blocked, list) or len(blocked) > MAX_BLOCKED_REQUESTS or any(
        not isinstance(item, dict) or set(item) != {"kind", "url"}
        or item["kind"] not in {"request", "websocket", "popup"}
        or not isinstance(item["url"], str) or len(item["url"]) > 2048
        for item in blocked
    ):
        raise RenderProtocolError("Invalid blocked request evidence")
    blocked = [{"kind": item["kind"], "url": _sanitize_url(item["url"])} for item in blocked]
    denial = _render_denial(page)
    if denial:
        return _fail_attempt(attempt, denial)
    if result["status"] == "failed":
        category = result["error_category"]
        if category not in {"deadline", "browser_failed", "invalid_request", "resource_limit"}:
            category = "browser_failed"
        return _fail_attempt(attempt, category)
    try:
        rendered_html = base64.b64decode(result["html_b64"], validate=True)
    except (ValueError, TypeError):
        raise RenderProtocolError("Invalid rendered HTML") from None
    if not rendered_html or len(rendered_html) > MAX_HTML_BYTES:
        raise RenderProtocolError("Rendered HTML exceeds its limit")
    try:
        rendered_text = rendered_html.decode("utf-8", errors="strict")
        raw_text = raw_html.decode("utf-8", errors="strict")
    except UnicodeError:
        raise RenderProtocolError("Rendered HTML is not UTF-8") from None

    parser = PageParser()
    parser.feed(rendered_text)
    parsed, _discovered = parser.result(
        base_url=page.final_url or page.requested_url,
        scope=CrawlScope.for_project(page.project),
    )
    raw_visible = VisibleTextParser()
    raw_visible.feed(raw_text)
    rendered_visible = VisibleTextParser()
    rendered_visible.feed(rendered_text)
    visible_text = rendered_visible.text()
    rendered_hash = hashlib.sha256(rendered_html).hexdigest()
    denial = _render_denial(page)
    if denial:
        return _fail_attempt(attempt, denial)
    key = save_private_artifact(
        scope=f"{project_artifact_scope(page.project)}/jobs/{page.crawl_run.job_id}",
        content=rendered_html,
        content_type="text/html",
        key_stem=rendered_hash[:32],
    )
    artifact, _ = Artifact.objects.get_or_create(
        key=key,
        defaults={
            "job": page.crawl_run.job,
            "project": page.project,
            "content_type": "text/html",
            "size_bytes": len(rendered_html),
        },
    )
    comparison = {
        "observation_label": "OrganicSEOOps browser observation; not proof of search-engine rendering.",
        "completeness": "unknown" if blocked or result["status"] == "partial" else "complete_for_supplied_html",
        "content_changed": raw_visible.text() != visible_text,
        "title_changed": page.title != parsed["title"],
        "description_changed": page.meta_description != parsed["meta_description"],
        "headings_changed": page.headings != parsed["headings"],
        "canonical_changed": page.canonical_url != parsed["canonical_url"],
        "directives_changed": page.robots_directives != parsed["robots_directives"],
        "links_changed": page.links != parsed["links"],
    }
    with transaction.atomic():
        locked = RenderAttempt.objects.select_for_update().get(pk=attempt.pk)
        observation = RenderedPageSnapshot.objects.create(
            attempt=locked,
            crawl_page=page,
            project=page.project,
            rendered_artifact=artifact,
            content_hash=rendered_hash,
            text_hash=hashlib.sha256(visible_text.encode()).hexdigest(),
            text_excerpt=visible_text,
            title=parsed["title"],
            meta_description=parsed["meta_description"],
            headings=parsed["headings"],
            canonical_url=parsed["canonical_url"],
            robots_directives=parsed["robots_directives"],
            hreflang=parsed["hreflang"],
            links=parsed["links"],
            comparison=comparison,
            blocked_requests=blocked,
            duration_ms=result["duration_ms"],
            method_version=locked.method_version,
        )
        locked.status = (
            RenderAttempt.Status.PARTIALLY_SUCCEEDED
            if blocked or result["status"] == "partial"
            else RenderAttempt.Status.SUCCEEDED
        )
        locked.error_category = "external_resources_blocked" if blocked else ""
        locked.completed_at = timezone.now()
        locked.save(update_fields=["status", "error_category", "completed_at"])
    return observation


def _require_current_access(page):
    try:
        require_project_action(project=page.project, user=page.crawl_run.job.actor, action=Action.LAUNCH_JOB)
    except PermissionDenied:
        raise ValidationError("The crawl actor can no longer render this page.") from None


def _render_denial(page):
    if JobCancellation.objects.filter(job=page.crawl_run.job).exists():
        return "cancelled"
    try:
        require_project_action(project=page.project, user=page.crawl_run.job.actor, action=Action.LAUNCH_JOB)
    except PermissionDenied:
        return "actor_revoked"
    return ""


def _sanitize_url(value):
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname:
            return f"{scheme}:" if scheme else ""
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
    except ValueError:
        return ""
    return urlunsplit((scheme, netloc, parsed.path, "", ""))[:2048]


def _fail_attempt(attempt, category):
    attempt.status = RenderAttempt.Status.FAILED
    attempt.error_category = category
    attempt.completed_at = timezone.now()
    attempt.save(update_fields=["status", "error_category", "completed_at"])
    return attempt


def _payload_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _directory_fd(path):
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _write_spool(directory, filename, payload):
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if not 0 < len(data) <= MAX_SPOOL_BYTES:
        raise RenderProtocolError("Spool payload exceeds its limit")
    directory_fd = _directory_fd(directory)
    temporary = f".{filename}.{secrets.token_hex(8)}.tmp"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, filename, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


def _read_spool(directory, filename):
    directory_fd = _directory_fd(directory)
    try:
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= MAX_SPOOL_BYTES:
                raise RenderProtocolError("Unsafe spool file")
            data = b""
            while len(data) <= MAX_SPOOL_BYTES:
                chunk = os.read(fd, min(65536, MAX_SPOOL_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data += chunk
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)
    if len(data) > MAX_SPOOL_BYTES:
        raise RenderProtocolError("Spool file exceeds its limit")
    try:
        value = json.loads(data)
    except (UnicodeError, json.JSONDecodeError):
        raise RenderProtocolError("Invalid spool JSON") from None
    if not isinstance(value, dict):
        raise RenderProtocolError("Invalid spool payload")
    return value


def _remove_spool(directory, filename):
    try:
        directory_fd = _directory_fd(directory)
    except OSError:
        return
    try:
        try:
            os.unlink(filename, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
    finally:
        os.close(directory_fd)
