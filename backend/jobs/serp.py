"""P11-02: provider observations, distinct from webmaster average position."""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit

from cryptography.fernet import InvalidToken
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from integrations.serp_models import SerpConfiguration
from integrations.oauth import _verified
from providers.services import _provider_cipher
from tenancy.models import Organization, Project, normalize_origin
from tenancy.services import Action, project_has_origin, require_project_action
from .models import JobCancellation, JobRun, JobSchedule, JobStatus, JobStep
from .serp_transport import SerpError, collect_serp
from .usage import require_billable_access, settle_usage, usage_denial

HANDLER = "collect_serp"
METHOD = "dataforseo-google-top10-v1"
STAGE = "Attempt one paid SERP observation"


class SerpCapacityError(ValidationError):
    """A shared provider slot can be retried later without renewing authorization."""


def money(value):
    if type(value) is not str or not re.fullmatch(r"(?:0|[1-9][0-9]{0,3})(?:\.[0-9]{1,6})?", value):
        raise ValidationError("Use a bounded USD decimal amount.")
    amount = Decimal(value)
    if not Decimal("0") < amount <= Decimal("1000"):
        raise ValidationError("Choose a positive exposure no greater than USD1000.")
    return amount


def validate_input(data):
    if type(data) is not dict or set(data) != {"engine", "query", "location_code", "language_code", "device", "origin", "max_cost_usd"}:
        raise ValidationError("Use exact SERP observation dimensions and exposure.")
    query = data["query"]
    if (data["engine"] != "google" or type(query) is not str or not 1 <= len(query) <= 200
        or query != query.strip() or ":" in query or any(ord(c) < 32 or ord(c) == 127 for c in query)
        or type(data["location_code"]) is not int or not 1 <= data["location_code"] <= 999999999
        or type(data["language_code"]) is not str or not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z]{2,4})?", data["language_code"])
        or data["device"] not in {"desktop", "mobile"} or type(data["origin"]) is not str
        or normalize_origin(data["origin"]) != data["origin"]):
        raise ValidationError("Choose a plain query, reviewed Google dimensions, and an exact project origin. Search operators are unavailable.")
    money(data["max_cost_usd"])


def configuration():
    config = SerpConfiguration.objects.filter(key="primary").first()
    if config is None or not config.enabled or config.reviewed_until <= timezone.now():
        raise ValidationError("SERP provider configuration or pricing review unavailable.")
    return config


def _authority(project, actor, data):
    require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
    if not _verified(actor) or not project_has_origin(project, data["origin"]):
        raise PermissionDenied


def selection(project, actor, data):
    validate_input(data)
    _authority(project, actor, data)
    config = configuration()
    if (str(data["location_code"]) not in config.locations or data["language_code"] not in config.languages
        or config.estimated_task_cost_usd > money(data["max_cost_usd"])):
        raise ValidationError("Refresh supported dimensions and estimated exposure.")
    return {"provider": "dataforseo", "configuration_id": config.pk, "revision": config.revision,
        "estimated_task_cost_usd": str(config.estimated_task_cost_usd), "depth": 10,
        "location_label": config.locations[str(data["location_code"])], "language_label": config.languages[data["language_code"]]}


def validate_job(job, *, current=False):
    validate_input(job.input_snapshot)
    config = job.config_snapshot
    keys = {"provider", "configuration_id", "revision", "estimated_task_cost_usd", "depth", "location_label", "language_label", "budget_month"}
    if (job.handler != HANDLER or job.method_version != METHOD or job.retry_of_id
        or type(config) is not dict or set(config) != keys or config["provider"] != "dataforseo" or config["depth"] != 10
        or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", str(config["budget_month"]))):
        raise ValidationError("Use an immutable explicit SERP selection.")
    money(config["estimated_task_cost_usd"])
    if current:
        frozen = {key: value for key, value in config.items() if key != "budget_month"}
        if selection(job.project, job.actor, job.input_snapshot) != frozen or config["budget_month"] != timezone.now().strftime("%Y-%m"):
            raise ValidationError("Source selection or budget month changed.")
    if job.schedule_id:
        from .serp_schedule import validate_scheduled_job
        validate_scheduled_job(job, current=current)
    elif job.scheduled_for is not None:
        raise ValidationError("Observation time requires its explicit schedule.")


def queue_observation(*, project, actor, data, revision, request_key, schedule=None, scheduled_for=None):
    from .services import queue_job
    validate_input(data)
    if type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,63}", request_key):
        raise ValidationError("Use a bounded observation request key.")
    with transaction.atomic():
        config = SerpConfiguration.objects.select_for_update().get(key="primary")
        Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().select_related("organization").get(pk=project.pk, organization_id=project.organization_id)
        _authority(project, actor, data)
        existing = JobRun.objects.filter(project=project, handler=HANDLER, idempotency_key=request_key).first()
        if existing:
            if (existing.actor_id != actor.pk or existing.input_snapshot != data
                or existing.schedule_id != (schedule.pk if schedule else None) or existing.scheduled_for != scheduled_for):
                raise ValidationError("Request key belongs to another observation.")
            return existing
        require_billable_access(organization=project.organization)
        selected = selection(project, actor, data)
        if type(revision) is not int or revision != selected["revision"]:
            raise ValidationError("Refresh provider configuration before submitting.")
        month = timezone.now().strftime("%Y-%m")
        # Customer-free accounting survives evidence deletion and credential/configuration revisions.
        reserved = config.reserved_exposure_usd if config.budget_month == month else Decimal("0")
        if reserved + money(data["max_cost_usd"]) > config.monthly_exposure_usd:
            raise ValidationError("Platform SERP monthly estimated exposure is exhausted.")
        if JobRun.objects.filter(project=project, handler=HANDLER, input_snapshot=data,
            status__in=[JobStatus.QUEUED, JobStatus.RUNNING]).exists():
            raise ValidationError("This exact observation already has unfinished work.")
        if JobRun.objects.filter(handler=HANDLER, status__in=[JobStatus.QUEUED, JobStatus.RUNNING]).exists():
            raise SerpCapacityError("The shared provider already has unfinished work; wait before another paid request.")
        config.budget_month, config.reserved_exposure_usd = month, reserved + money(data["max_cost_usd"])
        config.save(update_fields=["budget_month", "reserved_exposure_usd", "updated_at"])
        selected["budget_month"] = month
        return queue_job(project=project, actor=actor, handler=HANDLER, input_snapshot=data,
            config_snapshot=selected, idempotency_key=request_key, schedule=schedule, scheduled_for=scheduled_for)


