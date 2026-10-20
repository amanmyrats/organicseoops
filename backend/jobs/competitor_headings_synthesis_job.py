"""Fixed once-only private AI notes about original retained heading pairs."""
from . import competitor_synthesis_job as original, competitor_headings_synthesis as synthesis
from .competitor_headings_synthesis_selection import METHOD, selection_snapshot

HANDLER = "synthesize_competitor_headings_pair"
STAGE = original.STAGE
STATE = original.STATE
INTERPRETATION = "original_static_heading_facts_separate_from_unverified_cited_ai_notes_not_page_topics_content_gaps_approval_freshness_whole_site_or_causal_evidence"
CITATION_KIND = "static nonroot headings"
validate_input = original.validate_input


def read_source(**kwargs):
    return synthesis.read_competitor_headings_synthesis_source(**kwargs)


def validate_notes(value, comparison):
    return synthesis.validate_headings_interpretations(value, comparison)


def validate_job(job, *, current=False):
    return original._validate_job(job, current=current, handler=HANDLER)


def validate_result(result, job, source):
    return original._validate_result(result, job, source, handler=HANDLER)


def queue_competitor_headings_synthesis(*, project, actor, data, idempotency_key):
    return original._queue_synthesis(project=project, actor=actor, data=data, idempotency_key=idempotency_key, handler=HANDLER)


def execute_competitor_headings_synthesis(job_id, *, request=original.create_response):
    return original._execute_synthesis(job_id, request=request, handler=HANDLER)


def read_competitor_headings_synthesis(*, project, actor, job_id):
    return original._read_synthesis(project=project, actor=actor, job_id=job_id, handler=HANDLER)


def read_result(**kwargs):
    return read_competitor_headings_synthesis(**kwargs)
