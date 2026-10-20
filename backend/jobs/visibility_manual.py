"""D128 independently permitted human answer reports. Never a consumer/API collector."""
from datetime import datetime
import json
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from tenancy.models import normalize_origin
from .local_feedback import _text

METHOD = "visibility-human-answer-v1"
SOURCE = "customer_owned_manual_answer"
SURFACE = "customer_reported_answer"
MAX_BYTES = 24 * 1024
FIELDS = {"method_version", "source_kind", "surface", "origin", "configuration_revision", "intent_review_id",
    "prompt", "prompt_version", "prompt_kind", "requested_market", "requested_language", "source_label",
    "observation_reference", "observed_at", "reported_model", "reported_retrieval", "applied_location",
    "applied_language", "applied_device", "status", "answer", "evidence_note", "storage_permission",
    "not_response_only_copy", "no_personal_payload"}


def validate_manual_answer(data, *, as_of=None):
    """Exact scalar syntax only; declarations never establish current authority or a provider license."""
    as_of = timezone.now() if as_of is None else as_of
    if (not isinstance(as_of, datetime) or timezone.is_naive(as_of)
        or type(data) is not dict or set(data) != FIELDS
        or data["method_version"] != METHOD or data["source_kind"] != SOURCE or data["surface"] != SURFACE
        or any(data[key] is not True for key in ("storage_permission", "not_response_only_copy", "no_personal_payload"))
        or type(data["configuration_revision"]) is not int or not 1 <= data["configuration_revision"] < 2**31
        or type(data["intent_review_id"]) is not int or not 1 <= data["intent_review_id"] < 2**53
        or type(data["prompt_version"]) is not int or not 1 <= data["prompt_version"] < 2**31):
        raise ValidationError("Use exact manual answer fields, reviewed source and independent storage/privacy rights.")
    for key, limit, required in (("origin", 512, True), ("prompt", 500, True), ("prompt_kind", 16, True),
        ("requested_market", 80, True), ("requested_language", 35, True), ("source_label", 120, True),
        ("observation_reference", 64, True), ("observed_at", 64, True), ("reported_model", 120, False),
        ("reported_retrieval", 16, True), ("applied_location", 240, False), ("applied_language", 35, False),
        ("applied_device", 16, True), ("status", 16, True), ("answer", 4000, False), ("evidence_note", 500, True)):
        _text(data[key], limit, required=required)
    if (normalize_origin(data["origin"]) != data["origin"] or not data["origin"].startswith("https://")
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", data["observation_reference"])
        or data["prompt_kind"] not in {"neutral", "branded"}
        or data["reported_retrieval"] not in {"none", "reported", "unknown"}
        or data["applied_device"] not in {"desktop", "mobile", "unknown"}
        or not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", data["requested_language"])
        or data["applied_language"] and not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", data["applied_language"])
        or data["status"] not in {"complete", "partial", "unavailable"}
        or data["status"] == "unavailable" and data["answer"]
        or data["status"] != "unavailable" and not data["answer"].strip()):
        raise ValidationError("Keep exact human prompt/answer, categorical coverage and separate reported/unknown context.")
    try:
        stamp = datetime.fromisoformat(data["observed_at"])
        if timezone.is_naive(stamp) or stamp > as_of or len(json.dumps(data, allow_nan=False).encode()) > MAX_BYTES:
            raise ValueError
    except (TypeError, ValueError, UnicodeError):
        raise ValidationError("Use an aware nonfuture observation time and bounded serialized manual evidence.") from None
    return dict(data)


def require_manual_authority(*, project, actor, intake):
    from urllib.parse import urlsplit
    from integrations.oauth import _verified
    from tenancy.models import Project, ProjectConfiguration
    from tenancy.services import require_passive_security_scope
    from .visibility_prompts import _context
    project = Project.objects.select_related("organization").filter(pk=project.pk, organization_id=project.organization_id).first()
    if project is None or not _verified(actor):
        raise PermissionDenied
    data = validate_manual_answer(intake)
    verification = require_passive_security_scope(project=project, user=actor, origin=data["origin"])
    config = ProjectConfiguration.objects.get(project=project)
    if (config.revision != data["configuration_revision"] or config.target_country != data["requested_market"]
        or verification.verified_at > timezone.now()):
        raise ValidationError("Reload actual current project context and verified website scope.")
    # Actual manual prompt/intent; only pure source/neutral-branded validation is shared, never an API policy/job.
    context = _context(project, data["requested_language"], [{"text": data["prompt"], "kind": data["prompt_kind"],
        "intent_review_id": data["intent_review_id"]}])
    context["competitor_domains"] = list(dict.fromkeys(urlsplit(origin).hostname for origin in config.competitor_origins))
    context["business_facts"] = "unavailable_no_approved_fact_registry"
    return verification, context, data


