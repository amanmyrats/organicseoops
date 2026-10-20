"""Independent default-off own-project intent; source policy and delivery are separate."""
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action
from .models import ProjectAlertPreference
from .weekly_summary import _recipient


FAMILIES = ("crawl_failure", "integration_health")


def _preference(row):
    if row and (row.frequency not in {"off", "daily"} or not 1 <= row.revision < 2**31
                or row.frequency == "daily" and not any(getattr(row, family) for family in FAMILIES)):
        raise ValidationError("Alert preference needs review.")
    return {"channel": "email", "frequency": row.frequency if row else "off",
            "source_families": [family for family in FAMILIES if row and getattr(row, family)],
            "revision": row.revision if row else 0,
            "delivery_state": "enabled_optional" if settings.ALERT_DIGEST_DELIVERY_ENABLED else "rollout_off"}


def project_alert_preference(*, project, actor):
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    result = _preference(ProjectAlertPreference.objects.filter(project=project, user=actor).first())
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    return result


def set_project_alert_preference(*, project, actor, frequency, source_families, expected_revision):
    if (type(frequency) is not str or frequency not in {"off", "daily"}
        or type(source_families) is not list or len(source_families) > len(FAMILIES)
        or any(type(family) is not str or family not in FAMILIES for family in source_families)
        or len(set(source_families)) != len(source_families)
        or frequency == "daily" and not source_families
        or type(expected_revision) is not int or not 0 <= expected_revision < 2**31 - 1):
        raise ValidationError("Choose an exact current alert preference.")
    values = {"frequency": frequency, **{family: family in source_families for family in FAMILIES}}
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization_id=project.organization_id)
        actor = get_user_model().objects.select_for_update().get(pk=actor.pk)
        require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
        if frequency == "daily":
            _recipient(project, actor)
        row = ProjectAlertPreference.objects.filter(project=project, user=actor).first()
        _preference(row)
        if expected_revision != (row.revision if row else 0):
            raise ValidationError("Refresh the current alert preference before saving.")
        if row is None and (frequency != "off" or source_families):
            row = ProjectAlertPreference.objects.create(project=project, user=actor, **values)
        elif row and any(getattr(row, key) != value for key, value in values.items()):
            for key, value in values.items():
                setattr(row, key, value)
            row.revision += 1
            row.save(update_fields=[*values, "revision", "updated_at"])
        require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
        if frequency == "daily":
            _recipient(project, actor)
        return _preference(row)
