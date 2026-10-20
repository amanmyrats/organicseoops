"""Explicit, bounded GitHub manifest collection and disposable offline analysis."""
import base64
from datetime import timedelta
from hashlib import sha1, sha256
import json
import re
import secrets

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from integrations.repository_models import RepositoryGrant
from integrations.repository_oauth import grant_current, unseal, verify_grant_source
from integrations.repository_transport import RepositoryError, github_request
from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action
from .models import JobCancellation, JobRun, JobStatus, JobStep
from . import repository_advisories as advisories
from . import repository_code as code
from .repository_sandbox import CleanupPending, Engine
from .usage import require_billable_access, settle_usage, usage_denial

HANDLER = "analyze_repository"
METHOD = "repository-root-manifests-v1"
LOCK_METHOD = "repository-root-npm-lock-v1"
FILES = {"package.json", "pyproject.toml", "requirements.txt"}
ATTEMPT = "GitHub repository read attempt"
SANDBOX = "Disposable repository manifest analysis"
MAX_REQUESTS = 13
NAME = re.compile(r"(?:@[a-z0-9._-]{1,60}/)?[a-z0-9][a-z0-9._-]{0,99}\Z")
VERSION = re.compile(r"[0-9a-zA-Z.*~^<>=!|+, -]{1,80}\Z")
SECRET = re.compile(r"(?i)(?:gh[pousr]_|github_pat_|sk[-_]|akia|asia|bearer|password|secret|token|://|@.*:)")


def validate_input(data):
    if type(data) is not dict or type(data.get("operation")) is not str:
        raise ValidationError("Use an explicit repository analysis selection.")
    scan = data.get("operation") in advisories.OPERATIONS
    fields = {"grant_id", "grant_revision", "operation", "acknowledge_read_only_analysis"}
    if scan:
        fields.add("acknowledge_package_disclosure")
    if data["operation"] == code.OPERATION:
        fields.add("source_path")
    if (set(data) != fields
        or any(type(data[key]) is not int or not 0 < data[key] < 2**53 for key in ("grant_id", "grant_revision"))
        or data["operation"] not in {"root_dependency_inventory", code.OPERATION, *advisories.OPERATIONS}
        or data["acknowledge_read_only_analysis"] is not True or scan and data["acknowledge_package_disclosure"] is not True):
        raise ValidationError("Explicitly select an active repository grant and authorize root dependency-manifest analysis.")
    if data["operation"] == code.OPERATION:
        code.validate_path(data["source_path"])


def maximum_requests(data):
    return maximum_repository_requests(data) + int(data.get("operation") in advisories.OPERATIONS)


def maximum_repository_requests(data):
    if data.get("operation") == code.OPERATION:
        return 10 + len(data["source_path"].split("/"))
    return 11 if data.get("operation") == advisories.LOCK_OPERATION else MAX_REQUESTS


def configuration():
    image, controller, reference = settings.REPOSITORY_RUNNER_IMAGE, settings.REPOSITORY_CONTROLLER_ID, settings.REPOSITORY_ISOLATION_REVIEW_REFERENCE
    if (not settings.REPOSITORY_ANALYSIS_ENABLED or not re.fullmatch(r"[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}", image)
        or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", controller) or not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", reference)):
        raise ValidationError("A reviewed dedicated rootless controller and pinned runner image must be configured.")
    return {"runner_image": image, "controller_id": controller, "isolation_review_reference": reference}


def selection(project, actor, data):
    validate_input(data)
    require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
    grant = RepositoryGrant.objects.select_related("actor", "consent").get(pk=data["grant_id"], project=project, organization_id=project.organization_id)
    if grant.revision != data["grant_revision"] or not grant_current(grant):
        raise ValidationError("Refresh the exact repository consent before analysis.")
    lockfile = data["operation"] == advisories.LOCK_OPERATION
    extra = advisories.configuration(lockfile=lockfile) if data["operation"] in advisories.OPERATIONS else {}
    if lockfile:
        extra["parser_method"] = LOCK_METHOD
    if data["operation"] == code.OPERATION:
        extra["parser_method"], extra["code_rules"] = code.METHOD, code.RULES
    return grant, {**configuration(), **extra, "provider": "github", "repository": grant.repository, "repository_id": grant.repository_id,
        "commit_sha": grant.commit_sha, "permissions": {"contents": "read", "metadata": "read"}, "method": METHOD}


