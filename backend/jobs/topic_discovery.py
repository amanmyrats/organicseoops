import json
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from integrations.models import IntegrationConnection
from integrations.query_growth import query_growth_signals
from integrations.services import require_connection_capability
from tenancy.models import Organization, Project, ProjectConfiguration
from tenancy.services import Action, require_project_action

from .crawler import _crawl_execution_lock
from .feeds import collect_project_feed
from .news import collect_project_news, current_news_selection, validate_news_selection
from .models import JobCancellation, JobRun, JobStatus, JobStep, TopicCandidateSnapshot, UsageReservation
from .topic_candidates import normalize_topic_candidates
from .usage import settle_usage, usage_denial


METHOD_VERSION = "topic-discovery-v2"
MAX_STAGE_ITEMS = 20
MAX_SNAPSHOT_CANDIDATES = 40


def validate_topic_discovery_input(data):
    if type(data) is not dict or set(data) - {"news"} != {
        "feeds", "connection_id", "previous_import_id", "current_import_id",
    }:
        raise ValidationError("Check the topic discovery source selection.")
    feeds = data["feeds"]
    if (type(feeds) is not list or len(feeds) > 5 or any(not isinstance(url, str) for url in feeds)
        or len(feeds) != len(set(feeds))):
        raise ValidationError("Choose up to five unique feed URLs.")
    for url in feeds:
        if not isinstance(url, str) or len(url) > 512:
            raise ValidationError("Choose safe feed URLs.")
        try:
            parsed = urlsplit(url)
            valid = (parsed.scheme == "https" and bool(parsed.hostname) and parsed.port in (None, 443)
                     and parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment)
        except ValueError:
            valid = False
        if not valid:
            raise ValidationError("Choose safe feed URLs.")
    ids = (data["connection_id"], data["previous_import_id"], data["current_import_id"])
    if any(value is not None and (type(value) is not int or value < 1) for value in ids):
        raise ValidationError("Choose valid source imports.")
    if any(value is None for value in ids) and any(value is not None for value in ids):
        raise ValidationError("Query comparisons require one connection and two imports.")
    if data.get("news") is not None:
        validate_news_selection(data["news"])
    if not feeds and ids[0] is None and data.get("news") is None:
        raise ValidationError("Select at least one configured topic source.")
    return data


def queue_topic_discovery(*, project, actor, feeds, connection=None, previous_import_id=None,
                          current_import_id=None, idempotency_key, news=None):
    data = validate_topic_discovery_input({
        "feeds": feeds, "connection_id": connection.pk if connection is not None else None,
        "previous_import_id": previous_import_id, "current_import_id": current_import_id,
        **({"news": news} if news is not None else {}),
    })
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.LAUNCH_JOB)
        config = ProjectConfiguration.objects.filter(project=project).first()
        if data["feeds"] and (config is None or not set(data["feeds"]) <= set(config.rss_feed_urls)):
            raise ValidationError("Feeds must be configured for this project.")
        if news is not None:
            current_news_selection(project, actor, news)
        if connection is not None:
            connection = IntegrationConnection.objects.filter(pk=connection.pk, project=project).first()
            if connection is None:
                raise PermissionDenied
            query_growth_signals(project=project, user=actor, connection=connection,
                                 previous_import_id=previous_import_id, current_import_id=current_import_id)
        from .services import queue_job
        return queue_job(
            project=project, actor=actor, handler="discover_topics", input_snapshot=data,
            config_snapshot={"configuration_revision": config.revision if config else 0,
                             "market": config.target_country if config else "",
                             "languages": config.target_languages if config else []},
            idempotency_key=idempotency_key,
        )


