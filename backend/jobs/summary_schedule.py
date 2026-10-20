"""Bounded current-week opt-in discovery; the delivery kernel owns SMTP authority."""
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from kombu.exceptions import OperationalError

from config.artifacts import ArtifactStorageError, ArtifactValidationError
from .models import ProjectSummaryDelivery, ProjectSummaryPreference
from .summary_delivery import _week_start, recover_weekly_summaries, reserve_weekly_summary


def scan_weekly_summaries(*, after_id=0, through_id=None, week_start=None):
    if not settings.WEEKLY_SUMMARY_DELIVERY_ENABLED:
        return {"state": "disabled", "inspected": 0, "dispatch_failures": 0}
    if type(after_id) is not int or not 0 <= after_id < 2**63:
        raise ValidationError("Invalid weekly scan cursor.")
    current_week = _week_start().isoformat()
    if through_id is None and week_start is None and after_id == 0:
        through_id = ProjectSummaryPreference.objects.aggregate(last=Max("pk"))["last"] or 0
        week_start = current_week
    if type(through_id) is not int or not after_id <= through_id < 2**63 or type(week_start) is not str:
        raise ValidationError("Invalid weekly scan bounds.")
    if week_start != current_week:
        return {"state": "obsolete_week", "inspected": 0, "dispatch_failures": 0}
    preferences = list(ProjectSummaryPreference.objects.filter(pk__gt=after_id, pk__lte=through_id, frequency="weekly")
                       .select_related("project", "user").order_by("pk")[:21])
    queued = set(recover_weekly_summaries(limit=20))
    status = {"state": "current_week_scan", "inspected": 0, "eligible_queued": 0, "dispatch_failures": 0,
              "has_more": len(preferences) > 20}
    for preference in preferences[:20]:
        try:
            delivery_id = reserve_weekly_summary(project=preference.project, recipient=preference.user)
        except (PermissionDenied, ValidationError, ArtifactStorageError, ArtifactValidationError):
            continue  # Missing/denied source is not a report or a reason to stop later candidates.
        if delivery_id and ProjectSummaryDelivery.objects.filter(pk=delivery_id, state="queued").exists():
            queued.add(delivery_id)
    status["inspected"] = min(len(preferences), 20)
    status["eligible_queued"] = len(queued)
    from .tasks import scan_weekly_summaries_task, send_weekly_summary_task
    def dispatch():
        for delivery_id in sorted(queued):
            try:
                send_weekly_summary_task.apply_async(args=[delivery_id], queue="default",
                    task_id=f"weekly-summary-{delivery_id}", retry=False)
            except (OperationalError, OSError, TimeoutError):
                status["dispatch_failures"] += 1  # Durable queued rows remain recoverable.
        if status["has_more"]:
            try:
                scan_weekly_summaries_task.apply_async(args=[preferences[19].pk, through_id, week_start],
                                                     queue="default", countdown=1, retry=False)
            except (OperationalError, OSError, TimeoutError):
                status["dispatch_failures"] += 1  # Next hourly scan restarts the complete bounded traversal.
    transaction.on_commit(dispatch)
    return status
