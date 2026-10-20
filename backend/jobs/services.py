import json
from datetime import timedelta

from kombu.exceptions import OperationalError
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone

from tenancy.models import AuditEvent, AuditEventType, Organization
from tenancy.services import Action, require_project_action

from .models import JobCancellation, JobRun, JobStatus, JobStep, LEGAL_TRANSITIONS


def _snapshot(value):
    if not isinstance(value, dict):
        raise ValidationError("Job snapshots must be JSON objects.")
    try:
        encoded = json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        raise ValidationError("Job snapshots must be valid JSON.") from None
    if len(encoded.encode()) > 32768:
        raise ValidationError("Job snapshots must be at most 32 KiB.")
    return json.loads(encoded)


def _diagnostic_probe(data):
    if set(data) != {"sample", "simulate_partial"} or not isinstance(data["sample"], str) or not 1 <= len(data["sample"]) <= 100 or type(data["simulate_partial"]) is not bool:
        raise ValidationError("Check the diagnostic input.")
    return {"sample_length": len(data["sample"]), "method": "diagnostic-v1"}, data["simulate_partial"]


def _crawl_site(data):
    from .crawler import validate_crawl_input
    return validate_crawl_input(data)


def _verify_project_origin(data):
    from .security import validate_origin_verification_input
    return validate_origin_verification_input(data)


def _import_search_console_csv(data):
    from integrations.search_console import validate_search_console_import_input
    return validate_search_console_import_input(data)


def _discover_topics(data):
    from .topic_discovery import validate_topic_discovery_input
    return validate_topic_discovery_input(data)


def _sync_search_console(data):
    from integrations.search_console_sync import validate_sync_input
    return validate_sync_input(data)


def _search_console_coverage(data):
    from integrations.search_console_coverage_job import validate_coverage_input
    return validate_coverage_input(data)


def _ga4_landing(data):
    from integrations.ga4_sync import validate_ga4_sync_input
    return validate_ga4_sync_input(data)


def _audit_performance(data):
    from .performance_job import validate_performance_selection
    return validate_performance_selection(data)


def _ai_text(data):
    from .ai_text import validate_ai_text_input
    return validate_ai_text_input(data)


def _research(data):
    from .research import validate_research_input
    return validate_research_input(data)


def _content_generation(data):
    from .content_generation import validate_generation_input
    return validate_generation_input(data)


def _visibility_sample(data):
    from .visibility_collection import validate_collection_input
    return validate_collection_input(data)


def _repository_analysis(data):
    from .repository_analysis import validate_input
    return validate_input(data)


def _serp_observation(data):
    from .serp import validate_input
    return validate_input(data)


def _yandex_sync(data):
    from integrations.yandex_sync import validate_input
    return validate_input(data)


def _yandex_csv(data):
    from integrations.yandex_webmaster import validate_input
    return validate_input(data)


def _bot_logs(data):
    from .bot_log_import import validate_input
    return validate_input(data)


def _static_link_source(data):
    from .authority_link_collection import validate_input
    return validate_input(data)


def _competitor_root(data):
    from .competitor_collection import validate_input
    return validate_input(data)


def _competitor_page(data):
    from .competitor_page_collection import validate_input
    return validate_input(data)


def _competitor_synthesis(data):
    from .competitor_synthesis_job import validate_input
    return validate_input(data)


def _competitor_topics(data):
    from .competitor_topics_selection import validate_input
    return validate_input(data)


def _passive_headers(data):
    from .passive_header_collection import validate_input
    return validate_input(data)


def _passive_tls(data):
    from .passive_tls_collection import validate_input
    return validate_input(data)


def _passive_resources(data):
    from .passive_resource_collection import validate_input
    return validate_input(data)


def _passive_redirects(data):
    from .passive_redirect_collection import validate_input
    return validate_input(data)


def _passive_http_redirects(data):
    from .passive_http_redirect_collection import validate_input
    return validate_input(data)


def _passive_redirect_chain(data):
    from .passive_redirect_chain_collection import validate_input
    return validate_input(data)


def _competitor_lab(data):
    from .competitor_lab_collection import validate_input
    return validate_input(data)