def validate_job(job, *, current=False):
    validate_input(job.input_snapshot)
    config = job.config_snapshot
    keys = {"runner_image", "controller_id", "isolation_review_reference", "provider", "repository", "repository_id", "commit_sha", "permissions", "method"}
    scan = job.input_snapshot["operation"] in advisories.OPERATIONS
    lockfile = job.input_snapshot["operation"] == advisories.LOCK_OPERATION
    code_file = job.input_snapshot["operation"] == code.OPERATION
    if scan:
        keys |= {"advisory_provider", "advisory_method", "advisory_review_reference"}
    if lockfile:
        keys.add("parser_method")
    if code_file:
        keys |= {"parser_method", "code_rules"}
    if (job.handler != HANDLER or job.method_version != METHOD or job.retry_of_id or job.schedule_id or job.scheduled_for
        or type(config) is not dict or set(config) != keys or config["provider"] != "github" or config["method"] != METHOD
        or config["permissions"] != {"contents": "read", "metadata": "read"}
        or type(config["runner_image"]) is not str or not re.fullmatch(r"[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}", config["runner_image"])
        or type(config["commit_sha"]) is not str or not re.fullmatch(r"[0-9a-f]{40}", config["commit_sha"])):
        raise ValidationError("Use immutable, separately authorized repository analysis.")
    if lockfile and config["parser_method"] != LOCK_METHOD:
        raise ValidationError("Use the frozen root npm lockfile parser.")
    if code_file and (config["parser_method"] != code.METHOD or config["code_rules"] != code.RULES):
        raise ValidationError("Use the frozen selected-source Python rule set.")
    if scan and (config["advisory_provider"] != "osv" or config["advisory_method"] != (advisories.LOCK_METHOD if lockfile else advisories.METHOD)
        or type(config["advisory_review_reference"]) is not str or not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", config["advisory_review_reference"])):
        raise ValidationError("Use the frozen reviewed OSV disclosure selection.")
    if current and selection(job.project, job.actor, job.input_snapshot)[1] != config:
        raise ValidationError("Repository source or isolation selection changed.")


def source_current(job):
    try:
        require_project_action(project=job.project, user=job.actor, action=Action.MANAGE_PROJECT)
        grant = RepositoryGrant.objects.select_related("actor", "consent").get(pk=job.input_snapshot["grant_id"], project=job.project)
        return (grant_current(grant) and grant.revision == job.input_snapshot["grant_revision"]
            and grant.repository_id == job.config_snapshot["repository_id"] and grant.commit_sha == job.config_snapshot["commit_sha"])
    except (PermissionDenied, ObjectDoesNotExist):
        return False


def queue_analysis(*, project, actor, data, request_key):
    from .services import queue_job
    validate_input(data)
    if type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,63}", request_key):
        raise ValidationError("Use a bounded analysis request key.")
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().select_related("organization").get(pk=project.pk, organization_id=project.organization_id)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        existing = JobRun.objects.filter(project=project, handler=HANDLER, idempotency_key=request_key).first()
        if existing:
            if existing.actor_id != actor.pk or existing.input_snapshot != data:
                raise ValidationError("Request key belongs to another analysis selection.")
            return existing
        require_billable_access(organization=project.organization)
        _grant, config = selection(project, actor, data)
        if JobRun.objects.filter(project=project, handler=HANDLER, status__in=[JobStatus.QUEUED, JobStatus.RUNNING]).exists():
            raise ValidationError("This project has unfinished analysis or cleanup.")
        return queue_job(project=project, actor=actor, handler=HANDLER, input_snapshot=data, config_snapshot=config, idempotency_key=request_key)


def _checkpoint(job_id):
    job = JobRun.objects.select_related("project__organization", "actor").get(pk=job_id, handler=HANDLER)
    if (job.status != JobStatus.RUNNING or JobCancellation.objects.filter(job=job).exists()
        or timezone.now() > job.updated_at + timedelta(minutes=4)):
        raise PermissionDenied
    validate_job(job, current=True)
    denied = usage_denial(job=job)
    if denied:
        raise RepositoryError(denied)
    return job


