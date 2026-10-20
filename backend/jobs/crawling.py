import http.client
import io
import ipaddress
import json
import re
import select
import socket
import ssl
import subprocess
import sys
import time
import zlib
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import islice
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

from django.core.exceptions import ValidationError

from tenancy.models import normalize_origin


USER_AGENT = "OrganicSEOOpsBot/1.0"
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_DNS_SCRIPT = """import json, socket, sys
print(json.dumps([item[4][0] for item in socket.getaddrinfo(
    sys.argv[1], int(sys.argv[2]), socket.AF_UNSPEC, socket.SOCK_STREAM
)]))
"""


class FetchError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class FetchDenied(FetchError):
    pass


class FetchLimitExceeded(FetchError):
    pass


@dataclass(frozen=True)
class CrawlScope:
    hosts: frozenset[str]
    kind: str = "project"

    @classmethod
    def for_project(cls, project, *, competitor_origin=None):
        if competitor_origin is not None:
            try:
                competitor_origin = normalize_origin(competitor_origin)
                configured = set(project.configuration.competitor_origins)
            except (AttributeError, ValidationError):
                raise FetchDenied("competitor_not_selected") from None
            if competitor_origin not in configured:
                raise FetchDenied("competitor_not_selected")
            origins = [competitor_origin]
            kind = "competitor"
        else:
            origins = [project.canonical_origin, *project.domain_aliases.values_list("origin", flat=True)]
            kind = "project"
        hosts = frozenset(_origin_host(origin) for origin in origins)
        if not hosts:
            raise FetchDenied("empty_scope")
        return cls(hosts=hosts, kind=kind)

    def validate_url(self, value):
        if not isinstance(value, str) or not value or len(value) > 4096:
            raise FetchDenied("invalid_url")
        if "\\" in value or any(ord(character) < 32 for character in value):
            raise FetchDenied("invalid_url")
        try:
            parsed = urlsplit(value)
            scheme = parsed.scheme.lower()
            hostname = _normalize_hostname(parsed.hostname)
            port = parsed.port
        except (UnicodeError, ValueError):
            raise FetchDenied("invalid_url") from None
        expected_port = 443 if scheme == "https" else 80 if scheme == "http" else None
        if (
            expected_port is None
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or (port is not None and port != expected_port)
        ):
            raise FetchDenied("invalid_url")
        if hostname not in self.hosts:
            raise FetchDenied("outside_scope")
        host = f"[{hostname}]" if ":" in hostname else hostname
        path = quote(parsed.path or "/", safe="/%:@-._~!$&'()*+,;=")
        query = quote(parsed.query, safe="/%?:@-._~!$&'()*+,;=")
        normalized = urlunsplit((scheme, host, path, query, ""))
        if len(normalized) > 2048:
            raise FetchDenied("invalid_url")
        return normalized


@dataclass(frozen=True)
class RedirectHop:
    url: str
    status: int


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
    redirects: tuple[RedirectHop, ...] = ()
    header_observation: dict | None = None
    resource_observation: dict | None = None
    redirect_observation: dict | None = None
    observed_at: str | None = None


class _SocketReader(io.RawIOBase):
    def __init__(self, sock):
        super().__init__()
        self.sock = sock

    def readable(self):
        return True

    def readinto(self, buffer):
        return self.sock.recv_into(buffer)


