"""Two independent original source responses; never a followed upgrade or Location target match."""
import json

from django.core.exceptions import PermissionDenied, ValidationError

from tenancy.services import Action, require_project_action
from tenancy.support_requests import _safe_id
from . import passive_header_collection as lifecycle
from . import passive_header_source as verified_source
from . import passive_http_redirect_collection as http
from . import passive_redirect_collection as https
from .models import JobRun, JobStatus
from .passive_header_candidate_source import _metadata
from .usage import require_billable_access


METHOD = "passive-original-http-https-pair-v1"
MAX_RESULT_BYTES = 24576
INTERPRETATION = "two_separate_dated_responses_not_location_target_path_followed_upgrade_browser_behavior_current_https_availability_or_authenticated_http_identity"


def compare_http_https_observations(*, project, actor, http_job_id, https_job_id):
    ids = (http_job_id, https_job_id)
    for value in ids: _safe_id(value)
    if ids[0] == ids[1]: raise ValidationError("Choose two distinct independent HTTP and HTTPS observations.")
    handlers = (http.HANDLER, https.HANDLER)
    jobs = list(JobRun.objects.select_related("project", "actor").filter(pk__in=ids,
        project_id=project.pk, organization_id=project.organization_id, status=JobStatus.SUCCEEDED))
    jobs = {job.pk: job for job in jobs}
    if len(jobs) != 2 or any(jobs[key].handler != handler for key, handler in zip(ids, handlers)): raise PermissionDenied
    original = {key: _metadata(key, project=project, actor=actor, handler=handler) for key, handler in zip(ids, handlers)}
    if any(original[key]["job"] != lifecycle._row_pin(jobs[key]) for key in ids): raise PermissionDenied
    bindings = [jobs[key].config_snapshot["binding"] for key in ids]
    observed = [lifecycle.read_passive_header_observation(project=project, actor=actor, job_id=key, handler=handler)["collection"]
        for key, handler in zip(ids, handlers)]
    if observed[1]["url"] != "https" + observed[0]["url"][4:]:
        raise ValidationError("Select independent same-host default-port exact-source-path observations.")
    sources = {key: verified_source._source(project.pk, project.organization_id, actor, binding["origin"])
        for key, binding in zip(ids, bindings)}
    result = {"method_version": METHOD, "organization_id": project.organization_id, "project_id": project.pk,
        "source_current": True, "http": {"job_id": ids[0], "binding": bindings[0], "collection": observed[0]},
        "https": {"job_id": ids[1], "binding": bindings[1], "collection": observed[1]},
        "coverage": "two_independently_verified_same_host_default_port_exact_source_path_original_responses_only",
        "interpretation": INTERPRETATION}
    content = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(content) > MAX_RESULT_BYTES: raise ValidationError("Original response pair exceeds its private bound.")
    result = json.loads(content)
    # The second readback can change the first original. Fence BOTH complete sources and records.
    for key, handler, binding in zip(ids, handlers, bindings):
        current = JobRun.objects.select_related("project", "actor").get(pk=key, handler=handler)
        lifecycle._read_source(current, project, actor)
        if verified_source._source(project.pk, project.organization_id, actor, binding["origin"]) != sources[key]: raise PermissionDenied
    if any(_metadata(key, project=project, actor=actor, handler=handler) != original[key] for key, handler in zip(ids, handlers)): raise PermissionDenied
    if any(verified_source._source(project.pk, project.organization_id, actor, binding["origin"]) != sources[key]
        for key, binding in zip(ids, bindings)): raise PermissionDenied
    require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
    require_billable_access(organization=project.organization)
    return result