def entity_context(context):
    from urllib.parse import urlsplit
    return {"brand_aliases": context["brand_aliases"],
        "project_domains": list(dict.fromkeys(urlsplit(origin).hostname for origin in context["origins"])),
        "competitor_domains": context["competitor_domains"], "configuration_revision": context["configuration_revision"],
        "business_facts": context["business_facts"]}


def validate_manual_snapshot(row):
    from .visibility_entities import candidates, validate_matches
    data = validate_manual_answer(row.intake)
    _text(row.reason, 500, required=True)
    if (row.intent_review.project_id != row.project_id or row.intent_review_id != data["intent_review_id"]
        or row.verification.project_id != row.project_id or row.verification.origin != data["origin"]
        or timezone.is_naive(row.verified_at) or row.verified_at > timezone.now()
        or type(row.context) is not dict or set(row.context) != {"configuration_revision", "market", "language", "brand_aliases",
            "origins", "competitor_domains", "business_facts"}
        or row.context["configuration_revision"] != data["configuration_revision"]
        or row.context["market"] != data["requested_market"] or row.context["language"] != data["requested_language"]
        or type(row.context["brand_aliases"]) is not list or not row.context["brand_aliases"]
        or any(type(value) is not str or not 1 <= len(value) <= 120 for value in row.context["brand_aliases"])
        or type(row.context["origins"]) is not list or data["origin"] not in row.context["origins"]
        or any(type(origin) is not str or normalize_origin(origin) != origin for origin in row.context["origins"])
        or type(row.context["competitor_domains"]) is not list or len(row.context["competitor_domains"]) > 20
        or any(type(domain) is not str or not domain or len(domain) > 253 for domain in row.context["competitor_domains"])
        or row.context["business_facts"] != "unavailable_no_approved_fact_registry" or type(row.evaluated) is not bool):
        raise ValidationError("Keep actual scoped intent/source/context and exact human evidence.")
    context = entity_context(row.context)
    validate_matches(data["answer"], context, row.matches)
    if row.evaluated and (data["status"] != "complete" or candidates(data["answer"], context)["has_more"]):
        raise ValidationError("Partial/unavailable/truncated reports cannot become evaluated valid answers.")
    if len(json.dumps({"context": row.context, "matches": row.matches}, allow_nan=False).encode()) > 32 * 1024:
        raise ValidationError("Manual human evaluation exceeds its private evidence ceiling.")
    if row._state.adding:
        from .models import AIVisibilityManualObservation
        previous = AIVisibilityManualObservation.objects.filter(project_id=row.project_id,
            observation_id=row.observation_id).order_by("-revision").first()
        if row.evaluated and (previous is None or previous.revision + 1 != row.revision or previous.intake != row.intake):
            raise ValidationError("Evaluate a real exact unchanged report revision, never a new or edited answer.")
        verification, current, _data = require_manual_authority(project=row.project, actor=row.actor, intake=data)
        if current != row.context or verification.pk != row.verification_id or verification.verified_at != row.verified_at:
            raise ValidationError("New evidence must bind actual current source/context authority.")


def manual_source_current(row):
    try:
        verification, context, _data = require_manual_authority(project=row.project, actor=row.actor, intake=row.intake)
        return verification.pk == row.verification_id and verification.verified_at == row.verified_at and context == row.context
    except (PermissionDenied, ValidationError):
        return False


