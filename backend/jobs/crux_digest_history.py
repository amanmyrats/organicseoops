"""Own retained CrUX transport metadata, never source, eligibility or replay authority."""
from django.core.exceptions import ValidationError
from django.utils import timezone

from tenancy.services import Action, require_project_action
from .alert_digest_history import _row
from .models import ProjectCruxAlertDelivery


METHOD = "own-daily-crux-delivery-history-v1"
SCOPE = "own_retained_crux_transport_history_not_recipient_delivery_read_regression_or_current_eligibility"


def own_daily_crux_delivery_history(*, project, actor):
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    assessed = timezone.now()
    queryset = ProjectCruxAlertDelivery.objects.filter(project_id=project.pk, recipient_id=actor.pk).order_by(
        "-day_start", "-pk").values("id", "day_start", "state", "error_category", "created_at", "attempted_at", "sent_at")
    rows = list(queryset[:21])
    result = {"method_version": METHOD, "project_id": project.pk, "scope": SCOPE,
              "rows": [_row(row, assessed) for row in rows[:20]], "has_more": len(rows) > 20}
    if list(queryset[:21]) != rows:
        raise ValidationError("Own CrUX transport history changed during inspection.")
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    return result
