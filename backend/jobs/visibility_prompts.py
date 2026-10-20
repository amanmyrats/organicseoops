"""Human-reviewed methodology for declared native API text samples, not collection."""
import re
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from integrations.brand import default_brand_label
from tenancy.models import Organization, Project, ProjectConfiguration
from tenancy.services import Action, require_project_action
from .ai_text import _max_cost
from .intent_mapping import current_query_findings, _project_page
from .models import AIVisibilityPromptSet, IntentClusterReview

METHOD = "api-text-visibility-v1"
SURFACE = "openai_responses_text"


def sampling_policy(*, max_output_tokens, max_cost_usd):
    if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 256:
        raise ValidationError("Choose a1–256 output-token ceiling for each future sample.")
    cost = _max_cost(max_cost_usd)
    return {"method": METHOD, "surface": SURFACE, "collection": "user_selected_single_prompt",
        "require_standard_access": True,
        "repeat_minimum_hours": 24, "automatic_schedule": False, "internal_units_per_attempt": 1,
        "max_output_tokens": max_output_tokens, "max_cost_usd": str(cost), "retrieval": "none",
        "citation_measurement": "unavailable", "device_control": "unsupported", "location_control": "unsupported",
        "language_control": "prompt_text_only_not_guaranteed", "provider_store": False,
        "provider_zero_data_retention": "not_established", "customer_retention": "D098"}


def validate_prompts(prompts):
    if type(prompts) is not list or not 1 <= len(prompts) <= 5:
        raise ValidationError("Review one to five prompts.")
    for row in prompts:
        if (type(row) is not dict or set(row) != {"key", "kind", "text", "intent_review_id"}
            or type(row["key"]) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", row["key"])
            or type(row["kind"]) is not str or row["kind"] not in {"neutral", "branded"}
            or type(row["text"]) is not str or not 1 <= len(row["text"]) <= 500 or not row["text"].strip()
            or any(ord(char) < 32 and char not in "\n\t" for char in row["text"])
            or type(row["intent_review_id"]) is not int or row["intent_review_id"] < 1):
            raise ValidationError("Use bounded unchanged human prompt text, distinct keys, group and current intent review.")
    if (len({row["key"] for row in prompts}) != len(prompts)
        or len({row["text"].casefold().strip() for row in prompts}) != len(prompts)):
        raise ValidationError("Prompt keys and texts must be distinct.")


def validate_prompt_set_snapshot(row):
    validate_prompts(row.prompts)
    if (any(type(value) is not str or not value.strip() for value in
            (row.label, row.language, row.market, row.review_note))
        or type(row.context) is not dict
        or set(row.context) != {"configuration_revision", "market", "language", "brand_aliases", "origins"}
        or row.context["market"] != row.market or row.context["language"] != row.language
        or type(row.context["configuration_revision"]) is not int or row.context["configuration_revision"] < 1
        or type(row.context["brand_aliases"]) is not list or not row.context["brand_aliases"]
        or any(type(alias) is not str or not 1 <= len(alias) <= 120 for alias in row.context["brand_aliases"])
        or type(row.context["origins"]) is not list or not row.context["origins"]
        or any(type(origin) is not str or not 1 <= len(origin) <= 512 for origin in row.context["origins"])
        or type(row.policy) is not dict):
        raise ValidationError("Record bounded current project context and human coverage review.")
    if row.policy != sampling_policy(max_output_tokens=row.policy.get("max_output_tokens"),
                                     max_cost_usd=row.policy.get("max_cost_usd")):
        raise ValidationError("Only the declared API text/manual sampling methodology is supported.")


