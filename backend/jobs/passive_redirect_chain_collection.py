"""Once-only explicitly permitted selected chain; historical responses, not a security verdict."""
from django.core.exceptions import ValidationError

from . import passive_header_collection as lifecycle
from .passive_redirect_chain_source import passive_redirect_chain_source, validate_input as source_input
from .passive_redirect_chain_evidence import METHOD, MAX_RESULT_BYTES, validate_redirect_chain_evidence


HANDLER = "collect_passive_redirect_chain"
STAGE = "Observe explicitly selected redirect-chain responses"


def validate_input(data):
    return source_input(data)[0]


def validate_result(result, binding):
    return validate_redirect_chain_evidence(result, binding=binding)


def selection_snapshot(project, actor, data):
    return lifecycle.selection_snapshot(project, actor, data, handler=HANDLER)


def validate_job(job, *, current=False):
    if job.handler != HANDLER: raise ValidationError("Choose the independently permitted exact-chain job.")
    return lifecycle.validate_job(job, current=current)


def queue_passive_redirect_chain_collection(*, project, actor, data, idempotency_key):
    return lifecycle.queue_passive_header_collection(project=project, actor=actor, data=data,
        idempotency_key=idempotency_key, handler=HANDLER)


def execute_passive_redirect_chain_collection(job_id, *, fetcher=None):
    return lifecycle.execute_passive_header_collection(job_id, fetcher=fetcher, handler=HANDLER)


def read_passive_redirect_chain_observation(*, project, actor, job_id):
    return lifecycle.read_passive_header_observation(project=project, actor=actor, job_id=job_id, handler=HANDLER)
