from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from kombu.exceptions import OperationalError

from tenancy.models import Organization, ProjectOriginVerification

from .models import JobRun, JobStatus, JobStep, UsageReservation
from .services import reconcile_dispatch
from .usage import reconcile_usage, settle_usage


def reconcile_stuck_jobs(*, limit=100, stale_seconds=90):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 60:
        raise ValidationError("Invalid stuck-job recovery limit.")
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    candidates = list(JobRun.objects.filter(
        handler="diagnostic_probe", status__in=[JobStatus.RUNNING, JobStatus.WAITING_PROVIDER],
        updated_at__lte=cutoff,
    ).order_by("updated_at", "pk").values_list("pk", "organization_id")[:limit])
    recovered = 0
    for job_id, organization_id in candidates:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization_id)
            job = JobRun.objects.select_for_update(skip_locked=True, no_key=True).filter(
                pk=job_id, organization_id=organization_id,
            ).first()
            if job is None or job.status not in {JobStatus.RUNNING, JobStatus.WAITING_PROVIDER} or job.updated_at > cutoff:
                continue
            job.status = JobStatus.FAILED
            job.error_category = "worker_stalled"
            job.save(update_fields=["status", "error_category", "updated_at"])
            if UsageReservation.objects.filter(
                job=job,
                provider="diagnostic",
                state=UsageReservation.State.RESERVED,
            ).exists():
                settle_usage(job=job, actual_units=0)
            recovered += 1
    return recovered


def reconcile_stuck_crawls(*, limit=100, stale_seconds=90):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 60:
        raise ValidationError("Invalid stuck-crawl recovery limit.")
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    candidates = list(JobRun.objects.filter(
        handler="crawl_site", status=JobStatus.RUNNING, updated_at__lte=cutoff,
    ).order_by("updated_at", "pk").values_list("pk", "organization_id")[:limit])
    recovered = 0
    for job_id, organization_id in candidates:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization_id)
            job = JobRun.objects.select_for_update(skip_locked=True, no_key=True).select_related(
                "actor", "project",
            ).filter(pk=job_id, organization_id=organization_id).first()
            if job is None or job.status != JobStatus.RUNNING or job.updated_at > cutoff:
                continue
            from .crawler import _crawl_denial, _finish_crawl
            denied = _crawl_denial(job.pk)
            if denied:
                _finish_crawl(job.pk, cancelled=True, error_category=denied)
                continue
            from .tasks import execute_crawl_job_task
            try:
                execute_crawl_job_task.apply_async(
                    args=[job.pk], queue="crawl", task_id=f"job-{job.pk}", retry=False,
                )
            except (OperationalError, OSError, TimeoutError):
                job.dispatch_error = "broker_unavailable"
                job.save(update_fields=["dispatch_error", "updated_at"])
                continue
            job.dispatched_at = timezone.now()
            job.dispatch_error = ""
            job.save(update_fields=["dispatched_at", "dispatch_error", "updated_at"])
            recovered += 1
    return recovered


def reconcile_stuck_origin_verifications(*, limit=100, stale_seconds=90):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 60:
        raise ValidationError("Invalid origin-verification recovery limit.")
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    candidates = list(JobRun.objects.filter(
        handler="verify_project_origin",
        status=JobStatus.RUNNING,
        updated_at__lte=cutoff,
    ).order_by("updated_at", "pk").values_list("pk", "organization_id")[:limit])
    recovered = 0
    for job_id, organization_id in candidates:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization_id)
            job = JobRun.objects.select_for_update(skip_locked=True, no_key=True).select_related(
                "actor", "project",
            ).filter(pk=job_id, organization_id=organization_id).first()
            if job is None or job.status != JobStatus.RUNNING or job.updated_at > cutoff:
                continue
            from .security import _denial
            verification = ProjectOriginVerification.objects.filter(
                pk=job.input_snapshot.get("verification_id"),
                organization_id=job.organization_id,
                project_id=job.project_id,
            ).first()
            denial = _denial(job, verification)
            if denial:
                job.status = JobStatus.CANCELLED
                job.error_category = denial
                job.save(update_fields=["status", "error_category", "updated_at"])
                if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
                    settle_usage(job=job, actual_units=0)
                continue
            from .tasks import verify_project_origin_task
            try:
                verify_project_origin_task.apply_async(
                    args=[job.pk], queue="audit", task_id=f"job-{job.pk}", retry=False,
                )
            except (OperationalError, OSError, TimeoutError):
                job.dispatch_error = "broker_unavailable"
                job.save(update_fields=["dispatch_error", "updated_at"])
                continue
            job.dispatched_at = timezone.now()
            job.dispatch_error = ""
            job.save(update_fields=["dispatched_at", "dispatch_error", "updated_at"])
            recovered += 1
    return recovered


