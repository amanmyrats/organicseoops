"""Fixed private Lighthouse audit over the original committed once-only observation lifecycle."""
from hashlib import sha256

from django.core.exceptions import ValidationError

from . import competitor_collection as lifecycle, competitor_lab_fetch as producer, competitor_lab_selection as selection
from . import competitor_lab_source as source, competitor_page_source as page
from .passive_tls_evidence import _date


HANDLER = "collect_competitor_lighthouse"
METHOD = producer.METHOD
STAGE = "Audit selected competitor Lighthouse lab sample"


def validate_input(data):
    if (type(data) is not dict or set(data) != {"origin", "url", "strategy", "collection_permission", "provider_processing_permission", "use_permission", "storage_permission"}
        or data["use_permission"] is not True or data["storage_permission"] is not True):
        raise ValidationError("Separately declare collection, Google processing, independent use and storage for one exact page/device.")
    selected = source.validate_input({key:value for key,value in data.items() if key not in {"use_permission", "storage_permission"}})
    return {**selected, "use_permission":True, "storage_permission":True}


def binding_page(binding, data):
    try:
        if (type(binding) is not dict or set(binding) != {"method_version", "source", "performance_credential", "interpretation", "selection_sha256"}
            or binding["method_version"] != selection.METHOD or binding["interpretation"] != selection.INTERPRETATION
            or binding["selection_sha256"] != sha256(lifecycle._encode({key:value for key,value in binding.items() if key != "selection_sha256"})).hexdigest()): raise ValueError
        selection._validate_reference(binding["performance_credential"])
        selected = binding["source"]
        if (type(selected) is not dict or set(selected) != {"method_version", "provider", "page_source", "strategy", "provider_processing_permission", "interpretation", "source_sha256"}
            or selected["method_version"] != source.METHOD or selected["provider"] != source.PROVIDER or selected["interpretation"] != source.INTERPRETATION
            or selected["source_sha256"] != sha256(lifecycle._encode({key:value for key,value in selected.items() if key != "source_sha256"})).hexdigest()
            or producer._data(binding) != {key:value for key,value in data.items() if key not in {"use_permission", "storage_permission"}}): raise ValueError
        original = selected["page_source"]
        if (type(original) is not dict or set(original) != {"method_version", "organization_id", "project_id", "actor_id", "origin", "hostname", "scope_kind", "collection_permission",
            "configuration_revision", "configuration_updated_at", "source_sha256", "interpretation", "url"}
            or original["method_version"] != page.METHOD or original["scope_kind"] != page.SCOPE or original["interpretation"] != page.INTERPRETATION): raise ValueError
        _date(original["configuration_updated_at"], microseconds=False)
        if len(lifecycle._encode(binding)) > source.MAX_RESULT_BYTES: raise ValueError
        return original
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        raise ValidationError("Retain the complete original Lighthouse source and credential selection.") from None


def validate_result(result, binding):
    if type(result) is not dict or result.get("state") != "collected": raise ValidationError("Retain only original collected minimized Lighthouse evidence.")
    return producer.validate_result(result, binding)


def collect_competitor_lab(*, project, actor, binding, before_request, fetcher=None):
    options = (dict(robots_fetcher=fetcher, resolver=fetcher.resolver, connection_factory=fetcher.connection_factory, clock=fetcher.clock)
        if fetcher is not None else {})
    return producer.collect_competitor_lab(project=project, actor=actor, binding=binding,
        before_request=before_request, before_send=before_request, **options)


def selection_snapshot(project, actor, data):
    return lifecycle.selection_snapshot(project, actor, data, handler=HANDLER)


def validate_job(job, *, current=False):
    if job.handler != HANDLER: raise ValidationError("Choose the fixed competitor Lighthouse audit.")
    return lifecycle.validate_job(job, current=current)


def queue_competitor_lab_collection(*, project, actor, data, idempotency_key):
    return lifecycle.queue_competitor_collection(project=project, actor=actor, data=data, idempotency_key=idempotency_key, handler=HANDLER)


def execute_competitor_lab_collection(job_id, *, fetcher=None):
    return lifecycle.execute_competitor_collection(job_id, fetcher=fetcher, handler=HANDLER)


def read_competitor_lab_observation(*, project, actor, job_id):
    return lifecycle.read_competitor_observation(project=project, actor=actor, job_id=job_id, handler=HANDLER)
