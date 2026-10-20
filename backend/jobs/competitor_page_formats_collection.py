"""Explicit original static content-element counts over the checked once-only lifecycle."""
from django.core.exceptions import ValidationError

from . import competitor_collection as lifecycle
from .competitor_formats_fetch import METHOD, collect_competitor_page_formats
from .competitor_formats import validate_formats
from .competitor_page_collection import validate_input


HANDLER = "collect_competitor_page_formats"
STAGE = "Collect selected competitor page content-element counts"


def validate_result(result, binding):
    return lifecycle._validate_result(result, binding, method=METHOD, check_evidence=validate_formats, page=True)


def selection_snapshot(project, actor, data):
    return lifecycle.selection_snapshot(project, actor, data, handler=HANDLER)


def validate_job(job, *, current=False):
    if job.handler != HANDLER: raise ValidationError("Choose the explicit selected-page content-element job.")
    return lifecycle.validate_job(job, current=current)


def queue_competitor_page_formats_collection(*, project, actor, data, idempotency_key):
    return lifecycle.queue_competitor_collection(project=project, actor=actor, data=data,
        idempotency_key=idempotency_key, handler=HANDLER)


def execute_competitor_page_formats_collection(job_id, *, fetcher=None):
    return lifecycle.execute_competitor_collection(job_id, fetcher=fetcher, handler=HANDLER)


def read_competitor_page_formats_observation(*, project, actor, job_id):
    return lifecycle.read_competitor_observation(project=project, actor=actor, job_id=job_id, handler=HANDLER)