def reconcile_stuck_topic_jobs(*, limit=100, stale_seconds=90):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 90:
        raise ValidationError("Invalid topic-job recovery limit.")
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    candidates = list(JobRun.objects.filter(
        handler="discover_topics", status=JobStatus.RUNNING, updated_at__lte=cutoff,
    ).order_by("updated_at", "pk").values_list("pk", "organization_id")[:limit])
    recovered = 0
    for job_id, organization_id in candidates:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization_id)
            job = JobRun.objects.select_for_update(skip_locked=True, no_key=True).select_related("actor", "project").filter(
                pk=job_id, organization_id=organization_id,
            ).first()
            if job is None or job.status != JobStatus.RUNNING or job.updated_at > cutoff:
                continue
            from .topic_discovery import _denial, _step_count
            denied = _denial(job)
            if denied:
                JobStep.objects.filter(job=job, status=JobStep.Status.RUNNING).update(
                    status=JobStep.Status.FAILED, error_category=denied, output={"state": "unavailable"},
                )
                job.status = JobStatus.CANCELLED
                job.error_category = denied
                job.save(update_fields=["status", "error_category", "updated_at"])
                if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
                    settle_usage(job=job, actual_units=_step_count(job))
                continue
            from .tasks import execute_topics_task
            try:
                execute_topics_task.apply_async(args=[job.pk], queue="default", task_id=f"job-{job.pk}", retry=False)
            except (OperationalError, OSError, TimeoutError):
                job.dispatch_error = "broker_unavailable"
                job.save(update_fields=["dispatch_error", "updated_at"])
                continue
            job.dispatched_at = timezone.now()
            job.dispatch_error = ""
            job.save(update_fields=["dispatched_at", "dispatch_error", "updated_at"])
            recovered += 1
    return recovered


def reconcile_stuck_search_console_jobs(*, limit=100, stale_seconds=150):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 120:
        raise ValidationError("Invalid Search Console recovery limit.")
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    candidates = list(JobRun.objects.filter(
        handler="sync_search_console", status=JobStatus.RUNNING, updated_at__lte=cutoff,
    ).order_by("updated_at", "pk").values_list("pk", "organization_id")[:limit])
    recovered = 0
    for job_id, org_id in candidates:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            job = JobRun.objects.select_for_update(skip_locked=True, no_key=True).select_related("actor", "project").filter(
                pk=job_id, organization_id=org_id).first()
            if job is None or job.status != JobStatus.RUNNING or job.updated_at > cutoff:
                continue
            from integrations.search_console_sync import _denial, _finish
            if _denial(job):
                _finish(job.pk)
                continue
            from .tasks import sync_search_console_task
            try:
                sync_search_console_task.apply_async(args=[job.pk], queue="default", task_id=f"job-{job.pk}", retry=False)
            except (OperationalError, OSError, TimeoutError):
                job.dispatch_error = "broker_unavailable"
                job.save(update_fields=["dispatch_error", "updated_at"])
                continue
            job.dispatched_at = timezone.now()
            job.dispatch_error = ""
            job.save(update_fields=["dispatched_at", "dispatch_error", "updated_at"])
            recovered += 1
    return recovered


def reconcile_stuck_ga4_jobs(*, limit=100, stale_seconds=140):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 120:
        raise ValidationError("Invalid GA4 recovery limit.")
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    candidates = list(JobRun.objects.filter(
        handler="sync_ga4_landing", status=JobStatus.RUNNING, updated_at__lte=cutoff,
    ).order_by("updated_at", "pk").values_list("pk", "organization_id")[:limit])
    recovered = 0
    for job_id, org_id in candidates:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            job = JobRun.objects.select_for_update(skip_locked=True, no_key=True).select_related("actor", "project").filter(
                pk=job_id, organization_id=org_id).first()
            if job is None or job.status != JobStatus.RUNNING or job.updated_at > cutoff:
                continue
            from integrations.ga4_sync import _denial, _finish
            if _denial(job):
                _finish(job.pk)
                continue
            from .tasks import sync_ga4_landing_task
            try:
                sync_ga4_landing_task.apply_async(args=[job.pk], queue="default", task_id=f"job-{job.pk}", retry=False)
            except (OperationalError, OSError, TimeoutError):
                job.dispatch_error = "broker_unavailable"
                job.save(update_fields=["dispatch_error", "updated_at"])
                continue
            job.dispatched_at = timezone.now()
            job.dispatch_error = ""
            job.save(update_fields=["dispatched_at", "dispatch_error", "updated_at"])
            recovered += 1
    return recovered


