"""Unchanged, separately labeled public-video metadata; no scoring or persistence."""
from datetime import datetime, timedelta, timezone as utc
import http.client
import json
import re
import ssl
import time
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from tenancy.models import Project, ProjectConfiguration
from tenancy.services import Action, require_project_action
from .crawling import (FetchDenied, FetchError, FetchLimitExceeded, _connection_factory,
    _read_body, _remaining, _resolve_public_addresses, _set_socket_timeout, _system_resolver)
from .performance_transport import _API_KEY, _reject_json_constant, _unique_json_object

HOST = "www.googleapis.com"
PATH = "/youtube/v3/search"
MAX_BYTES = 128 * 1024
MAX_RESULTS = 20
FIELDS = "kind,regionCode,nextPageToken,items(kind,id(kind,videoId),snippet(publishedAt,channelId,title,channelTitle))"
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")


class YouTubeSourceError(Exception):
    def __init__(self, category):
        self.category = category
        super().__init__(category)


def validate_youtube_selection(value):
    if (type(value) is not dict or set(value) != {"phrase", "region_code", "relevance_language", "days"}
        or type(value["phrase"]) is not str or not 2 <= len(value["phrase"]) <= 120
        or value["phrase"] != value["phrase"].strip()
        or value["phrase"].startswith("-") or " -" in value["phrase"]
        or any(not (letter.isalnum() or letter in " -") for letter in value["phrase"])
        or value["region_code"] is not None and (type(value["region_code"]) is not str or not re.fullmatch(r"[A-Z]{2}", value["region_code"]))
        or type(value["relevance_language"]) is not str or not re.fullmatch(r"[a-z]{2}|zh-Hans|zh-Hant", value["relevance_language"])
        or type(value["days"]) is not int or value["days"] not in {1, 7}):
        raise ValidationError("Choose a bounded plain configured phrase, explicit region/language preference and one/seven-day window.")
    return value


def current_youtube_selection(project, actor, selection):
    validate_youtube_selection(selection)
    project = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    require_project_action(project=project, user=actor, action=Action.LAUNCH_JOB)
    config = ProjectConfiguration.objects.filter(project=project).first()
    if (not config or selection["phrase"] not in config.seed_topics
        or selection["relevance_language"] not in config.target_languages):
        raise PermissionDenied("Use the current project's configured seed and SEO language.")
    return config


def youtube_request_path(selection, as_of):
    validate_youtube_selection(selection)
    if timezone.is_naive(as_of):
        raise ValidationError("Use an aware UTC reference time.")
    end = as_of.astimezone(utc.utc)
    parameters = {"part": "snippet", "type": "video", "q": selection["phrase"], "order": "relevance",
        "maxResults": MAX_RESULTS, "safeSearch": "strict", "relevanceLanguage": selection["relevance_language"],
        "publishedAfter": (end - timedelta(days=selection["days"])).isoformat().replace("+00:00", "Z"),
        "publishedBefore": end.isoformat().replace("+00:00", "Z"), "fields": FIELDS}
    if selection["region_code"] is not None:
        parameters["regionCode"] = selection["region_code"]
    return PATH + "?" + urlencode(parameters)


