"""Prospective bounded request provenance, not successful audit or first-value evidence."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from tenancy.models import Organization, Project, ProjectConfiguration
from tenancy.services import Action, require_project_action

from .crawler import queue_crawl


def queue_first_audit(*, project, actor, page_limit, idempotency_key):
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.filter(pk=project.pk, organization_id=project.organization_id).first()
        if project is None:
            raise PermissionDenied
        require_project_action(project=project, user=actor, action=Action.LAUNCH_JOB)
        if ProjectConfiguration.objects.filter(project=project, source_choice="synthetic_demo").exists():
            raise ValidationError("Synthetic demo cannot queue actual project work.")
        return queue_crawl(project=project, actor=actor, seeds=[], page_limit=page_limit,
                           idempotency_key=idempotency_key, first_audit=True)


def retry_first_audit(*, job, actor, idempotency_key):
    from .crawler import FIRST_AUDIT_ENTRYPOINT
    from .crawling import CrawlScope
    from .models import JobRun
    from .services import retry_job

    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=job.organization_id)
        project = Project.objects.get(pk=job.project_id, organization_id=job.organization_id)
        require_project_action(project=project, user=actor, action=Action.LAUNCH_JOB)
        if ProjectConfiguration.objects.filter(project=project, source_choice="synthetic_demo").exists():
            raise ValidationError("Synthetic demo cannot retry actual project work.")
        current = JobRun.objects.select_for_update().get(pk=job.pk, project=project)
        pages = current.input_snapshot.get("page_limit")
        if (current.handler != "crawl_site"
            or current.config_snapshot.get("first_audit_entrypoint") != FIRST_AUDIT_ENTRYPOINT
            or type(pages) is not int or not 1 <= pages <= 5
            or current.input_snapshot.get("seeds") != [CrawlScope.for_project(project).validate_url(project.canonical_origin)]):
            raise ValidationError("Retry needs the original bounded audit and current project origin.")
        return retry_job(job=current, actor=actor, idempotency_key=idempotency_key)
