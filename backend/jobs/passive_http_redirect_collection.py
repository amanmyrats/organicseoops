"""Independently permitted plaintext first HTTP response; never followed upgrade proof."""
from django.core.exceptions import ValidationError

from . import passive_header_collection as lifecycle
from .passive_http_redirect_source import passive_http_redirect_source, validate_input as source_input
from .passive_http_redirect_evidence import validate_http_redirect_evidence


HANDLER = "collect_passive_http_redirects"
METHOD = "passive-http-redirect-collection-v1"
STAGE = "Observe selected first HTTP response Location metadata"


def validate_input(data):
    return source_input(data)[0]


def validate_result(result, binding):
    return validate_http_redirect_evidence(result, binding=binding)


def selection_snapshot(project, actor, data):
    return lifecycle.selection_snapshot(project, actor, data, handler=HANDLER)


def validate_job(job, *, current=False):
    if job.handler != HANDLER: raise ValidationError("Choose the independently authorized HTTP Location job.")
    return lifecycle.validate_job(job, current=current)


def queue_passive_http_redirect_collection(*, project, actor, data, idempotency_key):
    return lifecycle.queue_passive_header_collection(project=project, actor=actor, data=data,
        idempotency_key=idempotency_key, handler=HANDLER)


def execute_passive_http_redirect_collection(job_id, *, fetcher=None):
    return lifecycle.execute_passive_header_collection(job_id, fetcher=fetcher, handler=HANDLER)


def read_passive_http_redirect_observation(*, project, actor, job_id):
    return lifecycle.read_passive_header_observation(project=project, actor=actor, job_id=job_id, handler=HANDLER)
