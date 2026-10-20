"""Inspectable components, not inferred demand, competition or publication approval."""
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from integrations.models import IntegrationConnection
from integrations.query_growth import query_growth_signals
from integrations.services import require_connection_capability
from tenancy.models import Organization, Project, ProjectConfiguration
from tenancy.services import Action, require_project_action
from .action_review import _source
from .feeds import _origin, _safe_link
from .models import JobStatus, TopicCandidateSnapshot, TopicReview

METHOD = "topic-review-v1"
HUMAN_COMPONENTS = ("relevance", "business_value", "geographic_language_fit", "existing_coverage")


def validate_judgments(value):
    if type(value) is not dict or set(value) != set(HUMAN_COMPONENTS):
        raise ValidationError("Assess the exact human components; missing evidence stays unknown.")
    for item in value.values():
        if (type(item) is not dict or set(item) != {"score", "note"}
            or item["score"] is not None and (type(item["score"]) is not int or not 0 <= item["score"] <= 3)
            or type(item["note"]) is not str or len(item["note"]) > 240
            or item["score"] is not None and not item["note"].strip()):
            raise ValidationError("Known human scores need a rationale; use unknown for unavailable evidence.")
    return value


def snapshot_current(project, snapshot):
    config = ProjectConfiguration.objects.filter(project=project).first()
    if (snapshot.project_id != project.pk or snapshot.job.project_id != project.pk
        or snapshot.job.status not in {JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED}
        or snapshot.method_version not in {"topic-discovery-v1", "topic-discovery-v2"} or not config
        or snapshot.job.config_snapshot.get("configuration_revision") != config.revision
        or snapshot.job.config_snapshot.get("market") != config.target_country
        or snapshot.job.config_snapshot.get("languages") != config.target_languages):
        raise ValidationError("Topic source configuration changed; collect fresh evidence.")
    return config


def current_topic_candidate(*, project, actor, snapshot_id, candidate_index):
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    snapshot = TopicCandidateSnapshot.objects.filter(project=project, pk=snapshot_id).select_related("job").first()
    if snapshot is None:
        raise PermissionDenied
    config = snapshot_current(project, snapshot)
    if type(candidate_index) is not int or not 0 <= candidate_index < len(snapshot.output["candidates"]):
        raise ValidationError("Choose one actual bounded source candidate.")
    candidate = snapshot.output["candidates"][candidate_index]
    if candidate["kind"] == "public_feed_item":
        if (not candidate["source_feeds"] or not set(candidate["source_feeds"]) <= set(config.rss_feed_urls)
            or any(_origin(feed) not in config.research_allowed_origins or _origin(feed) in config.research_blocked_origins
                   for feed in candidate["source_feeds"])
            or not _safe_link(candidate["url"], set(config.research_allowed_origins) - set(config.research_blocked_origins))):
            raise ValidationError("Selected feed source is no longer approved.")
    elif candidate["kind"] == "provider_news_article":
        from .news import ATTRIBUTION, current_news_selection, news_request_url
        selection = snapshot.job.input_snapshot.get("news")
        current_news_selection(project, actor, selection, action=Action.VIEW_PROJECT)
        if (candidate.get("provider") != "gdelt" or candidate.get("attribution_url") != ATTRIBUTION
            or candidate.get("news_selection") != selection or candidate.get("news_as_of") != snapshot.job.created_at.isoformat()
            or candidate["source_feeds"] != [news_request_url(selection, snapshot.job.created_at)]
            or not _safe_link(candidate["url"], {selection["publisher_origin"]})):
            raise ValidationError("News candidate must retain exact currently allowed provider/publisher provenance.")
    elif candidate["kind"] == "first_party_query_growth":
        connection = IntegrationConnection.objects.filter(project=project, pk=candidate["connection_id"]).first()
        if connection is None:
            raise PermissionDenied
        require_connection_capability(connection, "query_metrics", dimensions=["query"])
        windows = candidate["source_windows"]
        current = query_growth_signals(project=project, user=actor, connection=connection,
            previous_import_id=windows[0]["import_id"], current_import_id=windows[1]["import_id"])
        if not any(all(row[key] == candidate[key] for key in
            ("query", "previous_observation_id", "current_observation_id", "click_change", "impression_change", "search_type"))
            for row in current["candidates"]):
            raise ValidationError("Query candidate no longer matches its exact comparable observations.")
    else:
        raise ValidationError("This topic source is not supported.")
    return snapshot, candidate, config