HANDLERS = {
    "analyze_repository": _repository_analysis,
    "collect_serp": _serp_observation,
    "sync_yandex_webmaster": _yandex_sync,
    "import_yandex_webmaster_csv": _yandex_csv,
    "classify_competitor_heading_topics": _competitor_topics,
    "collect_competitor_lighthouse": _competitor_lab,
    "collect_competitor_page_formats": _competitor_page,
    "collect_competitor_page_dates": _competitor_page,
    "collect_competitor_page_destinations": _competitor_page,
    "collect_competitor_page_headings": _competitor_page,
    "collect_competitor_page": _competitor_page,
    "collect_competitor_links_root": _competitor_root,
    "collect_competitor_schema_root": _competitor_root,
    "collect_passive_redirect_chain": _passive_redirect_chain,
    "collect_passive_http_redirects": _passive_http_redirects,
    "synthesize_competitor_pair": _competitor_synthesis,
    "synthesize_competitor_headings_pair": _competitor_synthesis,
    "collect_competitor_root": _competitor_root,
    "collect_passive_redirects": _passive_redirects,
    "collect_passive_resources": _passive_resources,
    "collect_passive_tls": _passive_tls,
    "collect_passive_headers": _passive_headers,
    "verify_authority_link_source": _static_link_source,
    "import_bot_logs": _bot_logs,
    "sample_ai_visibility": _visibility_sample,
    "diagnostic_probe": _diagnostic_probe,
    "crawl_site": _crawl_site,
    "verify_project_origin": _verify_project_origin,
    "import_search_console_csv": _import_search_console_csv,
    "discover_topics": _discover_topics,
    "sync_search_console": _sync_search_console,
    "collect_search_console_coverage": _search_console_coverage,
    "sync_ga4_landing": _ga4_landing,
    "audit_performance": _audit_performance,
    "ai_text": _ai_text,
    "research_topic": _research,
    "generate_content": _content_generation,
}
METHOD_VERSIONS = {
    "analyze_repository": "repository-root-manifests-v1",
    "collect_serp": "dataforseo-google-top10-v1",
    "sync_yandex_webmaster": "yandex-site-history-v1",
    "import_yandex_webmaster_csv": "yandex-query-url-csv-v1",
    "classify_competitor_heading_topics": "competitor-heading-topics-v1",
    "collect_competitor_lighthouse": "competitor-lighthouse-collect-v1",
    "collect_competitor_page_formats": "competitor-page-elements-collect-v1",
    "collect_competitor_page_dates": "competitor-page-dates-collect-v1",
    "collect_competitor_page_destinations": "competitor-page-destinations-v1",
    "collect_competitor_page_headings": "competitor-page-headings-collect-v1",
    "collect_competitor_page": "competitor-static-page-collect-v1",
    "collect_competitor_links_root": "competitor-static-root-links-collect-v1",
    "collect_competitor_schema_root": "competitor-static-schema-root-collect-v1",
    "collect_passive_redirect_chain": "passive-exact-redirect-chain-evidence-v1",
    "collect_passive_http_redirects": "passive-http-redirect-collection-v1",
    "synthesize_competitor_pair": "competitor-static-synthesis-v1",
    "synthesize_competitor_headings_pair": "competitor-heading-synthesis-v1",
    "collect_competitor_root": "competitor-static-root-collect-v1",
    "collect_passive_redirects": "passive-redirect-collection-v1",
    "collect_passive_resources": "passive-resource-collection-v1",
    "collect_passive_tls": "passive-tls-collection-v1",
    "collect_passive_headers": "passive-header-collection-v1",
    "verify_authority_link_source": "authority-static-link-collect-v1",
    "import_bot_logs": "bot-log-jsonl-v1",
    "sample_ai_visibility": "visibility-text-collection-v1",
    "diagnostic_probe": "diagnostic-v1",
    "crawl_site": "crawl-http-v2",
    "verify_project_origin": "origin-http-file-v1",
    "import_search_console_csv": "search-console-csv-v1",
    "discover_topics": "topic-discovery-v2",
    "sync_search_console": "search-console-api-v1",
    "collect_search_console_coverage": "search-console-coverage-v1",
    "sync_ga4_landing": "ga4-landing-api-v2",
    "audit_performance": "performance-observation-v1",
    "ai_text": "ai-text-v2",
    "research_topic": "research-v1",
    "generate_content": "content-generation-v1",
}


def _handler_allowed(handler):
    return handler in HANDLERS and (handler != "diagnostic_probe" or settings.DEBUG)


def _usage_request(handler, data, config):
    if handler == "analyze_repository":
        from .repository_analysis import maximum_requests
        return "repository_analysis", maximum_requests(data)
    if handler == "collect_serp":
        return "dataforseo_serp", 1
    if handler in {"collect_competitor_root", "collect_competitor_schema_root", "collect_competitor_links_root", "collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats", "collect_competitor_lighthouse"}:
        return "competitor_source", 1
    if handler in {"collect_passive_headers", "collect_passive_tls", "collect_passive_resources", "collect_passive_redirects", "collect_passive_http_redirects", "collect_passive_redirect_chain"}:
        return "passive_security", 1
    if handler == "verify_authority_link_source":
        return "authority_source", 1
    if handler == "diagnostic_probe":
        return "diagnostic", 0
    if handler == "verify_project_origin":
        return "passive_security", 0
    if handler in {"import_search_console_csv", "import_bot_logs", "import_yandex_webmaster_csv", "sync_yandex_webmaster"}:
        return "source_import", 1
    if handler == "discover_topics":
        return "topic_discovery", len(data["feeds"]) + int(data["connection_id"] is not None) + int(data.get("news") is not None)
    if handler == "sync_search_console":
        if data.get("report") == "query_page":
            return "search_console_api", 3
        return "search_console_api", 2 if config.get("scope_strategy") == "domain-page-v1" else 1 + 2 * len(data["dimensions"])
    if handler == "sync_ga4_landing":
        return "google_analytics_4", 5
    if handler == "collect_search_console_coverage":
        return "search_console_coverage", 3
    if handler == "audit_performance":
        return "performance", len(data["sources"])
    if handler in {"classify_competitor_heading_topics", "synthesize_competitor_pair", "synthesize_competitor_headings_pair", "ai_text", "generate_content", "sample_ai_visibility"}:
        return "ai", 1
    if handler == "research_topic":
        return "ai", len(data["source_urls"]) + 1
    return "crawler", data["page_limit"]


