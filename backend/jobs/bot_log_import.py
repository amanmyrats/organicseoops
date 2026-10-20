"""D122 transient intake and private derived-only offline job; never stores an upload."""
from hashlib import sha256
import json
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import Organization, Project
from tenancy.services import Action, require_passive_security_scope, require_project_action
from .bot_logs import METHOD, parse_bot_logs, validate_summary
from .models import IndexationEvidenceSnapshot, JobCancellation, JobRun, JobStatus, JobStep

HANDLER = "import_bot_logs"


def validate_input(data):
    if (type(data) is not dict or set(data) != {"summary", "authorize_logfile"}
        or data["authorize_logfile"] is not True):
        raise ValidationError("Explicit logfile authorization and minimized evidence are required.")
    validate_summary(data["summary"])
    return {}, False


def source_snapshot(project, actor, *, origin, inventory_id):
    project = Project.objects.select_related("organization").filter(pk=project.pk, organization_id=project.organization_id).first()
    if project is None:
        raise PermissionDenied
    verification = require_passive_security_scope(project=project, user=actor, origin=origin)
    snapshot = IndexationEvidenceSnapshot.objects.select_related("crawl_run__job__actor", "diagnostics").filter(
        pk=inventory_id, project=project, crawl_run__project=project, crawl_run__organization_id=project.organization_id,
        crawl_run__job__project=project, crawl_run__job__organization_id=project.organization_id,
        crawl_run__job__status__in=[JobStatus.SUCCEEDED, JobStatus.PARTIALLY_SUCCEEDED],
        crawl_run__completed_at__isnull=False, diagnostics__project=project,
    ).first()
    if snapshot is None or JobCancellation.objects.filter(job_id=snapshot.crawl_run.job_id).exists():
        raise PermissionDenied
    require_project_action(project=project, user=snapshot.crawl_run.job.actor, action=Action.LAUNCH_JOB)
    from .crawling import CrawlScope
    from .indexation import _hash_input
    if snapshot.input_hash != _hash_input(snapshot.diagnostics, CrawlScope.for_project(project)):
        raise PermissionDenied
    urls = []
    for row in snapshot.output.get("urls", [])[:40]:
        url = row.get("url") if type(row) is dict else None
        if type(url) is not str or not 1 <= len(url) <= 512:
            continue
        try:
            parts = urlsplit(url)
        except ValueError:
            continue
        if (parts.scheme + "://" + parts.netloc == origin and not parts.query and not parts.fragment
            and parts.username is None and parts.password is None):
            urls.append(url)
    urls = sorted(set(urls))
    return {"verification_id": verification.pk, "verified_at": verification.verified_at.isoformat(),
        "inventory_id": snapshot.pk, "inventory_hash": snapshot.input_hash,
        "inventory_urls_sha256": sha256(json.dumps(urls, separators=(",", ":")).encode()).hexdigest(),
        "crawl_run_id": snapshot.crawl_run_id, "method": METHOD}, urls


def validate_job(job, *, current=False):
    validate_input(job.input_snapshot)
    from .services import _snapshot
    _snapshot(job.input_snapshot)
    if (job.dispatch_error not in {"", "broker_unavailable"} or job.error_category not in {
        "", "actor_revoked", "source_or_actor_revoked", "cancel_requested", "usage_unreserved", "trial_unavailable",
        "trial_units_exhausted", "paid_unavailable", "billing_review_hold", "paid_period_changed", "paid_units_exhausted", "internal_capacity"}):
        raise ValidationError("Bot-log failures are categorical only.")
    config = job.config_snapshot
    if (type(config) is not dict or set(config) != {"verification_id", "verified_at", "inventory_id", "inventory_hash",
        "inventory_urls_sha256", "crawl_run_id", "method"} or config.get("method") != METHOD
        or job.method_version != METHOD or job.retry_of_id or job.schedule_id or job.scheduled_for):
        raise ValidationError("Bot-log jobs require exact-source manual intake.")
    if any(type(config[key]) is not int or config[key] < 1 for key in ("verification_id", "inventory_id", "crawl_run_id")):
        raise ValidationError("Bot-log source references are invalid.")
    import re
    if any(type(config[key]) is not str or not re.fullmatch(r"[0-9a-f]{64}", config[key])
           for key in ("inventory_hash", "inventory_urls_sha256")):
        raise ValidationError("Bot-log source digests are invalid.")
    from datetime import datetime
    try:
        stamp = datetime.fromisoformat(config["verified_at"])
        if timezone.is_naive(stamp) or stamp.isoformat() != config["verified_at"]:
            raise ValueError
    except (TypeError, ValueError):
        raise ValidationError("Bot-log verification time is invalid.") from None
    expected_output = result(job.input_snapshot["summary"])
    if job.output and job.output != expected_output:
        raise ValidationError("Only minimized derived bot-log output is permitted.")
    if current:
        actual, urls = source_snapshot(job.project, job.actor, origin=job.input_snapshot["summary"]["origin"],
                                       inventory_id=config["inventory_id"])
        if actual != config or any(row["known_url"] is not None and row["known_url"] not in urls
                                   for row in job.input_snapshot["summary"]["groups"]):
            raise PermissionDenied


