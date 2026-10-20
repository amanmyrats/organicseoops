"""Once-only private, cited hypotheses from one original retained heading observation."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from . import competitor_synthesis_job as original, competitor_topics_source as synthesis
from .competitor_topics_selection import METHOD, selection_snapshot, validate_input


HANDLER = original.TOPICS_HANDLER
STAGE = original.STAGE
STATE = "unverified_heading_topic_hypotheses_require_human_review"
INTERPRETATION = "original_single_heading_facts_separate_from_unverified_cited_topic_hypotheses_not_semantic_truth_page_topics_gaps_intent_freshness_rankings_whole_site_or_approval"
CITATION_KIND = "static nonroot headings"


def read_source(**kwargs):
    return synthesis.read_competitor_topics_source(**kwargs)


def validate_job(job, *, current=False):
    return original._validate_job(job, current=current, handler=HANDLER)


def build_result(job, source, response):
    topics = synthesis.validate_topic_hypotheses(response.structured, source["observation"])
    return {"method_version":METHOD, "organization_id":job.organization_id, "project_id":job.project_id,
        "source_selection_digest":source["selection_digest"], "model_id":job.input_snapshot["model_id"],
        "account_id":job.input_snapshot["account_id"], "generated_at":timezone.now().isoformat(timespec="microseconds"),
        "observation":source["observation"], **topics, "state":STATE, "interpretation":INTERPRETATION}


def validate_result(result, job, source):
    if job.handler != HANDLER: raise PermissionDenied
    if (type(result) is not dict or set(result) != {"method_version","organization_id","project_id","source_selection_digest",
        "model_id","account_id","generated_at","observation","topics","state","interpretation"}
        or (result["method_version"],result["organization_id"],result["project_id"],result["source_selection_digest"],
            result["model_id"],result["account_id"],result["state"],result["interpretation"]) !=
           (METHOD,job.organization_id,job.project_id,job.config_snapshot["source_selection_digest"],
            job.input_snapshot["model_id"],job.input_snapshot["account_id"],STATE,INTERPRETATION)
        or any(type(result[key]) is not int for key in ("organization_id","project_id","model_id","account_id"))
        or original.collection._encode(result["observation"]) != original.collection._encode(source["observation"])
        or source["selection_digest"] != result["source_selection_digest"]
        or original._date(result["generated_at"]) < original._date(source["observation"]["collection"]["observed_at"])
        or len(original.collection._encode(result)) > original.MAX_RESULT_BYTES):
        raise ValidationError("Retain original single-heading facts separately from bounded unverified topic hypotheses.")
    synthesis.validate_topic_hypotheses({"topics":result["topics"]}, result["observation"])
    return result


def queue_competitor_topics(*, project, actor, data, idempotency_key):
    return original._queue_synthesis(project=project, actor=actor, data=data, idempotency_key=idempotency_key, handler=HANDLER)


def execute_competitor_topics(job_id, *, request=original.create_response):
    return original._execute_synthesis(job_id, request=request, handler=HANDLER)


def read_competitor_topics(*, project, actor, job_id):
    return original._read_synthesis(project=project, actor=actor, job_id=job_id, handler=HANDLER)


def read_result(**kwargs):
    return read_competitor_topics(**kwargs)