def _required_action(handler):
    return (Action.MANAGE_PROJECT if handler in {"classify_competitor_heading_topics", "synthesize_competitor_pair", "synthesize_competitor_headings_pair", "collect_competitor_root", "collect_competitor_schema_root", "collect_competitor_links_root", "collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats", "collect_competitor_lighthouse", "collect_passive_headers", "collect_passive_tls", "collect_passive_resources", "collect_passive_redirects", "collect_passive_http_redirects", "collect_passive_redirect_chain", "verify_authority_link_source", "business_profile_request", "import_bot_logs", "import_yandex_webmaster_csv", "sync_yandex_webmaster", "collect_serp", "analyze_repository", "verify_project_origin", "collect_search_console_coverage", "sync_ga4_landing"}
            else Action.LAUNCH_JOB)


def create_job(*, project, actor, handler, input_snapshot, config_snapshot=None, idempotency_key="", retry_of=None,
               schedule=None, scheduled_for=None):
    if not _handler_allowed(handler):
        raise PermissionDenied
    require_project_action(project=project, user=actor, action=_required_action(handler))
    data = _snapshot(input_snapshot)
    HANDLERS[handler](data)
    config = _snapshot(config_snapshot or {})
    with transaction.atomic():
        require_project_action(project=project, user=actor, action=_required_action(handler))
        return JobRun.objects.create(
            organization=project.organization, project=project, actor=actor, handler=handler,
            input_snapshot=data, config_snapshot=config, method_version=(data.get("collection_method", METHOD_VERSIONS[handler])
                if handler == "verify_authority_link_source" else METHOD_VERSIONS[handler]),
            idempotency_key=idempotency_key,
            retry_of=retry_of,
            schedule=schedule, scheduled_for=scheduled_for,
        )


def queue_job(*, project, actor, handler, input_snapshot, idempotency_key, config_snapshot=None, retry_of=None,
              schedule=None, scheduled_for=None):
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 64:
        raise ValidationError("A bounded idempotency key is required.")
    data = _snapshot(input_snapshot)
    config = _snapshot(config_snapshot or {})
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=project.organization_id)
        require_project_action(project=project, user=actor, action=_required_action(handler))
        if handler in {"classify_competitor_heading_topics", "synthesize_competitor_pair", "synthesize_competitor_headings_pair"}:
            from .competitor_synthesis_job import _contract
            _contract(handler).validate_job(JobRun(project=project, organization=project.organization, actor=actor, handler=handler,
                method_version=METHOD_VERSIONS[handler], input_snapshot=data, config_snapshot=config,
                retry_of=retry_of, schedule=schedule, scheduled_for=scheduled_for), current=True)
        if handler in {"collect_competitor_root", "collect_competitor_schema_root", "collect_competitor_links_root", "collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats", "collect_competitor_lighthouse"}:
            from .competitor_collection import validate_job
            validate_job(JobRun(project=project, organization=project.organization, actor=actor, handler=handler,
                method_version=METHOD_VERSIONS[handler], input_snapshot=data, config_snapshot=config,
                retry_of=retry_of, schedule=schedule, scheduled_for=scheduled_for), current=True)
        if handler in {"collect_passive_headers", "collect_passive_tls", "collect_passive_resources", "collect_passive_redirects", "collect_passive_http_redirects", "collect_passive_redirect_chain"}:
            from .passive_header_collection import validate_job
            validate_job(JobRun(project=project, organization=project.organization, actor=actor, handler=handler,
                method_version=METHOD_VERSIONS[handler], input_snapshot=data, config_snapshot=config,
                retry_of=retry_of, schedule=schedule, scheduled_for=scheduled_for), current=True)
        if handler == "verify_authority_link_source":
            from .authority_link_collection import validate_job
            validate_job(JobRun(project=project, organization=project.organization, actor=actor, handler=handler,
                method_version=data.get("collection_method", METHOD_VERSIONS[handler]), input_snapshot=data, config_snapshot=config,
                retry_of=retry_of, schedule=schedule, scheduled_for=scheduled_for), current=True)
        if handler == "import_bot_logs":
            from .bot_log_import import validate_job
            validate_job(JobRun(project=project, organization=project.organization, actor=actor, handler=handler,
                method_version=METHOD_VERSIONS[handler], input_snapshot=data, config_snapshot=config,
                retry_of=retry_of, schedule=schedule, scheduled_for=scheduled_for), current=True)
            duplicate = JobRun.objects.filter(project=project, handler=handler,
                input_snapshot__summary__source_sha256=data["summary"]["source_sha256"]).first()
            if duplicate and duplicate.idempotency_key != idempotency_key:
                raise ValidationError("This log file was already staged; use its existing import history.")
        if handler == "sample_ai_visibility":
            from .visibility_collection import selection_snapshot, _repeat_denial
            from .visibility_schedule import validate_scheduled_job
            _model, _account, current_config = selection_snapshot(project, actor, data)
            existing = JobRun.objects.filter(project=project, handler=handler, idempotency_key=idempotency_key).first()
            if (config != current_config or retry_of or (scheduled_for and not schedule)
                or not existing and _repeat_denial(project, config, data)):
                raise ValidationError("Visibility requires exact-current selection and its repeat policy.")
            if schedule and not existing:
                validate_scheduled_job(JobRun(project=project, organization=project.organization, actor=actor,
                    handler=handler, method_version=METHOD_VERSIONS[handler], input_snapshot=data, config_snapshot=config, schedule=schedule,
                    scheduled_for=scheduled_for), current=True)
        if handler == "ai_text":
            from .ai_text import _selection
            _selection(data, organization_id=project.organization_id)
        job = JobRun.objects.filter(project=project, handler=handler, idempotency_key=idempotency_key).first()
        if job is not None:
            if (job.actor_id != actor.pk or job.input_snapshot != data or job.config_snapshot != config
                    or job.retry_of_id != (retry_of.pk if retry_of else None)
                    or job.schedule_id != (schedule.pk if schedule else None)
                    or job.scheduled_for != scheduled_for):
                raise ValidationError("Idempotency key belongs to another job request.")
            if job.status == JobStatus.QUEUED and not hasattr(job, "usage"):
                from .usage import reserve_usage
                provider, units = _usage_request(handler, data, config)
                reserve_usage(job=job, provider=provider, units=units)
        else:
            job = create_job(project=project, actor=actor, handler=handler, input_snapshot=data,
                             config_snapshot=config, idempotency_key=idempotency_key, retry_of=retry_of,
                             schedule=schedule, scheduled_for=scheduled_for)
            from .usage import reserve_usage
            provider, units = _usage_request(handler, data, config)
            reserve_usage(job=job, provider=provider, units=units)
            AuditEvent.objects.create(organization_id=job.organization_id, project_id=job.project_id,
                actor=actor, event_type=AuditEventType.JOB_QUEUED,
                details={"job_id": job.pk, "retry_of": job.retry_of_id})
            transaction.on_commit(lambda job_id=job.pk: dispatch_pending(job_id))
    return job