class _DeadlineSocket:
    def __init__(self, sock, deadline, clock):
        self._sock = sock
        self._deadline = deadline
        self._clock = clock

    def _prepare(self):
        self._sock.settimeout(_remaining(self._deadline, self._clock))

    def sendall(self, data, flags=0):
        self._prepare()
        try:
            return self._sock.sendall(data, flags)
        except TimeoutError:
            raise FetchLimitExceeded("timeout") from None

    def recv_into(self, buffer, nbytes=0, flags=0):
        self._prepare()
        try:
            return self._sock.recv_into(buffer, nbytes, flags)
        except TimeoutError:
            raise FetchLimitExceeded("timeout") from None

    def settimeout(self, value):
        self._sock.settimeout(min(value, _remaining(self._deadline, self._clock)))

    def makefile(self, mode="r", buffering=None, **_kwargs):
        if mode != "rb":
            raise ValueError("Only binary reads are supported")
        raw = _SocketReader(self)
        if buffering == 0:
            return raw
        return io.BufferedReader(raw, buffer_size=buffering or io.DEFAULT_BUFFER_SIZE)

    def __getattr__(self, name):
        return getattr(self._sock, name)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, address, port, *, deadline, clock):
        super().__init__(address, port, timeout=_remaining(deadline, clock))
        self._deadline = deadline
        self._clock = clock

    def connect(self):
        try:
            sock = socket.create_connection(
                (self.host, self.port),
                _remaining(self._deadline, self._clock),
                self.source_address,
            )
        except TimeoutError:
            raise FetchLimitExceeded("timeout") from None
        self.sock = _DeadlineSocket(sock, self._deadline, self._clock)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, address, port, *, server_hostname, deadline, clock):
        super().__init__(
            address,
            port,
            timeout=_remaining(deadline, clock),
            context=ssl.create_default_context(),
        )
        self._server_hostname = server_hostname
        self._deadline = deadline
        self._clock = clock

    def connect(self):
        try:
            raw_socket = socket.create_connection(
                (self.host, self.port),
                _remaining(self._deadline, self._clock),
                self.source_address,
            )
        except TimeoutError:
            raise FetchLimitExceeded("timeout") from None
        tls_socket = None
        try:
            tls_socket = self._context.wrap_socket(
                raw_socket,
                server_hostname=self._server_hostname,
                do_handshake_on_connect=False,
            )
            tls_socket.setblocking(False)
            while True:
                _remaining(self._deadline, self._clock)
                try:
                    tls_socket.do_handshake()
                    break
                except ssl.SSLWantReadError:
                    readers, writers = [tls_socket], []
                except ssl.SSLWantWriteError:
                    readers, writers = [], [tls_socket]
                readable, writable, _ = select.select(
                    readers, writers, [], _remaining(self._deadline, self._clock)
                )
                if not readable and not writable:
                    raise FetchLimitExceeded("timeout")
            _remaining(self._deadline, self._clock)
            tls_socket.setblocking(True)
            self.sock = _DeadlineSocket(tls_socket, self._deadline, self._clock)
        except BaseException:
            (tls_socket if tls_socket is not None else raw_socket).close()
            raise


def _connection_factory(scheme, address, hostname, port, deadline, clock):
    if scheme == "https":
        return _PinnedHTTPSConnection(
            address,
            port,
            server_hostname=hostname,
            deadline=deadline,
            clock=clock,
        )
    return _PinnedHTTPConnection(address, port, deadline=deadline, clock=clock)


def _system_resolver(hostname, port, timeout):
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", _DNS_SCRIPT, hostname, str(port)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={},
        )
        if result.returncode or len(result.stdout) > 65536:
            raise FetchError("dns_error")
        addresses = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        raise FetchLimitExceeded("timeout") from None
    except (OSError, json.JSONDecodeError):
        raise FetchError("dns_error") from None
    if not isinstance(addresses, list) or any(not isinstance(item, str) for item in addresses):
        raise FetchError("dns_error")
    return addresses