def _context(project, language, prompts):
    config = ProjectConfiguration.objects.filter(project=project).first()
    if (not config or not config.target_country or language not in config.target_languages or not config.brand_aliases):
        raise ValidationError("Configure current market, SEO language and explicit brand aliases first.")
    origins = [project.canonical_origin, *project.domain_aliases.order_by("pk").values_list("origin", flat=True)]
    terms = list(dict.fromkeys([*config.brand_aliases, *(urlsplit(origin).hostname for origin in origins)]))
    for row in prompts:
        mapping = IntentClusterReview.objects.filter(project=project, pk=row["intent_review_id"]).first()
        if mapping is None:
            raise PermissionDenied
        latest = IntentClusterReview.objects.filter(project=project, cluster_id=mapping.cluster_id).order_by("-revision").first()
        if latest.pk != mapping.pk or mapping.market != config.target_country or mapping.language != language:
            raise ValidationError("Reload exact-current intent coverage before reviewing prompts.")
        if mapping.source_finding_ids:
            current_query_findings(project, mapping.source_finding_ids)
        elif not set(mapping.manual_topics) <= set(config.seed_topics):
            raise ValidationError("The intent review's source topics changed.")
        if mapping.preferred_page:
            _project_page(project, mapping.preferred_page)
        branded = default_brand_label(row["text"], terms) == "branded"
        if branded != (row["kind"] == "branded"):
            raise ValidationError("Neutral prompts must omit configured brands/domains; branded prompts must name one explicitly.")
    return {"configuration_revision": config.revision, "market": config.target_country, "language": language,
        "brand_aliases": config.brand_aliases, "origins": origins}


def current_prompt_set(*, project, actor, row):
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    if row.project_id != project.pk:
        raise PermissionDenied
    validate_prompt_set_snapshot(row)
    latest = AIVisibilityPromptSet.objects.filter(project=project, set_id=row.set_id).order_by("-revision").first()
    if latest.pk != row.pk or row.context != _context(project, row.language, row.prompts):
        raise ValidationError("Methodology or current source context changed; review a new revision.")
    return row


def review_prompt_set(*, project, actor, request_key, label, language, prompts, review_note,
                      max_output_tokens, max_cost_usd, acknowledge_api_limits, set_id=None, expected_revision=None):
    if (type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key)
        or type(label) is not str or not 1 <= len(label.strip()) <= 120
        or type(language) is not str or type(review_note) is not str or not 1 <= len(review_note.strip()) <= 500
        or acknowledge_api_limits is not True or (set_id is None) != (expected_revision is None)):
        raise ValidationError("Review current intent coverage and acknowledge the API-only limits.")
    validate_prompts(prompts)
    policy = sampling_policy(max_output_tokens=max_output_tokens, max_cost_usd=max_cost_usd)
    if set_id is not None:
        try:
            set_id = UUID(str(set_id))
        except ValueError:
            raise ValidationError("Choose an actual project prompt set.") from None
        if type(expected_revision) is not int or not 1 <= expected_revision < 65535:
            raise ValidationError("Reload the current prompt-set revision.")
    with transaction.atomic():
        org = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=org)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        context = _context(project, language, prompts)
        existing = AIVisibilityPromptSet.objects.filter(project=project, request_key=request_key).first()
        if existing:
            current_prompt_set(project=project, actor=actor, row=existing)
            if (existing.actor_id != actor.pk or (set_id is not None and existing.set_id != set_id)
                or existing.revision != (expected_revision + 1 if set_id else 1)
                or (existing.label, existing.language, existing.prompts, existing.review_note, existing.policy, existing.context)
                != (label.strip(), language, prompts, review_note.strip(), policy, context)):
                raise ValidationError("Prompt review key belongs to another decision.")
            return existing
        if set_id:
            latest = AIVisibilityPromptSet.objects.filter(project=project, set_id=set_id).order_by("-revision").first()
            if latest is None or latest.revision != expected_revision:
                raise ValidationError("Prompt methodology changed; reload before correcting.")
            revision = latest.revision + 1
        else:
            set_id, revision = uuid4(), 1
        return AIVisibilityPromptSet.objects.create(project=project, actor=actor, set_id=set_id, revision=revision,
            request_key=request_key, label=label.strip(), language=language, market=context["market"],
            prompts=prompts, context=context, policy=policy, review_note=review_note.strip())
