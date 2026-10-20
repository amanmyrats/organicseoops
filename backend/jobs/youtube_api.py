from http import HTTPStatus
import re

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.views.decorators.debug import sensitive_variables, sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from providers.models import YouTubeAPIKey
from tenancy.models import ProjectConfiguration
from tenancy.services import Action, require_project_action
from .ai_text_api import _payload, _project
from .research_api import _result
from .usage import UsageLimitError
from .youtube import validate_youtube_selection, YouTubeSourceError
from .youtube_search import search_youtube, POLICY_VERSION, MEMORY_SECONDS


@sensitive_post_parameters()
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def project_youtube_search(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _result({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = _project(request, organization_id, project_id)
    if project is None:
        return _result({"message": "Project unavailable."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
            action=Action.VIEW_PROJECT if request.method == "GET" else Action.LAUNCH_JOB)
        if request.method == "GET":
            config = ProjectConfiguration.objects.filter(project=project).first()
            phrases = []
            if config:
                for phrase in config.seed_topics:
                    try:
                        validate_youtube_selection({"phrase": phrase, "region_code": None, "relevance_language": "en", "days": 1})
                        phrases.append(phrase)
                    except ValidationError:
                        pass
            return _result({"project_id": project.pk, "policy_version": POLICY_VERSION,
                "memory_seconds": MEMORY_SECONDS, "live_verified": False,
                "configured": YouTubeAPIKey.objects.filter(key="primary", state="active").exists(),
                "phrases": phrases, "languages": [value for value in config.target_languages
                    if re.fullmatch(r"[a-z]{2}|zh-Hans|zh-Hant", value)] if config else [],
                "google_trends": "unavailable_no_supported_contract"})
        if not ratelimit.consume(request, action="ai_text_request", user=request.user):
            return _result({"message": "Too many source requests."}, HTTPStatus.TOO_MANY_REQUESTS)
        data = _payload(request, {"selection", "policy_version", "accepted", "request_key"})
        return _result(search_youtube(project=project, actor=request.user, **data))
    except PermissionDenied:
        return _result({"message": "Current source/role unavailable."}, HTTPStatus.FORBIDDEN)
    except UsageLimitError as error:
        return _result({"message": "Search allowance unavailable.", "code": error.category}, HTTPStatus.TOO_MANY_REQUESTS)
    except YouTubeSourceError as error:
        return _result({"message": "YouTube search unavailable; no results were retained. No automatic retry.",
            "code": error.category}, HTTPStatus.TOO_MANY_REQUESTS if error.category in {"client_busy", "client_daily_quota", "quota_or_access_denied"} else HTTPStatus.CONFLICT)
    except (ValidationError, ValueError, TypeError, UnicodeError, IntegrityError):
        return _result({"message": "Check current configured seed/language, region, policy acceptance and request."}, HTTPStatus.CONFLICT)