class SafeFetcher:
    def __init__(
        self,
        scope,
        *,
        timeout=10,
        max_redirects=5,
        max_bytes=2 * 1024 * 1024,
        resolver=_system_resolver,
        connection_factory=_connection_factory,
        clock=time.monotonic,
    ):
        if timeout <= 0 or max_redirects < 0 or max_bytes <= 0:
            raise ValueError("Fetch limits must be positive")
        self.scope = scope
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.max_bytes = max_bytes
        self.resolver = resolver
        self.connection_factory = connection_factory
        self.clock = clock

    def observe_tls(self, origin, *, before_request, before_send, deadline=None):
        """One protected handshake only; HTTP and raw peer identities never leave this path."""
        from .passive_certificate import observe_peer_certificate_dates

        try:
            if (type(origin) is not str or not 1 <= len(origin) <= 255 or normalize_origin(origin) != origin
                or urlsplit(origin).scheme != "https" or urlsplit(origin).port is not None
                or self.scope.validate_url(origin + "/") != origin + "/"
                or not callable(before_request) or not callable(before_send)):
                raise ValueError
        except (ValueError, ValidationError):
            raise FetchDenied("invalid_tls_observation") from None
        deadline = min(self.clock() + self.timeout, deadline) if deadline is not None else self.clock() + self.timeout
        before_request(origin)
        hostname = urlsplit(origin).hostname
        addresses = _resolve_public_addresses(hostname, 443, resolver=self.resolver, timeout=_remaining(deadline, self.clock))
        before_send(origin)
        _remaining(deadline, self.clock)
        connection = self.connection_factory("https", addresses[0], hostname, 443, deadline, self.clock)
        try:
            connection.connect()
            _remaining(deadline, self.clock)
            before_send(origin)
            _remaining(deadline, self.clock)
            sock = connection.sock
            observed_at = datetime.now(UTC)
            dates = observe_peer_certificate_dates(sock.getpeercert(), observed_at=observed_at)
            version, cipher = sock.version(), sock.cipher()
            version = version if type(version) is str and version in {"TLSv1", "TLSv1.1", "TLSv1.2", "TLSv1.3"} else None
            cipher = {"name": cipher[0], "secret_bits": cipher[2]} if (
                type(cipher) is tuple and len(cipher) == 3 and type(cipher[0]) is str
                and 1 <= len(cipher[0]) <= 128 and re.fullmatch(r"[A-Za-z0-9_-]+", cipher[0])
                and type(cipher[2]) is int and 1 <= cipher[2] <= 512) else None
            result = {"method_version": "passive-tls-handshake-v1", "origin": origin,
                "observed_at": observed_at.isoformat(timespec="microseconds"), "certificate_dates": dates,
                "negotiated_tls": {"version": version, "cipher": cipher},
                "coverage": "one_default_context_hostname_chain_validated_handshake_only",
                "interpretation": "negotiated_parameters_not_all_supported_configuration_revocation_or_exploitability"}
            _remaining(deadline, self.clock)
            before_request(origin)
            _remaining(deadline, self.clock)
            return result
        except FetchError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException):
            raise FetchError("tls_observation_failed") from None
        finally:
            connection.close()

    def fetch(self, url, *, request_headers=None, before_request=None, before_send=None, deadline=None,
              observe_headers=False, observe_resources=False, observe_redirects=False, observe_http_redirects=False,
              static_document_type=None, redirect_chain_selection=None):
        deadline = min(self.clock() + self.timeout, deadline) if deadline is not None else self.clock() + self.timeout
        redirects = []
        current = self.scope.validate_url(url)
        if type(observe_headers) is not bool:
            raise FetchDenied("invalid_header_observation")
        if type(observe_resources) is not bool or observe_headers and observe_resources:
            raise FetchDenied("invalid_resource_observation")
        if type(observe_redirects) is not bool or observe_redirects and (observe_headers or observe_resources):
            raise FetchDenied("invalid_redirect_observation")
        if type(observe_http_redirects) is not bool or observe_http_redirects and (observe_headers or observe_resources or observe_redirects):
            raise FetchDenied("invalid_http_redirect_observation")
        if redirect_chain_selection is not None:
            from .passive_redirect_chain_source import MAX_TARGETS, validate_input
            try: redirect_chain_selection, _ = validate_input(redirect_chain_selection)
            except ValidationError: raise FetchDenied("invalid_redirect_chain_observation") from None
            if (url != redirect_chain_selection["url"] or request_headers is not None
                or observe_headers or observe_resources or observe_redirects or observe_http_redirects
                or static_document_type is not None or not callable(before_request) or not callable(before_send)):
                raise FetchDenied("invalid_redirect_chain_observation")
            for selected in [redirect_chain_selection["url"], *redirect_chain_selection["target_urls"]]:
                if self.scope.validate_url(selected) != selected: raise FetchDenied("invalid_redirect_chain_observation")
            chain_hops = []
            chain_limit = min(self.max_redirects, MAX_TARGETS)
        if static_document_type is not None:
            from .competitor_metadata import validate_url
            if (type(static_document_type) is not str or static_document_type not in {"text/plain", "text/html"}
                or observe_headers or observe_resources or observe_redirects or observe_http_redirects or request_headers is not None
                or not callable(before_request) or not callable(before_send)):
                raise FetchDenied("invalid_static_document")
            try: validate_url(url)
            except ValidationError: raise FetchDenied("invalid_static_document") from None
        if (observe_headers or observe_resources or observe_redirects) and (
            current != url or urlsplit(current).scheme != "https" or "?" in url or "#" in url
            or request_headers is not None or not callable(before_request) or not callable(before_send)
        ):
            raise FetchDenied("invalid_redirect_observation" if observe_redirects else "invalid_resource_observation" if observe_resources else "invalid_header_observation")
        if observe_http_redirects:
            from .passive_redirects import validate_http_source_url
            try: validate_http_source_url(url)
            except ValidationError: raise FetchDenied("invalid_http_redirect_observation") from None
            if current != url or request_headers is not None or not callable(before_request) or not callable(before_send):
                raise FetchDenied("invalid_http_redirect_observation")
        conditional_headers = _conditional_headers(request_headers)
        while True:
            if before_request is not None:
                before_request(current)
            remaining = _remaining(deadline, self.clock)
            parsed = urlsplit(current)
            port = 443 if parsed.scheme == "https" else 80
            addresses = _resolve_public_addresses(
                parsed.hostname, port, resolver=self.resolver, timeout=remaining
            )
            if before_send is not None:
                before_send(current)
            if observe_http_redirects or redirect_chain_selection is not None: _remaining(deadline, self.clock)
            connection = self.connection_factory(
                parsed.scheme,
                addresses[0],
                parsed.hostname,
                port,
                deadline,
                self.clock,
            )
            try:
                target = parsed.path or "/"
                if parsed.query:
                    target += f"?{parsed.query}"
                headers = {
                    "Host": _host_header(parsed.hostname, port, parsed.scheme),
                    "User-Agent": USER_AGENT,
                    "Accept": static_document_type or ("text/html" if observe_resources else "*/*"),
                    "Accept-Encoding": "gzip",
                    "Connection": "close",
                    **conditional_headers,
                }
                if before_send is not None:
                    # Establish pinned TCP/TLS first, then recheck current
                    # authority immediately before transmitting the GET.
                    connection.connect()
                    before_send(current)
                    if observe_resources or observe_redirects or observe_http_redirects or static_document_type is not None or redirect_chain_selection is not None:
                        _remaining(deadline, self.clock)
                connection.request(
                    "GET",
                    target,
                    headers=headers,
                )
                _set_socket_timeout(connection, _remaining(deadline, self.clock))
                response = connection.getresponse()
                _set_socket_timeout(connection, _remaining(deadline, self.clock))
                if redirect_chain_selection is not None:
                    from .passive_redirects import resolve_permitted_response_location
                    with response:
                        if (type(response.status) is not int or not 200 <= response.status <= 599
                            or response.msg.defects):
                            raise FetchError("response_headers_unavailable")
                        observed_at = datetime.now(UTC).isoformat(timespec="microseconds")
                        try:
                            resolved = resolve_permitted_response_location(selection=redirect_chain_selection,
                                current_url=current, status=response.status, fields=response.getheaders())
                        except ValidationError:
                            raise FetchError("response_headers_unavailable") from None
                        chain_hops.append({"url": current, "status": response.status, "observed_at": observed_at,
                            "response_location": resolved["response_location"], "target_state": resolved["state"]})
                        _remaining(deadline, self.clock)
                        before_request(current)
                        _remaining(deadline, self.clock)
                        state, target = resolved["state"], resolved["next_url"]
                        if target is not None:
                            if target in {hop["url"] for hop in chain_hops}: state = "redirect_loop"
                            elif len(chain_hops) > chain_limit: state = "redirect_limit"
                            else:
                                current = target
                                continue
                        observation = {"method_version": "passive-exact-redirect-chain-response-v1",
                            "hops": chain_hops, "state": state,
                            "coverage": "at_most_six_selected_original_header_responses_only",
                            "interpretation": "dated_exact_selected_responses_not_browser_behavior_current_availability_authenticated_http_identity_or_security_verdict"}
                        return FetchResponse(url=current, status=response.status, headers={}, body=b"",
                            redirect_observation=observation)
                if static_document_type is not None:
                    from .competitor_metadata import MAX_BODY_BYTES
                    with response:
                        if type(response.status) is not int or not 200 <= response.status <= 599 or response.msg.defects:
                            raise FetchError("static_document_unavailable")
                        body, document_headers = b"", {}
                        if response.status == 200:
                            framed_headers = _resource_response_headers(response, media_type=static_document_type)
                            body = _read_body(response, framed_headers, max_bytes=min(self.max_bytes, MAX_BODY_BYTES),
                                deadline=deadline, clock=self.clock, connection=connection, require_complete=True)
                            try: body.decode("utf-8-sig")
                            except UnicodeError: raise FetchError("static_document_unavailable") from None
                            document_headers = {"content-type": static_document_type}
                        observed_at = datetime.now(UTC).isoformat(timespec="microseconds")
                        _remaining(deadline, self.clock)
                        # Reuse the authority-only hook: before_request may
                        # additionally pace request starts and must not pace completion.
                        before_send(current)
                        _remaining(deadline, self.clock)
                        return FetchResponse(url=current, status=response.status, headers=document_headers, body=body,
                            observed_at=observed_at)
                if observe_resources:
                    from .passive_resources import MAX_BODY_BYTES, observe_static_resource_references
                    with response:
                        resource_headers = _resource_response_headers(response)
                        body = _read_body(response, resource_headers, max_bytes=min(self.max_bytes, MAX_BODY_BYTES),
                            deadline=deadline, clock=self.clock, connection=connection, require_complete=True)
                        try:
                            body.decode("utf-8-sig")
                        except UnicodeError:
                            raise FetchError("resource_body_unavailable") from None
                        observed_at = datetime.now(UTC).isoformat(timespec="microseconds")
                        observation = {"method_version": "passive-resource-response-v1", "observed_at": observed_at,
                            "resource_references": observe_static_resource_references(body, body_complete=True),
                            "coverage": "one_complete_length_framed_utf8_html_response_only",
                            "interpretation": "literal_candidates_not_browser_requests_or_whole_page_mixed_content_security"}
                        _remaining(deadline, self.clock)
                        before_request(current)
                        _remaining(deadline, self.clock)
                        return FetchResponse(url=current, status=response.status, headers={}, body=b"",
                                             resource_observation=observation)
                if observe_headers or observe_redirects or observe_http_redirects:
                    from .passive_headers import observe_response_headers
                    with response:
                        if (type(response.status) is not int or not 200 <= response.status <= 599
                            or response.msg.defects):
                            raise FetchError("response_headers_unavailable")
                        try:
                            if observe_redirects or observe_http_redirects:
                                from .passive_redirects import observe_response_location, observe_http_response_location
                                interpret = observe_http_response_location if observe_http_redirects else observe_response_location
                                observation = {"method_version": "passive-http-redirect-response-v1" if observe_http_redirects else "passive-redirect-response-v1",
                                    "observed_at": datetime.now(UTC).isoformat(timespec="microseconds"),
                                    "response_location": interpret(source_url=current, status=response.status, fields=response.getheaders()),
                                    "coverage": "one_original_first_http_response_only" if observe_http_redirects else "one_original_first_https_response_only",
                                    "interpretation": "plaintext_http_location_metadata_not_authenticated_identity_observed_https_followed_upgrade_browser_behavior_or_target_authority" if observe_http_redirects else "location_metadata_not_followed_chain_https_upgrade_browser_behavior_or_target_authority"}
                            else:
                                observation = observe_response_headers(response.getheaders())
                        except ValidationError:
                            raise FetchError("response_headers_unavailable") from None
                        _remaining(deadline, self.clock)
                        before_request(current)
                        _remaining(deadline, self.clock)
                        # First response only: neither Location nor body/cookies/policies leave transport.
                        if observe_redirects or observe_http_redirects:
                            return FetchResponse(url=current, status=response.status, headers={}, body=b"",
                                                 redirect_observation=observation)
                        return FetchResponse(url=current, status=response.status, headers={}, body=b"",
                                             header_observation=observation)
                headers = {name.lower(): value.strip() for name, value in response.getheaders()}
                if response.status in REDIRECT_STATUSES and headers.get("location"):
                    if len(redirects) >= self.max_redirects:
                        raise FetchLimitExceeded("redirect_limit")
                    redirects.append(RedirectHop(url=current, status=response.status))
                    current = _join_scoped(self.scope, current, headers["location"])
                    conditional_headers = {}
                    continue
                body = _read_body(
                    response,
                    headers,
                    max_bytes=self.max_bytes,
                    deadline=deadline,
                    clock=self.clock,
                    connection=connection,
                )
                return FetchResponse(
                    url=current,
                    status=response.status,
                    headers=headers,
                    body=body,
                    redirects=tuple(redirects),
                )
            except FetchError:
                raise
            except (OSError, ssl.SSLError, http.client.HTTPException):
                raise FetchError("network_error") from None
            finally:
                connection.close()