def record_manual_answer(*, project, actor, request_key, intake, reason, evaluated=False, matches=None,
                         observation_id=None, expected_revision=None):
    from uuid import UUID, uuid4
    from django.db import transaction
    from tenancy.models import Organization, Project
    from .models import AIVisibilityManualObservation
    if (type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key)
        or type(evaluated) is not bool or matches is not None and type(matches) is not list
        or (observation_id is None) != (expected_revision is None)
        or expected_revision is not None and (type(expected_revision) is not int or not 1 <= expected_revision < 2**31 - 1)):
        raise ValidationError("Choose an exact current report revision and request key.")
    _text(reason, 500, required=True)
    if observation_id is not None:
        try:
            observation_id = UUID(str(observation_id))
        except (ValueError, TypeError):
            raise ValidationError("Choose a project-owned manual observation.") from None
    matches = [] if matches is None else matches
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        verification, context, data = require_manual_authority(project=project, actor=actor, intake=intake)
        previous = None
        if observation_id:
            previous = AIVisibilityManualObservation.objects.filter(project=project, observation_id=observation_id).order_by("-revision").first()
            if previous is None or not manual_source_current(previous):
                raise PermissionDenied
        existing = AIVisibilityManualObservation.objects.filter(project=project, request_key=request_key).first()
        if existing:
            latest = AIVisibilityManualObservation.objects.filter(project=project, observation_id=existing.observation_id).order_by("-revision").first()
            if (latest.pk != existing.pk or existing.actor_id != actor.pk
                or observation_id and observation_id != existing.observation_id
                or (existing.revision, existing.intake, existing.reason, existing.evaluated, existing.matches)
                != (expected_revision + 1 if observation_id else 1, data, reason, evaluated, matches)
                or not manual_source_current(existing)):
                raise ValidationError("Manual report request key belongs to another or stale decision.")
            return existing
        if previous and previous.revision != expected_revision:
            raise ValidationError("Manual report changed; inspect the latest immutable revision.")
        same_reference = AIVisibilityManualObservation.objects.filter(project=project,
            intake__source_label=data["source_label"], intake__observation_reference=data["observation_reference"])
        if observation_id:
            same_reference = same_reference.exclude(observation_id=observation_id)
        if same_reference.exists():
            raise ValidationError("This source/reference already has an immutable observation; correct it instead of double-counting.")
        if evaluated and (previous is None or previous.intake != data):
            raise ValidationError("Record changed evidence unevaluated, then review its exact full answer separately.")
        return AIVisibilityManualObservation.objects.create(project=project, actor=actor, intent_review_id=data["intent_review_id"],
            verification=verification, verified_at=verification.verified_at, observation_id=observation_id or uuid4(),
            revision=previous.revision + 1 if previous else 1, request_key=request_key, intake=data, context=context,
            evaluated=evaluated, matches=matches, reason=reason)


def comparable_context(row):
    from hashlib import sha256
    data = row.intake
    return {key: data[key] for key in ("method_version", "source_kind", "surface", "origin", "source_label", "prompt_version", "prompt_kind",
        "intent_review_id", "requested_market", "requested_language", "reported_model", "reported_retrieval",
        "applied_location", "applied_language", "applied_device")} | {
        "prompt_sha256": sha256(data["prompt"].encode()).hexdigest(), "entity_context": entity_context(row.context)}


def manual_rates(*, project, actor):
    from hashlib import sha256
    from django.db.models import Exists, OuterRef
    from tenancy.services import Action, require_project_action
    from .models import AIVisibilityManualObservation
    from .visibility_entities import _rate
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    newer = AIVisibilityManualObservation.objects.filter(project=project, observation_id=OuterRef("observation_id"), revision__gt=OuterRef("revision"))
    rows = list(AIVisibilityManualObservation.objects.filter(project=project).annotate(newer=Exists(newer)).filter(newer=False)
        .select_related("project__organization", "intent_review", "verification", "actor").order_by("-pk")[:101])
    groups = {}
    for row in rows[:100]:
        context = comparable_context(row)
        key = sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
        group = groups.setdefault(key, {"comparison_key": key, "context": context, "report_ids": [], "eligible_report_ids": [],
            "statuses": {}, "exclusions": {}, "numerator": 0, "competitors": {domain: 0 for domain in row.context["competitor_domains"]}})
        group["report_ids"].append(row.pk)
        status = row.intake["status"]
        group["statuses"][status] = group["statuses"].get(status, 0) + 1
        exclusion = ""
        if not manual_source_current(row):
            exclusion = "stale_source_or_actor"
        elif status != "complete":
            exclusion = "partial_or_unavailable"
        elif not row.evaluated:
            exclusion = "unevaluated"
        else:
            try:
                validate_manual_snapshot(row)
            except (ValidationError, PermissionDenied):
                exclusion = "invalid_or_changed_evidence"
            if not exclusion and any(match["decision"] == "uncertain" for match in row.matches):
                exclusion = "uncertain_entity"
        if exclusion:
            group["exclusions"][exclusion] = group["exclusions"].get(exclusion, 0) + 1
            continue
        group["eligible_report_ids"].append(row.pk)
        confirmed = [match for match in row.matches if match["decision"] == "confirmed"]
        group["numerator"] += int(any(match["kind"] in {"brand", "project_domain"} for match in confirmed))
        for domain in group["competitors"]:
            group["competitors"][domain] += int(any(match["kind"] in {"competitor", "competitor_domain"} and match["entity"] == domain for match in confirmed))
    for group in groups.values():
        denominator = len(group["eligible_report_ids"])
        group["mention_rate"] = _rate(group.pop("numerator"), denominator)
        group["competitor_mention_rates"] = {domain: _rate(count, denominator) for domain, count in group.pop("competitors").items()}
        group["citation_rate"] = {"numerator": None, "denominator": 0, "percent": None, "state": "unavailable"}
    return {"project_id": project.pk, "method": METHOD, "surface": SURFACE, "groups": list(groups.values()), "has_more": len(rows) > 100,
        "scope": "latest_100_current_report_revisions_not_all_chats_or_api_samples", "external_cost": None, "referrals": None}