def dispatch_pending(job_id, *, stale_after=None):
    from .tasks import (collect_search_console_coverage_task, execute_ai_text_task, execute_crawl_job_task,
                         execute_job_task, execute_performance_task, execute_topics_task,
                         sync_ga4_landing_task, sync_search_console_task, verify_project_origin_task,
                           execute_research_task, execute_content_generation_task, execute_visibility_sample_task,
                             execute_bot_log_import_task, execute_static_link_collection_task, execute_passive_header_collection_task,
                               execute_passive_tls_collection_task, execute_passive_resource_collection_task,
                                  execute_passive_redirect_collection_task, execute_competitor_collection_task,
                                      execute_competitor_synthesis_task, execute_competitor_topics_task, execute_competitor_headings_synthesis_task, execute_passive_http_redirect_collection_task,
                                          execute_passive_redirect_chain_collection_task, execute_competitor_schema_collection_task,
                                              execute_competitor_links_collection_task, execute_competitor_page_collection_task,
                                                  execute_competitor_page_headings_collection_task, execute_competitor_page_destinations_collection_task, execute_competitor_page_dates_collection_task, execute_competitor_page_formats_collection_task, execute_competitor_lab_collection_task)

    organization_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        job = JobRun.objects.select_for_update(no_key=True).filter(
            pk=job_id, organization_id=organization_id,
        ).first()
        if job is None or job.status != JobStatus.QUEUED or (
            job.dispatched_at is not None and (stale_after is None or job.dispatched_at > stale_after)
        ):
            return False
        if job.handler in {"classify_competitor_heading_topics", "synthesize_competitor_pair", "synthesize_competitor_headings_pair"}:
            from .competitor_synthesis_job import _denial, _finish
            if _denial(job):
                _finish(job.pk)
                return False
        if job.handler in {"collect_competitor_root", "collect_competitor_schema_root", "collect_competitor_links_root", "collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats", "collect_competitor_lighthouse"}:
            from .competitor_collection import _denial, _finish
            if _denial(job):
                _finish(job.pk)
                return False
        if job.handler == "sample_ai_visibility":
            from .visibility_collection import _denial, _finish
            if _denial(job):
                _finish(job.pk)
                return False
        if job.handler == "verify_authority_link_source":
            from .authority_link_collection import _denial, _finish
            if _denial(job):
                _finish(job.pk)
                return False
        if job.handler in {"collect_passive_headers", "collect_passive_tls", "collect_passive_resources", "collect_passive_redirects", "collect_passive_http_redirects", "collect_passive_redirect_chain"}:
            from .passive_header_collection import _denial, _finish
            if _denial(job):
                _finish(job.pk)
                return False
        if JobCancellation.objects.filter(job=job).exists():
            job.status = JobStatus.CANCELLED
            job.save(update_fields=["status", "updated_at"])
            from .usage import settle_usage
            if hasattr(job, "usage"):
                transaction.on_commit(lambda: settle_usage(job=job, actual_units=0))
            return False
        try:
            require_project_action(project=job.project, user=job.actor, action=_required_action(job.handler))
        except PermissionDenied:
            job.status = JobStatus.CANCELLED
            job.error_category = "actor_revoked"
            job.save(update_fields=["status", "error_category", "updated_at"])
            from .usage import settle_usage
            if hasattr(job, "usage"):
                transaction.on_commit(lambda: settle_usage(job=job, actual_units=0))
            return False
        from .usage import usage_denial
        denied = usage_denial(job=job)
        if denied:
            job.status = JobStatus.CANCELLED
            job.error_category = denied
            job.save(update_fields=["status", "error_category", "updated_at"])
            if hasattr(job, "usage"):
                from .usage import settle_usage
                transaction.on_commit(lambda: settle_usage(job=job, actual_units=0))
            return False
        if job.handler == "import_bot_logs":
            from .bot_log_import import source_current
            if not source_current(job):
                job.status = JobStatus.CANCELLED
                job.error_category = "source_or_actor_revoked"
                job.save(update_fields=["status", "error_category", "updated_at"])
                from .usage import settle_usage
                transaction.on_commit(lambda: settle_usage(job=job, actual_units=0))
                return False
        retry_after = getattr(getattr(job, "search_console_import_state", None), "retry_after", None)
        if retry_after is not None and retry_after > timezone.now():
            return False
        try:
            if job.handler == "crawl_site":
                task, queue = execute_crawl_job_task, "crawl"
            elif job.handler == "collect_competitor_root":
                task, queue = execute_competitor_collection_task, "crawl"
            elif job.handler == "collect_competitor_lighthouse":
                task, queue = execute_competitor_lab_collection_task, "audit"
            elif job.handler == "collect_competitor_page_formats":
                task, queue = execute_competitor_page_formats_collection_task, "crawl"
            elif job.handler == "collect_competitor_page_dates":
                task, queue = execute_competitor_page_dates_collection_task, "crawl"
            elif job.handler == "collect_competitor_page_destinations":
                task, queue = execute_competitor_page_destinations_collection_task, "crawl"
            elif job.handler == "collect_competitor_page_headings":
                task, queue = execute_competitor_page_headings_collection_task, "crawl"
            elif job.handler == "collect_competitor_page":
                task, queue = execute_competitor_page_collection_task, "crawl"
            elif job.handler == "collect_competitor_links_root":
                task, queue = execute_competitor_links_collection_task, "crawl"
            elif job.handler == "collect_competitor_schema_root":
                task, queue = execute_competitor_schema_collection_task, "crawl"
            elif job.handler == "classify_competitor_heading_topics":
                task, queue = execute_competitor_topics_task, "ai"
            elif job.handler == "synthesize_competitor_headings_pair":
                task, queue = execute_competitor_headings_synthesis_task, "ai"
            elif job.handler == "synthesize_competitor_pair":
                task, queue = execute_competitor_synthesis_task, "ai"
            elif job.handler == "collect_passive_headers":
                task, queue = execute_passive_header_collection_task, "audit"
            elif job.handler == "collect_passive_tls":
                task, queue = execute_passive_tls_collection_task, "audit"
            elif job.handler == "collect_passive_resources":
                task, queue = execute_passive_resource_collection_task, "audit"
            elif job.handler == "collect_passive_redirects":
                task, queue = execute_passive_redirect_collection_task, "audit"
            elif job.handler == "collect_passive_http_redirects":
                task, queue = execute_passive_http_redirect_collection_task, "audit"
            elif job.handler == "collect_passive_redirect_chain":
                task, queue = execute_passive_redirect_chain_collection_task, "audit"
            elif job.handler == "verify_authority_link_source":
                task, queue = execute_static_link_collection_task, "crawl"
            elif job.handler == "verify_project_origin":
                task, queue = verify_project_origin_task, "audit"
            elif job.handler == "discover_topics":
                task, queue = execute_topics_task, "default"
            elif job.handler == "sync_search_console":
                task, queue = sync_search_console_task, "default"
            elif job.handler == "sync_ga4_landing":
                task, queue = sync_ga4_landing_task, "default"
            elif job.handler == "collect_search_console_coverage":
                task, queue = collect_search_console_coverage_task, "default"
            elif job.handler == "audit_performance":
                task, queue = execute_performance_task, "audit"
            elif job.handler == "ai_text":
                task, queue = execute_ai_text_task, "ai"
            elif job.handler == "research_topic":
                task, queue = execute_research_task, "ai"
            elif job.handler == "generate_content":
                task, queue = execute_content_generation_task, "ai"
            elif job.handler == "sample_ai_visibility":
                task, queue = execute_visibility_sample_task, "ai"
            elif job.handler == "analyze_repository":
                from .tasks import analyze_repository_task
                task, queue = analyze_repository_task, "repository"
            elif job.handler == "collect_serp":
                from .tasks import collect_serp_task
                task, queue = collect_serp_task, "default"
            elif job.handler == "sync_yandex_webmaster":
                from .tasks import sync_yandex_task
                task, queue = sync_yandex_task, "default"
            elif job.handler == "import_bot_logs":
                task, queue = execute_bot_log_import_task, "default"
            else:
                task, queue = execute_job_task, "default"
            task.apply_async(args=[job.pk], queue=queue, task_id=f"job-{job.pk}", retry=False)
        except (OperationalError, OSError, TimeoutError):
            job.dispatch_error = "broker_unavailable"
            job.save(update_fields=["dispatch_error", "updated_at"])
            return False
        job.dispatched_at = timezone.now()
        job.dispatch_error = ""
        job.save(update_fields=["dispatched_at", "dispatch_error", "updated_at"])
    return True


