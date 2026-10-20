"""Inspectable lexical candidates and human corrections, not inferred factual truth."""
from decimal import Decimal
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from providers.models import normalize_compatible_endpoint
from tenancy.models import Organization, Project, ProjectConfiguration
from tenancy.services import Action, require_project_action
from .models import AIVisibilityAnswerReview, JobRun, JobStatus
from .visibility_collection import HANDLER, METHOD as COLLECTION_METHOD, valid_answer

METHOD = "visibility-entities-v1"
KINDS = {"brand", "competitor", "project_domain", "competitor_domain", "other_domain"}
DECISIONS = {"confirmed", "rejected", "uncertain"}


def answer_for(job):
    answer = job.output.get("answer") if job.handler == HANDLER and job.method_version == COLLECTION_METHOD and type(job.output) is dict else None
    if not valid_answer(answer):
        raise ValidationError("This sample has no bounded collected answer evidence.")
    return answer


def entity_context(job, config):
    original = job.config_snapshot["visibility"]["context"]
    return {"brand_aliases": original["brand_aliases"],
        "project_domains": list(dict.fromkeys(urlsplit(origin).hostname for origin in original["origins"])),
        "competitor_domains": list(dict.fromkeys(urlsplit(origin).hostname for origin in config.competitor_origins)),
        "configuration_revision": config.revision,
        "business_facts": "unavailable_no_approved_fact_registry"}


def _safe_url(value):
    if type(value) is not str or not 1 <= len(value) <= 2048 or any(ord(char) < 32 for char in value) or "\\" in value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.port not in {None, 80 if parsed.scheme == "http" else 443}:
            return None
        normalize_compatible_endpoint(urlunsplit(("https", parsed.hostname, parsed.path, "", "")))
    except (ValidationError, ValueError):
        return None
    return parsed.hostname.lower()


def _spans(text, term, *, domain=False):
    # casefold may expand a character (e.g. ß); map back to exact original Unicode codepoints.
    positions = [index for index, char in enumerate(text) for _ in char.casefold()]
    boundary = r"[\w.-]" if domain else r"\w"
    for match in re.finditer("(?<!" + boundary + ")" + re.escape(term.casefold()) + "(?!" + boundary + ")", text.casefold()):
        yield positions[match.start()], positions[match.end() - 1] + 1


def candidates(answer, context):
    rows = {}
    for kind, terms in (("brand", context["brand_aliases"]), ("project_domain", context["project_domains"]), ("competitor_domain", context["competitor_domains"])):
        for term in terms:
            for start, end in _spans(answer, term, domain=kind != "brand"):
                entity = "project_brand" if kind == "brand" else term.lower()
                key = (kind, entity, start, end)
                rows[key] = {"kind": kind, "entity": entity, "start": start, "end": end, "decision": "uncertain",
                    "note": "Lexical candidate only; review alias/domain meaning in the full answer."}
    links = []
    for match in re.finditer(r"https?://[^\s<>\"']+", answer):
        value = match.group().rstrip(".,;!?)")
        domain = _safe_url(value)
        start, end = match.start(), match.start() + len(value)
        links.append({"start": start, "end": end, "text": value, "domain": domain, "safe_syntax": domain is not None,
            "citation": "unavailable_text_link_not_measured_citation", "redirect": "not_fetched_unknown"})
        if domain:
            kind = "project_domain" if domain in context["project_domains"] else "competitor_domain" if domain in context["competitor_domains"] else "other_domain"
            rows[(kind, domain, start, end)] = {"kind": kind, "entity": domain, "start": start, "end": end, "decision": "uncertain",
                "note": "Safe-syntax text link, not a measured citation; exact host only, redirects not fetched."}
    # Explicit coverage ceiling; a truncated candidate list cannot establish absence.
    ordered = sorted(rows.values(), key=lambda row: (row["start"], row["end"], row["kind"]))
    return {"method": METHOD, "span_units": "unicode_codepoints", "matches": ordered[:100], "links": links[:50],
        "has_more": len(ordered) > 100 or len(links) > 50, "factual_comparison": context["business_facts"],
        "citation_measurement": "unavailable", "evaluation": "human_review_required"}


