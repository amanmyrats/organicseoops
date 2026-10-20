"""Explicit human intent/page reviews from current project-scoped query findings."""
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max

from integrations.models import ImportRun, SourceDimension
from integrations.services import require_connection_capability
from tenancy.models import Organization, Project, ProjectConfiguration, normalize_origin
from tenancy.services import Action, project_has_origin, require_project_action

from .models import Finding, IntentClusterReview


def current_query_findings(project, ids):
    findings = list(Finding.objects.filter(pk__in=ids, project=project)
                    .select_related("source_metric__import_run__connection"))
    if len(findings) != len(ids):
        raise PermissionDenied
    for finding in findings:
        metric = finding.source_metric
        if (metric is None or metric.dimension != SourceDimension.QUERY or not metric.query
            or metric.import_run.status != ImportRun.Status.SUCCEEDED
            or metric.import_run.coverage_state != ImportRun.CoverageState.COMPLETE
            or metric.import_run.row_errors):
            raise ValidationError("A cluster needs complete current query-only source evidence.")
        require_connection_capability(metric.import_run.connection, "query_metrics", dimensions=[SourceDimension.QUERY])
    return findings


def _project_page(project, value):
    try:
        parsed = urlsplit(value)
        origin = normalize_origin(f"{parsed.scheme}://{parsed.netloc}")
    except (ValueError, ValidationError):
        raise ValidationError("Choose an exact configured project page URL.") from None
    if (not project_has_origin(project, origin) or parsed.username or parsed.password
        or parsed.query or parsed.fragment or "\\" in value or any(ord(char) < 32 for char in value)):
        raise ValidationError("Choose an exact configured project page URL.")
    return origin + (parsed.path or "/")


def review_intent_cluster(*, project, actor, request_key, label, source_finding_ids, intent,
                          page_kind, preferred_page, reason, language,
                          manual_topics=None, proposed_action="unselected", action_reason="", affected_page="",
                          cluster_id=None, expected_revision=None):
    manual_topics = [] if manual_topics is None else manual_topics
    if (type(request_key) is not str or not 8 <= len(request_key) <= 64
        or not request_key[0].isascii() or not request_key[0].isalnum()
        or any(not char.isascii() or not (char.isalnum() or char in "_-") for char in request_key)
        or type(label) is not str or not 1 <= len(label.strip()) <= 120
        or type(reason) is not str or not 1 <= len(reason.strip()) <= 500
        or type(language) is not str or intent not in IntentClusterReview.Intent.values
        or page_kind not in IntentClusterReview.PageKind.values
        or type(source_finding_ids) is not list or len(source_finding_ids) > 10
        or any(type(pk) is not int or pk < 1 for pk in source_finding_ids)
        or len(set(source_finding_ids)) != len(source_finding_ids)
        or type(manual_topics) is not list or len(manual_topics) > 10
        or any(type(topic) is not str or not 1 <= len(topic) <= 120 or topic != topic.strip()
               for topic in manual_topics)
        or len(set(manual_topics)) != len(manual_topics)
        or bool(source_finding_ids) == bool(manual_topics)
        or type(preferred_page) is not str or len(preferred_page) > 512):
        raise ValidationError("Choose bounded, current query evidence and a human mapping decision.")
    if (proposed_action not in IntentClusterReview.ProposedAction.values
        or type(action_reason) is not str or len(action_reason) > 500
        or type(affected_page) is not str or len(affected_page) > 512):
        raise ValidationError("Choose a bounded, unapproved action proposal.")
    if (cluster_id is None) != (expected_revision is None):
        raise ValidationError("Correct one known cluster revision, or create a new cluster.")
    if cluster_id is not None:
        try:
            cluster_id = UUID(str(cluster_id))
        except ValueError:
            raise ValidationError("Select a current cluster.") from None
        if type(expected_revision) is not int or not 1 <= expected_revision < 65535:
            raise ValidationError("Select a current cluster revision.")

    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        config = ProjectConfiguration.objects.filter(project=project).first()
        if not config or not config.target_country or language not in config.target_languages:
            raise ValidationError("Configure the project's market and selected SEO language first.")
        if manual_topics and any(topic not in config.seed_topics for topic in manual_topics):
            raise ValidationError("Manual topics must be current project onboarding seeds.")

        if page_kind == IntentClusterReview.PageKind.UNMAPPED:
            if preferred_page:
                raise ValidationError("An unmapped cluster cannot claim a page.")
        else:
            preferred_page = _project_page(project, preferred_page)
        if proposed_action == "unselected":
            if action_reason or affected_page:
                raise ValidationError("An unselected action cannot claim an implementation.")
        elif not action_reason.strip():
            raise ValidationError("Explain why the human action is proposed.")
        elif proposed_action == "create" and page_kind != "proposed":
            raise ValidationError("Creating content needs a proposed page.")
        elif proposed_action in {"keep", "refresh", "merge", "redirect", "retire"} and page_kind != "existing_unverified":
            raise ValidationError("Existing-page actions need a selected existing page.")
        if proposed_action in {"merge", "redirect"}:
            affected_page = _project_page(project, affected_page)
            if affected_page == preferred_page:
                raise ValidationError("Source and destination must be distinct pages.")
        elif affected_page:
            raise ValidationError("Only merge or redirect proposals may name an affected source page.")

        existing = IntentClusterReview.objects.filter(project=project, request_key=request_key).first()
        if existing:
            latest_revision = IntentClusterReview.objects.filter(project=project, cluster_id=existing.cluster_id).aggregate(
                maximum=Max("revision"))["maximum"]
            if existing.revision != latest_revision:
                raise ValidationError("The reviewed cluster changed; reload its latest revision.")
            if (existing.actor_id != actor.pk or (cluster_id is not None and existing.cluster_id != cluster_id)
                or existing.revision != (expected_revision + 1 if cluster_id else 1)
                or (existing.label, existing.source_finding_ids, existing.manual_topics,
                    existing.intent, existing.page_kind,
                    existing.preferred_page, existing.reason, existing.language, existing.market,
                    existing.proposed_action, existing.action_reason, existing.affected_page)
                != (label.strip(), source_finding_ids, manual_topics, intent, page_kind, preferred_page,
                    reason.strip(), language, config.target_country,
                    proposed_action, action_reason.strip(), affected_page)):
                raise ValidationError("Intent review key belongs to a different decision.")
            return existing

        if cluster_id is not None:
            latest = IntentClusterReview.objects.filter(project=project, cluster_id=cluster_id).order_by("-revision").first()
            if latest is None or latest.revision != expected_revision:
                raise ValidationError("Intent mapping changed; reload before correcting it.")
            revision = latest.revision + 1
        else:
            cluster_id, revision = uuid4(), 1

        if source_finding_ids:
            current_query_findings(project, source_finding_ids)

        return IntentClusterReview.objects.create(project=project, actor=actor,
            request_key=request_key, cluster_id=cluster_id, revision=revision, label=label.strip(),
            source_finding_ids=source_finding_ids, manual_topics=manual_topics,
            market=config.target_country, language=language,
            intent=intent, page_kind=page_kind, preferred_page=preferred_page, reason=reason.strip(),
            proposed_action=proposed_action, action_reason=action_reason.strip(), affected_page=affected_page)