def reconcile_stuck_search_console_coverage(*, limit=100, stale_seconds=110):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 90:
        raise ValidationError("Invalid coverage recovery limit.")
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    candidates = list(JobRun.objects.filter(
        handler="collect_search_console_coverage", status=JobStatus.RUNNING, updated_at__lte=cutoff,
    ).order_by("updated_at", "pk").values_list("pk", "organization_id")[:limit])
    recovered = 0
    from integrations.search_console_coverage_job import _denial, _finish
    from .tasks import collect_search_console_coverage_task
    for job_id, org_id in candidates:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            job = JobRun.objects.select_for_update(skip_locked=True, no_key=True).select_related(
                "actor", "project",
            ).filter(pk=job_id, organization_id=org_id).first()
            if job is None or job.status != JobStatus.RUNNING or job.updated_at > cutoff:
                continue
            if _denial(job):
                _finish(job.pk)
                continue
            try:
                collect_search_console_coverage_task.apply_async(
                    args=[job.pk], queue="default", task_id=f"job-{job.pk}", retry=False)
            except (OperationalError, OSError, TimeoutError):
                job.dispatch_error = "broker_unavailable"
                job.save(update_fields=["dispatch_error", "updated_at"])
                continue
            job.dispatched_at = timezone.now()
            job.dispatch_error = ""
            job.save(update_fields=["dispatched_at", "dispatch_error", "updated_at"])
            recovered += 1
    return recovered


def reconcile_stuck_performance_jobs(*, limit=100, stale_seconds=160):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 140:
        raise ValidationError("Invalid performance audit recovery limit.")
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    candidates = list(JobRun.objects.filter(
        handler="audit_performance", status=JobStatus.RUNNING, updated_at__lte=cutoff,
    ).order_by("updated_at", "pk").values_list("pk", "organization_id")[:limit])
    recovered = 0
    for job_id, org_id in candidates:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            job = JobRun.objects.select_for_update(skip_locked=True, no_key=True).select_related("actor", "project").filter(
                pk=job_id, organization_id=org_id).first()
            if job is None or job.status != JobStatus.RUNNING or job.updated_at > cutoff:
                continue
            from .performance_job import _denial, _finish
            if _denial(job):
                _finish(job.pk)
                continue
            from .tasks import execute_performance_task
            try:
                execute_performance_task.apply_async(args=[job.pk], queue="audit", task_id=f"job-{job.pk}", retry=False)
            except (OperationalError, OSError, TimeoutError):
                job.dispatch_error = "broker_unavailable"
                job.save(update_fields=["dispatch_error", "updated_at"])
                continue
            job.dispatched_at = timezone.now()
            job.dispatch_error = ""
            job.save(update_fields=["dispatched_at", "dispatch_error", "updated_at"])
            recovered += 1
    return recovered


def reconcile_stuck_ai_text(*, limit=100, stale_seconds=90):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 75:
        raise ValidationError("Invalid AI job recovery limit.")
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    candidates = list(JobRun.objects.filter(
        handler="ai_text", status=JobStatus.RUNNING, updated_at__lte=cutoff,
    ).order_by("updated_at", "pk").values_list("pk", "organization_id")[:limit])
    recovered = 0
    from .ai_text import _finish
    for job_id, org_id in candidates:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=org_id)
            job = JobRun.objects.select_for_update(skip_locked=True, no_key=True).filter(pk=job_id, organization_id=org_id).first()
            if job is None or job.status != JobStatus.RUNNING or job.updated_at > cutoff:
                continue
            recovered += bool(_finish(job.pk, error="request_outcome_unknown"))
    return recovered


