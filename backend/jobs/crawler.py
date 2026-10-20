import hashlib
import json
import math
import time
from collections import Counter, deque
from contextlib import contextmanager
from html.parser import HTMLParser
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from config.artifacts import cleanup_private_artifacts, save_private_artifact
from tenancy.artifacts import project_artifact_scope
from tenancy.customer_artifact_barrier import project_artifact_barrier
from tenancy.models import Organization, ProjectConfiguration
from tenancy.services import Action, require_project_action

from .crawling import CrawlScope, FetchDenied, FetchError, SafeFetcher, discover_robots, discover_sitemaps
from .models import Artifact, CrawlPageSnapshot, CrawlRun, JobCancellation, JobRun, JobStatus, JobStep, UsageReservation
from .usage import settle_usage, usage_denial


METHOD_VERSION = "crawl-http-v2"
MAX_PAGES = 25
MAX_SEEDS = 20
HOST_DELAY_SECONDS = 1
CRAWL_DEADLINE_SECONDS = 270
DEFAULT_QUERY_VARIANT_LIMIT = 5
FIRST_AUDIT_ENTRYPOINT = "bounded-first-audit-request-v1"


def validate_crawl_input(data):
    if not isinstance(data, dict) or set(data) != {"seeds", "page_limit"}:
        raise ValidationError("Check the crawl input.")
    if type(data["page_limit"]) is not int or not 1 <= data["page_limit"] <= MAX_PAGES:
        raise ValidationError(f"Crawl page limit must be between 1 and {MAX_PAGES}.")
    seeds = data["seeds"]
    if (
        not isinstance(seeds, list)
        or len(seeds) > MAX_SEEDS
        or any(not isinstance(seed, str) or not seed or len(seed) > 2048 for seed in seeds)
    ):
        raise ValidationError(f"Crawl seeds must contain at most {MAX_SEEDS} bounded URLs.")
    return data


def queue_crawl(*, project, actor, seeds, page_limit, idempotency_key, first_audit=False):
    data = validate_crawl_input({"seeds": seeds, "page_limit": page_limit})
    if type(first_audit) is not bool or first_audit and (seeds or page_limit > 5):
        raise ValidationError("First audit requests use canonical discovery and a one-to-five-page budget.")
    scope = CrawlScope.for_project(project)
    normalized = []
    for seed in [project.canonical_origin, *data["seeds"]]:
        try:
            seed = scope.validate_url(seed)
        except FetchDenied:
            raise ValidationError("Crawl seeds must stay within the project domain or aliases.") from None
        if seed not in normalized:
            normalized.append(seed)
    from .services import queue_job

    return queue_job(
        project=project,
        actor=actor,
        handler="crawl_site",
        input_snapshot={"seeds": normalized, "page_limit": page_limit},
        config_snapshot={
            "host_delay_seconds": HOST_DELAY_SECONDS,
            "url_parameter_policy": project_url_parameter_policy(project),
            **({"first_audit_entrypoint": FIRST_AUDIT_ENTRYPOINT} if first_audit else {}),
        },
        idempotency_key=idempotency_key,
    )


def default_url_parameter_policy(*, variant_limit=DEFAULT_QUERY_VARIANT_LIMIT):
    return {
        "ignored": [],
        "pagination": [],
        "facet": [],
        "variant_limit": variant_limit,
    }


def project_url_parameter_policy(project):
    configuration = ProjectConfiguration.objects.filter(project=project).only(
        "ignored_query_parameters", "pagination_query_parameters", "facet_query_parameters", "query_variant_limit",
    ).first()
    if configuration is None:
        return default_url_parameter_policy()
    return {
        "ignored": configuration.ignored_query_parameters,
        "pagination": configuration.pagination_query_parameters,
        "facet": configuration.facet_query_parameters,
        "variant_limit": configuration.query_variant_limit,
    }