def reconcile_dispatch(*, limit=100, stale_seconds=60):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 30:
        raise ValidationError("Invalid dispatch reconciliation limit.")
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    pending_ids = list(JobRun.objects.filter(status=JobStatus.QUEUED).filter(
        Q(dispatched_at__isnull=True) | Q(dispatched_at__lte=cutoff)
    ).order_by("created_at", "pk").values_list("pk", flat=True)[:limit])
    return sum(dispatch_pending(pk, stale_after=cutoff) for pk in pending_ids)


def execute_job(job_id):
    if JobRun.objects.filter(pk=job_id, handler="analyze_repository").exists():
        from .repository_analysis import execute_analysis
        return execute_analysis(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_serp").exists():
        from .serp import execute_observation
        return execute_observation(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_competitor_lighthouse").exists():
        from .competitor_lab_collection import execute_competitor_lab_collection
        return execute_competitor_lab_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_competitor_page_formats").exists():
        from .competitor_page_formats_collection import execute_competitor_page_formats_collection
        return execute_competitor_page_formats_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_competitor_page_dates").exists():
        from .competitor_page_dates_collection import execute_competitor_page_dates_collection
        return execute_competitor_page_dates_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_competitor_page_destinations").exists():
        from .competitor_page_destinations_collection import execute_competitor_page_destinations_collection
        return execute_competitor_page_destinations_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_competitor_page_headings").exists():
        from .competitor_page_headings_collection import execute_competitor_page_headings_collection
        return execute_competitor_page_headings_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_competitor_page").exists():
        from .competitor_page_collection import execute_competitor_page_collection
        return execute_competitor_page_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_competitor_links_root").exists():
        from .competitor_links_collection import execute_competitor_links_collection
        return execute_competitor_links_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_competitor_schema_root").exists():
        from .competitor_schema_collection import execute_competitor_schema_collection
        return execute_competitor_schema_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_passive_redirect_chain").exists():
        from .passive_redirect_chain_collection import execute_passive_redirect_chain_collection
        return execute_passive_redirect_chain_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_passive_http_redirects").exists():
        from .passive_http_redirect_collection import execute_passive_http_redirect_collection
        return execute_passive_http_redirect_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="classify_competitor_heading_topics").exists():
        from .competitor_topics_job import execute_competitor_topics
        return execute_competitor_topics(job_id)
    if JobRun.objects.filter(pk=job_id, handler="synthesize_competitor_headings_pair").exists():
        from .competitor_headings_synthesis_job import execute_competitor_headings_synthesis
        return execute_competitor_headings_synthesis(job_id)
    if JobRun.objects.filter(pk=job_id, handler="synthesize_competitor_pair").exists():
        from .competitor_synthesis_job import execute_competitor_synthesis
        return execute_competitor_synthesis(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_competitor_root").exists():
        from .competitor_collection import execute_competitor_collection
        return execute_competitor_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_passive_redirects").exists():
        from .passive_redirect_collection import execute_passive_redirect_collection
        return execute_passive_redirect_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_passive_resources").exists():
        from .passive_resource_collection import execute_passive_resource_collection
        return execute_passive_resource_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_passive_tls").exists():
        from .passive_tls_collection import execute_passive_tls_collection
        return execute_passive_tls_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_passive_headers").exists():
        from .passive_header_collection import execute_passive_header_collection
        return execute_passive_header_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="verify_authority_link_source").exists():
        from .authority_link_collection import execute_static_link_collection
        return execute_static_link_collection(job_id)
    if JobRun.objects.filter(pk=job_id, handler="sync_yandex_webmaster").exists():
        from integrations.yandex_sync import execute_sync
        return execute_sync(job_id)
    if JobRun.objects.filter(pk=job_id, handler="import_yandex_webmaster_csv").exists():
        from integrations.yandex_webmaster import execute_import
        return execute_import(job_id)
    if JobRun.objects.filter(pk=job_id, handler="import_bot_logs").exists():
        from .bot_log_import import execute_bot_log_import
        return execute_bot_log_import(job_id)
    if JobRun.objects.filter(pk=job_id, handler="sample_ai_visibility").exists():
        from .visibility_collection import execute_visibility_sample
        return execute_visibility_sample(job_id)
    if JobRun.objects.filter(pk=job_id, handler="generate_content").exists():
        from .content_generation import execute_content_generation
        return execute_content_generation(job_id)
    if JobRun.objects.filter(pk=job_id, handler="research_topic").exists():
        from .research import execute_research
        return execute_research(job_id)
    if JobRun.objects.filter(pk=job_id, handler="crawl_site").exists():
        from .crawler import execute_crawl_job
        return execute_crawl_job(job_id)
    if JobRun.objects.filter(pk=job_id, handler="verify_project_origin").exists():
        from .security import execute_origin_verification
        return execute_origin_verification(job_id)
    if JobRun.objects.filter(pk=job_id, handler="import_search_console_csv").exists():
        from integrations.search_console import execute_search_console_csv_import
        return execute_search_console_csv_import(job_id)
    if JobRun.objects.filter(pk=job_id, handler="discover_topics").exists():
        from .topic_discovery import execute_topic_discovery
        return execute_topic_discovery(job_id)
    if JobRun.objects.filter(pk=job_id, handler="sync_search_console").exists():
        from integrations.search_console_sync import execute_search_console_sync
        return execute_search_console_sync(job_id)
    if JobRun.objects.filter(pk=job_id, handler="sync_ga4_landing").exists():
        from integrations.ga4_sync import execute_ga4_landing_sync
        return execute_ga4_landing_sync(job_id)
    if JobRun.objects.filter(pk=job_id, handler="collect_search_console_coverage").exists():
        from integrations.search_console_coverage_job import execute_search_console_coverage
        return execute_search_console_coverage(job_id)
    if JobRun.objects.filter(pk=job_id, handler="audit_performance").exists():
        from .performance_job import execute_performance_audit
        return execute_performance_audit(job_id)
    if JobRun.objects.filter(pk=job_id, handler="ai_text").exists():
        from .ai_text import execute_ai_text
        return execute_ai_text(job_id)
    organization_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return False
    cancelled = False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        job = JobRun.objects.select_for_update(no_key=True).filter(
            pk=job_id, organization_id=organization_id,
        ).first()
        if job is None or job.status != JobStatus.QUEUED:
            return False
        if JobCancellation.objects.filter(job=job).exists():
            job.status = JobStatus.CANCELLED
            job.save(update_fields=["status", "updated_at"])
            cancelled = True
    if not cancelled:
        try:
            run_diagnostic(job)
        except PermissionDenied:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=organization_id)
                current = JobRun.objects.select_for_update(no_key=True).get(pk=job.pk)
                current.status = JobStatus.CANCELLED
                current.error_category = "actor_revoked"
                current.save(update_fields=["status", "error_category", "updated_at"])
        except Exception:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=organization_id)
                current = JobRun.objects.select_for_update(no_key=True).get(pk=job.pk)
                if current.status != JobStatus.QUEUED:
                    return False
                current.status = JobStatus.RUNNING
                current.save(update_fields=["status", "updated_at"])
                current.status = JobStatus.FAILED
                current.error_category = "handler_failed"
                current.save(update_fields=["status", "error_category", "updated_at"])
    from .usage import settle_usage
    if hasattr(job, "usage"):
        settle_usage(job=job, actual_units=0)
    return True


