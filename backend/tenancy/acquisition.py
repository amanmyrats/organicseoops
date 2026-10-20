"""Derivable acquisition-v1 milestones from retained authoritative records."""
from django.contrib.auth import get_user_model
from integrations.models import ImportRun
from jobs.models import ActionReview, FirstAuditValueAcknowledgment

from .models import AuditEventType, OrganizationTrial, PaddleCheckoutLinkReceipt, PaddleFirstActiveObservation


def acquisition_milestones():
    user = get_user_model()
    trial = OrganizationTrial.objects.filter(started_at__isnull=False).filter(
        organization__audit_events__event_type__in=[AuditEventType.TRIAL_GRANTED, AuditEventType.TRIAL_APPROVED]
    ).distinct()
    imported = ImportRun.objects.filter(status=ImportRun.Status.SUCCEEDED, rows_imported__gt=0,
                                         job__status="succeeded").values("project__organization_id").distinct()
    accepted = ActionReview.objects.filter(state=ActionReview.State.ACCEPTED).order_by().values("project__organization_id").distinct()
    counts = {
        "registration_succeeded": ("user", user.objects.filter(registration_origin=user.RegistrationOrigin.SELF_SERVICE).count()),
        "email_verified": ("user", user.objects.filter(first_email_verified_at__isnull=False).count()),
        "trial_activated": ("organization", trial.count()),
        "first_import_succeeded": ("organization", imported.count()),
        "first_audit_succeeded": ("organization", FirstAuditValueAcknowledgment.objects.count()),
        "first_action_accepted": ("organization", accepted.count()),
        "checkout_initiated": ("checkout_attempt", PaddleCheckoutLinkReceipt.objects.count()),
        "paid_activation_confirmed": ("organization", PaddleFirstActiveObservation.objects.count()),
    }
    unavailable = ("public_page_view", "public_cta_selected")
    milestones = {event: {"grain": grain, "count": count, "state": "derivable"}
                  for event, (grain, count) in counts.items()}
    milestones.update({event: {"count": None, "state": "unavailable"} for event in unavailable})
    return {"dictionary_version": "acquisition-v1", "basis": "current_retained_operational_records",
            "funnel_rates_available": False, "milestones": milestones}