def validate_url_parameter_policy(value):
    if not isinstance(value, dict) or set(value) != {"ignored", "pagination", "facet", "variant_limit"}:
        raise ValidationError("Invalid snapshotted URL parameter policy.")
    names = []
    for category in ("ignored", "pagination", "facet"):
        items = value[category]
        if (
            not isinstance(items, list)
            or len(items) > 50
            or any(not isinstance(item, str) or not item or len(item) > 100 for item in items)
            or any(any(ord(character) < 33 or ord(character) > 126 or character in "&=#" for character in item)
                   for item in items)
            or len(items) != len(set(items))
        ):
            raise ValidationError("Invalid snapshotted URL parameter policy.")
        names.extend(items)
    if len(names) != len(set(names)) or type(value["variant_limit"]) is not int or not 1 <= value["variant_limit"] <= 25:
        raise ValidationError("Invalid snapshotted URL parameter policy.")
    return value


def snapshotted_url_parameter_policy(job):
    if "url_parameter_policy" in job.config_snapshot:
        return True, validate_url_parameter_policy(job.config_snapshot["url_parameter_policy"])
    if job.method_version == "crawl-http-v1":
        return False, default_url_parameter_policy(variant_limit=MAX_PAGES)
    raise ValidationError("The crawl job is missing its URL parameter policy snapshot.")


def crawl_url_identity(url, policy):
    ignored = set(policy["ignored"])
    if not ignored:
        return url
    parsed = urlsplit(url)
    pairs = [(name, item) for name, item in parse_qsl(parsed.query, keep_blank_values=True) if name not in ignored]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(pairs, doseq=True), ""))


class CrawlStopped(Exception):
    pass