@sensitive_variables()
def credentials(config):
    try:
        values = json.loads(_provider_cipher().decrypt(config.encrypted_credentials[3:].encode()))
        if (not config.encrypted_credentials.startswith("v1:") or type(values) is not list or len(values) != 2
            or any(type(value) is not str or not 1 <= len(value) <= 512
                or any(ord(c) < 33 or ord(c) > 126 for c in value) for value in values) or ":" in values[0]):
            raise ValueError
        return values
    except (InvalidToken, ValidationError, ValueError, TypeError, UnicodeError, RecursionError):
        raise SerpError("credential_unavailable") from None


def _checkpoint(job_id):
    job = JobRun.objects.select_related("project__organization", "actor").get(pk=job_id, handler=HANDLER)
    if job.status != JobStatus.RUNNING or JobCancellation.objects.filter(job=job).exists():
        raise PermissionDenied
    validate_job(job, current=True)
    denied = usage_denial(job=job)
    if denied:
        raise SerpError(denied)
    return job


def _attempt(job_id):
    with transaction.atomic():
        SerpConfiguration.objects.select_for_update().get(key="primary")
        identity = JobRun.objects.values_list("organization_id", flat=True).get(pk=job_id)
        Organization.objects.select_for_update().get(pk=identity)
        job = JobRun.objects.select_for_update(of=("self",)).select_related("project__organization", "actor").get(pk=job_id)
        _checkpoint(job_id)
        if job.steps.exists():
            raise SerpError("request_outcome_unknown")
        JobStep.objects.create(job=job, sequence=1, name=STAGE, status=JobStep.Status.RUNNING,
            output={"reserved_exposure_usd": job.input_snapshot["max_cost_usd"], "reported_cost_usd": None, "provider_task_id": None})


def _reported_cost(payload):
    try:
        value = Decimal(str(payload.get("cost")))
        if not value.is_finite() or not Decimal("0") <= value <= Decimal("1000000"):
            return None
        return str(value)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _url(value):
    if type(value) is not str or len(value) > 1024 or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise ValueError
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError
    return parts


def parse_observation(payload, data):
    try:
        if payload.get("status_code") != 20000 or type(payload.get("tasks")) is not list or len(payload["tasks"]) != 1:
            raise ValueError
        task = payload["tasks"][0]
        if task.get("status_code") != 20000:
            raise SerpError("provider_task_unavailable")
        task_id = task.get("id")
        if type(task_id) is not str or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", task_id):
            raise ValueError
        if type(task.get("result")) is not list or len(task["result"]) != 1:
            raise ValueError
        result, echo = task["result"][0], task.get("data", {})
        for key in ("location_code", "language_code", "device"):
            if echo.get(key) != data[key]:
                raise ValueError
        if (result.get("keyword") != data["query"] or result.get("location_code") != data["location_code"]
            or result.get("language_code") != data["language_code"]):
            raise ValueError
        observed = datetime.strptime(result["datetime"], "%Y-%m-%d %H:%M:%S %z")
        if timezone.is_naive(observed) or observed > timezone.now() + timedelta(minutes=5):
            raise ValueError
        items = result.get("items")
        if type(items) is not list or len(items) > 200:
            raise ValueError
        rows, features, seen = [], set(), set()
        for item in items:
            feature = item.get("type")
            if type(feature) is not str or not re.fullmatch(r"[a-z_]{1,64}", feature):
                raise ValueError
            features.add(feature)
            if feature != "organic":
                continue
            rank = item.get("rank_group")
            if type(rank) is not int or not 1 <= rank <= 200 or rank in seen:
                raise ValueError
            seen.add(rank)
            if rank > 10:
                continue
            absolute = item.get("rank_absolute")
            if type(absolute) is not int or not 1 <= absolute <= 1000:
                raise ValueError
            url = item.get("url")
            parts = _url(url)
            rows.append({"rank_group": rank, "rank_absolute": absolute, "url": url,
                "domain": parts.hostname.lower(), "feature": feature,
                "matches_origin": normalize_origin(f"{parts.scheme}://{parts.netloc}") == data["origin"]})
        rows.sort(key=lambda row: row["rank_group"])
        output = {"method": METHOD, "provider": "dataforseo", "provider_task_id": task_id,
            "observed_at": observed.isoformat(), "collected_at": timezone.now().isoformat(),
            "dimensions": {key: data[key] for key in ("engine", "query", "location_code", "language_code", "device", "origin")},
            "os": "windows" if data["device"] == "desktop" else "android", "depth": 10,
            "coverage": "provider_returned_top10_organic_only_not_universal_or_personalized_rank",
            "not_found_means": "not_observed_in_returned_top10_not_unranked", "backfill": False,
            "features": sorted(features), "rows": rows, "reported_cost_usd": _reported_cost(payload),
            "source_sha256": sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()}
        if len(json.dumps(output).encode()) > 24576:
            raise ValueError
        return output
    except SerpError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        raise SerpError("malformed_response") from None


