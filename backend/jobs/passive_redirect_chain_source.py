"""Explicit exact-URL permissions, not an observed chain or a network/commercial grant."""
import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError

from tenancy.services import Action, require_project_action
from tenancy.support_requests import _safe_id
from . import passive_header_source as verified_source
from .passive_redirects import validate_http_source_url


METHOD = "passive-redirect-chain-source-v1"
OBSERVATIONS = ("redirect_chain",)
MAX_TARGETS = 5


def validate_input(data):
    if (type(data) is not dict or set(data) != {"url", "target_urls", "observations", "collection_permission"}
        or data["collection_permission"] is not True or type(data["observations"]) is not list
        or data["observations"] != list(OBSERVATIONS) or type(data["target_urls"]) is not list
        or len(data["target_urls"]) > MAX_TARGETS):
        raise ValidationError("Independently permit one exact source and at most five exact redirect target URLs.")
    origins = []
    urls = [data["url"], *data["target_urls"]]
    for url in urls:
        if type(url) is str and url.startswith("http://"):
            parts = validate_http_source_url(url)
            origin = parts.scheme + "://" + parts.netloc
        else:
            _, origin = verified_source.validate_input({"url": url, "observations": ["response_headers"],
                "collection_permission": True})
        if origin not in origins: origins.append(origin)
    if len(set(urls)) != len(urls):
        raise ValidationError("Choose distinct exact source and target URLs; a repeated URL grants no additional scope.")
    return {"url": urls[0], "target_urls": urls[1:], "observations": list(OBSERVATIONS), "collection_permission": True}, origins


def passive_redirect_chain_source(*, project, actor, data):
    data, origins = validate_input(data)
    for value in (project.pk, project.organization_id, actor.pk): _safe_id(value)
    original = {origin: verified_source._source(project.pk, project.organization_id, actor, origin) for origin in origins}
    digest = hashlib.sha256(json.dumps({"selection": data, "sources": original}, sort_keys=True,
        separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()
    result = {"method_version": METHOD, "organization_id": project.organization_id, "project_id": project.pk,
        "actor_id": actor.pk, **data, "origins": [{"origin": origin, "verification_id": row["verification"]["id"],
            "verified_at": row["verification"]["verified_at"].isoformat()} for origin, row in original.items()],
        "source_digest": digest,
        "interpretation": "explicit_exact_url_allowlist_not_observed_chain_network_job_or_commercial_reservation"}
    for origin, row in original.items():
        if verified_source._source(project.pk, project.organization_id, actor, origin) != row: raise PermissionDenied
    require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
    return result