class PacedFetcher:
    def __init__(self, fetcher, *, denial, deadline, delay_seconds, clock=time.monotonic, sleep=time.sleep):
        self.fetcher = fetcher
        self.scope = fetcher.scope
        self.max_bytes = fetcher.max_bytes
        self.denial = denial
        self.deadline = deadline
        self.delay_seconds = delay_seconds
        self.clock = clock
        self.sleep = sleep
        self.last_started = {}

    def fetch(self, url, **kwargs):
        url = self.scope.validate_url(url)
        kwargs.setdefault("before_send", self._before_send)
        return self.fetcher.fetch(
            url,
            before_request=self._before_request,
            deadline=self.deadline,
            **kwargs,
        )

    def _before_send(self, url):
        denied = self.denial(url)
        if denied:
            raise CrawlStopped(denied)
        if self.clock() >= self.deadline:
            raise CrawlStopped("crawl_deadline")

    def _before_request(self, url):
        denied = self.denial(url)
        if denied:
            raise CrawlStopped(denied)
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise CrawlStopped("crawl_deadline")
        host = urlsplit(url).hostname
        previous = self.last_started.get(host)
        if previous is not None:
            wait = self.delay_seconds - (self.clock() - previous)
            if wait > 0:
                if wait >= remaining:
                    raise CrawlStopped("crawl_deadline")
                self.sleep(wait)
        denied = self.denial(url)
        if denied:
            raise CrawlStopped(denied)
        if self.clock() >= self.deadline:
            raise CrawlStopped("crawl_deadline")
        self.last_started[host] = self.clock()


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts = []
        self.description = ""
        self.canonical = ""
        self.robots = []
        self.hreflang = []
        self.raw_links = []
        self.headings = []
        self.structured_data = []
        self.structured_data_errors = []
        self._json_blocks_seen = 0
        self._title = False
        self._heading = None
        self._heading_parts = []
        self._json_ld = False
        self._json_parts = []

    def handle_starttag(self, tag, attrs):
        attributes = {name.lower(): value or "" for name, value in attrs}
        tag = tag.lower()
        if tag == "title":
            self._title = True
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and len(self.headings) < 100:
            self._heading = tag
            self._heading_parts = []
        elif tag == "meta":
            name = attributes.get("name", "").lower()
            if name == "description" and not self.description:
                self.description = attributes.get("content", "")[:1000]
            elif name in {"robots", "googlebot", "bingbot"} and len(self.robots) < 20:
                self.robots.append({"agent": name, "content": attributes.get("content", "")[:500]})
        elif tag == "link":
            rel = set(attributes.get("rel", "").lower().split())
            href = attributes.get("href", "")
            if "canonical" in rel and href and not self.canonical:
                self.canonical = href
            if "alternate" in rel and attributes.get("hreflang") and href and len(self.hreflang) < 100:
                self.hreflang.append({"language": attributes["hreflang"][:35], "url": href})
        elif tag == "a" and attributes.get("href") and len(self.raw_links) < 1000:
            self.raw_links.append(attributes["href"])
        elif tag == "script" and attributes.get("type", "").lower().split(";", 1)[0].strip() == "application/ld+json":
            self._json_blocks_seen += 1
            self._json_ld = self._json_blocks_seen <= 20
            self._json_parts = []
            if self._json_blocks_seen == 21:
                self.structured_data_errors.append({"block": 21, "category": "block_limit"})

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self._title = False
        if self._heading == tag:
            text = " ".join("".join(self._heading_parts).split())[:1000]
            self.headings.append({"level": tag, "text": text})
            self._heading = None
            self._heading_parts = []
        if tag == "script" and self._json_ld:
            raw = "".join(self._json_parts).strip()
            category = ""
            if not raw:
                category = "empty"
            elif len(raw.encode()) > 16384:
                category = "size_limit"
            else:
                try:
                    value = json.loads(raw, parse_constant=_reject_json_constant)
                    if _safe_json(value):
                        self.structured_data.append(value)
                    else:
                        category = "shape_limit"
                except (TypeError, ValueError, RecursionError):
                    category = "invalid_json"
            if category:
                self.structured_data_errors.append({"block": self._json_blocks_seen, "category": category})
            self._json_ld = False
            self._json_parts = []

    def handle_data(self, data):
        if self._title and sum(map(len, self.title_parts)) < 500:
            self.title_parts.append(data)
        if self._heading is not None and sum(map(len, self._heading_parts)) < 1000:
            self._heading_parts.append(data)
        if self._json_ld and sum(map(len, self._json_parts)) < 16384:
            self._json_parts.append(data)

    def result(self, *, base_url, scope):
        links = []
        internal_urls = []
        for raw in self.raw_links:
            url = _normalize_link(base_url, raw)
            if not url:
                continue
            try:
                internal = scope.validate_url(url)
            except FetchDenied:
                links.append({"url": url, "internal": False})
            else:
                links.append({"url": internal, "internal": True})
                if internal not in internal_urls:
                    internal_urls.append(internal)
        canonical = _normalize_link(base_url, self.canonical) if self.canonical else ""
        if canonical:
            try:
                canonical_target = scope.validate_url(canonical)
            except FetchDenied:
                pass
            else:
                if canonical_target not in internal_urls:
                    internal_urls.append(canonical_target)
        hreflang = [
            {"language": item["language"], "url": _normalize_link(base_url, item["url"])}
            for item in self.hreflang
        ]
        return {
            "title": " ".join("".join(self.title_parts).split())[:500],
            "meta_description": " ".join(self.description.split())[:1000],
            "headings": self.headings,
            "canonical_url": canonical,
            "robots_directives": self.robots,
            "hreflang": [item for item in hreflang if item["url"]],
            "links": links,
            "structured_data": self.structured_data,
            "structured_data_errors": self.structured_data_errors,
        }, internal_urls


