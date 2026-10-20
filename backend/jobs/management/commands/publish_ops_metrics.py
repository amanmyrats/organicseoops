"""Publish source-neutral aggregate job/provider metrics; never emit tenant IDs."""
from datetime import timedelta

import boto3
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Max
from django.utils import timezone

from jobs.models import AIUsageRecord, JobRun, JobStatus
from tenancy.models import Organization, OrganizationDeletionRun


def _metrics(now):
    cutoff = now - timedelta(minutes=5)
    jobs = JobRun.objects.filter(updated_at__gte=cutoff)
    lifecycle = jobs.filter(status__in=[JobStatus.SUCCEEDED, JobStatus.FAILED,
                                        JobStatus.PARTIALLY_SUCCEEDED, JobStatus.CANCELLED]).aggregate(
        maximum=Max(F("updated_at") - F("created_at")))["maximum"]
    ai = AIUsageRecord.objects.filter(finished_at__gte=cutoff)
    values = [("FailedJobs", jobs.filter(status=JobStatus.FAILED).count(), "Count"),
              ("ProviderFailedOrUnknown", ai.filter(status__in=[AIUsageRecord.Status.FAILED,
                                                                   AIUsageRecord.Status.UNKNOWN]).count(), "Count"),
              ("OverdueCustomerDeletionRuns", OrganizationDeletionRun.objects.filter(
                  due_at__lt=now).exclude(state=OrganizationDeletionRun.State.COMPLETE).count(), "Count"),
              ("ClosedTenantsMissingDeletionRun", Organization.objects.filter(
                  closed_at__lte=now - timedelta(days=30), deletion_run__isnull=True).count(), "Count")]
    if lifecycle is not None:
        values.append(("MaxJobLifecycleMs", max(0, lifecycle.total_seconds() * 1000), "Milliseconds"))
    provider_duration = ai.filter(duration_ms__isnull=False).aggregate(maximum=Max("duration_ms"))["maximum"]
    if provider_duration is not None:
        values.append(("MaxMeasuredProviderDurationMs", provider_duration, "Milliseconds"))
    return [{"MetricName": name, "Dimensions": [{"Name": "Environment", "Value": "production"}],
             "Value": value, "Unit": unit} for name, value, unit in values]


class Command(BaseCommand):
    help = "Publish bounded operational counts/latencies from current job records"

    def handle(self, *args, **options):
        if not settings.PRODUCTION_APP_HOST or not settings.SES_FEEDBACK_REGION:
            raise CommandError("Only the configured production app host may publish metrics")
        boto3.client("cloudwatch", region_name=settings.SES_FEEDBACK_REGION).put_metric_data(
            Namespace="OrganicSEOOps/Jobs", MetricData=_metrics(timezone.now()))