@dataclass
class RobotsResult:
    url: str
    status: str
    sitemap_urls: tuple[str, ...] = ()
    denied_sitemaps: int = 0
    error_code: str = ""
    _parser: RobotFileParser | None = field(default=None, repr=False)
    _scope: CrawlScope | None = field(default=None, repr=False)

    def allows(self, url, user_agent=USER_AGENT):
        try:
            url = self._scope.validate_url(url) if self._scope else url
        except FetchDenied:
            return False
        if self.status == "missing":
            return True
        return bool(self.status == "available" and self._parser and self._parser.can_fetch(user_agent, url))


def discover_robots(fetcher, origin):
    robots_url = urljoin(fetcher.scope.validate_url(origin), "/robots.txt")
    try:
        response = fetcher.fetch(robots_url)
    except FetchError as error:
        return RobotsResult(url=robots_url, status="failed", error_code=error.code, _scope=fetcher.scope)
    if response.status in {401, 403, 451}:
        return RobotsResult(url=response.url, status="denied", _scope=fetcher.scope)
    if response.status in {404, 410}:
        return RobotsResult(url=response.url, status="missing", _scope=fetcher.scope)
    if not 200 <= response.status < 300:
        return RobotsResult(url=response.url, status="failed", error_code=f"http_{response.status}", _scope=fetcher.scope)

    text = response.body.decode("utf-8", errors="replace")
    parser = RobotFileParser(response.url)
    parser.parse(text.splitlines())
    sitemaps = []
    denied = 0
    for line in text.splitlines():
        directive, separator, value = line.partition(":")
        if separator and directive.strip().lower() == "sitemap":
            value = value.split("#", 1)[0].strip()
            try:
                value = _join_scoped(fetcher.scope, response.url, value)
            except FetchDenied:
                denied += 1
                continue
            if value not in sitemaps:
                sitemaps.append(value)
    return RobotsResult(
        url=response.url,
        status="available",
        sitemap_urls=tuple(sitemaps),
        denied_sitemaps=denied,
        _parser=parser,
        _scope=fetcher.scope,
    )