def cancel_job(*, job, actor):
    require_project_action(project=job.project, user=actor, action=_required_action(job.handler))
    with transaction.atomic():
        current = JobRun.objects.get(pk=job.pk)
        if current.status == JobStatus.CANCELLED:
            return current, False, False
        if current.status not in LEGAL_TRANSITIONS:
            raise ValidationError("This job already finished and cannot be cancelled.")
        request, created = JobCancellation.objects.get_or_create(job=current, defaults={"requested_by": actor})
        if created:
            AuditEvent.objects.create(organization_id=current.organization_id, project_id=current.project_id,
                actor=actor, event_type=AuditEventType.JOB_CANCEL_REQUESTED, details={"job_id": current.pk})
        try:
            with transaction.atomic():
                current = JobRun.objects.select_for_update(nowait=True, no_key=True).get(pk=job.pk)
                if current.status == JobStatus.QUEUED:
                    current.status = JobStatus.CANCELLED
                    current.save(update_fields=["status", "updated_at"])
                    if current.handler == "sample_ai_visibility":
                        from .visibility_schedule import finish_scheduled_occurrence
                        finish_scheduled_occurrence(current)
                    from .usage import settle_usage
                    if hasattr(current, "usage"):
                        transaction.on_commit(lambda: settle_usage(job=current, actual_units=0))
                elif current.status not in LEGAL_TRANSITIONS and current.status != JobStatus.CANCELLED:
                    raise ValidationError("This job already finished and cannot be cancelled.")
        except DatabaseError:
            return current, created, True
    return current, created, current.status != JobStatus.CANCELLED