def execute_crawl_job(job_id, *, fetcher_factory=SafeFetcher, clock=time.monotonic, sleep=time.sleep):
    organization_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return False
    with project_artifact_barrier(organization_id, shared=True), _crawl_execution_lock(job_id) as acquired:
        if not acquired:
            return False
        try:
            return _execute_crawl_job(job_id, fetcher_factory=fetcher_factory, clock=clock, sleep=sleep)
        except CrawlStopped as stopped:
            category = str(stopped)
            if category in {
                "cancelled", "actor_revoked", "internal_capacity", "scope_revoked",
                "trial_unavailable", "trial_units_exhausted", "usage_unreserved",
            }:
                return _finish_crawl(job_id, cancelled=True, error_category=category)
            observed = CrawlPageSnapshot.objects.filter(crawl_run__job_id=job_id).exists()
            return _finish_crawl(job_id, failed=not observed, partial=observed, error_category=category)
        except Exception:
            if CrawlRun.objects.filter(job_id=job_id).exists():
                observed = CrawlPageSnapshot.objects.filter(crawl_run__job_id=job_id).exists()
                return _finish_crawl(
                    job_id,
                    failed=not observed,
                    partial=observed,
                    error_category="handler_failed",
                )
            _fail_crawl(job_id, "handler_failed")
            return True


@contextmanager
def _crawl_execution_lock(job_id):
    # PostgreSQL releases this session lock if a worker process or connection dies.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [-int(job_id)])
        acquired = cursor.fetchone()[0]
    try:
        yield acquired
    finally:
        if acquired:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [-int(job_id)])