def _finish(job_id, *, output=None, error="", cost=None):
    with transaction.atomic():
        config = SerpConfiguration.objects.select_for_update().get(key="primary")
        identity = JobRun.objects.values_list("organization_id", flat=True).get(pk=job_id)
        Organization.objects.select_for_update().get(pk=identity)
        job = JobRun.objects.select_for_update(of=("self",)).select_related("project__organization", "actor").get(pk=job_id)
        if job.status != JobStatus.RUNNING:
            return False
        step = job.steps.filter(sequence=1).first()
        if cost is not None and Decimal(cost) > money(job.input_snapshot["max_cost_usd"]):
            config.enabled = False
            config.revision += 1
            config.save()
            error = "reported_cost_exceeded_estimate"
        try:
            _authority(job.project, job.actor, job.input_snapshot)
            denied = usage_denial(job=job)
        except PermissionDenied:
            denied = "actor_or_origin_revoked"
        cancelled = JobCancellation.objects.filter(job=job).exists() or bool(denied)
        job.output = output if output and not cancelled else {}
        job.error_category = (denied or "cancelled") if cancelled else error
        job.status = JobStatus.CANCELLED if cancelled else JobStatus.FAILED if error or not output else JobStatus.SUCCEEDED
        job.save(update_fields=["status", "output", "error_category", "updated_at"])
        if step:
            step.status = JobStep.Status.SUCCEEDED if output else JobStep.Status.FAILED
            step.progress_percent = 100
            step.error_category = job.error_category
            step.output = {**step.output, "reported_cost_usd": cost,
                "provider_task_id": output["provider_task_id"] if output else None}
            step.save()
        if job.schedule_id and (job.status != JobStatus.SUCCEEDED or cost is None):
            JobSchedule.objects.filter(pk=job.schedule_id).update(enabled=False,
                last_error_category=(job.error_category or "provider_cost_unknown")[:40])
        if hasattr(job, "usage"):
            settle_usage(job=job, actual_units=int(step is not None))
        return job.status == JobStatus.SUCCEEDED


@sensitive_variables()
def execute_observation(job_id):
    from .crawler import _crawl_execution_lock
    with _crawl_execution_lock(job_id) as acquired:
        if not acquired:
            return False
        with transaction.atomic():
            identity = JobRun.objects.values_list("organization_id", flat=True).get(pk=job_id, handler=HANDLER)
            Organization.objects.select_for_update().get(pk=identity)
            job = JobRun.objects.select_for_update().get(pk=job_id)
            if job.status != JobStatus.QUEUED:
                return False
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
        cost = None
        try:
            job = _checkpoint(job_id)
            secret = credentials(configuration())
            payload = collect_serp(job.input_snapshot, secret, checkpoint=lambda: _checkpoint(job_id), before_send=lambda: _attempt(job_id))
            cost = _reported_cost(payload)
            output = parse_observation(payload, job.input_snapshot)
            return _finish(job_id, output=output, cost=cost)
        except (PermissionDenied, ObjectDoesNotExist):
            return _finish(job_id, error="actor_or_source_revoked", cost=cost)
        except ValidationError:
            return _finish(job_id, error="selection_changed", cost=cost)
        except SerpError as error:
            return _finish(job_id, error=error.category, cost=cost)


def recover_observations(*, limit=20):
    from .crawler import _crawl_execution_lock
    ids = list(JobRun.objects.filter(handler=HANDLER, status=JobStatus.RUNNING,
        updated_at__lt=timezone.now() - timedelta(minutes=3)).order_by("pk").values_list("pk", flat=True)[:limit])
    recovered = 0
    for job_id in ids:
        with _crawl_execution_lock(job_id) as acquired:
            if acquired:
                _finish(job_id, error="request_outcome_unknown")
                recovered += 1
    return recovered
