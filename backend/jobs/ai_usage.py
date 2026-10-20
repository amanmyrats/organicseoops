import re
from decimal import Decimal, ROUND_UP

from django.utils import timezone

from .models import AIUsageRecord


_SAFE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")


def _safe_id(value):
    return value if type(value) is str and _SAFE_ID.fullmatch(value) else ""


def _tokens(value):
    return value if type(value) is int and 0 <= value <= 100_000_000 else None


def record_ai_attempt(*, job, step):
    config = job.config_snapshot
    data = job.input_snapshot
    if ((job.handler, job.method_version) not in {("classify_competitor_heading_topics", "competitor-heading-topics-v1"), ("synthesize_competitor_pair", "competitor-static-synthesis-v1"), ("synthesize_competitor_headings_pair", "competitor-heading-synthesis-v1"), ("ai_text", "ai-text-v2"), ("research_topic", "research-v1"), ("generate_content", "content-generation-v1"), ("sample_ai_visibility", "visibility-text-collection-v1")}
        or type(config) is not dict or type(data) is not dict
        or any(type(config.get(key)) is not int or config[key] < 1 for key in ("provider_id",))
        or any(type(data.get(key)) is not int or data[key] < 1 for key in ("model_id", "account_id"))):
        return None
    record, _created = AIUsageRecord.objects.get_or_create(job=job, defaults={
        "step": step, "organization_id": job.organization_id, "project_id": job.project_id,
        "provider_id": config["provider_id"], "model_id": data["model_id"], "account_id": data["account_id"],
        "operation_version": job.method_version,
    })
    if record.step_id != step.pk or record.project_id != job.project_id or record.organization_id != job.organization_id:
        raise ValueError("AI usage scope or step changed.")
    return record


def finish_ai_usage(*, job, step, result=None, error="", provider_request_id="", duration_ms=None,
                    input_tokens=None, output_tokens=None):
    record = record_ai_attempt(job=job, step=step)
    if record is None or record.status != AIUsageRecord.Status.ATTEMPTED:
        return record
    record.status = (AIUsageRecord.Status.COMPLETED if result is not None else
                     AIUsageRecord.Status.UNKNOWN if error in {"", "handler_failed", "request_outcome_unknown",
                                                                "provider_unavailable"} else AIUsageRecord.Status.FAILED)
    record.error_category = error or ("request_outcome_unknown" if result is None else "")
    record.provider_request_id = _safe_id(getattr(result, "request_id", None) if result is not None
                                           else provider_request_id)
    record.provider_response_id = _safe_id(getattr(result, "response_id", None)) if result is not None else ""
    record.input_tokens = _tokens(getattr(result, "input_tokens", None) if result is not None else input_tokens)
    record.output_tokens = _tokens(getattr(result, "output_tokens", None) if result is not None else output_tokens)
    record.duration_ms = duration_ms if type(duration_ms) is int and 0 <= duration_ms <= 120_000 else None
    if record.input_tokens is not None and record.output_tokens is not None:
        config = job.config_snapshot
        try:
            estimate = ((record.input_tokens * Decimal(config["input_price_usd_per_million"])
                         + record.output_tokens * Decimal(config["output_price_usd_per_million"]))
                        / Decimal(1_000_000)).quantize(Decimal("0.000001"), rounding=ROUND_UP)
            record.estimated_cost_usd = estimate if estimate.is_finite() and estimate < 1_000_000 else None
        except (ValueError, KeyError, ArithmeticError):
            record.estimated_cost_usd = None
    record.finished_at = timezone.now()
    record.save()
    return record
