import base64
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


PROTOCOL_VERSION = 1
METHOD_VERSION = "playwright-1.63.0-chromium-v1"
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_SPOOL_BYTES = 3 * 1024 * 1024
MAX_BLOCKED_REQUESTS = 100
STALE_SPOOL_SECONDS = 120
CLEANUP_INTERVAL_SECONDS = 30
REQUEST_DIR = Path("/var/lib/organicseoops/render-requests")
RESULT_DIR = Path("/var/lib/organicseoops/render-results")
UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.json"
UUID_FILE = re.compile(UUID_PATTERN).fullmatch
TEMP_FILE = re.compile(rf"\.{UUID_PATTERN}\.(?:[0-9]+|[0-9a-f]{{16}})\.tmp").fullmatch
HEX64 = re.compile(r"[0-9a-f]{64}").fullmatch


class InvalidRequest(Exception):
    pass


def canonical_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_request(value):
    fields = {
        "protocol", "request_id", "token", "source_hash", "method_version", "base_url",
        "deadline_ms", "html_b64", "request_hash",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise InvalidRequest("fields")
    if value["protocol"] != PROTOCOL_VERSION or value["method_version"] != METHOD_VERSION:
        raise InvalidRequest("version")
    if not UUID_FILE(f"{value['request_id']}.json") or not re.fullmatch(r"[0-9a-f]{64}", value["token"]):
        raise InvalidRequest("identity")
    if not HEX64(value["source_hash"]) or not HEX64(value["request_hash"]):
        raise InvalidRequest("hash")
    unsigned = {key: item for key, item in value.items() if key != "request_hash"}
    if canonical_hash(unsigned) != value["request_hash"]:
        raise InvalidRequest("request_hash")
    if type(value["deadline_ms"]) is not int or value["deadline_ms"] > int(time.time() * 1000) + 30000:
        raise InvalidRequest("deadline")
    if not isinstance(value["base_url"], str) or not value["base_url"].startswith(("http://", "https://")):
        raise InvalidRequest("base_url")
    try:
        html = base64.b64decode(value["html_b64"], validate=True)
    except (TypeError, ValueError):
        raise InvalidRequest("html") from None
    if not html or len(html) > MAX_HTML_BYTES or hashlib.sha256(html).hexdigest() != value["source_hash"]:
        raise InvalidRequest("source_hash")
    try:
        return html.decode("utf-8", errors="strict")
    except UnicodeError:
        raise InvalidRequest("encoding") from None


def result_base(request):
    return {
        "protocol": request.get("protocol"),
        "request_id": request.get("request_id"),
        "token": request.get("token"),
        "request_hash": request.get("request_hash"),
        "source_hash": request.get("source_hash"),
        "method_version": request.get("method_version"),
    }


def sanitize_url(value):
    try:
        parsed = urlsplit(str(value))
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname:
            return f"{scheme}:" if scheme else ""
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
    except ValueError:
        return ""
    return urlunsplit((scheme, netloc, parsed.path, "", ""))[:2048]


def render_child(request):
    html = validate_request(request)
    remaining_ms = request["deadline_ms"] - int(time.time() * 1000)
    if remaining_ms <= 0:
        raise TimeoutError
    from playwright.sync_api import sync_playwright

    blocked = []
    started = time.monotonic()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, chromium_sandbox=True)
        context = browser.new_context(service_workers="block", java_script_enabled=True)
        context.set_default_timeout(remaining_ms)

        def record(kind, url):
            if len(blocked) < MAX_BLOCKED_REQUESTS:
                blocked.append({"kind": kind, "url": sanitize_url(url)})

        def block_route(route):
            record("request", route.request.url)
            route.abort("blockedbyclient")

        def block_websocket(websocket):
            record("websocket", websocket.url)
            # Leaving the route disconnected creates a local mock; messages are discarded.
            websocket.on_message(lambda _message: None)

        context.route("**/*", block_route)
        context.route_web_socket("**/*", block_websocket)
        page = context.new_page()

        def close_popup(popup):
            record("popup", popup.url)
            popup.close()

        page.on("popup", close_popup)
        page.set_content(html, wait_until="domcontentloaded", timeout=remaining_ms)
        page.wait_for_timeout(min(250, max(1, request["deadline_ms"] - int(time.time() * 1000))))
        rendered = page.content().encode()
        context.close()
        browser.close()
    if len(rendered) > MAX_HTML_BYTES:
        raise MemoryError
    return {
        **result_base(request),
        "status": "partial" if blocked else "succeeded",
        "error_category": "external_resources_blocked" if blocked else "",
        "duration_ms": min(60000, int((time.monotonic() - started) * 1000)),
        "blocked_requests": blocked,
        "html_b64": base64.b64encode(rendered).decode("ascii"),
    }


