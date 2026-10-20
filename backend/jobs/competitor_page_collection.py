"""Explicit original selected-page job over the checked once-only competitor lifecycle."""
from django.core.exceptions import ValidationError

from . import competitor_collection as lifecycle
from .competitor_fetch import PAGE_METHOD as METHOD, collect_competitor_page_metadata
from .competitor_metadata import validate_metadata
from .competitor_page_source import validate_input as validate_page_source


HANDLER = "collect_competitor_page"
STAGE = "Collect selected competitor page"


def validate_input(data):
    if (type(data) is not dict or set(data) != {"origin", "url", "collection_permission", "use_permission", "storage_permission"}
        or data["use_permission"] is not True or data["storage_permission"] is not True):
        raise ValidationError("Select one exact competitor URI and separately declare collection, independent use and storage permission.")
    source = validate_page_source({key: data[key] for key in ("origin", "url", "collection_permission")})
    return {**source, "use_permission": True, "storage_permission": True}


def validate_result(result, binding):
    return lifecycle._validate_result(result, binding, method=METHOD, check_evidence=validate_metadata, page=True)


def selection_snapshot(project, actor, data):
    return lifecycle.selection_snapshot(project, actor, data, handler=HANDLER)


def validate_job(job, *, current=False):
    if job.handler != HANDLER: raise ValidationError("Choose the explicit competitor selected-page job.")
    return lifecycle.validate_job(job, current=current)


def queue_competitor_page_collection(*, project, actor, data, idempotency_key):
    return lifecycle.queue_competitor_collection(project=project, actor=actor, data=data,
        idempotency_key=idempotency_key, handler=HANDLER)


def execute_competitor_page_collection(job_id, *, fetcher=None):
    return lifecycle.execute_competitor_collection(job_id, fetcher=fetcher, handler=HANDLER)


def read_competitor_page_observation(*, project, actor, job_id):
    return lifecycle.read_competitor_observation(project=project, actor=actor, job_id=job_id, handler=HANDLER)