def _attempt(job_id, *, advisory=False):
    with transaction.atomic():
        identity = JobRun.objects.values_list("organization_id", flat=True).get(pk=job_id)
        Organization.objects.select_for_update().get(pk=identity)
        job = JobRun.objects.select_for_update().get(pk=job_id)
        _checkpoint(job_id)
        name = advisories.ATTEMPT if advisory else ATTEMPT
        count = job.steps.filter(name=name).count()
        if count >= (1 if advisory else maximum_repository_requests(job.input_snapshot)) or advisory and job.input_snapshot["operation"] not in advisories.OPERATIONS:
            raise RepositoryError("repository_request_limit")
        return JobStep.objects.create(job=job, sequence=15 if advisory else count + 1, name=name, status=JobStep.Status.RUNNING)


def _request(job_id):
    lockfile = JobRun.objects.values_list("input_snapshot", flat=True).get(pk=job_id)["operation"] == advisories.LOCK_OPERATION
    def request(path, *, token, checkpoint):
        holder = []
        def current():
            _checkpoint(job_id)
            checkpoint()
        try:
            options = {"response_limit": 1048576} if lockfile and "/git/blobs/" in path else {}
            payload = github_request(path, token=token, checkpoint=current,
                before_send=lambda: holder.append(_attempt(job_id)), **options)
            if holder:
                holder[0].status, holder[0].progress_percent = JobStep.Status.SUCCEEDED, 100
                holder[0].save(update_fields=["status", "progress_percent"])
            return payload
        except Exception:
            if holder:
                holder[0].status = JobStep.Status.FAILED
                holder[0].error_category = "source_request_unconfirmed"
                holder[0].save(update_fields=["status", "error_category"])
            raise
    return request


def collect_advisories(job, analysis):
    holder = []
    try:
        result = advisories.lookup(analysis, checkpoint=lambda: _checkpoint(job.pk),
            before_send=lambda: holder.append(_attempt(job.pk, advisory=True)))
        if holder:
            holder[0].status, holder[0].progress_percent = JobStep.Status.SUCCEEDED, 100
            holder[0].save(update_fields=["status", "progress_percent"])
        return result
    except Exception:
        if holder:
            holder[0].status, holder[0].error_category = JobStep.Status.FAILED, "advisory_request_unconfirmed"
            holder[0].save(update_fields=["status", "error_category"])
        raise


@sensitive_variables()
def collect_manifests(job, grant):
    request = _request(job.pk)
    checkpoint = lambda: _checkpoint(job.pk)
    lockfile = job.input_snapshot["operation"] == advisories.LOCK_OPERATION
    source_path = job.input_snapshot["source_path"] if job.input_snapshot["operation"] == code.OPERATION else ""
    parts = source_path.split("/") if source_path else []
    allowed = {"package-lock.json"} if lockfile else FILES
    if parts:
        allowed = {parts[-1]}
    size_limit, encoded_limit = (524288, 720000) if lockfile else (131072, 180000)
    verify_grant_source(grant, request=request, authority_checkpoint=checkpoint)
    token = unseal(f"grant:{grant.consent_id}", grant.encrypted_tokens)["access_token"]
    commit = request(f"/repos/{grant.repository}/git/commits/{grant.commit_sha}", token=token, checkpoint=checkpoint)
    try:
        tree_sha = commit["tree"]["sha"]
        if commit.get("sha") != grant.commit_sha or not re.fullmatch(r"[0-9a-f]{40}", tree_sha):
            raise ValueError
        parent_sha = tree_sha
        for directory in parts[:-1]:
            entries = _tree_entries(request, grant.repository, parent_sha, token, checkpoint)
            entry = next((row for row in entries if row["path"] == directory), None)
            if entry is None:
                return [], tree_sha
            if (entry.get("type") != "tree" or entry.get("mode") != "040000" or type(entry.get("sha")) is not str
                or not re.fullmatch(r"[0-9a-f]{40}", entry["sha"])):
                raise ValueError
            parent_sha = entry["sha"]
        files = []
        for entry in _tree_entries(request, grant.repository, parent_sha, token, checkpoint):
            name = entry["path"]
            if name not in allowed:
                continue
            if (entry.get("type") != "blob" or entry.get("mode") not in {"100644", "100755"}
                or type(entry.get("size")) is not int or not 0 <= entry["size"] <= size_limit
                or not re.fullmatch(r"[0-9a-f]{40}", str(entry.get("sha")))):
                raise ValueError
            blob = request(f"/repos/{grant.repository}/git/blobs/{entry['sha']}", token=token, checkpoint=checkpoint)
            if (blob.get("sha") != entry["sha"] or blob.get("size") != entry["size"] or blob.get("encoding") != "base64"
                or type(blob.get("content")) is not str or len(blob["content"]) > encoded_limit):
                raise ValueError
            raw = base64.b64decode(blob["content"].replace("\n", ""), validate=True)
            if len(raw) != entry["size"] or sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False).hexdigest() != entry["sha"]:
                raise ValueError
            files.append({"name": source_path or name, "content_b64": base64.b64encode(raw).decode(), "sha256": sha256(raw).hexdigest()})
        return files, tree_sha
    except (KeyError, TypeError, ValueError, AttributeError, UnicodeError):
        raise RepositoryError("bounded_repository_source_unavailable") from None