def run_request(request):
    remaining = max(0.05, min(20, (request.get("deadline_ms", 0) - int(time.time() * 1000)) / 1000))
    process = subprocess.Popen(
        [sys.executable, __file__, "--child"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(
            json.dumps(request, separators=(",", ":")).encode(), timeout=remaining,
        )
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        return {**result_base(request), "status": "failed", "error_category": "deadline",
                "duration_ms": int(remaining * 1000), "blocked_requests": [], "html_b64": ""}
    if process.returncode or len(output) > MAX_SPOOL_BYTES:
        return {**result_base(request), "status": "failed", "error_category": "browser_failed",
                "duration_ms": 0, "blocked_requests": [], "html_b64": ""}
    try:
        result = json.loads(output)
    except (UnicodeError, json.JSONDecodeError):
        return {**result_base(request), "status": "failed", "error_category": "browser_failed",
                "duration_ms": 0, "blocked_requests": [], "html_b64": ""}
    return result


def directory_fd(path):
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def read_json(directory, filename):
    parent = directory_fd(directory)
    try:
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= MAX_SPOOL_BYTES:
                raise InvalidRequest("file")
            data = os.read(fd, MAX_SPOOL_BYTES + 1)
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    if len(data) > MAX_SPOOL_BYTES:
        raise InvalidRequest("size")
    try:
        value = json.loads(data)
    except (UnicodeError, json.JSONDecodeError):
        raise InvalidRequest("json") from None
    if not isinstance(value, dict):
        raise InvalidRequest("payload")
    return value


def write_json(directory, filename, value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if not 0 < len(data) <= MAX_SPOOL_BYTES:
        raise InvalidRequest("result_size")
    parent = directory_fd(directory)
    temporary = f".{filename}.{os.getpid()}.tmp"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, filename, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass
        os.close(parent)


def remove_file(directory, filename):
    parent = directory_fd(directory)
    try:
        try:
            os.unlink(filename, dir_fd=parent)
        except FileNotFoundError:
            pass
    finally:
        os.close(parent)


def cleanup_stale(directory, now=None):
    cutoff = (time.time() if now is None else now) - STALE_SPOOL_SECONDS
    for entry in os.scandir(directory):
        if not (UUID_FILE(entry.name) or TEMP_FILE(entry.name)):
            continue
        try:
            info = entry.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_mtime < cutoff:
            remove_file(directory, entry.name)


def serve():
    next_cleanup = 0
    while True:
        now = time.time()
        if now >= next_cleanup:
            cleanup_stale(REQUEST_DIR, now)
            cleanup_stale(RESULT_DIR, now)
            next_cleanup = now + CLEANUP_INTERVAL_SECONDS
        for entry in os.scandir(REQUEST_DIR):
            if not UUID_FILE(entry.name) or not entry.is_file(follow_symlinks=False):
                continue
            if (RESULT_DIR / entry.name).exists():
                continue
            try:
                request = read_json(REQUEST_DIR, entry.name)
                validate_request(request)
                result = run_request(request)
                write_json(RESULT_DIR, entry.name, result)
            except InvalidRequest:
                remove_file(REQUEST_DIR, entry.name)
            except OSError:
                continue
        time.sleep(0.05)


if __name__ == "__main__":
    if sys.argv[1:] == ["--child"]:
        try:
            value = json.loads(sys.stdin.buffer.read(MAX_SPOOL_BYTES + 1))
            output = render_child(value)
        except TimeoutError:
            output = {**result_base(value), "status": "failed", "error_category": "deadline",
                      "duration_ms": 0, "blocked_requests": [], "html_b64": ""}
        except (Exception, KeyboardInterrupt):
            sys.exit(1)
        sys.stdout.write(json.dumps(output, separators=(",", ":")))
    else:
        serve()
