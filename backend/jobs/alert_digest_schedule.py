"""Bounded opt-in discovery; the checked daily kernel owns all outgoing authority."""
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from kombu.exceptions import OperationalError

from .alert_digest_delivery import recover_daily_alert_digests, reserve_daily_alert_digest
from .alert_digest_source import _day
from .models import ProjectAlertDelivery, ProjectAlertPreference


def scan_daily_alert_digests(*, after_id=0, through_id=None, day_start=None):
    if not settings.ALERT_DIGEST_DELIVERY_ENABLED:
        return {"state": "disabled", "inspected": 0, "dispatch_failures": 0}
    if type(after_id) is not int or not 0 <= after_id < 2**63:
        raise ValidationError("Invalid daily digest scan cursor.")
    current_day = _day()[0].date().isoformat()
    if through_id is None and day_start is None and after_id == 0:
        through_id = ProjectAlertPreference.objects.aggregate(last=Max("pk"))["last"] or 0
        day_start = current_day
    if type(through_id) is not int or not after_id <= through_id < 2**63 or type(day_start) is not str:
        raise ValidationError("Invalid daily digest scan bounds.")
    if day_start != current_day:
        return {"state": "obsolete_day", "inspected": 0, "dispatch_failures": 0}
    preferences = list(ProjectAlertPreference.objects.filter(pk__gt=after_id, pk__lte=through_id, frequency="daily")
                       .select_related("project", "user").order_by("pk")[:21])
    queued = set(recover_daily_alert_digests(limit=20))
    status = {"state": "current_day_scan", "inspected": 0, "eligible_queued": 0, "dispatch_failures": 0,
              "has_more": len(preferences) > 20}
    for preference in preferences[:20]:
        if _day()[0].date().isoformat() != day_start:
            status.update(state="obsolete_day", has_more=False)
            break
        status["inspected"] += 1
        try:
            delivery_id = reserve_daily_alert_digest(project=preference.project, recipient=preference.user)
        except (PermissionDenied, ValidationError):
            continue
        if delivery_id and ProjectAlertDelivery.objects.filter(pk=delivery_id, state="queued", day_start=day_start).exists():
            queued.add(delivery_id)
    status["eligible_queued"] = len(queued)
    from .tasks import scan_daily_alert_digests_task, send_daily_alert_digest_task
    def dispatch():
        if _day()[0].date().isoformat() != day_start or not settings.ALERT_DIGEST_DELIVERY_ENABLED:
            status.update(state="obsolete_day" if settings.ALERT_DIGEST_DELIVERY_ENABLED else "disabled", has_more=False)
            return
        for delivery_id in sorted(queued):
            try:
                send_daily_alert_digest_task.apply_async(args=[delivery_id], queue="default",
                    task_id=f"daily-alert-digest-{delivery_id}", retry=False)
            except (OperationalError, OSError, TimeoutError):
                status["dispatch_failures"] += 1
        if status["has_more"]:
            try:
                scan_daily_alert_digests_task.apply_async(args=[preferences[19].pk, through_id, day_start],
                                                         queue="default", countdown=1, retry=False)
            except (OperationalError, OSError, TimeoutError):
                status["dispatch_failures"] += 1
    transaction.on_commit(dispatch)
    return status