def _execute_crawl_job(job_id, *, fetcher_factory, clock, sleep):
    organization_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").filter(pk=job_id).first()
        if job is None or job.handler != "crawl_site" or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        validate_crawl_input(job.input_snapshot)
        crawl_run, _ = CrawlRun.objects.get_or_create(
            job=job,
            defaults={
                "organization": job.organization,
                "project": job.project,
                "page_limit": job.input_snapshot["page_limit"],
            },
        )
        denied = "cancelled" if JobCancellation.objects.filter(job=job).exists() else ""
        if not denied:
            try:
                require_project_action(project=job.project, user=job.actor, action=Action.LAUNCH_JOB)
            except PermissionDenied:
                denied = "actor_revoked"
        if not denied:
            denied = usage_denial(job=job)
        if not denied and job.status == JobStatus.QUEUED:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])

    if denied:
        return _finish_crawl(job_id, cancelled=True, error_category=denied)

    scope = CrawlScope.for_project(job.project)
    delay_seconds = job.config_snapshot.get("host_delay_seconds")
    if delay_seconds != HOST_DELAY_SECONDS:
        raise ValidationError("Invalid snapshotted crawl delay.")
    _configured, parameter_policy = snapshotted_url_parameter_policy(job)
    fetcher = PacedFetcher(
        fetcher_factory(scope),
        denial=lambda url: _crawl_denial(job_id, pending_url=url),
        deadline=clock() + CRAWL_DEADLINE_SECONDS,
        delay_seconds=delay_seconds,
        clock=clock,
        sleep=sleep,
    )
    robots = None
    robots_by_origin = {}
    if not crawl_run.discovery:
        origin = job.project.canonical_origin
        robots = discover_robots(fetcher, origin)
        crawl_run.robots_status = robots.status
        if robots.status not in {"available", "missing"}:
            crawl_run.discovery = {"error": robots.error_code or f"robots_{robots.status}"}
            crawl_run.save(update_fields=["robots_status", "discovery"])
            observed = crawl_run.pages.exists()
            return _finish_crawl(job_id, failed=not observed, partial=observed, error_category="robots_unavailable")
        robots_by_origin[_origin_key(origin)] = robots
        sitemap_seeds = [*robots.sitemap_urls, urljoin(origin, "/sitemap.xml")]
        sitemaps = discover_sitemaps(
            fetcher,
            sitemap_seeds,
            max_depth=2,
            max_sitemaps=5,
            max_urls=crawl_run.page_limit * 4,
        )
        urls = []
        for url in [*job.input_snapshot["seeds"], *sitemaps.urls]:
            if url not in urls:
                urls.append(url)
        fallback_sitemap = scope.validate_url(urljoin(origin, "/sitemap.xml"))
        sitemap_failures = [
            failure for failure in sitemaps.failures
            if not (
                failure.url == fallback_sitemap
                and fallback_sitemap not in robots.sitemap_urls
                and failure.code in {"http_404", "http_410"}
            )
        ]
        crawl_run.discovery = {
            "urls": urls,
            "sitemap_urls": list(sitemaps.urls),
            "sitemaps_fetched": len(sitemaps.sitemap_urls),
            "sitemap_failures": len(sitemap_failures),
            "sitemap_failure_details": [
                {"url": failure.url, "code": failure.code} for failure in sitemap_failures[:10]
            ],
            "denied_urls": sitemaps.denied_urls,
            "truncated": sitemaps.truncated,
        }
        crawl_run.save(update_fields=["robots_status", "discovery"])
        JobStep.objects.get_or_create(
            job=job,
            sequence=1,
            defaults={
                "name": "Discover crawl scope",
                "status": JobStep.Status.SUCCEEDED,
                "progress_percent": 10,
                "output": {
                    key: value for key, value in crawl_run.discovery.items()
                    if key not in {"urls", "sitemap_urls"}
                },
            },
        )
    elif crawl_run.robots_status == "available":
        robots = discover_robots(fetcher, job.project.canonical_origin)
        if robots.status != "available":
            observed = crawl_run.pages.exists()
            return _finish_crawl(job_id, failed=not observed, partial=observed, error_category="robots_unavailable")
        robots_by_origin[_origin_key(job.project.canonical_origin)] = robots
    elif crawl_run.robots_status == "missing":
        robots = discover_robots(fetcher, job.project.canonical_origin)
        if robots.status not in {"available", "missing"}:
            observed = crawl_run.pages.exists()
            return _finish_crawl(job_id, failed=not observed, partial=observed, error_category="robots_unavailable")
        robots_by_origin[_origin_key(job.project.canonical_origin)] = robots

    existing_pages = list(crawl_run.pages.all())
    crawl_run.pages_attempted = len(existing_pages)
    crawl_run.pages_observed = sum(not page.error_category for page in existing_pages)
    crawl_run.save(update_fields=["pages_attempted", "pages_observed"])
    visited = {crawl_url_identity(page.requested_url, parameter_policy) for page in existing_pages}
    resume_links = [item["url"] for page in existing_pages for item in page.links if item.get("internal")]
    for page in existing_pages:
        if not page.canonical_url:
            continue
        try:
            canonical_target = scope.validate_url(page.canonical_url)
        except FetchDenied:
            continue
        if canonical_target not in resume_links:
            resume_links.append(canonical_target)
    pending = deque()
    queued = set(visited)
    for url in [*crawl_run.discovery.get("urls", []), *resume_links]:
        identity = crawl_url_identity(url, parameter_policy)
        if identity not in queued:
            pending.append(url)
            queued.add(identity)
    family_counts = {}
    for url in visited:
        family = _url_family(url)
        family_counts[family] = family_counts.get(family, 0) + 1
    family_limit = max(5, math.ceil(crawl_run.page_limit / 2))
    failures = crawl_run.pages.exclude(error_category="").count()
    skipped_family = 0
    skipped_parameter_variants = 0
    skipped_robots = 0
    robots_failures = []
    parameter_variant_counts = Counter(
        (parsed.scheme, parsed.netloc, parsed.path)
        for url in visited
        if (parsed := urlsplit(url)).query
    )

    while pending and crawl_run.pages_attempted < crawl_run.page_limit:
        requested_url = pending.popleft()
        identity = crawl_url_identity(requested_url, parameter_policy)
        parsed_identity = urlsplit(identity)
        parameter_key = None
        if parsed_identity.query:
            parameter_key = (parsed_identity.scheme, parsed_identity.netloc, parsed_identity.path)
            if parameter_variant_counts[parameter_key] >= parameter_policy["variant_limit"]:
                skipped_parameter_variants += 1
                continue
        family = _url_family(requested_url)
        if family_counts.get(family, 0) >= family_limit:
            skipped_family += 1
            continue
        family_counts[family] = family_counts.get(family, 0) + 1
        denied = _crawl_denial(job_id)
        if denied:
            return _finish_crawl(job_id, cancelled=True, error_category=denied)
        origin = _origin_key(requested_url)
        policy = robots_by_origin.get(origin)
        if policy is None:
            policy = discover_robots(fetcher, origin)
            robots_by_origin[origin] = policy
        if policy.status not in {"available", "missing"} or not policy.allows(requested_url):
            skipped_robots += 1
            if len(robots_failures) < 20:
                robots_failures.append({
                    "origin": origin,
                    "status": policy.status,
                    "code": policy.error_code or ("disallowed" if policy.status in {"available", "missing"} else "unavailable"),
                })
            continue
        if parameter_key is not None:
            parameter_variant_counts[parameter_key] += 1
        prior = CrawlPageSnapshot.objects.filter(
            project=job.project,
            requested_url=requested_url,
        ).exclude(crawl_run=crawl_run).order_by("-observed_at", "-pk").first()
        headers = {}
        if prior and prior.etag:
            headers["If-None-Match"] = prior.etag
        if prior and prior.last_modified:
            headers["If-Modified-Since"] = prior.last_modified
        try:
            response = fetcher.fetch(requested_url, request_headers=headers)
        except FetchError as error:
            response = None
            error_category = error.code
        else:
            error_category = ""
        snapshot_data, discovered = _persist_page(
            job=job,
            crawl_run=crawl_run,
            requested_url=requested_url,
            response=response,
            prior=prior,
            error_category=error_category,
        )
        if snapshot_data.get("error_category"):
            failures += 1
        for url in discovered:
            identity = crawl_url_identity(url, parameter_policy)
            if identity not in queued:
                pending.append(url)
                queued.add(identity)

    crawl_run.discovery = {
        **crawl_run.discovery,
        "queue_remaining": len(pending),
        "skipped_family": skipped_family,
        "skipped_parameter_variants": skipped_parameter_variants,
        "skipped_robots": skipped_robots,
        "robots_failures": robots_failures,
    }
    crawl_run.save(update_fields=["discovery"])
    denied = _crawl_denial(job_id)
    if denied:
        return _finish_crawl(job_id, cancelled=True, error_category=denied)
    coverage_failures = (
        failures + crawl_run.discovery.get("sitemap_failures", 0) + skipped_robots + skipped_family
        + skipped_parameter_variants + bool(pending)
    )
    return _finish_crawl(
        job_id,
        failed=bool(coverage_failures and not crawl_run.pages_observed),
        partial=bool(coverage_failures and crawl_run.pages_observed),
        error_category=("partial_coverage" if crawl_run.pages_observed else "crawl_incomplete") if coverage_failures else "",
    )