def _tree_entries(request, repository, tree_sha, token, checkpoint):
    tree = request(f"/repos/{repository}/git/trees/{tree_sha}", token=token, checkpoint=checkpoint)
    if (tree.get("sha") != tree_sha or tree.get("truncated") is not False or type(tree.get("tree")) is not list
        or len(tree["tree"]) > 1000):
        raise ValueError
    names = set()
    for entry in tree["tree"]:
        if type(entry) is not dict or type(entry.get("path")) is not str or entry["path"] in names:
            raise ValueError
        names.add(entry["path"])
    return tree["tree"]


def _result(value, *, nonce, files, lockfile=False):
    keys = {"method", "nonce", "status", "manifests", "dependencies", "excluded_or_unsupported", "scope"}
    if lockfile:
        keys.add("lockfile")
    scope = "root_npm_lockfile_reported_packages_not_installed_manifest_consistency_or_whole_repository" if lockfile else "root_declared_dependencies_only_not_installed_versions_vulnerabilities_or_whole_repository"
    if (type(value) is not dict or set(value) != keys or value["method"] != (LOCK_METHOD if lockfile else METHOD) or value["nonce"] != nonce
        or value["status"] != "succeeded" or value["scope"] != scope
        or type(value["excluded_or_unsupported"]) is not int or not 0 <= value["excluded_or_unsupported"] <= (5000 if lockfile else 3000)
        or value["manifests"] != [{"name": row["name"], "sha256": row["sha256"]} for row in files]
        or type(value["dependencies"]) is not list or len(value["dependencies"]) > (50 if lockfile else 100)):
        raise RepositoryError("sandbox_result_unavailable")
    groups = {("package-lock.json", "npm", "lockfile.packages")} if lockfile else {
        ("package.json", "npm", key) for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
    } | {("pyproject.toml", "pypi", "project.dependencies"), ("requirements.txt", "pypi", "requirements")}
    for row in value["dependencies"]:
        if (type(row) is not dict or set(row) != {"manifest", "ecosystem", "group", "name", "constraint"}
            or any(type(row[key]) is not str for key in ("manifest", "ecosystem", "group"))
            or row["manifest"] not in {item["name"] for item in files}
            or (row["manifest"], row["ecosystem"], row["group"]) not in groups
            or type(row["name"]) is not str or not NAME.fullmatch(row["name"]) or SECRET.search(row["name"])
            or type(row["constraint"]) is not str or not VERSION.fullmatch(row["constraint"]) or SECRET.search(row["constraint"])):
            raise RepositoryError("sandbox_result_unavailable")
        if lockfile and not advisories.NPM_PIN.fullmatch(row["constraint"]):
            raise RepositoryError("sandbox_result_unavailable")
    if lockfile:
        meta = value["lockfile"]
        counters = {"package_entries", "supported_entries", "retained_unique_packages", "excluded_entries", "omitted_unique_packages"}
        if (type(meta) is not dict or set(meta) != counters | {"status", "version"}
            or any(type(meta[key]) is not int or not 0 <= meta[key] <= 5000 for key in counters)
            or meta["retained_unique_packages"] != len(value["dependencies"])
            or meta["supported_entries"] + meta["excluded_entries"] != meta["package_entries"]
            or meta["retained_unique_packages"] + meta["omitted_unique_packages"] > meta["supported_entries"]
            or meta["omitted_unique_packages"] > 0 and meta["retained_unique_packages"] != 50
            or value["excluded_or_unsupported"] != meta["excluded_entries"] + meta["omitted_unique_packages"] + int(not files)
            or (not files and (meta["status"] != "missing" or meta["version"] is not None or any(meta[key] for key in counters)))
            or (files and (type(meta["version"]) is not int or meta["version"] not in {2, 3}
                or meta["status"] != ("partial" if meta["excluded_entries"] or meta["omitted_unique_packages"] else "parsed")))
            or len({(row["name"], row["constraint"]) for row in value["dependencies"]}) != len(value["dependencies"])):
            raise RepositoryError("sandbox_result_unavailable")
    result = {key: item for key, item in value.items() if key != "nonce"}
    if len(json.dumps(result).encode()) > 30000:
        raise RepositoryError("sandbox_output_limit")
    return result