def reconcile_diagnostic_jobs():
    stuck = reconcile_stuck_jobs() if settings.DEBUG else 0
    from integrations.search_console import reconcile_search_console_artifacts
    from integrations.business_profile_read import recover_business_attempts
    from integrations.yandex_sync import reconcile_stuck_syncs
    from .serp import recover_observations
    from .repository_analysis import enqueue_recovery
    return {
        "dispatch": reconcile_dispatch(),
        "yandex": reconcile_stuck_syncs(),
        "serp": recover_observations(),
        "repository_recovery_queued": enqueue_recovery(),
        "stuck": stuck,
        "crawls": reconcile_stuck_crawls(),
        "origin_verifications": reconcile_stuck_origin_verifications(),
        "topics": reconcile_stuck_topic_jobs(),
        "search_console": reconcile_stuck_search_console_jobs(),
        "ga4": reconcile_stuck_ga4_jobs(),
        "search_console_coverage": reconcile_stuck_search_console_coverage(),
        "performance": reconcile_stuck_performance_jobs(),
        "ai_text": reconcile_stuck_ai_text(),
        "research": reconcile_stuck_research(),
        "content_generation": reconcile_stuck_content_generation(),
        "visibility_samples": reconcile_stuck_visibility_samples(),
        "static_link_sources": reconcile_stuck_static_link_sources(),
        "competitor_roots": reconcile_stuck_competitor_roots(),
        "competitor_synthesis": reconcile_stuck_competitor_synthesis(),
        "passive_headers": reconcile_stuck_passive_headers(),
        "passive_tls": reconcile_stuck_passive_tls(),
        "passive_resources": reconcile_stuck_passive_resources(),
        "passive_redirects": reconcile_stuck_passive_redirects(),
        "passive_http_redirects": reconcile_stuck_passive_http_redirects(),
        "passive_redirect_chain": reconcile_stuck_passive_redirect_chain(),
        "youtube_search": reconcile_stuck_youtube_search(),
        "business_profile": recover_business_attempts(),
        "integration_artifacts": reconcile_search_console_artifacts(),
        "usage": reconcile_usage(),
    }


def reconcile_stuck_youtube_search(*, limit=100, stale_seconds=90):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 90:
        raise ValidationError("Invalid YouTube attempt recovery limit.")
    from .youtube_search import finish_youtube_attempt
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    jobs = list(JobRun.objects.filter(handler="search_youtube", status=JobStatus.RUNNING,
        updated_at__lte=cutoff).order_by("updated_at", "pk")[:limit])
    return sum(finish_youtube_attempt(job, error="request_outcome_unknown") for job in jobs)


def reconcile_stuck_research(*, limit=100, stale_seconds=150):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 120:
        raise ValidationError("Invalid research recovery limit.")
    from .crawler import _crawl_execution_lock
    from .research import _finish
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    ids = list(JobRun.objects.filter(handler="research_topic", status=JobStatus.RUNNING,
                                    updated_at__lte=cutoff).order_by("updated_at", "pk").values_list("pk", flat=True)[:limit])
    recovered = 0
    for job_id in ids:
        with _crawl_execution_lock(job_id) as acquired:
            if acquired and JobRun.objects.filter(pk=job_id, status=JobStatus.RUNNING, updated_at__lte=cutoff).exists():
                recovered += bool(_finish(job_id, error="request_outcome_unknown"))
    return recovered


def reconcile_stuck_content_generation(*, limit=100, stale_seconds=90):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 75:
        raise ValidationError("Invalid draft recovery limit.")
    from .crawler import _crawl_execution_lock
    from .content_generation import _finish
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    ids = list(JobRun.objects.filter(handler="generate_content", status=JobStatus.RUNNING,
        updated_at__lte=cutoff).order_by("updated_at", "pk").values_list("pk", flat=True)[:limit])
    recovered = 0
    for job_id in ids:
        with _crawl_execution_lock(job_id) as acquired:
            if acquired and JobRun.objects.filter(pk=job_id, status=JobStatus.RUNNING, updated_at__lte=cutoff).exists():
                recovered += bool(_finish(job_id, error="request_outcome_unknown"))
    return recovered


def reconcile_stuck_visibility_samples(*, limit=100, stale_seconds=90):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 75:
        raise ValidationError("Invalid visibility sample recovery limit.")
    from .crawler import _crawl_execution_lock
    from .visibility_collection import HANDLER, _finish
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    ids = list(JobRun.objects.filter(handler=HANDLER, status=JobStatus.RUNNING,
        updated_at__lte=cutoff).order_by("updated_at", "pk").values_list("pk", flat=True)[:limit])
    recovered = 0
    for job_id in ids:
        with _crawl_execution_lock(job_id) as acquired:
            if acquired and JobRun.objects.filter(pk=job_id, status=JobStatus.RUNNING, updated_at__lte=cutoff).exists():
                recovered += bool(_finish(job_id, error="request_outcome_unknown"))
    return recovered


