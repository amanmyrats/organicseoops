"""D132 minimized static-HTML evidence and separately permissioned bounded collection."""
from datetime import datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
import time
from urllib.parse import unquote, urljoin, urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from tenancy.models import normalize_origin
from .local_feedback import _text, validate_owned_website_url
from .static_robots import strict_robots_policy

METHOD = "authority-static-link-parse-v1"
REFERENCE_METHOD = "authority-static-uri-parse-v1"
MAX_BODY_BYTES = 128 * 1024
MAX_ANCHORS = 1000
MAX_MATCHES = 20
MAX_RESULT_BYTES = 32 * 1024
COLLECTION_METHOD = "authority-static-link-collect-v1"
REFERENCE_COLLECTION_METHOD = "authority-static-uri-collect-v1"
COLLECTION_DEADLINE_SECONDS = 30
# HTMLParser is not a browser. Exclude inert/raw-text containers rather than
# interpreting their text as active anchors; CSS visibility remains unknown.
EXCLUDED = {"script", "style", "template", "noscript", "textarea", "title", "xmp", "iframe"}


def _reference_identity(value, source_url):
    _text(value, 1024, required=True)
    if ("?" in value or "#" in value or any(ord(char) < 33 or char == "\\" for char in value)
        or any(ord(char) < 32 or char == "\\" for char in unquote(value))):
        raise ValidationError("Static URI references must retain safe bounded URL syntax.")
    resolved = urljoin(source_url, value)
    parts = urlsplit(resolved)
    origin = normalize_origin(parts.scheme + "://" + parts.netloc)
    validate_owned_website_url(resolved, approved_origin=origin)
    if parts.port not in {None, 443} or "?" in resolved or "#" in resolved:
        raise ValidationError("Static URI references require unparameterized standard-port HTTPS URLs.")
    return origin + (parts.path or "/")


class _TargetLinks(HTMLParser):
    def __init__(self, target, *, source_url=None):
        super().__init__(convert_charrefs=True)
        self.target = target
        self.source_url = source_url
        self.target_identity = _reference_identity(target, source_url) if source_url is not None else target
        self.unsupported_references = 0
        self.hidden = []
        self.anchor = None
        self.matches = []
        self.anchors_seen = 0
        self.matches_seen = 0
        self.structure_uncertain = False
        self.base_seen = False

    def handle_starttag(self, tag, attrs):
        if tag in EXCLUDED:
            self.hidden.append(tag)
            return
        if self.hidden:
            return
        if tag == "base":
            self.base_seen = True
        if tag != "a":
            return
        self.anchors_seen += 1
        if self.anchor is not None:
            self.structure_uncertain = True
        self.anchor = None
        if self.anchors_seen > MAX_ANCHORS:
            return
        names = [name for name, _value in attrs]
        if names.count("href") > 1 or names.count("rel") > 1:
            self.structure_uncertain = True
            return
        attributes = dict(attrs)
        href = attributes.get("href")
        matching = href == self.target
        if self.source_url is not None:
            matching = False
            if href:
                try:
                    matching = _reference_identity(href, self.source_url) == self.target_identity
                except (ValidationError, ValueError, UnicodeError):
                    self.unsupported_references += 1
        if matching:
            self.matches_seen += 1
        self.anchor = {"matching": matching, "text": "", "text_truncated": False,
                       "rel": attributes.get("rel") or ""}

    def handle_data(self, value):
        if self.hidden or self.anchor is None or not self.anchor["matching"]:
            return
        text = self.anchor["text"] + value
        self.anchor["text_truncated"] |= len(text) > 240
        self.anchor["text"] = text[:240]

    def handle_endtag(self, tag):
        if tag in EXCLUDED:
            if self.hidden and self.hidden[-1] == tag:
                self.hidden.pop()
            else:
                self.structure_uncertain = True
            return
        if self.hidden or tag != "a":
            return
        if self.anchor is None:
            # Beyond the inventory limit we did not inspect start tags.
            if self.anchors_seen <= MAX_ANCHORS:
                self.structure_uncertain = True
            return
        if self.anchor["matching"] and len(self.matches) < MAX_MATCHES:
            self.matches.append({"parsed_href": self.target, "anchor_text": self.anchor["text"],
                "anchor_text_truncated": self.anchor["text_truncated"], "rel": self.anchor["rel"][:100],
                "rel_truncated": len(self.anchor["rel"]) > 100})
        self.anchor = None


def parse_static_link_source(*, body, source_url, target_url, observed_at):
    """D132 literal v1; historical evidence never changes its href interpretation."""
    return _parse_static_link_source(body=body, source_url=source_url, target_url=target_url,
        observed_at=observed_at, resolve_references=False)


def parse_static_link_references(*, body, source_url, target_url, observed_at):
    """D138 no-base URI references; no browser or destination fetch."""
    return _parse_static_link_source(body=body, source_url=source_url, target_url=target_url,
        observed_at=observed_at, resolve_references=True)