def _sandbox_step(job):
    nonce = secrets.token_hex(32)
    name = f"seoops-repo-{job.pk}-{secrets.token_hex(16)}"
    label = sha256(f"{job.organization_id}:{job.project_id}:{job.pk}:{nonce}".encode()).hexdigest()
    return JobStep.objects.create(job=job, sequence=17 if job.input_snapshot["operation"] == code.OPERATION else 14, name=SANDBOX, status=JobStep.Status.RUNNING,
        output={"name": name, "label": label, "cleanup_confirmed": False}), nonce


def _cleanup(engine, step):
    engine.remove(step.output["name"], step.output["label"])
    step.output = {**step.output, "cleanup_confirmed": True}
    step.progress_percent = 100
    step.save(update_fields=["output", "progress_percent"])


def _finish(job_id, *, output=None, error=""):
    with transaction.atomic():
        identity = JobRun.objects.values_list("organization_id", flat=True).get(pk=job_id)
        Organization.objects.select_for_update().get(pk=identity)
        job = JobRun.objects.select_for_update(of=("self",)).select_related("project__organization", "actor").get(pk=job_id)
        if job.status != JobStatus.RUNNING:
            return False
        step = job.steps.filter(name=SANDBOX).first()
        if step and step.output.get("cleanup_confirmed") is not True:
            job.error_category = "sandbox_cleanup_pending"
            job.save(update_fields=["error_category"])  # Preserve original claim time for bounded controller recovery.
            return False
        cancelled = JobCancellation.objects.filter(job=job).exists() or not source_current(job) or bool(usage_denial(job=job))
        job.status = JobStatus.CANCELLED if cancelled else JobStatus.FAILED if error or not output else JobStatus.SUCCEEDED
        job.error_category = "actor_or_source_revoked" if cancelled else error
        job.output = output if output and not cancelled else {}
        job.save(update_fields=["status", "error_category", "output", "updated_at"])
        if step:
            step.status = JobStep.Status.SUCCEEDED if job.status == JobStatus.SUCCEEDED else JobStep.Status.FAILED
            step.error_category = job.error_category
            step.save(update_fields=["status", "error_category"])
        if hasattr(job, "usage"):
            settle_usage(job=job, actual_units=job.steps.filter(name__in=[ATTEMPT, advisories.ATTEMPT]).count())
        return job.status == JobStatus.SUCCEEDED