def _persist_page(*, job, crawl_run, requested_url, response, prior, error_category):
    with transaction.atomic():
        current = CrawlRun.objects.select_for_update().get(pk=crawl_run.pk)
        if response is None:
            snapshot_data = {"requested_url": requested_url, "error_category": error_category}
            discovered = []
        else:
            snapshot_data, discovered = _snapshot_response(job, current, requested_url, response, prior)
        CrawlPageSnapshot.objects.create(crawl_run=current, project=job.project, **snapshot_data)
        current.pages_attempted += 1
        if not snapshot_data.get("error_category"):
            current.pages_observed += 1
        current.save(update_fields=["pages_attempted", "pages_observed"])
    crawl_run.pages_attempted = current.pages_attempted
    crawl_run.pages_observed = current.pages_observed
    return snapshot_data, discovered


def _snapshot_response(job, crawl_run, requested_url, response, prior):
    base = {
        "requested_url": requested_url,
        "final_url": response.url,
        "redirect_chain": [{"url": hop.url, "status": hop.status} for hop in response.redirects],
        "status_code": response.status,
        "etag": response.headers.get("etag", "")[:500],
        "last_modified": response.headers.get("last-modified", "")[:200],
    }
    if response.status == 304:
        if prior is None or not prior.content_hash:
            return {**base, "error_category": "unexpected_not_modified"}, []
        base["etag"] = base["etag"] or prior.etag
        base["last_modified"] = base["last_modified"] or prior.last_modified
        copied = {
            field: getattr(prior, field)
            for field in (
                "title", "meta_description", "headings", "canonical_url", "robots_directives",
                "hreflang", "links", "structured_data", "structured_data_errors", "content_hash", "raw_artifact",
            )
        }
        return {**base, **copied, "reused_from": prior}, [item["url"] for item in prior.links if item.get("internal")]

    content_hash = hashlib.sha256(response.body).hexdigest()
    content_type_header = response.headers.get("content-type", "")
    content_type = content_type_header.split(";", 1)[0].lower()
    if response.body and content_type in {"text/html", "application/xhtml+xml"}:
        try:
            text = _decode_html(response.body, content_type_header)
        except (LookupError, UnicodeError):
            return {**base, "content_hash": content_hash, "error_category": "invalid_html_encoding"}, []
        parser = PageParser()
        try:
            parser.feed(text)
        except (ValueError, RecursionError):
            return {**base, "content_hash": content_hash, "error_category": "malformed_html"}, []
        parsed, discovered = parser.result(base_url=response.url, scope=CrawlScope.for_project(job.project))
        key = save_private_artifact(
            scope=f"{project_artifact_scope(job.project)}/jobs/{job.pk}",
            content=response.body,
            content_type="text/html",
            key_stem=content_hash[:32],
        )
        artifact, _ = Artifact.objects.get_or_create(
            key=key,
            defaults={
                "job": job,
                "project": job.project,
                "content_type": "text/html",
                "size_bytes": len(response.body),
            },
        )
        return {**base, **parsed, "content_hash": content_hash, "raw_artifact": artifact}, discovered
    return {**base, "content_hash": content_hash}, []