def _parse_static_link_source(*, body, source_url, target_url, observed_at, resolve_references):
    if type(body) is not bytes or not 1 <= len(body) <= MAX_BODY_BYTES:
        raise ValidationError("Choose bounded original UTF-8 static HTML bytes.")
    for value in (source_url, target_url):
        _text(value, 1024, required=True)
        try:
            parts = urlsplit(value)
            origin = normalize_origin(parts.scheme + "://" + parts.netloc)
            validate_owned_website_url(value, approved_origin=origin)
            if parts.port not in {None, 443}:
                raise ValueError
        except (ValueError, UnicodeError):
            raise ValidationError("Choose standard-port external source and own-target HTTPS URLs.") from None
    if urlsplit(source_url).hostname == urlsplit(target_url).hostname:
        raise ValidationError("An own-target page is not an external link source.")
    _text(observed_at, 64, required=True)
    try:
        date = datetime.fromisoformat(observed_at)
        if timezone.is_naive(date) or date > timezone.now():
            raise ValueError
        html = body.decode("utf-8-sig")
        _text(html, MAX_BODY_BYTES, required=True)
        parser = _TargetLinks(target_url, source_url=source_url if resolve_references else None)
        parser.feed(html)
        parser.close()
    except (UnicodeError, ValueError, AssertionError, RecursionError):
        raise ValidationError("Retain valid original UTF-8 HTML and an aware nonfuture collection date.") from None
    uncertain = parser.structure_uncertain or bool(parser.hidden) or parser.anchor is not None or resolve_references and parser.base_seen
    if resolve_references and parser.base_seen:
        parser.matches = []  # No base-dependent positive evidence, including bases occurring after an anchor.
    state = ("unavailable_base_dependent_references" if resolve_references and parser.base_seen
             else "unavailable_ambiguous_markup" if uncertain
             else "observed_resolved_target_in_static_uri_references" if resolve_references and parser.matches
             else "observed_absolute_target_in_parsed_html" if parser.matches
             else "not_observed_in_bounded_static_html_not_link_loss")
    result = {"method": REFERENCE_METHOD if resolve_references else METHOD, "source_url": source_url, "target_url": target_url, "observed_at": observed_at,
        "body_sha256": sha256(body).hexdigest(), "body_size_bytes": len(body), "matching_links": parser.matches,
        "state": state, "href_semantics": "html_character_references_decoded_exact_absolute_href_no_url_resolution",
        "coverage": {"anchors_seen": parser.anchors_seen, "anchors_inspected": min(parser.anchors_seen, MAX_ANCHORS),
            "anchor_limit_reached": parser.anchors_seen > MAX_ANCHORS, "matches_seen": parser.matches_seen,
            "matches_capped": parser.matches_seen > MAX_MATCHES, "structure_uncertain": uncertain,
            "base_element_seen": parser.base_seen, "surface": "returned_static_html_not_rendered",
            "excluded_containers": sorted(EXCLUDED), "whole_site": "not_established", "browser_visibility": "unknown"},
        "source_authority": "not_established_by_parser", "unlinked_or_lost_link": "not_established",
        "raw_body_retention": "not_selected_transient_only",
        "interpretation": "parsed_static_markup_not_rendered_link_or_permission_or_link_loss_proof"}
    if resolve_references:
        result["href_semantics"] = "bounded_stdlib_uri_reference_join_against_final_source_no_base_no_browser_repair"
        result["coverage"].update({"unsupported_references": parser.unsupported_references,
            "reference_resolution": "unavailable_base_element" if parser.base_seen else "bounded_no_base_stdlib_uri_references"})
    if len(json.dumps(result, allow_nan=False).encode()) > MAX_RESULT_BYTES:
        raise ValidationError("Minimized static-link result exceeds its private 32 KiB ceiling.")
    return result