def validate_matches(answer, context, matches):
    if type(matches) is not list or len(matches) > 100:
        raise ValidationError("Review at most100 exact entity spans.")
    seen = set()
    for row in matches:
        if (type(row) is not dict or set(row) != {"kind", "entity", "start", "end", "decision", "note"}
            or type(row["kind"]) is not str or row["kind"] not in KINDS
            or type(row["decision"]) is not str or row["decision"] not in DECISIONS
            or type(row["entity"]) is not str or not 1 <= len(row["entity"]) <= 253
            or type(row["start"]) is not int or type(row["end"]) is not int or not 0 <= row["start"] < row["end"] <= len(answer)
            or not answer[row["start"]:row["end"]].strip()
            or not valid_answer(row["note"]) or not 1 <= len(row["note"].strip()) <= 240):
            raise ValidationError("Use exact bounded Unicode-codepoint spans, entity, decision and human rationale.")
        kind, entity = row["kind"], row["entity"]
        if kind == "brand":
            if entity != "project_brand":
                raise ValidationError("Resolve a human-reviewed brand alias to this project brand only.")
        elif kind == "competitor":
            if entity not in context["competitor_domains"]:
                raise ValidationError("A human-reviewed competitor name must resolve to a configured competitor domain.")
        else:
            if _safe_url("https://" + entity + "/") != entity:
                raise ValidationError("Domain entities must be safe exact lowercase public hostnames.")
            if kind == "project_domain" and entity not in context["project_domains"] or kind == "competitor_domain" and entity not in context["competitor_domains"]:
                raise ValidationError("Domain match must resolve to the snapshotted project or configured competitor.")
            text = answer[row["start"]:row["end"]]
            if text.casefold() != entity and _safe_url(text) != entity:
                raise ValidationError("Domain evidence must name its exact hostname; redirects/variants are not inferred.")
        identity = (kind, entity, row["start"], row["end"])
        if identity in seen:
            raise ValidationError("Do not duplicate the same evidence span.")
        seen.add(identity)


def validate_review_snapshot(row):
    if not row.project_id or not row.job_id or row.job.project_id != row.project_id or not row.actor_id:
        raise ValidationError("Review must stay inside the collected answer's project.")
    answer = answer_for(row.job)
    if row.method_version != METHOD or row.answer_sha256 != sha256(answer.encode()).hexdigest():
        raise ValidationError("Review must retain the exact immutable answer and extraction version.")
    context = row.context
    original = row.job.config_snapshot["visibility"]["context"]
    if (type(context) is not dict or set(context) != {"brand_aliases", "project_domains", "competitor_domains", "configuration_revision", "business_facts"}
        or context["brand_aliases"] != original["brand_aliases"]
        or context["project_domains"] != list(dict.fromkeys(urlsplit(origin).hostname for origin in original["origins"]))
        or type(context["configuration_revision"]) is not int or context["configuration_revision"] < 1
        or type(context["competitor_domains"]) is not list or len(context["competitor_domains"]) > 20
        or any(type(domain) is not str or _safe_url("https://" + domain + "/") != domain for domain in context["competitor_domains"])
        or context["business_facts"] != "unavailable_no_approved_fact_registry"
        or type(row.evaluated) is not bool or not valid_answer(row.review_note) or not 1 <= len(row.review_note.strip()) <= 500):
        raise ValidationError("Keep original answer entity scope, reviewed competitor context and explicit factual limits.")
    if row.evaluated and (row.job.status != JobStatus.SUCCEEDED or row.job.output.get("collection_eligible") is not True):
        raise ValidationError("Failed/partial/cancelled samples cannot become evaluated valid answers.")
    if row.evaluated and candidates(answer, context)["has_more"]:
        raise ValidationError("Truncated extraction cannot establish an evaluated negative; retain unevaluated coverage.")
    validate_matches(answer, context, row.matches)
    if type(row.factual_notes) is not list or len(row.factual_notes) > 10:
        raise ValidationError("Use at most ten human factual-uncertainty notes.")
    for note in row.factual_notes:
        if (type(note) is not dict or set(note) != {"start", "end", "note"} or type(note["start"]) is not int
            or type(note["end"]) is not int or not 0 <= note["start"] < note["end"] <= len(answer)
            or not valid_answer(note["note"]) or not 1 <= len(note["note"].strip()) <= 240):
            raise ValidationError("Factual concerns need exact evidence and human uncertainty notes, never a verified-fact claim.")
    if len(json.dumps({"context": context, "matches": row.matches, "notes": row.factual_notes}).encode()) > 32768:
        raise ValidationError("Review exceeds the private evidence limit.")
    if row._state.adding:
        require_project_action(project=row.project, user=row.actor, action=Action.APPROVE)
        config = ProjectConfiguration.objects.get(project=row.project)
        if context != entity_context(row.job, config):
            raise ValidationError("A new review must snapshot actual current configured competitor context.")


def review_answer(*, project, actor, job_id, request_key, expected_revision, expected_configuration_revision,
                  matches, evaluated, review_note, factual_notes):
    if (type(job_id) is not int or job_id < 1 or type(expected_revision) is not int or not 0 <= expected_revision < 65535
        or type(expected_configuration_revision) is not int or expected_configuration_revision < 1
        or type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key)):
        raise ValidationError("Reload the exact current human review and entity configuration.")
    with transaction.atomic():
        org = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=org)
        require_project_action(project=project, user=actor, action=Action.APPROVE)
        job = JobRun.objects.filter(pk=job_id, project=project, handler=HANDLER).first()
        if job is None:
            raise PermissionDenied
        config = ProjectConfiguration.objects.get(project=project)
        if config.revision != expected_configuration_revision:
            raise ValidationError("Entity configuration changed; inspect before correcting.")
        context = entity_context(job, config)
        digest = sha256(answer_for(job).encode()).hexdigest()
        previous = AIVisibilityAnswerReview.objects.filter(job=job).order_by("-revision").first()
        existing = AIVisibilityAnswerReview.objects.filter(project=project, request_key=request_key).first()
        if existing:
            if (previous is None or previous.pk != existing.pk or existing.job_id != job.pk or existing.actor_id != actor.pk
                or (existing.revision, existing.answer_sha256, existing.context, existing.matches, existing.evaluated, existing.review_note, existing.factual_notes)
                != (expected_revision + 1, digest, context, matches, evaluated, review_note, factual_notes)):
                raise ValidationError("Review key belongs to another decision.")
            return existing
        if (previous.revision if previous else 0) != expected_revision:
            raise ValidationError("Answer review changed; reload before correcting.")
        return AIVisibilityAnswerReview.objects.create(project=project, job=job, actor=actor, request_key=request_key,
            revision=expected_revision + 1, answer_sha256=digest, method_version=METHOD, context=context,
            matches=matches, evaluated=evaluated, review_note=review_note, factual_notes=factual_notes)