def _denial(job, *, check_query=False):
    if JobCancellation.objects.filter(job=job).exists():
        return "cancelled"
    try:
        require_project_action(project=job.project, user=job.actor, action=Action.LAUNCH_JOB)
    except PermissionDenied:
        return "actor_revoked"
    denied = usage_denial(job=job)
    if denied:
        return denied
    config = ProjectConfiguration.objects.filter(project=job.project).first()
    if (config.revision if config else 0) != job.config_snapshot.get("configuration_revision"):
        return "source_scope_changed"
    if job.input_snapshot["feeds"] and (
        config is None or not set(job.input_snapshot["feeds"]) <= set(config.rss_feed_urls)
    ):
        return "source_scope_revoked"
    connection_id = job.input_snapshot["connection_id"]
    if job.input_snapshot.get("news") is not None:
        try:
            current_news_selection(job.project, job.actor, job.input_snapshot["news"])
        except (PermissionDenied, ValidationError):
            return "source_scope_revoked"
    if check_query and connection_id is not None:
        connection = IntegrationConnection.objects.filter(pk=connection_id, project=job.project).first()
        if connection is None:
            return "source_scope_revoked"
        try:
            require_connection_capability(connection, "query_metrics", dimensions=["query"])
        except ValidationError:
            return "source_scope_revoked"
    return ""


def _discard_revoked_query(job):
    if job.input_snapshot["connection_id"] is None or not _denial(job, check_query=True):
        return
    step = JobStep.objects.filter(job=job, name="Compare first-party queries", status=JobStep.Status.SUCCEEDED).first()
    if step is not None:
        step.status = JobStep.Status.FAILED
        step.error_category = "source_scope_revoked"
        step.output = {"state": "failed", "error": "source_scope_revoked"}
        step.save(update_fields=["status", "error_category", "output"])


def _step_count(job):
    return sum(step.output.get("state") != "not_collected" for step in JobStep.objects.filter(job=job, name__in=[
        "Compare first-party queries", "Collect configured feed", "Collect selected news",
    ]).only("output"))


def _candidate_output(job, steps):
    data = job.input_snapshot
    query = next((step.output for step in steps if step.name == "Compare first-party queries" and step.status == JobStep.Status.SUCCEEDED), None)
    feeds = [step.output for step in steps if step.name == "Collect configured feed" and step.status != JobStep.Status.RUNNING]
    output = normalize_topic_candidates(query_growth=query, feeds=feeds)
    news = next((step.output for step in steps if step.name == "Collect selected news" and step.status != JobStep.Status.RUNNING), None)
    if data.get("news") is not None:
        output["method"] = "topic-candidates-v2"
        output["news"] = {key: value for key, value in (news or {"state": "not_collected"}).items() if key != "items"}
        output["coverage"]["news_state"] = (news or {}).get("state", "not_collected")
        if news and news.get("state") not in {"failed", "not_collected"}:
            normalized = normalize_topic_candidates(feeds=[news])
            for candidate in normalized["candidates"]:
                candidate.update(kind="provider_news_article", provider="gdelt", attribution_url=news["attribution_url"],
                    news_selection=news["selection"], news_as_of=news["as_of"], date_basis="provider_reported_not_verified_publication",
                    market_language=news["market_language"])
            output["candidates"].extend(normalized["candidates"])
            output["coverage"]["source_labels"].append("provider_news_metadata_observation")
    output["coverage"]["truncated"] |= any(step.output.get("truncated", False) or step.output.get("truncated_candidates", False) for step in steps)
    output["coverage"]["truncated"] |= len(output["candidates"]) > MAX_SNAPSHOT_CANDIDATES
    output["coverage"]["query_source_error"] = next((step.error_category for step in steps if step.name == "Compare first-party queries" and step.status == JobStep.Status.FAILED), "")
    output["coverage"]["selected_feeds"] = len(data["feeds"])
    output["coverage"]["market"] = job.config_snapshot["market"]
    output["coverage"]["languages"] = job.config_snapshot["languages"]
    output["query_source"] = ({
        "connection_id": query["connection_id"], "property": query["property"],
        "provider": query["provider"], "previous": query["previous"], "current": query["current"],
        "coverage": query["coverage"],
    } if query else {"state": "not_selected" if data["connection_id"] is None else "unavailable"})
    output["feeds"] = [
        {"url": result["source_feed"], "state": result["state"],
         "collected_at": result.get("collected_at"), "total_seen": result.get("total_seen"),
         "rejected": result.get("rejected"), "truncated": result.get("truncated", False),
         "error": result.get("error", "")}
        for result in feeds
    ]
    output["candidates"] = output["candidates"][:MAX_SNAPSHOT_CANDIDATES]
    failed = bool(output["coverage"]["failed_feeds"] or output["coverage"]["partial_feeds"]
                  or output["coverage"]["query_source_error"] or output["coverage"]["truncated"]
                  or data.get("news") is not None and (news or {}).get("state") != "complete_for_bounded_feed")
    useful = any(step.status == JobStep.Status.SUCCEEDED for step in steps)
    return output, failed, useful