def _crawl_denial(job_id, *, pending_url=None):
    job = JobRun.objects.select_related("project", "actor").get(pk=job_id)
    if JobCancellation.objects.filter(job=job).exists():
        return "cancelled"
    try:
        require_project_action(project=job.project, user=job.actor, action=Action.LAUNCH_JOB)
    except PermissionDenied:
        return "actor_revoked"
    if pending_url:
        try:
            CrawlScope.for_project(job.project).validate_url(pending_url)
        except FetchDenied:
            return "scope_revoked"
    return usage_denial(job=job)


def _finish_crawl(job_id, *, failed=False, partial=False, cancelled=False, error_category=""):
    with transaction.atomic():
        organization_id = JobRun.objects.values_list("organization_id", flat=True).get(pk=job_id)
        Organization.objects.select_for_update().get(pk=organization_id)
        job = JobRun.objects.select_for_update(no_key=True).get(pk=job_id)
        crawl_run = CrawlRun.objects.select_for_update().get(job=job)
        if job.status not in {JobStatus.RUNNING, JobStatus.QUEUED}:
            return True
        actual_units = crawl_run.pages.count()
        crawl_run.pages_attempted = actual_units
        crawl_run.pages_observed = crawl_run.pages.filter(error_category="").count()
        if cancelled:
            job.status = JobStatus.CANCELLED
        elif failed:
            job.status = JobStatus.FAILED
        elif partial:
            job.status = JobStatus.PARTIALLY_SUCCEEDED
        else:
            job.status = JobStatus.SUCCEEDED
        job.error_category = error_category
        job.output = {
            "pages_attempted": actual_units,
            "pages_observed": crawl_run.pages_observed,
            "robots_status": crawl_run.robots_status,
            "discovery_truncated": bool(crawl_run.discovery.get("truncated") or crawl_run.discovery.get("queue_remaining")),
            "sitemap_failures": crawl_run.discovery.get("sitemap_failures", 0),
            "skipped_family": crawl_run.discovery.get("skipped_family", 0),
            "skipped_parameter_variants": crawl_run.discovery.get("skipped_parameter_variants", 0),
            "skipped_robots": crawl_run.discovery.get("skipped_robots", 0),
        }
        job.save(update_fields=["status", "error_category", "output", "updated_at"])
        crawl_run.completed_at = timezone.now()
        crawl_run.save(update_fields=["pages_attempted", "pages_observed", "completed_at"])
        JobStep.objects.update_or_create(
            job=job,
            sequence=2,
            defaults={
                "name": "Fetch pages",
                "status": JobStep.Status.FAILED if failed or partial or cancelled else JobStep.Status.SUCCEEDED,
                "progress_percent": 100,
                "output": {"attempted": actual_units, "observed": crawl_run.pages_observed},
                "error_category": error_category,
            },
        )
        if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
            settle_usage(job=job, actual_units=actual_units)
        from .first_audit_evidence import capture_bounded_completion
        job._first_audit_completed_at = crawl_run.completed_at
        capture_bounded_completion(job=job)
        transaction.on_commit(lambda job_id=job.pk: _cleanup_crawl_artifacts(job_id))
    return True


