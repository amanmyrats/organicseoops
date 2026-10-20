"""Human GA4 measurement definitions, distinct from observed report metrics."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from tenancy.models import AuditEvent, AuditEventType, Organization, Project
from tenancy.services import Action, require_project_action

from .models import GA4MeasurementReview, IntegrationConnection
from .services import require_connection_capability


def record_ga4_measurement_review(*, project, user, connection, expected_revision, definitions,
                                  instrumentation_state, instrumentation_notes, attribution_notes,
                                  consent_notes, tracking_change_notes, event_quality_state):
    if type(expected_revision) is not int or not 0 <= expected_revision < 65535:
        raise ValidationError("Reload the GA4 measurement review revision.")
    if type(definitions) is not list or any(type(item) is not dict for item in definitions) or any(
        type(value) is not str for value in (instrumentation_state, event_quality_state, instrumentation_notes,
            attribution_notes, consent_notes, tracking_change_notes)
    ):
        raise ValidationError("Choose bounded GA4 measurement definitions and notes.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=user, action=Action.MANAGE_PROJECT)
        connection = IntegrationConnection.objects.select_for_update().filter(
            pk=connection.pk, project=project, provider="google_analytics_4").first()
        if connection is None:
            raise PermissionDenied
        require_connection_capability(connection, "landing_metrics", dimensions=["hostname", "landing_page"])
        values = {"definitions": definitions, "instrumentation_state": instrumentation_state,
                  "event_quality_state": event_quality_state,
                  "instrumentation_notes": instrumentation_notes, "attribution_notes": attribution_notes,
                  "consent_notes": consent_notes, "tracking_change_notes": tracking_change_notes}
        previous = GA4MeasurementReview.objects.filter(project=project, connection=connection).order_by("-revision").first()
        revision = previous.revision if previous else 0
        if revision != expected_revision:
            if (previous and revision == expected_revision + 1 and previous.actor_id == user.pk
                and all(getattr(previous, field) == value for field, value in values.items())):
                return previous
            raise ValidationError("GA4 review changed; reload its current revision.")
        row = GA4MeasurementReview(project=project, connection=connection, actor=user, revision=revision + 1,
            property_id=connection.external_property_id, currency=connection.currency,
            timezone=connection.timezone, **values)
        row.save()
        AuditEvent.objects.create(organization=organization, project=project, actor=user,
            event_type=AuditEventType.GA4_MEASUREMENT_REVIEWED,
            details={"connection_id": connection.pk, "property_id": connection.external_property_id,
                     "revision": row.revision, "instrumentation_state": row.instrumentation_state})
        return row