def static_link_source_authority(*, project, actor, link_review_id, source_collection_permission):
    """Resolve a real current selected source. A read binding is not a job/budget or network grant."""
    from django.core.exceptions import PermissionDenied
    from tenancy.models import Project, ProjectConfiguration
    from .authority_links import require_current_link_review
    from .models import AuthorityLinkReview
    from .research_sources import source_url

    if source_collection_permission is not True:
        raise PermissionDenied
    if type(link_review_id) is not int or not 1 <= link_review_id < 2**53:
        raise ValidationError("Choose an actual current human verification review.")
    project = Project.objects.select_related("organization").filter(pk=project.pk, organization_id=project.organization_id).first()
    if project is None:
        raise PermissionDenied
    row = AuthorityLinkReview.objects.select_related("project__organization", "actor", "source_actor", "assignee",
        "reviewed_revision__actor", "approved_by").filter(project=project, pk=link_review_id).first()
    if row is None:
        raise PermissionDenied
    if (row.state not in {"approved", "reported"} or row.proposal.get("action") != "verify_source"
        or AuthorityLinkReview.objects.filter(project=project, link_id=row.link_id, revision__gt=row.revision).exists()):
        raise ValidationError("Choose the unchanged latest human-approved source verification activity.")
    require_current_link_review(row, actor=actor)
    config = ProjectConfiguration.objects.filter(project=project).first()
    if config is None or source_url(row.intake["source_url"], config) != row.intake["source_url"]:
        raise ValidationError("Choose the exact normalized source within current allowed-not-blocked research origins.")
    return {"method": "authority-static-source-authority-v1", "project_id": project.pk,
        "organization_id": project.organization_id, "link_review_id": row.pk, "link_id": str(row.link_id),
        "link_revision": row.revision, "link_state": row.state, "actor_id": actor.pk,
        "source_actor_id": row.source_actor_id, "reviewer_id": row.reviewed_revision.actor_id,
        "approved_by_id": row.approved_by_id, "assignee_id": row.assignee_id,
        "configuration_revision": config.revision, "source_url": row.intake["source_url"],
        "source_origin": normalize_origin("https://" + urlsplit(row.intake["source_url"]).netloc),
        "target_url": row.intake["target_url"], "target_evidence": row.target_evidence,
        "source_collection_permission": True, "rights": {key: row.intake[key] for key in
            ("use_permission", "storage_permission", "not_restricted_provider_copy", "no_personal_payload")},
        "interpretation": "current_read_binding_requires_job_budget_and_boundary_rechecks_not_network_authorization"}


def collect_static_link_source(*, project, actor, binding, before_request, fetcher=None,
                               clock=time.monotonic, sleep=time.sleep, collection_method=COLLECTION_METHOD):
    """One robots/source attempt; the owning job supplies mandatory budget/cancel checks.

    Raw bodies and unrelated links are never returned. Injected transport is for
    local checks; production uses the public-address-pinned SafeFetcher.
    """
    from .crawler import CrawlStopped, PacedFetcher
    from .crawling import CrawlScope, FetchDenied, FetchError, SafeFetcher, USER_AGENT

    if (type(binding) is not dict or not callable(before_request)
        or collection_method not in (COLLECTION_METHOD, REFERENCE_COLLECTION_METHOD)):
        raise PermissionDenied

    def current():
        before_request()
        fresh = static_link_source_authority(project=project, actor=actor,
            link_review_id=binding.get("link_review_id"),
            source_collection_permission=binding.get("source_collection_permission"))
        if fresh != binding:
            raise PermissionDenied

    current()
    origin, source, target = binding["source_origin"], binding["source_url"], binding["target_url"]
    scope = CrawlScope(frozenset({urlsplit(source).hostname}), kind="authority_static_source")
    robots = None
    source_phase = False

    def checkpoint(url):
        current()
        try:
            validate_owned_website_url(url, approved_origin=origin)
            if scope.validate_url(url) != url:
                raise ValidationError("Unnormalized source redirect.")
        except ValidationError:
            raise FetchDenied("static_source_redirect_scope") from None
        if source_phase and not robots.can_fetch(USER_AGENT, url):
            raise FetchDenied("static_source_robots_denied")
        return ""

    transport = fetcher or SafeFetcher(scope, timeout=8, max_redirects=2, max_bytes=MAX_BODY_BYTES)
    paced = PacedFetcher(transport, denial=checkpoint, deadline=clock() + COLLECTION_DEADLINE_SECONDS,
                         delay_seconds=1, clock=clock, sleep=sleep)
    try:
        response = paced.fetch(origin + "/robots.txt", before_send=checkpoint)
        checkpoint(response.url)
        robots, robots_state, paced.delay_seconds = strict_robots_policy(response)
        source_phase = True
        response = paced.fetch(source, before_send=checkpoint)
        checkpoint(response.url)
        if response.status != 200:
            raise FetchError("static_source_http_status")
        kind = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if kind != "text/html":
            raise FetchError("static_source_content_type")
        observed_at = timezone.now().isoformat()
        parser = parse_static_link_references if collection_method == REFERENCE_COLLECTION_METHOD else parse_static_link_source
        evidence = parser(body=response.body, source_url=response.url, target_url=target, observed_at=observed_at)
        result = {"method": collection_method, "state": "collected", "requested_url": source,
            "url": response.url, "observed_at": observed_at, "robots": robots_state,
            "redirects": [{"url": hop.url, "status": hop.status} for hop in response.redirects], "evidence": evidence}
        if len(json.dumps(result, allow_nan=False).encode()) > MAX_RESULT_BYTES:
            raise FetchError("static_source_result_limit")
    except FetchError as error:
        result = {"method": collection_method, "state": "unavailable", "error_category": error.code}
    except CrawlStopped:
        result = {"method": collection_method, "state": "unavailable", "error_category": "static_source_deadline"}
    except (UnicodeError, ValidationError, ValueError, RecursionError):
        result = {"method": collection_method, "state": "unavailable", "error_category": "static_source_document_invalid"}
    current()
    return result
