"""Own retained transport diagnostics, never current sending or retry authority."""
from django.core.exceptions import ValidationError
from django.utils import timezone

from tenancy.services import Action, require_project_action
from .models import ProjectSummaryDelivery


METHOD = "own-weekly-delivery-history-v1"
SCOPE = "own_retained_transport_history_not_recipient_delivery_read_or_current_eligibility"
_ERRORS = {"queued": {""}, "sending": {""}, "sent": {""},
           "skipped": {"current_source_or_recipient_changed"},
           "unknown": {"delivery_uncertain", "worker_outcome_unknown"}}


def _row(row):
    dates = [row[key] for key in ("created_at", "attempted_at", "sent_at") if row[key] is not None]
    if (not 1 <= row["id"] < 2**53 or row["week_start"].weekday() != 0
        or row["state"] not in _ERRORS or row["error_category"] not in _ERRORS[row["state"]]
        or (row["attempted_at"] is None) != (row["state"] == "queued")
        or (row["sent_at"] is not None) != (row["state"] == "sent")
        or any(timezone.is_naive(value) for value in dates) or dates != sorted(dates)):
        raise ValidationError("Own weekly transport history needs review.")
    return {"id": row["id"], "week_start": row["week_start"].isoformat(),
            "state": "transport_accepted" if row["state"] == "sent" else row["state"],
            "error_category": row["error_category"], "created_at": row["created_at"].isoformat(),
            "attempted_at": row["attempted_at"].isoformat() if row["attempted_at"] else None,
            "accepted_at": row["sent_at"].isoformat() if row["sent_at"] else None}


def own_weekly_delivery_history(*, project, actor):
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    rows = list(ProjectSummaryDelivery.objects.filter(project_id=project.pk, recipient_id=actor.pk)
                .order_by("-week_start", "-pk").values("id", "week_start", "state", "error_category",
                                                     "created_at", "attempted_at", "sent_at")[:21])
    result = {"method_version": METHOD, "project_id": project.pk, "scope": SCOPE,
              "rows": [_row(row) for row in rows[:20]], "has_more": len(rows) > 20}
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    return result