def _stop(job_id, *, category, cancelled=False):
    with transaction.atomic():
        organization_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
        if organization_id is None:
            return False
        Organization.objects.select_for_update().get(pk=organization_id)
        job = JobRun.objects.select_for_update(no_key=True).filter(pk=job_id, handler="discover_topics").first()
        if job is None or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        denied = _denial(job)
        if denied:
            category, cancelled = denied, True
        count = _step_count(job)
        for step in JobStep.objects.filter(job=job, status=JobStep.Status.RUNNING):
            output = {"state": "failed", "error": category}
            if step.name == "Collect configured feed":
                output.update(items=[], source_feed=job.input_snapshot["feeds"][step.sequence - 2])
            step.status = JobStep.Status.FAILED
            step.error_category = category
            step.output = output
            step.save(update_fields=["status", "error_category", "output"])
        useful = JobStep.objects.filter(job=job, status=JobStep.Status.SUCCEEDED).exists()
        output = None
        if useful and not cancelled:
            try:
                output, _failed, useful = _candidate_output(job, list(job.steps.order_by("sequence")))
            except (KeyError, TypeError, ValueError, ValidationError):
                useful = False
        if job.status == JobStatus.QUEUED and not cancelled:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
        job.status = JobStatus.CANCELLED if cancelled else JobStatus.PARTIALLY_SUCCEEDED if useful else JobStatus.FAILED
        job.error_category = category
        job.output = {"attempted_stages": count, "coverage": "partial" if useful else "unavailable"}
        job.save(update_fields=["status", "error_category", "output", "updated_at"])
        if useful and output is not None:
            try:
                with transaction.atomic():
                    TopicCandidateSnapshot.objects.create(
                        job=job, project=job.project, method_version=job.method_version, output=output,
                    )
            except ValidationError:
                job.status = JobStatus.FAILED
                job.error_category = "artifact_invalid"
                job.output = {"attempted_stages": count, "coverage": "unavailable"}
                job.save(update_fields=["status", "error_category", "output", "updated_at"])
        if UsageReservation.objects.filter(job=job, state=UsageReservation.State.RESERVED).exists():
            settle_usage(job=job, actual_units=count)
    return True


def execute_topic_discovery(job_id, *, fetcher_factory=None):
    with _crawl_execution_lock(job_id) as acquired:
        if not acquired:
            return False
        try:
            return _execute(job_id, fetcher_factory=fetcher_factory)
        except Exception:
            return _stop(job_id, category="handler_failed")