@dataclass(frozen=True)
class SitemapFailure:
    url: str
    code: str


@dataclass(frozen=True)
class SitemapResult:
    urls: tuple[str, ...]
    sitemap_urls: tuple[str, ...]
    failures: tuple[SitemapFailure, ...]
    denied_urls: int
    truncated: bool


def discover_sitemaps(fetcher, seeds, *, max_depth=3, max_sitemaps=50, max_urls=10000):
    if max_depth < 0 or max_sitemaps <= 0 or max_urls <= 0:
        raise ValueError("Discovery limits must be positive")
    pending = deque()
    pending_urls = set()
    visited = []
    visited_set = set()
    found = []
    found_set = set()
    failures = []
    denied = 0
    truncated = False
    initial = list(islice(iter(seeds), max_sitemaps + 1))
    for seed in initial:
        try:
            seed = fetcher.scope.validate_url(seed)
        except FetchDenied:
            denied += 1
            continue
        if seed in pending_urls:
            continue
        if len(pending) >= max_sitemaps:
            truncated = True
            break
        pending.append((seed, 0))
        pending_urls.add(seed)
    if len(initial) > max_sitemaps:
        truncated = True

    while pending and len(visited) < max_sitemaps and len(found) < max_urls:
        raw_url, depth = pending.popleft()
        try:
            sitemap_url = fetcher.scope.validate_url(raw_url)
        except FetchDenied:
            denied += 1
            continue
        pending_urls.discard(sitemap_url)
        if sitemap_url in visited_set:
            continue
        visited.append(sitemap_url)
        visited_set.add(sitemap_url)
        try:
            response = fetcher.fetch(sitemap_url)
            if not 200 <= response.status < 300:
                failures.append(SitemapFailure(_safe_reference(sitemap_url), f"http_{response.status}"))
                continue
            body = _maybe_decompress_sitemap(response.body, fetcher.max_bytes)
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                raise FetchError("invalid_xml_encoding") from None
            if "<!doctype" in text.lower() or "<!entity" in text.lower():
                raise FetchError("unsafe_xml")
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError:
            failures.append(SitemapFailure(_safe_reference(sitemap_url), "malformed_xml"))
            continue
        except FetchError as error:
            failures.append(SitemapFailure(_safe_reference(sitemap_url), error.code))
            continue

        root_name = _local_name(root.tag)
        if root_name not in {"sitemapindex", "urlset"}:
            failures.append(SitemapFailure(_safe_reference(sitemap_url), "unsupported_root"))
            continue
        locations = (
            element.text.strip()
            for element in root.iter()
            if _local_name(element.tag) == "loc" and element.text and element.text.strip()
        )
        if root_name == "sitemapindex":
            for location in locations:
                try:
                    location = _join_scoped(fetcher.scope, response.url, location)
                except FetchDenied:
                    denied += 1
                    continue
                if depth >= max_depth:
                    if len(failures) < max_sitemaps:
                        failures.append(SitemapFailure(_safe_reference(location), "depth_limit"))
                    truncated = True
                elif location not in visited_set and location not in pending_urls:
                    if len(visited) + len(pending) >= max_sitemaps:
                        truncated = True
                        continue
                    pending.append((location, depth + 1))
                    pending_urls.add(location)
        else:
            for location in locations:
                try:
                    location = _join_scoped(fetcher.scope, response.url, location)
                except FetchDenied:
                    denied += 1
                    continue
                if location not in found_set:
                    found.append(location)
                    found_set.add(location)
                    if len(found) >= max_urls:
                        truncated = True
                        break

    if pending or len(visited) >= max_sitemaps and pending:
        truncated = True
    return SitemapResult(
        urls=tuple(found),
        sitemap_urls=tuple(visited),
        failures=tuple(failures),
        denied_urls=denied,
        truncated=truncated,
    )


