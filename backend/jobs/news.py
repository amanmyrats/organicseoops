"""GDELT metadata only. Publisher bodies/images are neither fetched nor licensed here."""
from datetime import timedelta
import re
from urllib.parse import urlencode, urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from tenancy.models import Project, ProjectConfiguration
from tenancy.services import Action, require_project_action
from .crawling import CrawlScope, FetchDenied, FetchError, SafeFetcher
from .feeds import MAX_FEED_BYTES, parse_feed

ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
ATTRIBUTION = "https://www.gdeltproject.org/"
METHOD = "gdelt-doc-metadata-v1"
SUPPORTED_PHRASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 -]{1,119}")


def validate_news_selection(value):
    if (type(value) is not dict or set(value) != {"phrase", "publisher_origin", "days"}
        or type(value["phrase"]) is not str or not SUPPORTED_PHRASE.fullmatch(value["phrase"])
        or not value["phrase"].strip() or value["phrase"] != value["phrase"].strip()
        or type(value["publisher_origin"]) is not str
        or type(value["days"]) is not int or value["days"] not in {1, 7}):
        raise ValidationError("Choose a plain bounded configured phrase, approved publisher and one/seven-day window.")
    from .feeds import _origin
    try:
        parsed = urlsplit(value["publisher_origin"])
        if (parsed.scheme != "https" or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path or _origin(value["publisher_origin"]) != value["publisher_origin"]):
            raise ValidationError("Select one exact HTTPS publisher origin.")
    except ValueError:
        raise ValidationError("Select one exact HTTPS publisher origin.") from None
    return value


def current_news_selection(project, actor, selection, *, action=Action.LAUNCH_JOB):
    validate_news_selection(selection)
    project = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    require_project_action(project=project, user=actor, action=action)
    config = ProjectConfiguration.objects.filter(project=project).first()
    if (not config or selection["phrase"] not in config.seed_topics
        or selection["publisher_origin"] not in config.research_allowed_origins
        or selection["publisher_origin"] in config.research_blocked_origins):
        raise PermissionDenied("News selection is not currently configured for this project.")
    return config


def news_request_url(selection, as_of):
    validate_news_selection(selection)
    if timezone.is_naive(as_of):
        raise ValidationError("News windows require an aware UTC reference time.")
    from datetime import timezone as utc
    end = as_of.astimezone(utc.utc)
    return ENDPOINT + "?" + urlencode({
        "query": f'"{selection["phrase"]}" domainis:{urlsplit(selection["publisher_origin"]).hostname}',
        "mode": "artlist", "format": "rss", "maxrecords": 20, "sort": "datedesc",
        "startdatetime": (end - timedelta(days=selection["days"])).strftime("%Y%m%d%H%M%S"),
        "enddatetime": end.strftime("%Y%m%d%H%M%S"),
    })


def collect_project_news(*, project, actor, selection, as_of, fetcher=None, checkpoint=None):
    current_news_selection(project, actor, selection)
    url = news_request_url(selection, as_of)
    provenance = {"provider": "gdelt", "method": METHOD, "selection": selection, "as_of": as_of.isoformat(),
        "attribution_url": ATTRIBUTION, "source_feed": url, "record_limit": 20,
        "market_language": "not_verified_english_translingual_search", "publisher_content": "not_fetched_not_licensed",
        "coverage": "top_n_provider_metadata_not_complete_news_or_search_demand"}

    def before_request(requested):
        if requested != url:
            raise FetchDenied("news_endpoint_denied")
        current_news_selection(project, actor, selection)
        if checkpoint:
            checkpoint()

    fetcher = fetcher or SafeFetcher(CrawlScope(frozenset({"api.gdeltproject.org"}), kind="news"),
        timeout=8, max_redirects=0, max_bytes=MAX_FEED_BYTES)
    try:
        response = fetcher.fetch(url, before_request=before_request)
        before_request(response.url)
    except FetchError as error:
        return {**provenance, "state": "failed", "error": error.code, "items": []}
    current_news_selection(project, actor, selection)
    if response.status != 200:
        return {**provenance, "state": "failed", "error": "news_rate_limited" if response.status == 429 else "news_http_status", "items": []}
    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() not in {
        "application/rss+xml", "application/xml", "text/xml"}:
        return {**provenance, "state": "failed", "error": "unsupported_news_type", "items": []}
    result = parse_feed(body=response.body, feed_url=url, allowed_origins={selection["publisher_origin"]})
    # The provider's RSS timestamp is not verified publisher publication evidence.
    for item in result["items"]:
        item["observation"] = "provider_news_metadata_not_popularity_or_business_relevance"
    result["truncated"] = result.get("truncated", False) or len(result["items"]) >= 20
    result["items"] = result["items"][:20]
    if result["state"] != "failed" and result["truncated"]:
        result["state"] = "partial"
    return {**provenance, **result}
