"""Explicit original selected-page destination references over the checked once-only lifecycle."""
from django.core.exceptions import ValidationError

from . import competitor_collection as lifecycle
from .competitor_fetch import PAGE_DESTINATIONS_METHOD as METHOD, collect_competitor_page_destinations
from .competitor_destinations import validate_destinations
from .competitor_page_collection import validate_input


HANDLER = "collect_competitor_page_destinations"
STAGE = "Collect selected competitor page destinations"


def validate_result(result, binding):
    return lifecycle._validate_result(result, binding, method=METHOD, check_evidence=validate_destinations, page=True)


def selection_snapshot(project, actor, data):
    return lifecycle.selection_snapshot(project, actor, data, handler=HANDLER)


def validate_job(job, *, current=False):
    if job.handler != HANDLER: raise ValidationError("Choose the explicit competitor selected-page destination-reference job.")
    return lifecycle.validate_job(job, current=current)


def queue_competitor_page_destinations_collection(*, project, actor, data, idempotency_key):
    return lifecycle.queue_competitor_collection(project=project, actor=actor, data=data,
        idempotency_key=idempotency_key, handler=HANDLER)


def execute_competitor_page_destinations_collection(job_id, *, fetcher=None):
    return lifecycle.execute_competitor_collection(job_id, fetcher=fetcher, handler=HANDLER)


def read_competitor_page_destinations_observation(*, project, actor, job_id):
    return lifecycle.read_competitor_observation(project=project, actor=actor, job_id=job_id, handler=HANDLER)