@sensitive_variables()
def execute_analysis(job_id):
    from .crawler import _crawl_execution_lock
    if not settings.REPOSITORY_CONTROLLER_HOST or settings.PRODUCTION_APP_HOST or settings.FEEDBACK_WORKER_HOST:
        return False  # A misrouted task cannot collect code or control containers on an application host.
    with _crawl_execution_lock(job_id) as acquired:
        if not acquired:
            return False
        with transaction.atomic():
            identity = JobRun.objects.values_list("organization_id", flat=True).get(pk=job_id, handler=HANDLER)
            Organization.objects.select_for_update().get(pk=identity)
            job = JobRun.objects.select_for_update().get(pk=job_id)
            if job.status != JobStatus.QUEUED or job.config_snapshot["controller_id"] != settings.REPOSITORY_CONTROLLER_ID:
                return False
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
        engine = step = None
        try:
            job = _checkpoint(job_id)
            grant, _config = selection(job.project, job.actor, job.input_snapshot)
            engine = Engine(image=job.config_snapshot["runner_image"], controller_id=job.config_snapshot["controller_id"])
            files, tree_sha = collect_manifests(job, grant)
            _checkpoint(job_id)
            step, nonce = _sandbox_step(job)
            lockfile = job.input_snapshot["operation"] == advisories.LOCK_OPERATION
            code_file = job.input_snapshot["operation"] == code.OPERATION
            parser_method = job.config_snapshot.get("parser_method", METHOD)
            raw = engine.run(name=step.output["name"], label=step.output["label"], request={"method": parser_method, "nonce": nonce, "files": files},
                checkpoint=lambda: _checkpoint(job_id))
            _cleanup(engine, step)
            result = code.validate_result(raw, nonce=nonce, files=files) if code_file else _result(raw, nonce=nonce, files=files, lockfile=lockfile)
            advisory_result = collect_advisories(job, result) if job.input_snapshot["operation"] in advisories.OPERATIONS else None
            verify_grant_source(grant, request=_request(job_id), authority_checkpoint=lambda: _checkpoint(job_id))
            output = {"method": METHOD, "source": job.config_snapshot, "tree_sha": tree_sha,
                "collected_at": timezone.now().isoformat(), "coverage": "selected_python_source_only_no_execution_or_whole_repository_assessment" if code_file else
                    "root_npm_package_lock_only_no_installed_or_manifest_consistency_proof" if lockfile else "three_supported_root_manifests_only_no_recursive_collection",
                "cleanup_confirmed": True, "analysis": result}
            if advisory_result is not None:
                output["advisories"] = advisory_result
            if len(json.dumps(output).encode()) > 65536:
                raise RepositoryError("repository_output_limit")
            return _finish(job_id, output=output)
        except CleanupPending:
            return _finish(job_id, error="sandbox_cleanup_pending")
        except (PermissionDenied, ValidationError, ObjectDoesNotExist, RepositoryError, OSError) as error:
            if engine and step and not step.output.get("cleanup_confirmed"):
                try:
                    _cleanup(engine, step)
                except CleanupPending:
                    return _finish(job_id, error="sandbox_cleanup_pending")
            return _finish(job_id, error=getattr(error, "category", "repository_analysis_unavailable"))


def enqueue_recovery():
    from .tasks import recover_repository_analysis_task
    ids = list(JobRun.objects.filter(handler=HANDLER, status=JobStatus.RUNNING,
        updated_at__lt=timezone.now() - timedelta(minutes=6)).order_by("pk").values_list("pk", flat=True)[:20])
    for job_id in ids:
        recover_repository_analysis_task.apply_async(args=[job_id], queue="repository")
    return len(ids)


def recover_analysis(job_id):
    from .crawler import _crawl_execution_lock
    if not settings.REPOSITORY_CONTROLLER_HOST:
        return False
    with _crawl_execution_lock(job_id) as acquired:
        if not acquired:
            return False
        job = JobRun.objects.filter(pk=job_id, handler=HANDLER, status=JobStatus.RUNNING).first()
        if job is None or job.config_snapshot["controller_id"] != settings.REPOSITORY_CONTROLLER_ID or job.updated_at > timezone.now() - timedelta(minutes=6):
            return False
        step = job.steps.filter(name=SANDBOX).first()
        if step and not step.output.get("cleanup_confirmed"):
            try:
                engine = Engine(image=job.config_snapshot["runner_image"], controller_id=job.config_snapshot["controller_id"])
                _cleanup(engine, step)
            except (RepositoryError, OSError):
                return _finish(job_id, error="sandbox_cleanup_pending")
        return _finish(job_id, error="interrupted_analysis_not_replayed")
