import re
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from tenancy.billing_state import paid_access_state
from tenancy.models import Organization, PaddleSubscription
from tenancy.services import (
    Action,
    PAID_UNIT_LIMIT,
    TrialAllowanceError,
    active_trial_for_policy,
    require_entitlement_capacity,
    require_project_action,
)

from .models import JobRun, JobStatus, UsageReservation


class UsageLimitError(ValidationError):
    def __init__(self, message, *, category="internal_capacity"):
        self.category = category
        super().__init__(message, code=category)


def require_billable_access(*, organization):
    try:
        require_entitlement_capacity(organization=organization)
    except TrialAllowanceError as error:
        raise UsageLimitError("Billable access is unavailable.", category=error.code) from None


def _units_used(records):
    return records.aggregate(units=models.Sum(models.Case(
        models.When(state=UsageReservation.State.RESERVED, then=models.F("reserved_units")),
        models.When(state=UsageReservation.State.SETTLED, then=models.F("actual_units")),
        default=models.Value(0), output_field=models.BigIntegerField(),
    )))["units"] or 0


def _entitlement_denial(*, organization, units, additional_units, reservation=None):
    if units == 0:
        return ""
    trial = active_trial_for_policy(organization=organization)
    if trial is not None:
        if reservation is not None and not trial.started_at <= reservation.created_at < trial.ends_at:
            return "trial_unavailable"
        records = UsageReservation.objects.filter(
            organization=organization,
            created_at__gte=trial.started_at,
            created_at__lt=trial.ends_at,
        )
        return "trial_units_exhausted" if _units_used(records) + additional_units > trial.unit_limit else ""
    subscription = PaddleSubscription.objects.filter(organization=organization).first()
    if subscription is None or subscription.verified_at is None:
        return "trial_unavailable"
    if organization.is_suspended or subscription.environment != settings.PADDLE_ENVIRONMENT:
        return "paid_unavailable"
    state = paid_access_state(subscription)
    if state == "billing_review_hold":
        return state
    if state not in {"paid_active", "cancellation_scheduled", "payment_grace"}:
        return "paid_unavailable"
    start = subscription.grace_usage_starts_at or subscription.period_starts_at
    end = (subscription.failed_at + timedelta(days=7)
           if state == "payment_grace" else subscription.period_ends_at)
    if reservation is not None and not start <= reservation.created_at < end:
        return "paid_period_changed"
    records = UsageReservation.objects.filter(
        organization=organization,
        created_at__gte=start,
        created_at__lt=end,
    )
    return "paid_units_exhausted" if _units_used(records) + additional_units > PAID_UNIT_LIMIT else ""