def retry_job(*, job, actor, idempotency_key):
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=job.organization_id)
        current = JobRun.objects.select_for_update().select_related("project").get(pk=job.pk)
        require_project_action(project=current.project, user=actor, action=_required_action(current.handler))
        if current.status not in {JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.PARTIALLY_SUCCEEDED}:
            raise ValidationError("Only failed, cancelled or partial jobs can be retried.")
        if current.handler == "analyze_repository":
            raise ValidationError("Repository analysis requires a fresh explicit source selection; cleanup must finish before another attempt.")
        if current.handler == "collect_serp":
            raise ValidationError("Paid SERP observations require a fresh explicit selection; unknown outcomes are never retried automatically.")
        if current.handler == "sync_yandex_webmaster":
            raise ValidationError("Yandex sync requires a fresh explicit source/window selection.")
        if current.handler in {"import_search_console_csv", "import_bot_logs", "import_yandex_webmaster_csv"}:
            raise ValidationError("Source imports require a new source upload instead of generic retry.")
        if current.handler == "discover_topics":
            raise ValidationError("Topic discovery requires a fresh source selection instead of generic retry.")
        if current.handler in {"classify_competitor_heading_topics", "synthesize_competitor_pair", "synthesize_competitor_headings_pair", "collect_competitor_root", "collect_competitor_schema_root", "collect_competitor_links_root", "collect_competitor_page", "collect_competitor_page_headings", "collect_competitor_page_destinations", "collect_competitor_page_dates", "collect_competitor_page_formats", "collect_competitor_lighthouse", "collect_passive_headers", "collect_passive_tls", "collect_passive_resources", "collect_passive_redirects", "collect_passive_http_redirects", "collect_passive_redirect_chain", "verify_authority_link_source", "research_topic", "generate_content", "sample_ai_visibility"}:
            raise ValidationError("Source-grounded research and drafts require fresh source/model selection instead of generic retry.")
        if current.handler == "sync_search_console":
            raise ValidationError("Search Console requires a fresh authorized sync selection instead of generic retry.")
        if current.handler == "sync_ga4_landing":
            raise ValidationError("GA4 requires a fresh authorized source selection instead of generic retry.")
        if current.handler == "audit_performance":
            raise ValidationError("Performance audits require fresh source selection instead of generic retry.")
        return queue_job(project=current.project, actor=actor, handler=current.handler,
                         input_snapshot=current.input_snapshot, config_snapshot=current.config_snapshot,
                         idempotency_key=idempotency_key, retry_of=current)


