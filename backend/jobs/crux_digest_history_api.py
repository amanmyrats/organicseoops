from .alert_digest_history_api import _history
from .crux_digest_history import own_daily_crux_delivery_history


def project_crux_alert_deliveries(request, organization_id, project_id):
    return _history(request, organization_id, project_id, source=own_daily_crux_delivery_history,
                    action="crux_delivery_history_read")