def _origin_host(origin):
    try:
        origin = normalize_origin(origin)
        parsed = urlsplit(origin)
        port = parsed.port
    except (ValidationError, ValueError):
        raise FetchDenied("invalid_scope") from None
    expected_port = 443 if parsed.scheme == "https" else 80
    if port is not None and port != expected_port:
        raise FetchDenied("invalid_scope")
    return _normalize_hostname(parsed.hostname)


def _normalize_hostname(hostname):
    if not hostname:
        return ""
    return hostname.rstrip(".").encode("idna").decode("ascii").lower()


def _resolve_public_addresses(hostname, port, *, resolver, timeout):
    addresses = tuple(
        dict.fromkeys(address.split("%", 1)[0] for address in resolver(hostname, port, timeout))
    )
    if not addresses:
        raise FetchError("dns_error")
    try:
        parsed = [ipaddress.ip_address(address) for address in addresses]
    except ValueError:
        raise FetchDenied("non_public_address") from None
    if any(not address.is_global or address.is_multicast or address.is_unspecified for address in parsed):
        raise FetchDenied("non_public_address")
    return addresses


def _host_header(hostname, port, scheme):
    host = f"[{hostname}]" if ":" in hostname else hostname
    expected = 443 if scheme == "https" else 80
    return host if port == expected else f"{host}:{port}"


