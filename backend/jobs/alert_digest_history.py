"""Own retained daily transport metadata, never incident, current eligibility or replay."""
from datetime import timezone as utc

from django.core.exceptions import ValidationError
from django.utils import timezone

from tenancy.services import Action, require_project_action
from .models import ProjectAlertDelivery
from .summary_history import _ERRORS


METHOD = "own-daily-operational-delivery-history-v1"
SCOPE = "own_retained_transport_history_not_recipient_delivery_read_incident_or_current_eligibility"


def _row(row, assessed):
    dates = [row[key] for key in ("created_at", "attempted_at", "sent_at") if row[key] is not None]
    if (type(row["id"]) is not int or not 1 <= row["id"] < 2**53
        or row["state"] not in _ERRORS or row["error_category"] not in _ERRORS[row["state"]]
        or (row["attempted_at"] is None) != (row["state"] == "queued")
        or (row["sent_at"] is not None) != (row["state"] == "sent")
        or any(timezone.is_naive(value) or value > assessed for value in dates) or dates != sorted(dates)
        or row["day_start"] >= row["created_at"].astimezone(utc.utc).date()):
        raise ValidationError("Own daily transport history needs review.")
    return {"id": row["id"], "day_start": row["day_start"].isoformat(),
            "state": "transport_accepted" if row["state"] == "sent" else row["state"],
            "error_category": row["error_category"], "created_at": row["created_at"].isoformat(),
            "attempted_at": row["attempted_at"].isoformat() if row["attempted_at"] else None,
            "accepted_at": row["sent_at"].isoformat() if row["sent_at"] else None}


def own_daily_alert_delivery_history(*, project, actor):
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    assessed = timezone.now()
    queryset = ProjectAlertDelivery.objects.filter(project_id=project.pk, recipient_id=actor.pk).order_by(
        "-day_start", "-pk").values("id", "day_start", "state", "error_category", "created_at", "attempted_at", "sent_at")
    rows = list(queryset[:21])
    result = {"method_version": METHOD, "project_id": project.pk, "scope": SCOPE,
              "rows": [_row(row, assessed) for row in rows[:20]], "has_more": len(rows) > 20}
    if list(queryset[:21]) != rows:
        raise ValidationError("Own daily transport history changed during inspection.")
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    return result
