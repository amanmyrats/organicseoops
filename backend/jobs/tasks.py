from celery import shared_task


@shared_task(name="jobs.collect_competitor_lighthouse", ignore_result=True, soft_time_limit=45, time_limit=60,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_competitor_lab_collection_task(job_id):
    from .competitor_lab_collection import execute_competitor_lab_collection
    return execute_competitor_lab_collection(job_id)


@shared_task(name="jobs.collect_competitor_page_formats", ignore_result=True, soft_time_limit=45, time_limit=60,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_competitor_page_formats_collection_task(job_id):
    from .competitor_page_formats_collection import execute_competitor_page_formats_collection
    return execute_competitor_page_formats_collection(job_id)


@shared_task(name="jobs.collect_competitor_page_dates", ignore_result=True, soft_time_limit=45, time_limit=60,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_competitor_page_dates_collection_task(job_id):
    from .competitor_page_dates_collection import execute_competitor_page_dates_collection
    return execute_competitor_page_dates_collection(job_id)


@shared_task(name="jobs.collect_competitor_page_destinations", ignore_result=True, soft_time_limit=45, time_limit=60,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_competitor_page_destinations_collection_task(job_id):
    from .competitor_page_destinations_collection import execute_competitor_page_destinations_collection
    return execute_competitor_page_destinations_collection(job_id)


@shared_task(name="jobs.collect_competitor_page_headings", ignore_result=True, soft_time_limit=45, time_limit=60,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_competitor_page_headings_collection_task(job_id):
    from .competitor_page_headings_collection import execute_competitor_page_headings_collection
    return execute_competitor_page_headings_collection(job_id)


@shared_task(name="jobs.collect_competitor_page", ignore_result=True, soft_time_limit=45, time_limit=60,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_competitor_page_collection_task(job_id):
    from .competitor_page_collection import execute_competitor_page_collection
    return execute_competitor_page_collection(job_id)

@shared_task(name="jobs.collect_competitor_links_root", ignore_result=True, soft_time_limit=45, time_limit=60,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_competitor_links_collection_task(job_id):
    from .competitor_links_collection import execute_competitor_links_collection
    return execute_competitor_links_collection(job_id)


@shared_task(name="jobs.collect_competitor_schema_root", ignore_result=True, soft_time_limit=45, time_limit=60,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_competitor_schema_collection_task(job_id):
    from .competitor_schema_collection import execute_competitor_schema_collection
    return execute_competitor_schema_collection(job_id)


@shared_task(name="jobs.collect_passive_redirect_chain", ignore_result=True, soft_time_limit=25, time_limit=40,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_passive_redirect_chain_collection_task(job_id):
    from .passive_redirect_chain_collection import execute_passive_redirect_chain_collection
    return execute_passive_redirect_chain_collection(job_id)


@shared_task(name="jobs.collect_passive_http_redirects", ignore_result=True, soft_time_limit=25, time_limit=40,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_passive_http_redirect_collection_task(job_id):
    from .passive_http_redirect_collection import execute_passive_http_redirect_collection
    return execute_passive_http_redirect_collection(job_id)


@shared_task(name="jobs.classify_competitor_heading_topics", ignore_result=True, soft_time_limit=90, time_limit=110,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_competitor_topics_task(job_id):
    from .competitor_topics_job import execute_competitor_topics
    return execute_competitor_topics(job_id)


@shared_task(name="jobs.synthesize_competitor_headings_pair", ignore_result=True, soft_time_limit=90, time_limit=110,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_competitor_headings_synthesis_task(job_id):
    from .competitor_headings_synthesis_job import execute_competitor_headings_synthesis
    return execute_competitor_headings_synthesis(job_id)


@shared_task(name="jobs.synthesize_competitor_pair", ignore_result=True, soft_time_limit=90, time_limit=110,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_competitor_synthesis_task(job_id):
    from .competitor_synthesis_job import execute_competitor_synthesis
    return execute_competitor_synthesis(job_id)


@shared_task(name="jobs.collect_competitor_root", ignore_result=True, soft_time_limit=45, time_limit=60,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_competitor_collection_task(job_id):
    from .competitor_collection import execute_competitor_collection
    return execute_competitor_collection(job_id)


@shared_task(name="jobs.collect_passive_redirects", ignore_result=True, soft_time_limit=25, time_limit=40,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_passive_redirect_collection_task(job_id):
    from .passive_redirect_collection import execute_passive_redirect_collection
    return execute_passive_redirect_collection(job_id)


@shared_task(name="jobs.collect_passive_resources", ignore_result=True, soft_time_limit=25, time_limit=40,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_passive_resource_collection_task(job_id):
    from .passive_resource_collection import execute_passive_resource_collection
    return execute_passive_resource_collection(job_id)


@shared_task(name="jobs.collect_passive_tls", ignore_result=True, soft_time_limit=25, time_limit=40,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_passive_tls_collection_task(job_id):
    from .passive_tls_collection import execute_passive_tls_collection
    return execute_passive_tls_collection(job_id)


@shared_task(name="jobs.collect_passive_headers", ignore_result=True, soft_time_limit=25, time_limit=40,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_passive_header_collection_task(job_id):
    from .passive_header_collection import execute_passive_header_collection
    return execute_passive_header_collection(job_id)


@shared_task(name="jobs.send_daily_crux_digest", ignore_result=True, soft_time_limit=75, time_limit=90,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def send_daily_crux_digest_task(delivery_id):
    from .crux_digest_delivery import deliver_daily_crux_digest
    return deliver_daily_crux_digest(delivery_id)


@shared_task(name="jobs.scan_daily_crux_digests", ignore_result=True, soft_time_limit=105, time_limit=120,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def scan_daily_crux_digests_task(after_id=0, through_id=None, day_start=None):
    from .crux_digest_schedule import scan_daily_crux_digests
    return scan_daily_crux_digests(after_id=after_id, through_id=through_id, day_start=day_start)


@shared_task(name="jobs.send_daily_alert_digest", ignore_result=True, soft_time_limit=75, time_limit=90,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def send_daily_alert_digest_task(delivery_id):
    from .alert_digest_delivery import deliver_daily_alert_digest
    return deliver_daily_alert_digest(delivery_id)


@shared_task(name="jobs.scan_daily_alert_digests", ignore_result=True, soft_time_limit=105, time_limit=120,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def scan_daily_alert_digests_task(after_id=0, through_id=None, day_start=None):
    from .alert_digest_schedule import scan_daily_alert_digests
    return scan_daily_alert_digests(after_id=after_id, through_id=through_id, day_start=day_start)


@shared_task(name="jobs.send_weekly_summary", ignore_result=True, soft_time_limit=75, time_limit=90,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def send_weekly_summary_task(delivery_id):
    from .summary_delivery import deliver_weekly_summary
    return deliver_weekly_summary(delivery_id)


@shared_task(name="jobs.scan_weekly_summaries", ignore_result=True, soft_time_limit=105, time_limit=120,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def scan_weekly_summaries_task(after_id=0, through_id=None, week_start=None):
    from .summary_schedule import scan_weekly_summaries
    return scan_weekly_summaries(after_id=after_id, through_id=through_id, week_start=week_start)


@shared_task(name="jobs.verify_authority_link_source", ignore_result=True, soft_time_limit=45, time_limit=60,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_static_link_collection_task(job_id):
    from .authority_link_collection import execute_static_link_collection
    return execute_static_link_collection(job_id)


@shared_task(name="jobs.import_bot_logs", ignore_result=True, soft_time_limit=15, time_limit=30,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_bot_log_import_task(job_id):
    from .bot_log_import import execute_bot_log_import
    return execute_bot_log_import(job_id)


@shared_task(name="jobs.sample_ai_visibility", ignore_result=True, soft_time_limit=45, time_limit=60,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_visibility_sample_task(job_id):
    from .visibility_collection import execute_visibility_sample
    return execute_visibility_sample(job_id)


@shared_task(name="jobs.generate_content", ignore_result=True, soft_time_limit=45, time_limit=60,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_content_generation_task(job_id):
    from .content_generation import execute_content_generation
    return execute_content_generation(job_id)


@shared_task(name="jobs.research_topic", ignore_result=True, soft_time_limit=90, time_limit=110,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_research_task(job_id):
    from .research import execute_research
    return execute_research(job_id)

from .crawler import execute_crawl_job
from .services import execute_job
from .schedules import run_due_schedules
from .recovery import reconcile_diagnostic_jobs
from .renderer import render_page_snapshot
from tenancy.customer_artifact_barrier import ArtifactAdmissionUnavailable
from .security import execute_origin_verification


@shared_task(name="jobs.execute", ignore_result=True, soft_time_limit=15, time_limit=30,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_job_task(job_id):
    return execute_job(job_id)


@shared_task(name="jobs.execute_crawl", ignore_result=True, soft_time_limit=300, time_limit=330,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_crawl_job_task(job_id):
    return execute_crawl_job(job_id)


@shared_task(name="jobs.discover_topics", ignore_result=True, soft_time_limit=60, time_limit=75,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_topics_task(job_id):
    from .topic_discovery import execute_topic_discovery
    return execute_topic_discovery(job_id)


@shared_task(name="jobs.sync_search_console", ignore_result=True, soft_time_limit=100, time_limit=115,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def sync_search_console_task(job_id):
    from integrations.search_console_sync import execute_search_console_sync
    return execute_search_console_sync(job_id)


@shared_task(name="jobs.sync_ga4_landing", ignore_result=True, soft_time_limit=85, time_limit=100,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def sync_ga4_landing_task(job_id):
    from integrations.ga4_sync import execute_ga4_landing_sync
    return execute_ga4_landing_sync(job_id)


@shared_task(name="jobs.collect_search_console_coverage", ignore_result=True, soft_time_limit=60, time_limit=75,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def collect_search_console_coverage_task(job_id):
    from integrations.search_console_coverage_job import execute_search_console_coverage
    return execute_search_console_coverage(job_id)


@shared_task(name="jobs.audit_performance", ignore_result=True, soft_time_limit=115, time_limit=130,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_performance_task(job_id):
    from .performance_job import execute_performance_audit
    return execute_performance_audit(job_id)


@shared_task(name="jobs.ai_text", ignore_result=True, soft_time_limit=45, time_limit=60,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def execute_ai_text_task(job_id):
    from .ai_text import execute_ai_text
    return execute_ai_text(job_id)


@shared_task(name="jobs.execute_render", ignore_result=True, soft_time_limit=30, time_limit=45,
             acks_late=True, reject_on_worker_lost=True, max_retries=8,
             autoretry_for=(ArtifactAdmissionUnavailable,), retry_backoff=10,
             retry_backoff_max=120, retry_jitter=False)
def execute_render_task(snapshot_id):
    return bool(render_page_snapshot(snapshot_id))


@shared_task(name="jobs.verify_project_origin", ignore_result=True, soft_time_limit=15, time_limit=30,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def verify_project_origin_task(job_id):
    return execute_origin_verification(job_id)


@shared_task(name="jobs.schedule_due", ignore_result=True, soft_time_limit=15, time_limit=30,
             acks_late=True, max_retries=0)
def schedule_due_task():
    from integrations.search_console_backfill import advance_search_console_backfills
    from integrations.search_console_schedule import run_due_search_console_schedules
    from .visibility_schedule import run_due_visibility_schedules
    from .serp_schedule import run_due_schedules as run_due_serp_schedules
    return run_due_schedules() + advance_search_console_backfills() + run_due_search_console_schedules() + run_due_visibility_schedules() + run_due_serp_schedules()


@shared_task(name="jobs.reconcile", ignore_result=True, soft_time_limit=15, time_limit=30,
             acks_late=True, max_retries=0)
def reconcile_jobs_task():
    from tenancy.paddle_jobs import recover_paddle_receipts
    from tenancy.customer_snapshot import recover_stale_customer_snapshots
    counts = reconcile_diagnostic_jobs()
    counts["paddle_receipts"] = recover_paddle_receipts()
    counts["customer_exports"] = recover_stale_customer_snapshots()
    return counts


@shared_task(name="jobs.sync_yandex", ignore_result=True, soft_time_limit=90, time_limit=120,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def sync_yandex_task(job_id):
    from integrations.yandex_sync import execute_sync
    return execute_sync(job_id)


@shared_task(name="jobs.collect_serp", ignore_result=True, soft_time_limit=75, time_limit=90,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def collect_serp_task(job_id):
    from .serp import execute_observation
    return execute_observation(job_id)


@shared_task(name="jobs.analyze_repository", ignore_result=True, soft_time_limit=270, time_limit=300,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def analyze_repository_task(job_id):
    from .repository_analysis import execute_analysis
    return execute_analysis(job_id)


@shared_task(name="jobs.recover_repository", ignore_result=True, soft_time_limit=45, time_limit=60,
             acks_late=True, reject_on_worker_lost=True, max_retries=0)
def recover_repository_analysis_task(job_id):
    from .repository_analysis import recover_analysis
    return recover_analysis(job_id)