def _resource_response_headers(response, *, media_type="text/html"):
    from .passive_headers import observe_response_headers

    if type(response.status) is not int or response.status != 200 or response.msg.defects:
        raise FetchError("resource_body_unavailable")
    fields = response.getheaders()
    try:
        # Reuse original bounded syntax validation; no header observation is returned.
        observe_response_headers(fields)
    except ValidationError:
        raise FetchError("resource_body_unavailable") from None
    selected = {key: [] for key in ("content-length", "content-type", "content-encoding")}
    for name, value in fields:
        name = name.lower()
        if name in {"transfer-encoding", "trailer", "content-range"}:
            raise FetchError("resource_body_unavailable")
        if name in selected:
            selected[name].append(value.strip(" \t"))
    if (len(selected["content-length"]) != 1 or len(selected["content-type"]) != 1
        or len(selected["content-encoding"]) > 1):
        raise FetchError("resource_body_unavailable")
    length, content_type = selected["content-length"][0], selected["content-type"][0]
    encoding = selected["content-encoding"][0].lower() if selected["content-encoding"] else "identity"
    # ponytail: length-framed UTF-8 only; add chunked/charset contracts with completeness evidence.
    content_pattern = r'text/html[ \t]*;[ \t]*charset[ \t]*=[ \t]*(utf-8|"utf-8")' if media_type == "text/html" else (
        r'application/json([ \t]*;[ \t]*charset[ \t]*=[ \t]*(utf-8|"utf-8"))?' if media_type == "application/json" else
        r'text/plain([ \t]*;[ \t]*charset[ \t]*=[ \t]*(utf-8|"utf-8"))?')
    if (not re.fullmatch(r"[0-9]{1,10}", length)
        or not re.fullmatch(content_pattern, content_type, re.I)
        or encoding not in {"identity", "gzip"} or response.chunked or response.length != int(length)):
        raise FetchError("resource_body_unavailable")
    return {"content-length": length, "content-encoding": encoding}