def parse_youtube_search(payload):
    """Reject malformed pages rather than altering, ranking or silently dropping results."""
    if (type(payload) is not dict or payload.get("kind") != "youtube#searchListResponse"
        or set(payload) - {"kind", "regionCode", "nextPageToken", "items"}
        or type(payload.get("items")) is not list or len(payload["items"]) > MAX_RESULTS
        or type(payload.get("regionCode")) is not str or not re.fullmatch(r"[A-Z]{2}", payload["regionCode"])
        or "nextPageToken" in payload and (type(payload["nextPageToken"]) is not str
            or not 1 <= len(payload["nextPageToken"]) <= 512
            or any(ord(letter) < 33 or ord(letter) > 126 for letter in payload["nextPageToken"]))):
        raise YouTubeSourceError("malformed_search_page")
    seen = set()
    for row in payload["items"]:
        if (type(row) is not dict or set(row) != {"kind", "id", "snippet"} or row["kind"] != "youtube#searchResult"
            or type(row["id"]) is not dict or set(row["id"]) != {"kind", "videoId"} or row["id"]["kind"] != "youtube#video"
            or type(row["id"]["videoId"]) is not str or not VIDEO_ID.fullmatch(row["id"]["videoId"])
            or type(row["snippet"]) is not dict or set(row["snippet"]) != {"publishedAt", "channelId", "title", "channelTitle"}
            or any(type(row["snippet"][key]) is not str for key in row["snippet"])
            or not CHANNEL_ID.fullmatch(row["snippet"]["channelId"])
            or any(not 1 <= len(row["snippet"][key]) <= 512 or "\x00" in row["snippet"][key] for key in ("title", "channelTitle"))
            or len(row["snippet"]["publishedAt"]) > 40):
            raise YouTubeSourceError("malformed_search_result")
        try:
            moment = datetime.fromisoformat(row["snippet"]["publishedAt"].replace("Z", "+00:00"))
        except ValueError:
            raise YouTubeSourceError("malformed_search_date") from None
        if timezone.is_naive(moment):
            raise YouTubeSourceError("malformed_search_date")
        if row["id"]["videoId"] in seen:
            raise YouTubeSourceError("duplicate_search_result")
        seen.add(row["id"]["videoId"])
    return payload


def youtube_video_url(video_id):
    if type(video_id) is not str or not VIDEO_ID.fullmatch(video_id):
        raise ValidationError("Choose an actual bounded YouTube video identifier.")
    return "https://www.youtube.com/watch?v=" + video_id


@sensitive_variables()
def youtube_search_request(*, project, actor, selection, as_of, api_key, checkpoint=None,
                           resolver=_system_resolver, connection_factory=_connection_factory, clock=time.monotonic):
    current_youtube_selection(project, actor, selection)
    if type(api_key) is not str or not _API_KEY.fullmatch(api_key):
        raise YouTubeSourceError("credential_unavailable")
    path = youtube_request_path(selection, as_of)
    deadline = clock() + 10
    connection = None
    try:
        if checkpoint:
            checkpoint()
        addresses = _resolve_public_addresses(HOST, 443, resolver=resolver, timeout=_remaining(deadline, clock))
        connection = connection_factory("https", addresses[0], HOST, 443, deadline, clock)
        current_youtube_selection(project, actor, selection)
        if checkpoint:
            checkpoint()
        connection.request("GET", path, headers={"Host": HOST, "X-goog-api-key": api_key,
            "Accept": "application/json", "Accept-Encoding": "identity", "Connection": "close"})
        _set_socket_timeout(connection, _remaining(deadline, clock))
        response = connection.getresponse()
        if response.status != 200:
            raise YouTubeSourceError("quota_or_access_denied" if response.status in {403, 429} else
                "redirect_denied" if response.status in {301, 302, 303, 307, 308} else
                "credential_rejected" if response.status == 401 else "provider_unavailable")
        headers = {name.lower(): value.strip() for name, value in response.getheaders()}
        if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise YouTubeSourceError("malformed_search_page")
        body = _read_body(response, headers, max_bytes=MAX_BYTES, deadline=deadline, clock=clock, connection=connection)
        try:
            payload = json.loads(body, parse_constant=_reject_json_constant, object_pairs_hook=_unique_json_object)
        except (ValueError, UnicodeError, RecursionError):
            raise YouTubeSourceError("malformed_search_page") from None
        current_youtube_selection(project, actor, selection)
        if checkpoint:
            checkpoint()
        return parse_youtube_search(payload)
    except (YouTubeSourceError, PermissionDenied, ValidationError):
        raise
    except FetchDenied:
        raise YouTubeSourceError("egress_denied") from None
    except FetchLimitExceeded as error:
        raise YouTubeSourceError(error.code) from None
    except TimeoutError:
        raise YouTubeSourceError("timeout") from None
    except ssl.SSLCertVerificationError:
        raise YouTubeSourceError("tls_verification_failed") from None
    except (FetchError, ssl.SSLError, OSError, http.client.HTTPException):
        raise YouTubeSourceError("network_unavailable") from None
    except (TypeError, ValueError, UnicodeError):
        raise YouTubeSourceError("malformed_search_page") from None
    finally:
        if connection is not None:
            connection.close()
