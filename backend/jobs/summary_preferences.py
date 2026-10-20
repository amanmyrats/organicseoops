"""Default-off self-project intent, separate from required mail and actual delivery."""
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action
from .models import ProjectSummaryPreference
from .weekly_summary import _recipient


def _summary(row):
    return {"channel": "email", "frequency": row.frequency if row else "off",
            "revision": row.revision if row else 0,
            "delivery_state": "enabled_optional" if settings.WEEKLY_SUMMARY_DELIVERY_ENABLED else "rollout_off"}


def project_summary_preference(*, project, actor):
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    row = ProjectSummaryPreference.objects.filter(project=project, user=actor).first()
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    return _summary(row)


def set_project_summary_preference(*, project, actor, frequency, expected_revision):
    if (type(frequency) is not str or frequency not in {"off", "weekly"}
        or type(expected_revision) is not int or not 0 <= expected_revision < 2**31 - 1):
        raise ValidationError("Choose an exact current summary preference.")
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization_id=project.organization_id)
        actor = get_user_model().objects.select_for_update().get(pk=actor.pk)
        require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
        if frequency == "weekly":
            _recipient(project, actor)
        row = ProjectSummaryPreference.objects.filter(project=project, user=actor).first()
        if expected_revision != (row.revision if row else 0):
            raise ValidationError("Refresh the current summary preference before saving.")
        if row is None and frequency == "weekly":
            row = ProjectSummaryPreference.objects.create(project=project, user=actor, frequency=frequency)
        elif row and row.frequency != frequency:
            row.frequency = frequency
            row.revision += 1
            row.save(update_fields=["frequency", "revision", "updated_at"])
        # A concurrent source/verification/role loss must roll back preference changes, even after insert.
        require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
        if frequency == "weekly":
            _recipient(project, actor)
        return _summary(row)
