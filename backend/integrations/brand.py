import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from tenancy.models import Organization, Project, ProjectConfiguration
from tenancy.services import Action, require_project_action

from .models import IntegrationCapability, IntegrationConnection, QueryBrandReview, SearchMetricObservation
from .services import require_connection_capability


BRAND_METHOD = "alias-boundary-v1"


class BrandReviewConflict(Exception):
    pass


def default_brand_label(query, aliases):
    if not aliases:
        return QueryBrandReview.Label.UNCLASSIFIED
    folded = query.casefold()
    return (
        QueryBrandReview.Label.BRANDED
        if any(re.search(r"(?<!\w)" + re.escape(alias.casefold()) + r"(?!\w)", folded) for alias in aliases)
        else QueryBrandReview.Label.NON_BRANDED
    )


def review_query_brand(*, project, connection_id, observation_id, user, expected_revision, label, reason):
    if type(expected_revision) is not int or expected_revision < 0 or label not in QueryBrandReview.Label.values:
        raise ValidationError("Check the brand review revision and label.")
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 240:
        raise ValidationError("Add a short reason for this brand review.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=user, action=Action.LAUNCH_JOB)
        connection = IntegrationConnection.objects.select_for_update().filter(pk=connection_id, project=project).first()
        if connection is None:
            raise PermissionDenied
        require_connection_capability(connection, IntegrationCapability.QUERY_METRICS, dimensions=["query"])
        observation = SearchMetricObservation.objects.select_for_update().filter(
            pk=observation_id, import_run__project=project, import_run__connection=connection, query__gt="",
        ).first()
        if observation is None:
            raise PermissionDenied
        previous = QueryBrandReview.objects.filter(observation=observation).order_by("-revision").first()
        if (previous.revision if previous else 0) != expected_revision:
            raise BrandReviewConflict
        review = QueryBrandReview.objects.create(
            observation=observation, actor=user, revision=expected_revision + 1, label=label, reason=reason,
        )
    return review


def brand_aliases(project):
    configuration = ProjectConfiguration.objects.filter(project=project).first()
    return (configuration.brand_aliases, configuration.revision) if configuration else ([], 0)
