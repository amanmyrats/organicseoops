"""Private project-only report snapshots; no public bucket or raw source export."""
import csv
from hashlib import sha256
from io import StringIO
import json
import re
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from config.artifacts import ArtifactNotFound, ArtifactStorageError, ArtifactValidationError
from tenancy.artifacts import delete_project_artifact, read_project_artifact, save_project_artifact
from tenancy.customer_artifact_barrier import project_artifact_barrier
from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action

from .models import ActionOutcomeSnapshot, ActionReview, Finding, ProjectReportSnapshot


def _ids(values):
    return (type(values) is list and len(values) <= 20
            and all(type(value) is int and value > 0 for value in values)
            and len(set(values)) == len(values))


def _csv_safe(value):
    text = str(value) if value is not None else ""
    return "'" + text if re.match(r"^[\s\ufeff\u200b]*[=+\-@]", text) else text


def _render_report(project, findings, actions, outcomes, content_format):
    rows = []
    for finding in findings:
        if (finding.source_passive_header_id or finding.source_passive_resource_id or finding.source_passive_tls_id
            or finding.source_passive_redirect_id or finding.source_passive_redirect_chain_id):
            raise PermissionDenied
        source = (finding.source_metric_id or finding.source_api_page_id or finding.source_diagnostics_id
                  or finding.source_indexation_id or finding.source_performance_id)
        rows.append({"kind": "candidate", "source_id": source, "id": finding.pk,
                     "recorded_at": finding.detected_at.isoformat(), "summary": finding.subject,
                     "method_version": finding.method_version, "confidence": finding.confidence,
                     "coverage": finding.evidence.get("coverage", "unknown")})
    for review in actions:
        rows.append({"kind": "human_action", "source_id": review.intent_cluster_id or review.opportunity_id,
                     "id": review.pk, "recorded_at": review.created_at.isoformat(),
                     "summary": review.action_kind + ": " + ", ".join(review.affected_urls),
                     "state": review.state, "criteria": review.acceptance_criteria,
                     "implementation_at": review.implemented_at.isoformat() if review.implemented_at else None,
                     "verification_at": review.verified_at.isoformat() if review.verified_at else None,
                     "outcome_at": review.outcome_reviewed_at.isoformat() if review.outcome_reviewed_at else None,
                     "coverage": "manual_review_not_automatically_executed"})
    for outcome in outcomes:
        rows.append({"kind": "observed_page_outcome", "source_id": outcome.action_review_id,
                     "id": outcome.pk, "recorded_at": outcome.created_at.isoformat(),
                     "summary": outcome.page, "method_version": outcome.method_version,
                     "coverage": outcome.report["coverage"], "search_metrics": outcome.report["search_metrics"],
                     "conversion": outcome.report["conversion"],
                     "interpretation": outcome.report["interpretation"]})
    if content_format == ProjectReportSnapshot.Format.CSV:
        output = StringIO(newline="")
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(["kind", "record_id", "source_id", "recorded_at", "summary", "details"])
        for row in rows:
            writer.writerow([_csv_safe(row.get(key)) for key in ("kind", "id", "source_id", "recorded_at", "summary")]
                            + [_csv_safe(json.dumps({key: value for key, value in row.items()
                                                     if key not in {"kind", "id", "source_id", "recorded_at", "summary"}},
                                                     ensure_ascii=False, sort_keys=True))])
        return output.getvalue().encode("utf-8")
    return json.dumps({"version": "project-report-v1", "project_id": project.pk,
                       "created_at": timezone.now().isoformat(), "rows": rows,
                       "limits": "selected_source_rows_only_not_complete_provider_coverage_or_causal_uplift"},
                      ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def create_project_report(*, project, actor, request_key, content_format, finding_ids, action_review_ids, outcome_ids):
    if (type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", request_key)
        or content_format not in ProjectReportSnapshot.Format.values
        or not all(_ids(values) for values in (finding_ids, action_review_ids, outcome_ids))
        or not any((finding_ids, action_review_ids, outcome_ids))):
        raise ValidationError("Choose bounded project-only report source IDs and format.")
    with project_artifact_barrier(project.organization_id, shared=True):
        key = None
        try:
            with transaction.atomic():
                organization = Organization.objects.select_for_update().get(pk=project.organization_id)
                project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
                require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
                require_ordinary_report_findings(project, finding_ids)
                existing = ProjectReportSnapshot.objects.filter(project=project, request_key=request_key).first()
                if existing:
                    if (existing.created_by_id != actor.pk or existing.content_format != content_format
                        or existing.finding_ids != finding_ids or existing.action_review_ids != action_review_ids
                        or existing.outcome_ids != outcome_ids):
                        raise ValidationError("Report request key belongs to a different snapshot.")
                    return existing
                findings = list(Finding.objects.filter(project=project, pk__in=finding_ids).order_by("pk"))
                actions = list(ActionReview.objects.filter(project=project, pk__in=action_review_ids).order_by("pk"))
                outcomes = list(ActionOutcomeSnapshot.objects.filter(project=project, pk__in=outcome_ids).order_by("pk"))
                if any(len(items) != len(expected) for items, expected in (
                    (findings, finding_ids), (actions, action_review_ids), (outcomes, outcome_ids)
                )):
                    raise PermissionDenied
                for action in actions:
                    if ActionReview.objects.filter(project=project, action_id=action.action_id).aggregate(
                        latest=Max("revision"))["latest"] != action.revision:
                        raise ValidationError("Choose the latest reviewed action before exporting it.")
                data = _render_report(project, findings, actions, outcomes, content_format)
                if not 1 <= len(data) <= 131072:
                    raise ValidationError("Report exceeds the bounded private snapshot size.")
                key = save_project_artifact(project=project, content=data,
                                            content_type="application/json" if content_format == "json" else "text/csv",
                                            key_stem=uuid4().hex)
                return ProjectReportSnapshot.objects.create(project=project, created_by=actor,
                    request_key=request_key, content_format=content_format, artifact_key=key,
                    content_sha256=sha256(data).hexdigest(), size_bytes=len(data),
                    finding_ids=finding_ids, action_review_ids=action_review_ids, outcome_ids=outcome_ids)
        except Exception as exc:
            if key:
                try:
                    delete_project_artifact(project=project, key=key)
                except ArtifactStorageError:
                    pass  # Exact-project orphan is swept by the existing retention runner.
            if isinstance(exc, (ArtifactStorageError, ArtifactValidationError)):
                raise ValidationError("Private report storage is unavailable.") from None
            raise


def require_ordinary_report_findings(project, finding_ids):
    if Finding.objects.filter(Q(source_passive_header__isnull=False) | Q(source_passive_resource__isnull=False)
        | Q(source_passive_tls__isnull=False) | Q(source_passive_redirect__isnull=False) | Q(source_passive_redirect_chain__isnull=False),
        project=project, pk__in=finding_ids).exists():
        raise PermissionDenied


def read_project_report(*, project, actor, snapshot):
    project = Project.objects.get(pk=project.pk, organization_id=project.organization_id)
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    if snapshot.project_id != project.pk:
        raise PermissionDenied
    snapshot = ProjectReportSnapshot.objects.filter(pk=snapshot.pk, project=project).first()
    if snapshot is None:
        raise PermissionDenied
    require_ordinary_report_findings(project, snapshot.finding_ids)
    try:
        data = read_project_artifact(project=project, key=snapshot.artifact_key)
    except (ArtifactNotFound, ArtifactValidationError, ArtifactStorageError):
        raise ValidationError("Private report is unavailable.") from None
    if len(data) != snapshot.size_bytes or sha256(data).hexdigest() != snapshot.content_sha256:
        raise ValidationError("Private report integrity check failed.")
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    require_ordinary_report_findings(project, snapshot.finding_ids)
    if not ProjectReportSnapshot.objects.filter(pk=snapshot.pk, project=project,
            artifact_key=snapshot.artifact_key, content_sha256=snapshot.content_sha256,
            size_bytes=snapshot.size_bytes, content_format=snapshot.content_format).exists():
        raise PermissionDenied
    return data