def reconcile_stuck_static_link_sources(*, limit=100, stale_seconds=90):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 75:
        raise ValidationError("Invalid static-link source recovery limit.")
    from .crawler import _crawl_execution_lock
    from .authority_link_collection import HANDLER, _finish
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    ids = list(JobRun.objects.filter(handler=HANDLER, status=JobStatus.RUNNING, updated_at__lte=cutoff)
               .order_by("updated_at", "pk").values_list("pk", flat=True)[:limit])
    recovered = 0
    for job_id in ids:
        with _crawl_execution_lock(job_id) as acquired:
            if acquired and JobRun.objects.filter(pk=job_id, status=JobStatus.RUNNING, updated_at__lte=cutoff).exists():
                recovered += bool(_finish(job_id, error="request_outcome_unknown"))
    return recovered


def reconcile_stuck_competitor_roots(*, limit=100, stale_seconds=90):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 75:
        raise ValidationError("Invalid competitor recovery limit.")
    from .crawler import _crawl_execution_lock
    from .competitor_collection import COMPETITOR_OBSERVATION_HANDLERS, _finish
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    ids = list(JobRun.objects.filter(handler__in=COMPETITOR_OBSERVATION_HANDLERS, status=JobStatus.RUNNING, updated_at__lte=cutoff)
        .order_by("updated_at", "pk").values_list("pk", flat=True)[:limit])
    recovered = 0
    for job_id in ids:
        with _crawl_execution_lock(job_id) as acquired:
            if acquired and JobRun.objects.filter(pk=job_id, status=JobStatus.RUNNING, updated_at__lte=cutoff).exists():
                recovered += bool(_finish(job_id, error="request_outcome_unknown"))
    return recovered


def reconcile_stuck_competitor_synthesis(*, limit=100, stale_seconds=150):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 120:
        raise ValidationError("Invalid competitor synthesis recovery limit.")
    from .crawler import _crawl_execution_lock
    from .competitor_synthesis_job import SYNTHESIS_HANDLERS, _finish
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    ids = list(JobRun.objects.filter(handler__in=SYNTHESIS_HANDLERS, status=JobStatus.RUNNING, updated_at__lte=cutoff)
        .order_by("updated_at", "pk").values_list("pk", flat=True)[:limit])
    recovered = 0
    for job_id in ids:
        with _crawl_execution_lock(job_id) as acquired:
            if acquired and JobRun.objects.filter(pk=job_id, status=JobStatus.RUNNING, updated_at__lte=cutoff).exists():
                recovered += bool(_finish(job_id, error="request_outcome_unknown"))
    return recovered


def reconcile_stuck_passive_headers(*, limit=100, stale_seconds=90, handler="collect_passive_headers"):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 75:
        raise ValidationError("Invalid passive header recovery limit.")
    from .crawler import _crawl_execution_lock
    from .passive_header_collection import PASSIVE_HANDLERS, _finish
    if handler not in PASSIVE_HANDLERS: raise ValidationError("Invalid passive recovery handler.")
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    ids = list(JobRun.objects.filter(handler=handler, status=JobStatus.RUNNING, updated_at__lte=cutoff)
        .order_by("updated_at", "pk").values_list("pk", flat=True)[:limit])
    recovered = 0
    for job_id in ids:
        with _crawl_execution_lock(job_id) as acquired:
            if acquired and JobRun.objects.filter(pk=job_id, status=JobStatus.RUNNING, updated_at__lte=cutoff).exists():
                recovered += bool(_finish(job_id, error="request_outcome_unknown"))
    return recovered


def reconcile_stuck_passive_tls(*, limit=100, stale_seconds=90):
    return reconcile_stuck_passive_headers(limit=limit, stale_seconds=stale_seconds, handler="collect_passive_tls")


def reconcile_stuck_passive_resources(*, limit=100, stale_seconds=90):
    return reconcile_stuck_passive_headers(limit=limit, stale_seconds=stale_seconds, handler="collect_passive_resources")


def reconcile_stuck_passive_redirects(*, limit=100, stale_seconds=90):
    return reconcile_stuck_passive_headers(limit=limit, stale_seconds=stale_seconds, handler="collect_passive_redirects")


def reconcile_stuck_passive_http_redirects(*, limit=100, stale_seconds=90):
    return reconcile_stuck_passive_headers(limit=limit, stale_seconds=stale_seconds, handler="collect_passive_http_redirects")


def reconcile_stuck_passive_redirect_chain(*, limit=100, stale_seconds=90):
    return reconcile_stuck_passive_headers(limit=limit, stale_seconds=stale_seconds, handler="collect_passive_redirect_chain")
