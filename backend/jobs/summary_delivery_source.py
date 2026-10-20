"""Current optional eligibility only; callers must re-resolve at actual delivery."""
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from tenancy.email_feedback import is_email_suppressed
from tenancy.models import Organization
from tenancy.services import Action, require_entitlement_capacity, require_project_action
from .models import ProjectSummaryPreference
from .weekly_summary import _recipient, retained_weekly_report_source


def _binding(project, recipient):
    require_project_action(project=project, user=recipient, action=Action.VIEW_PROJECT)
    preference = ProjectSummaryPreference.objects.filter(project=project, user=recipient).first()
    if preference is None or preference.frequency != "weekly":
        return None
    _recipient(project, recipient)
    email = get_user_model().objects.values_list("email", flat=True).get(pk=recipient.pk)
    address = EmailAddress.objects.filter(user_id=recipient.pk, email=email, primary=True, verified=True).first()
    if address is None or is_email_suppressed(email):
        raise PermissionDenied
    require_entitlement_capacity(organization=Organization.objects.get(pk=project.organization_id))
    return preference.pk, preference.revision, address.pk, email


def current_weekly_delivery_source(*, project, recipient):
    original = _binding(project, recipient)
    if original is None:
        # No private report I/O or implied message from an absent/off optional preference.
        require_project_action(project=project, user=recipient, action=Action.VIEW_PROJECT)
        return {"method_version": "optional-weekly-delivery-source-v1", "project_id": project.pk,
                "state": "unavailable_preference_off", "preference_revision": None, "source": None}
    source = retained_weekly_report_source(project=project, recipient=recipient)
    if _binding(project, recipient) != original:
        raise PermissionDenied
    return {"method_version": "optional-weekly-delivery-source-v1", "project_id": project.pk,
            "state": "eligible_current_source_not_sent" if source["state"] == "available_selected_snapshot"
                     else "unavailable_no_report", "preference_revision": original[1], "source": source}
