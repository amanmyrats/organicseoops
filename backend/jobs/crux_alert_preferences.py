"""Independent own material-CrUX intent only; no source read, dispatch or sender."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action
from .models import ProjectCruxAlertPreference
from .weekly_summary import _recipient


def _preference(row):
    if row and (row.frequency not in {"off", "daily"} or not 1 <= row.revision < 2**31):
        raise ValidationError("CrUX alert preference needs review.")
    return {"channel": "email", "source_family": "crux_material", "frequency": row.frequency if row else "off",
            "revision": row.revision if row else 0,
            "delivery_state": "enabled_optional" if settings.CRUX_ALERT_DELIVERY_ENABLED else "rollout_off"}


def project_crux_alert_preference(*, project, actor):
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    result = _preference(ProjectCruxAlertPreference.objects.filter(project=project, user=actor).first())
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    return result


def set_project_crux_alert_preference(*, project, actor, frequency, expected_revision):
    if (type(frequency) is not str or frequency not in {"off", "daily"}
        or type(expected_revision) is not int or not 0 <= expected_revision < 2**31 - 1):
        raise ValidationError("Choose an exact current CrUX alert preference.")
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization_id=project.organization_id)
        actor = get_user_model().objects.select_for_update().get(pk=actor.pk)
        require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
        if frequency == "daily":
            _recipient(project, actor)
        row = ProjectCruxAlertPreference.objects.filter(project=project, user=actor).first()
        _preference(row)
        if expected_revision != (row.revision if row else 0):
            raise ValidationError("Refresh the current CrUX alert preference before saving.")
        if row is None and frequency == "daily":
            row = ProjectCruxAlertPreference.objects.create(project=project, user=actor, frequency=frequency)
        elif row and row.frequency != frequency:
            row.frequency = frequency
            row.revision += 1
            row.save(update_fields=["frequency", "revision", "updated_at"])
        require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
        if frequency == "daily":
            _recipient(project, actor)
        return _preference(row)
