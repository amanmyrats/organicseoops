"""Bounded like-for-like API observation history; no inferred visits or uplift."""
from hashlib import sha256
import json

from django.core.exceptions import ValidationError

from tenancy.services import Action, require_project_action
from .models import AIVisibilityAnswerReview, JobRun
from .visibility_collection import HANDLER
from .visibility_entities import validate_review_snapshot

METHOD = "visibility-history-v1"


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def comparable_context(job, review):
    config, data = job.config_snapshot, job.input_snapshot
    method = config["visibility"]
    prompt = method["prompt"]
    return {"set_id": method["set_id"], "set_revision": method["revision"], "prompt_key": prompt["key"],
        "prompt_sha256": sha256(prompt["text"].encode()).hexdigest(), "prompt_group": prompt["kind"],
        "prompt_method": method["methodology"], "collection_method": job.method_version,
        "repeat_policy": job.schedule.input_snapshot["policy"] if job.schedule_id else None,
        "surface": method["policy"]["surface"], "mode": "text_only_no_tools",
        "provider_id": config["provider_id"], "requested_model": config["model_identifier"],
        "model_revision": config["model_revision"], "returned_model": job.output.get("returned_model"),
        "account_id": data["account_id"], "credential_revision": config["credential_revision"],
        "max_output_tokens": data["max_output_tokens"], "requested_market": method["context"]["market"],
        "requested_language": method["context"]["language"], "applied_location_device": "unsupported",
        "applied_language": "not_guaranteed", "human_context_sha256": _digest(method["context"]),
        "entity_method": review.method_version if review else None,
        "entity_context_sha256": _digest(review.context) if review else None}


def observation_history(*, project, actor, before_id=None, limit=20):
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    if (before_id is not None and (type(before_id) is not int or before_id < 1)
        or type(limit) is not int or not 1 <= limit <= 20):
        raise ValidationError("Use a bounded history cursor.")
    query = JobRun.objects.filter(project=project, handler=HANDLER).order_by("-pk")
    if before_id is not None:
        query = query.filter(pk__lt=before_id)
    jobs = list(query[:limit + 1])
    selected = jobs[:limit]
    reviews = {row.job_id: row for row in AIVisibilityAnswerReview.objects.filter(job_id__in=[job.pk for job in selected])
        .order_by("job_id", "-revision").distinct("job_id")}
    rows, groups, previous = [], {}, {}
    # Annotate only observed predecessors within this page; older-page context is not inferred.
    for job in reversed(selected):
        review = reviews.get(job.pk)
        context = comparable_context(job, review)
        group_key = _digest(context)
        prior = previous.get((context["set_id"], context["prompt_key"]))
        changed = [field for field in context if prior is not None and context[field] != prior[field]]
        previous[(context["set_id"], context["prompt_key"])] = context
        evaluation = "unevaluated"
        if job.status != "succeeded" or job.output.get("collection_eligible") is not True:
            evaluation = "failed_partial_cancelled_unknown_or_not_collected"
        elif review and review.evaluated:
            try:
                validate_review_snapshot(review)
                evaluation = "uncertain_entity" if any(row["decision"] == "uncertain" for row in review.matches) else "human_evaluated"
            except ValidationError:
                evaluation = "invalid_or_changed_evidence"
        groups.setdefault(group_key, {"key": group_key, "context": context, "sample_ids": []})["sample_ids"].append(job.pk)
        rows.append({"id": job.pk, "project_id": project.pk, "comparison_key": group_key, "context": context,
            "schedule_id": job.schedule_id, "scheduled_for": job.scheduled_for.isoformat() if job.scheduled_for else None,
            "prompt_set_id": job.input_snapshot["prompt_set_id"], "status": job.status, "error_category": job.error_category,
            "created_at": job.created_at.isoformat(), "collected_at": job.output.get("collected_at"),
            "evaluation": evaluation, "review_revision": review.revision if review else None,
            "reviewed_at": review.created_at.isoformat() if review else None,
            "changes_from_prior_page_observation": changed, "prior_context": "observed_on_this_page" if prior else "not_loaded",
            "answer_evidence_available": bool(job.output), "citation_measurement": "unavailable"})
    return {"method": METHOD, "project_id": project.pk, "observations": list(reversed(rows)),
        "comparison_groups": list(groups.values()), "has_more": len(jobs) > limit,
        "next_before_id": selected[-1].pk if len(jobs) > limit else None,
        "rate_scope": "history_page_is_not_a_rate_denominator; inspect_exact_methodology_rates_separately",
        "referrals": {"status": "unavailable", "visits": None, "conversions": None, "revenue": None,
            "reason": "no_authorized_exact_origin_analytics_referrer_campaign_grain", "direct_unknown": "not_inferred_as_ai"},
        "limitations": "Latest human corrections annotate original collection dates; API samples are not consumer sessions, global share, visits or causal improvement."}