def _rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
        "percent": str((Decimal(numerator) * 100 / denominator).quantize(Decimal("0.01"))) if denominator else None,
        "state": "sampled_human_evaluated" if denominator else "unavailable"}


def sample_rates(*, project, actor, prompt_set_id):
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    if type(prompt_set_id) is not int or not project.visibility_prompt_sets.filter(pk=prompt_set_id).exists():
        raise PermissionDenied
    jobs = list(JobRun.objects.filter(project=project, handler=HANDLER, input_snapshot__prompt_set_id=prompt_set_id).order_by("-pk")[:101])
    groups = {}
    for job in jobs[:100]:
        review = AIVisibilityAnswerReview.objects.filter(job=job).order_by("-revision").first()
        entity_digest = sha256(json.dumps(review.context, sort_keys=True).encode()).hexdigest() if review else "unevaluated"
        key = (job.input_snapshot["model_id"], job.config_snapshot["model_revision"], job.input_snapshot["account_id"],
               job.output.get("returned_model"), entity_digest,
               json.dumps(job.schedule.input_snapshot["policy"], sort_keys=True) if job.schedule_id else "manual")
        group = groups.setdefault(key, {"requested_model": job.config_snapshot["model_identifier"], "model_revision": key[1],
            "account_id": key[2], "returned_model": key[3], "entity_context_sha256": key[4], "sample_ids": [],
            "repeat_policy": json.loads(key[5]) if job.schedule_id else None,
            "eligible_sample_ids": [], "prompt_mix": {"neutral": 0, "branded": 0}, "statuses": {}, "exclusions": {},
            "mention_numerator": 0, "competitor_numerators": {}, "separate_prompt_groups": {"neutral": [0, 0], "branded": [0, 0]}})
        group["sample_ids"].append(job.pk)
        group["statuses"][job.status] = group["statuses"].get(job.status, 0) + 1
        kind = job.config_snapshot["visibility"]["prompt"]["kind"]
        group["prompt_mix"][kind] += 1
        exclusion = ""
        if job.status != JobStatus.SUCCEEDED or job.output.get("collection_eligible") is not True:
            exclusion = "failed_partial_cancelled_unknown_or_not_collected"
        elif review is None or not review.evaluated:
            exclusion = "unevaluated"
        else:
            try:
                validate_review_snapshot(review)
            except (ValidationError, PermissionDenied):
                exclusion = "invalid_or_changed_evidence"
            if not exclusion and any(row["decision"] == "uncertain" for row in review.matches):
                exclusion = "uncertain_entity"
        if exclusion:
            group["exclusions"][exclusion] = group["exclusions"].get(exclusion, 0) + 1
            continue
        group["eligible_sample_ids"].append(job.pk)
        confirmed = [row for row in review.matches if row["decision"] == "confirmed"]
        mentioned = any(row["kind"] in {"brand", "project_domain"} for row in confirmed)
        group["mention_numerator"] += int(mentioned)
        group["separate_prompt_groups"][kind][0] += int(mentioned)
        group["separate_prompt_groups"][kind][1] += 1
        for domain in set(review.context["competitor_domains"]):
            present = any(row["kind"] in {"competitor", "competitor_domain"} and row["entity"] == domain for row in confirmed)
            group["competitor_numerators"][domain] = group["competitor_numerators"].get(domain, 0) + int(present)
    output = []
    for group in groups.values():
        count = len(group["eligible_sample_ids"])
        group["mention_rate"] = _rate(group.pop("mention_numerator"), count)
        group["citation_rate"] = {**_rate(0, 0), "numerator": None, "reason": "no_citation_capable_samples"}
        group["neutral_branded_rates"] = {kind: _rate(*pair) for kind, pair in group.pop("separate_prompt_groups").items()}
        group["competitor_mention_rates"] = {domain: _rate(value, count) for domain, value in group.pop("competitor_numerators").items()}
        output.append(group)
    return {"method": METHOD, "project_id": project.pk, "prompt_set_id": prompt_set_id,
        "scope": "latest_100_sample_jobs_of_this_exact_methodology_revision", "has_more": len(jobs) > 100,
        "groups": output, "surface": "openai_responses_text", "mode": "text_only_no_tools",
        "limitations": "Human-evaluated samples only; no consumer/global visibility, competitor market share or referral visits."}
