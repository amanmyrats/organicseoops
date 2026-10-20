"""Fixed single-heading model preparation; no key, reservation or provider call."""
from django.core.exceptions import PermissionDenied, ValidationError

from . import competitor_topics_source as source, competitor_synthesis_job as original
from .competitor_comparison import _read_pair_sources
from .models import JobRun, JobStatus


METHOD = "competitor-heading-topics-v1"


def validate_input(data):
    if (type(data) is not dict or set(data) != {"job_id", "ai_processing_permission", "model_id", "account_id",
        "max_output_tokens", "max_cost_usd", "allow_free"}
        or data["ai_processing_permission"] is not True or type(data["allow_free"]) is not bool
        or type(data["max_output_tokens"]) is not int or not 128 <= data["max_output_tokens"] <= 2048):
        raise ValidationError("Choose one original heading observation, separate AI permission and explicit bounded model budget.")
    for key in ("job_id", "model_id", "account_id"):
        original.collection._safe_id(data[key])
    original._max_cost(data["max_cost_usd"])
    return dict(data)


def selection_snapshot(project, actor, data):
    data = validate_input(data)
    job = JobRun.objects.select_related("project", "actor").filter(pk=data["job_id"], project_id=project.pk,
        organization_id=project.organization_id, handler=source.HANDLER, status=JobStatus.SUCCEEDED).first()
    if job is None: raise PermissionDenied
    ids = (job.pk,)
    callers = _read_pair_sources((job,), project, actor)
    pins = original.synthesis._pins(ids)
    packet = source.read_competitor_topics_source(project=project, actor=actor, job_id=job.pk, ai_processing_permission=True)
    return original._model_snapshot(project, actor, data, packet, ids=ids, original=pins, callers=callers,
        handler=source.HANDLER, method=METHOD, source_method=source.METHOD,
        instructions=source.INSTRUCTIONS, output_schema=source.OUTPUT_SCHEMA)
