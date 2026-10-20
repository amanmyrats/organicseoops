"""Explicit independently permitted resources over the checked once-only lifecycle."""
from django.core.exceptions import ValidationError

from . import passive_header_collection as lifecycle
from .passive_resource_source import passive_resource_source, validate_input as source_input
from .passive_resource_evidence import validate_resource_evidence


HANDLER = "collect_passive_resources"
METHOD = "passive-resource-collection-v1"
STAGE = "Observe selected static resource references"


def validate_input(data):
    return source_input(data)[0]


def validate_result(result, binding):
    return validate_resource_evidence(result, binding=binding)


def selection_snapshot(project, actor, data):
    return lifecycle.selection_snapshot(project, actor, data, handler=HANDLER)


def validate_job(job, *, current=False):
    if job.handler != HANDLER: raise ValidationError("Choose the independently authorized resource job.")
    return lifecycle.validate_job(job, current=current)


def queue_passive_resource_collection(*, project, actor, data, idempotency_key):
    return lifecycle.queue_passive_header_collection(project=project, actor=actor, data=data,
        idempotency_key=idempotency_key, handler=HANDLER)


def execute_passive_resource_collection(job_id, *, fetcher=None):
    return lifecycle.execute_passive_header_collection(job_id, fetcher=fetcher, handler=HANDLER)


def read_passive_resource_observation(*, project, actor, job_id):
    return lifecycle.read_passive_header_observation(project=project, actor=actor, job_id=job_id, handler=HANDLER)