def _fail_crawl(job_id, category):
    with transaction.atomic():
        organization_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
        if organization_id is None:
            return
        Organization.objects.select_for_update().get(pk=organization_id)
        job = JobRun.objects.select_for_update(no_key=True).filter(pk=job_id).first()
        if job is None or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return
        if job.status == JobStatus.QUEUED:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
        job.status = JobStatus.FAILED
        job.error_category = category
        job.save(update_fields=["status", "error_category", "updated_at"])
        crawl_run = CrawlRun.objects.filter(job=job).first()
        attempted = crawl_run.pages.count() if crawl_run else 0
        CrawlRun.objects.filter(job=job, completed_at__isnull=True).update(completed_at=timezone.now())
        if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
            settle_usage(job=job, actual_units=attempted)


def _cleanup_crawl_artifacts(job_id):
    job = JobRun.objects.select_related("project").filter(pk=job_id).first()
    if job is None:
        return
    with project_artifact_barrier(job.organization_id, shared=True):
        cleanup_private_artifacts(
            scope=f"{project_artifact_scope(job.project)}/jobs/{job.pk}",
            keep_keys=set(job.artifacts.values_list("key", flat=True)),
        )


def _normalize_link(base, value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        return ""
    try:
        parsed = urlsplit(urljoin(base, value))
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        port = parsed.port
    except (UnicodeError, ValueError):
        return ""
    expected_port = 443 if scheme == "https" else 80 if scheme == "http" else None
    if expected_port is None or not hostname or parsed.username or parsed.password or (port and port != expected_port):
        return ""
    host = f"[{hostname}]" if ":" in hostname else hostname
    path = quote(parsed.path or "/", safe="/%:@-._~!$&'()*+,;=")
    query = quote(parsed.query, safe="/%?:@-._~!$&'()*+,;=")
    normalized = urlunsplit((scheme, host, path, query, ""))
    return normalized if len(normalized) <= 2048 else ""


def _decode_html(body, content_type):
    charset = "utf-8"
    for parameter in content_type.split(";")[1:]:
        name, separator, value = parameter.strip().partition("=")
        if separator and name.lower() == "charset":
            charset = value.strip('"\' ') or charset
            break
    return body.decode(charset, errors="strict")


def _safe_json(value):
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > 20 or nodes > 1000 or isinstance(item, float) and not math.isfinite(item):
            return False
        if isinstance(item, dict):
            pending.extend((nested, depth + 1) for nested in item.values())
        elif isinstance(item, list):
            pending.extend((nested, depth + 1) for nested in item)
    return True


def _reject_json_constant(_value):
    raise ValueError


def _url_family(url):
    parsed = urlsplit(url)
    first = next((part for part in parsed.path.split("/") if part), "")
    return parsed.hostname, first


def _origin_key(url):
    parsed = urlsplit(url)
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return urlunsplit((parsed.scheme, host, "", "", ""))