def reserve_usage(*, job, provider, units):
    if (not isinstance(provider, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", provider)
            or type(units) is not int or not 0 <= units <= settings.INTERNAL_PROJECT_MONTHLY_UNITS):
        raise ValidationError("Choose a bounded provider and internal unit estimate.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=job.organization_id)
        job = JobRun.objects.select_related("actor", "project").get(pk=job.pk, organization=organization)
        require_project_action(project=job.project, user=job.actor, action=Action.LAUNCH_JOB)
        if job.status != JobStatus.QUEUED:
            raise ValidationError("Only queued jobs can reserve usage.")
        existing = UsageReservation.objects.filter(job=job).first()
        if existing is not None:
            if existing.provider != provider or existing.reserved_units != units:
                raise ValidationError("Reservation request conflicts with existing job usage.")
            return existing

        entitlement_denial = _entitlement_denial(organization=organization, units=units, additional_units=units)
        if entitlement_denial:
            raise UsageLimitError(
                "Commercial work is unavailable or allowance reached.",
                category=entitlement_denial,
            )

        period_start = timezone.now().date().replace(day=1)
        records = UsageReservation.objects.filter(organization=organization, period_start=period_start)
        scopes = (
            (records, settings.INTERNAL_ORG_MONTHLY_UNITS, settings.INTERNAL_ORG_ACTIVE_JOBS),
            (records.filter(project=job.project), settings.INTERNAL_PROJECT_MONTHLY_UNITS, settings.INTERNAL_PROJECT_ACTIVE_JOBS),
            (records.filter(provider=provider), settings.INTERNAL_PROVIDER_MONTHLY_UNITS, settings.INTERNAL_PROVIDER_ACTIVE_JOBS),
        )
        for scope, unit_limit, active_limit in scopes:
            if _units_used(scope) + units > unit_limit or scope.filter(state=UsageReservation.State.RESERVED).count() >= active_limit:
                raise UsageLimitError("Internal job usage or concurrency ceiling reached.")
        return UsageReservation.objects.create(
            job=job, organization=organization, project=job.project, provider=provider,
            period_start=period_start, reserved_units=units,
        )


def usage_denial(*, job):
    reservation = UsageReservation.objects.filter(job_id=job.pk).first()
    if reservation is None or reservation.state != UsageReservation.State.RESERVED:
        return "usage_unreserved"
    organization = Organization.objects.get(pk=job.organization_id)
    entitlement_denial = _entitlement_denial(
        organization=organization,
        units=reservation.reserved_units,
        additional_units=0,
        reservation=reservation,
    )
    if entitlement_denial:
        return entitlement_denial
    records = UsageReservation.objects.filter(
        organization_id=job.organization_id,
        period_start=reservation.period_start,
    )
    for scope, unit_limit, active_limit in (
        (records, settings.INTERNAL_ORG_MONTHLY_UNITS, settings.INTERNAL_ORG_ACTIVE_JOBS),
        (records.filter(project_id=job.project_id), settings.INTERNAL_PROJECT_MONTHLY_UNITS, settings.INTERNAL_PROJECT_ACTIVE_JOBS),
        (records.filter(provider=reservation.provider), settings.INTERNAL_PROVIDER_MONTHLY_UNITS, settings.INTERNAL_PROVIDER_ACTIVE_JOBS),
    ):
        if _units_used(scope) > unit_limit or scope.filter(state=UsageReservation.State.RESERVED).count() > active_limit:
            return "internal_capacity"
    return ""


def settle_usage(*, job, actual_units):
    if type(actual_units) is not int or actual_units < 0:
        raise ValidationError("Actual usage must be a nonnegative integer.")
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=job.organization_id)
        reservation = UsageReservation.objects.select_for_update().get(job_id=job.pk)
        if reservation.state != UsageReservation.State.RESERVED:
            if reservation.actual_units != actual_units:
                raise ValidationError("Settled usage cannot be changed by a repeat request.")
            return reservation
        reservation.actual_units = actual_units
        reservation.state = UsageReservation.State.SETTLED if actual_units else UsageReservation.State.RELEASED
        reservation.settled_at = timezone.now()
        reservation.save(update_fields=["actual_units", "state", "settled_at"])
    return reservation


def reconcile_usage(*, limit=100):
    from .competitor_collection import COMPETITOR_OBSERVATION_HANDLERS
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValidationError("Invalid reconciliation limit.")
    stranded = list(UsageReservation.objects.filter(
        provider__in=["repository_analysis", "dataforseo_serp", "competitor_source", "authority_source", "diagnostic", "crawler", "passive_security", "source_import", "topic_discovery", "search_console_api", "search_console_coverage", "google_analytics_4", "business_profile", "performance", "ai"],
        state=UsageReservation.State.RESERVED,
        job__status__in=[JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.PARTIALLY_SUCCEEDED],
    ).order_by("created_at", "pk").select_related("job")[:limit])
    for reservation in stranded:
        actual_units = 0
        if reservation.provider == "repository_analysis":
            from .repository_analysis import ATTEMPT
            from .repository_advisories import ATTEMPT as advisory_attempt
            actual_units = reservation.job.steps.filter(name__in=[ATTEMPT, advisory_attempt]).count()
        if reservation.provider == "dataforseo_serp":
            actual_units = int(reservation.job.steps.filter(sequence=1).exists())
        if reservation.provider == "competitor_source" and reservation.job.handler in COMPETITOR_OBSERVATION_HANDLERS:
            actual_units = int(reservation.job.steps.exists())
        if reservation.provider == "authority_source":
            actual_units = int(reservation.job.steps.exists())
        if reservation.provider == "passive_security" and reservation.job.handler in {"collect_passive_headers", "collect_passive_tls", "collect_passive_resources", "collect_passive_redirects", "collect_passive_http_redirects", "collect_passive_redirect_chain"}:
            actual_units = int(reservation.job.steps.exists())
        if reservation.provider == "crawler":
            crawl_run = getattr(reservation.job, "crawl_run", None)
            actual_units = crawl_run.pages.count() if crawl_run else 0
        elif reservation.provider == "source_import" and hasattr(reservation.job, "import_run"):
            actual_units = 1
        elif reservation.provider == "source_import" and reservation.job.handler == "import_bot_logs":
            actual_units = int(reservation.job.status == JobStatus.SUCCEEDED)
        elif reservation.provider == "topic_discovery":
            actual_units = sum(step.output.get("state") != "not_collected" for step in reservation.job.steps.filter(name__in=[
                "Compare first-party queries", "Collect configured feed",
            ]).only("output"))
        elif reservation.provider == "search_console_api":
            actual_units = reservation.job.steps.filter(name__in=["Verify selected property", "Search Analytics page"]).count()
        elif reservation.provider == "google_analytics_4":
            actual_units = reservation.job.steps.filter(name__in=[
                "GA4 property check", "GA4 web streams", "GA4 compatibility", "GA4 report page",
            ]).count()
        elif reservation.provider == "business_profile":
            actual_units = reservation.job.steps.count()
        elif reservation.provider == "search_console_coverage":
            actual_units = reservation.job.steps.filter(name__in=[
                "Verify selected property", "List selected sitemaps", "Inspect selected URL in Google index",
            ]).count()
        elif reservation.provider == "performance":
            actual_units = reservation.job.steps.filter(name="Collect performance source").count()
        elif reservation.provider == "ai":
            actual_units = reservation.job.steps.filter(name="Request selected model").count()
        settle_usage(job=reservation.job, actual_units=actual_units)
    return len(stranded)