def queue_bot_log_import(*, project, actor, content, origin, window_start, window_end,
                         inventory_id, authorize_logfile, idempotency_key):
    if authorize_logfile is not True or type(inventory_id) is not int or inventory_id < 1:
        raise ValidationError("Confirm logfile authorization and select an existing inventory.")
    config, urls = source_snapshot(project, actor, origin=origin, inventory_id=inventory_id)
    summary = parse_bot_logs(content, origin=origin, window_start=window_start, window_end=window_end, known_urls=urls)
    # Raw content is never passed to a model, storage helper or task.
    from .services import queue_job
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=project.organization_id)
        Project.objects.select_for_update().get(pk=project.pk)
        current, _urls = source_snapshot(project, actor, origin=origin, inventory_id=inventory_id)
        if current != config:
            raise PermissionDenied
        return queue_job(project=project, actor=actor, handler=HANDLER,
            input_snapshot={"summary": summary, "authorize_logfile": True}, config_snapshot=config,
            idempotency_key=idempotency_key)


def result(summary):
    families = {}
    for row in summary["groups"]:
        url = row["known_url"]
        if url is None:
            continue
        key = (row["agent"], urlsplit(url).path.split("/")[1])
        family = families.setdefault(key, {"agent": row["agent"], "representative_inventory_url": url,
            "known_urls": 0, "request_count": 0, "redirect_or_error_requests": 0})
        family["known_urls"] += 1
        family["request_count"] += row["request_count"]
        family["redirect_or_error_requests"] += sum(count for code, count in row["status_counts"].items() if int(code) >= 300)
    return {"summary": summary, "request_candidates": {
        "unmatched_inventory_requests": sum(row["request_count"] for row in summary["groups"] if row["known_url"] is None),
        "redirect_or_error_requests": sum(count for row in summary["groups"] for code, count in row["status_counts"].items()
                                           if int(code) >= 300),
        "interpretation": "partial_request_distribution_not_proven_waste_or_visitors"},
        "inventory_families": list(families.values()), "family_method": "same_first_path_segment_known_inventory_only"}


def source_current(job):
    try:
        validate_job(job, current=True)
        return True
    except (PermissionDenied, ValidationError, Project.DoesNotExist):
        return False


def execute_bot_log_import(job_id):
    organization_id = JobRun.objects.filter(pk=job_id, handler=HANDLER).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return False
    # Pure <=24KiB computation, one atomic commit: a crash leaves QUEUED and safe
    # redispatch, never half-written RUNNING work or a non-idempotent external call.
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        if job.status != JobStatus.QUEUED:
            return False
        Project.objects.select_for_update().get(pk=job.project_id)
        from .usage import settle_usage, usage_denial
        denial = "cancel_requested" if JobCancellation.objects.filter(job=job).exists() else ""
        if not denial and not source_current(job):
            denial = "source_or_actor_revoked"
        if not denial:
            denial = usage_denial(job=job)
        if denial:
            job.status = JobStatus.CANCELLED
            job.error_category = denial
            job.save(update_fields=["status", "error_category", "updated_at"])
            if hasattr(job, "usage"):
                settle_usage(job=job, actual_units=0)
            return False
        job.status = JobStatus.RUNNING
        job.save(update_fields=["status", "updated_at"])
        JobStep.objects.create(job=job, sequence=1, name="Finalize minimized bot-log evidence",
            status=JobStep.Status.SUCCEEDED, progress_percent=100, output={"method": METHOD})
        job.output = result(job.input_snapshot["summary"])
        job.status = JobStatus.SUCCEEDED
        job.save(update_fields=["status", "output", "updated_at"])
        settle_usage(job=job, actual_units=1)
        return True