def transition(job, target):
    with transaction.atomic():
        current = JobRun.objects.select_for_update(no_key=True).get(pk=job.pk)
        if target not in LEGAL_TRANSITIONS.get(current.status, set()):
            raise ValidationError("Invalid job status transition.")
        require_project_action(project=current.project, user=current.actor, action=_required_action(current.handler))
        current.status = target
        current.save(update_fields=["status", "updated_at"])
    return current


def run_diagnostic(job):
    if not settings.DEBUG:
        raise PermissionDenied
    # ponytail: diagnostic stages commit atomically; real long handlers need per-stage commits/leases for live progress (P04-05).
    with transaction.atomic():
        job = transition(job, JobStatus.RUNNING)
        if job.handler != "diagnostic_probe":
            raise PermissionDenied
        output, partial = _diagnostic_probe(job.input_snapshot)
        JobStep.objects.create(job=job, sequence=1, name="Validate input", status=JobStep.Status.SUCCEEDED,
                               progress_percent=50, output=output)
        if JobCancellation.objects.filter(job=job).exists():
            job.status = JobStatus.CANCELLED
            job.output = {**output, "cancelled_after_step": 1}
            job.save(update_fields=["status", "output", "updated_at"])
            return job
        from .usage import usage_denial
        denied = usage_denial(job=job)
        if denied:
            job.status = JobStatus.CANCELLED
            job.error_category = denied
            job.save(update_fields=["status", "error_category", "updated_at"])
            return job
        try:
            require_project_action(project=job.project, user=job.actor, action=Action.LAUNCH_JOB)
        except PermissionDenied:
            job.status = JobStatus.CANCELLED
            job.error_category = "actor_revoked"
            job.save(update_fields=["status", "error_category", "updated_at"])
            return job
        JobStep.objects.create(job=job, sequence=2, name="Synthetic observation",
                               status=JobStep.Status.FAILED if partial else JobStep.Status.SUCCEEDED,
                               progress_percent=100, error_category="synthetic_partial" if partial else "",
                               output={"observation": "partial" if partial else "complete"})
        job = transition(job, JobStatus.PARTIALLY_SUCCEEDED if partial else JobStatus.SUCCEEDED)
        job.output = {**output, "partial": partial}
        job.save(update_fields=["output", "updated_at"])
    return job