def score_topic_components(*, snapshot, candidate_index, candidate, judgments, mapping):
    validate_judgments(judgments)
    components = [{"name": name, "score": judgments[name]["score"], "maximum": 3, "basis": "human_judgment_not_measured",
        "note": judgments[name]["note"]} for name in HUMAN_COMPONENTS]
    query = candidate["kind"] == "first_party_query_growth"
    components += [
        {"name": "growth", "score": 1 if query else None, "maximum": 1,
         "basis": "one_point_for_observed_comparable_first_party_growth_not_strength" if query else "unavailable_feed_is_not_trend_measurement",
         "click_change": candidate.get("click_change"), "impression_change": candidate.get("impression_change")},
        {"name": "freshness", "score": None if query or candidate.get("freshness") == "unknown" else 0 if candidate.get("freshness") == "stale" else 1,
          "maximum": 1, "basis": "provider_reported_date_not_verified_publication_or_current_freshness" if candidate["kind"] == "provider_news_article" else "feed_reported_date_at_collection_not_verified_publication_or_current_freshness",
         "published_at": candidate.get("published_at")},
        {"name": "evidence", "score": 1 if query else min(3, len(candidate["source_feeds"])), "maximum": 3,
         "basis": "bounded_source_observation_count_not_authority_confidence_or_demand"},
        {"name": "competition", "score": None, "maximum": 3, "basis": "unavailable_no_connected_competition_provider"},
    ]
    known = [value for value in components if value["score"] is not None]
    return {"method": METHOD, "snapshot_id": snapshot.pk, "candidate_index": candidate_index,
        "components": components, "assessed_points": sum(value["score"] for value in known),
        "available_points": sum(value["maximum"] for value in known),
        "unknown_components": [value["name"] for value in components if value["score"] is None],
        "demand_volume": "unavailable_not_zero", "as_of_collection": snapshot.created_at.isoformat(),
        "existing_mapping": {"id": mapping.pk, "revision": mapping.revision, "page_kind": mapping.page_kind,
            "preferred_page": mapping.preferred_page, "action": mapping.proposed_action,
            "evidence": "human_selected_not_verified_page_coverage"} if mapping else None,
        "limitations": "incomplete_components_not_a_comparable_SEO_score_or_automatic_creation_publication_instruction"}


def review_topic(*, project, actor, snapshot_id, candidate_index, expected_revision, request_key,
                 label, classification, language, intent_review_id, judgments, reason):
    validate_judgments(judgments)
    if (type(snapshot_id) is not int or snapshot_id < 1 or type(candidate_index) is not int or not 0 <= candidate_index <= 39
        or type(expected_revision) is not int or not 0 <= expected_revision < 2147483647
        or type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key)
        or type(label) is not str or not 1 <= len(label.strip()) <= 240
        or type(classification) is not str or classification not in {"unknown", "trending", "evergreen"}
        or type(language) is not str or type(reason) is not str or not 1 <= len(reason.strip()) <= 500
        or intent_review_id is not None and (type(intent_review_id) is not int or intent_review_id < 1)):
        raise ValidationError("Choose a bounded human topic decision and its current revision.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.LAUNCH_JOB)
        snapshot, candidate, config = current_topic_candidate(project=project, actor=actor,
            snapshot_id=snapshot_id, candidate_index=candidate_index)
        if not config.target_country or language not in config.target_languages:
            raise ValidationError("Choose the current project's market and SEO language.")
        mapping = _source(project, intent_review_id)[0] if intent_review_id else None
        if mapping and (mapping.market != config.target_country or mapping.language != language):
            raise ValidationError("Mapped intent must match this project's market and language.")
        if judgments["existing_coverage"]["score"] is not None and not mapping:
            raise ValidationError("A known coverage judgment needs an explicit current page/intent mapping.")
        fields = {"label": label.strip(), "classification": classification, "language": language,
            "market": config.target_country, "intent_cluster_id": intent_review_id, "judgments": judgments, "reason": reason.strip()}
        existing = TopicReview.objects.filter(project=project, request_key=request_key).first()
        if existing:
            if (existing.actor_id != actor.pk or existing.snapshot_id != snapshot.pk or existing.candidate_index != candidate_index
                or existing.revision != expected_revision + 1 or any(getattr(existing, key) != value for key, value in fields.items())):
                raise ValidationError("Topic request key belongs to another review.")
            if TopicReview.objects.filter(snapshot=snapshot, candidate_index=candidate_index).order_by("-revision").first().pk != existing.pk:
                raise ValidationError("Topic history changed; reload the latest review.")
            return existing
        latest = TopicReview.objects.filter(snapshot=snapshot, candidate_index=candidate_index).order_by("-revision").first()
        if (latest.revision if latest else 0) != expected_revision:
            raise ValidationError("Topic review changed; reload before correcting it.")
        return TopicReview.objects.create(project=project, actor=actor, snapshot=snapshot, candidate_index=candidate_index,
            revision=expected_revision + 1, request_key=request_key, **fields,
            report=score_topic_components(snapshot=snapshot, candidate_index=candidate_index, candidate=candidate,
                                          judgments=judgments, mapping=mapping))


def current_topic_review(*, project, actor, review_id):
    review = TopicReview.objects.filter(project=project, pk=review_id).first()
    if review is None:
        raise PermissionDenied
    if TopicReview.objects.filter(snapshot=review.snapshot, candidate_index=review.candidate_index).order_by("-revision").first().pk != review.pk:
        raise ValidationError("Topic judgment changed; choose its latest reviewed revision.")
    current_topic_candidate(project=project, actor=actor, snapshot_id=review.snapshot_id, candidate_index=review.candidate_index)
    if review.intent_cluster_id:
        _source(project, review.intent_cluster_id)
    return review