def _read_body(response, headers, *, max_bytes, deadline, clock, connection, require_complete=False):
    try:
        content_length = int(headers.get("content-length", "0"))
    except ValueError:
        raise FetchError("invalid_content_length") from None
    if content_length < 0 or content_length > max_bytes:
        raise FetchLimitExceeded("response_too_large")
    encoding = headers.get("content-encoding", "identity").lower()
    if encoding not in {"", "identity", "gzip"}:
        raise FetchError("unsupported_content_encoding")
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
    output = bytearray()
    wire_bytes = 0
    try:
        while True:
            _set_socket_timeout(connection, _remaining(deadline, clock))
            read = getattr(response, "read1", response.read)
            chunk = read(min(65536, max_bytes - wire_bytes + 1))
            if not chunk:
                break
            wire_bytes += len(chunk)
            if wire_bytes > max_bytes:
                raise FetchLimitExceeded("response_too_large")
            output.extend(
                decompressor.decompress(chunk, max_bytes - len(output) + 1)
                if decompressor
                else chunk
            )
            if len(output) > max_bytes or decompressor and decompressor.unconsumed_tail:
                raise FetchLimitExceeded("response_too_large")
            if require_complete and decompressor and decompressor.unused_data:
                raise FetchError("incomplete_response_body")
        if require_complete and (wire_bytes != content_length or decompressor and not decompressor.eof):
            raise FetchError("incomplete_response_body")
        if decompressor and not require_complete:
            output.extend(decompressor.flush(max_bytes - len(output) + 1))
            if len(output) > max_bytes or not decompressor.eof:
                raise FetchLimitExceeded("response_too_large")
    except zlib.error:
        raise FetchError("invalid_content_encoding") from None
    return bytes(output)


def _maybe_decompress_sitemap(body, max_bytes):
    if not body.startswith(b"\x1f\x8b"):
        return body
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        output = decompressor.decompress(body, max_bytes + 1)
        if len(output) > max_bytes or decompressor.unconsumed_tail:
            raise FetchLimitExceeded("response_too_large")
        output += decompressor.flush(max_bytes - len(output) + 1)
    except zlib.error:
        raise FetchError("invalid_gzip") from None
    if len(output) > max_bytes or not decompressor.eof:
        raise FetchLimitExceeded("response_too_large")
    return output


def _local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def _safe_reference(value):
    try:
        parsed = urlsplit(value)
        hostname = _normalize_hostname(parsed.hostname)
        host = f"[{hostname}]" if ":" in hostname else hostname
        return urlunsplit((parsed.scheme.lower(), host, parsed.path, "", ""))
    except (UnicodeError, ValueError):
        return "invalid-url"


def _remaining(deadline, clock):
    remaining = deadline - clock()
    if remaining <= 0:
        raise FetchLimitExceeded("timeout")
    return remaining


def _set_socket_timeout(connection, timeout):
    sock = getattr(connection, "sock", None)
    if sock is not None:
        sock.settimeout(timeout)


def _join_scoped(scope, base, reference):
    try:
        return scope.validate_url(urljoin(base, reference))
    except (TypeError, UnicodeError, ValueError):
        raise FetchDenied("invalid_url") from None


def _conditional_headers(headers):
    if headers is None:
        return {}
    if not isinstance(headers, dict) or not set(headers) <= {"If-None-Match", "If-Modified-Since"}:
        raise FetchDenied("invalid_request_headers")
    cleaned = {}
    for name, value in headers.items():
        if not isinstance(value, str) or not value or len(value) > 500 or any(ord(character) < 32 for character in value):
            raise FetchDenied("invalid_request_headers")
        try:
            value.encode("latin-1")
        except UnicodeEncodeError:
            raise FetchDenied("invalid_request_headers") from None
        cleaned[name] = value
    return cleaned