def _execute(job_id, *, fetcher_factory):
    organization_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return False
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        if job.handler != "discover_topics" or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return False
        validate_topic_discovery_input(job.input_snapshot)
        denied = _denial(job)
        if not denied and job.status == JobStatus.QUEUED:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
    if denied:
        return _stop(job_id, category=denied, cancelled=True)

    data = job.input_snapshot
    stages = [(1, "Compare first-party queries", None)] if data["connection_id"] is not None else []
    stages.extend((index + 2, "Collect configured feed", url) for index, url in enumerate(data["feeds"]))
    if data.get("news") is not None:
        stages.append((7, "Collect selected news", "news"))
    for sequence, name, url in stages:
        saved = JobStep.objects.filter(job_id=job_id, sequence=sequence).first()
        if saved is not None and saved.status != JobStep.Status.RUNNING:
            continue
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization_id)
            current = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
            denied = _denial(current, check_query=url is None)
            if denied == "source_scope_revoked" and url is None and data["feeds"]:
                JobStep.objects.update_or_create(
                    job=current, sequence=sequence, defaults={
                        "name": name, "status": JobStep.Status.FAILED, "error_category": denied,
                        "output": {"state": "not_collected", "error": denied},
                    },
                )
                current.save(update_fields=["updated_at"])
                continue
            if not denied and saved is None:
                JobStep.objects.create(
                    job=current, sequence=sequence, name=name, status=JobStep.Status.RUNNING,
                    progress_percent=min(99, 100 * _step_count(current) // len(stages)),
                    output={"state": "pending"},
                )
        if denied:
            return _stop(job_id, category=denied, cancelled=True)
        if name == "Collect selected news":
            try:
                def checkpoint():
                    current.refresh_from_db()
                    if _denial(current):
                        raise PermissionDenied
                result = collect_project_news(project=current.project, actor=current.actor, selection=data["news"],
                    as_of=current.created_at, fetcher=fetcher_factory("news") if fetcher_factory is not None else None,
                    checkpoint=checkpoint)
            except PermissionDenied:
                result = {"state": "failed", "error": "source_scope_revoked", "items": []}
            except Exception:
                result = {"state": "failed", "error": "news_unavailable", "items": []}
        elif url is None:
            connection = IntegrationConnection.objects.get(pk=data["connection_id"], project=current.project)
            try:
                result = query_growth_signals(
                    project=current.project, user=current.actor, connection=connection,
                    previous_import_id=data["previous_import_id"], current_import_id=data["current_import_id"],
                )
                result["truncated_candidates"] |= len(result["candidates"]) > MAX_SNAPSHOT_CANDIDATES
                result["candidates"] = result["candidates"][:MAX_SNAPSHOT_CANDIDATES]
            except (ValidationError, PermissionDenied):
                result = {"state": "failed", "error": "source_unavailable"}
        else:
            try:
                result = collect_project_feed(
                    project=current.project, user=current.actor, feed_url=url,
                    fetcher=fetcher_factory(url) if fetcher_factory is not None else None,
                )
            except PermissionDenied:
                result = {"state": "failed", "error": "source_scope_revoked", "items": [], "source_feed": url}
            except Exception:
                result = {"state": "failed", "error": "feed_unavailable", "items": [], "source_feed": url}
            if result["state"] != "failed":
                result["truncated"] |= len(result["items"]) > MAX_STAGE_ITEMS
                if result["truncated"]:
                    result["state"] = "partial"
                result["items"] = result["items"][:MAX_STAGE_ITEMS]
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization_id)
            current = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
            denied = _denial(current, check_query=url is None)
            step = JobStep.objects.select_for_update().get(job=current, sequence=sequence)
            if denied == "source_scope_revoked" and url is None and data["feeds"]:
                step.status = JobStep.Status.FAILED
                step.error_category = denied
                step.output = {"state": "failed", "error": denied}
                step.save(update_fields=["status", "error_category", "output"])
                current.save(update_fields=["updated_at"])
                continue
            step.status = JobStep.Status.FAILED if denied or result.get("state") == "failed" else JobStep.Status.SUCCEEDED
            step.progress_percent = min(99, 100 * _step_count(current) // len(stages))
            step.output = {"state": "unavailable"} if denied else result
            step.error_category = denied or result.get("error", "")[:64]
            step.save(update_fields=["status", "progress_percent", "output", "error_category"])
            current.save(update_fields=["updated_at"])
        if denied:
            return _stop(job_id, category=denied, cancelled=True)

    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        current = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        denied = _denial(current)
        if denied:
            pass
        else:
            _discard_revoked_query(current)
            steps = list(JobStep.objects.filter(job=current).order_by("sequence"))
            output, source_failed, useful = _candidate_output(current, steps)
            current.status = JobStatus.PARTIALLY_SUCCEEDED if source_failed and useful else JobStatus.FAILED if source_failed else JobStatus.SUCCEEDED
            current.error_category = "partial_sources" if source_failed and useful else "sources_unavailable" if source_failed else ""
            current.output = {"candidate_count": len(output["candidates"]), "coverage": output["coverage"], "snapshot_method": current.method_version}
            current.save(update_fields=["status", "error_category", "output", "updated_at"])
            if useful:
                TopicCandidateSnapshot.objects.create(job=current, project=current.project, method_version=current.method_version, output=output)
            if UsageReservation.objects.filter(job=current, state=UsageReservation.State.RESERVED).exists():
                settle_usage(job=current, actual_units=_step_count(current))
    if denied:
        return _stop(job_id, category=denied, cancelled=True)
    return True
