"""Owner-only bounded archive of selected, already-private project reports."""
from io import BytesIO
import json
from zipfile import ZIP_STORED, ZipFile

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from config.artifacts import ArtifactStorageError
from jobs.models import ProjectReportSnapshot
from jobs.reporting import read_project_report

from .models import Organization
from .services import Action, require_organization_action


def selected_report_bundle(*, organization, actor, report_ids):
    if (type(report_ids) is not list or not 1 <= len(report_ids) <= 20
        or any(type(value) is not int or value < 1 for value in report_ids)
        or len(set(report_ids)) != len(report_ids)):
        raise ValidationError("Select one to twenty distinct retained private reports.")
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_EXPORT)
        reports = list(ProjectReportSnapshot.objects.select_related("project").filter(
            project__organization=organization, pk__in=report_ids).order_by("project_id", "pk"))
        if len(reports) != len(report_ids):
            raise PermissionDenied
        output = BytesIO()
        manifest = {"version": "selected-project-reports-v1", "organization_id": organization.pk,
                    "scope": "selected_project_reports_only_not_complete_organization_export", "reports": []}
        with ZipFile(output, mode="w", compression=ZIP_STORED) as archive:
            for report in reports:
                try:
                    data = read_project_report(project=report.project, actor=actor, snapshot=report)
                except ValidationError:
                    raise ArtifactStorageError("Private report unavailable.") from None
                filename = f"project-{report.project_id}/report-{report.pk}.{report.content_format}"
                archive.writestr(filename, data)
                manifest["reports"].append({"project_id": report.project_id, "report_id": report.pk,
                    "filename": filename, "created_at": report.created_at.isoformat(),
                    "content_sha256": report.content_sha256, "size_bytes": report.size_bytes})
            archive.writestr("manifest.json", json.dumps(manifest, separators=(",", ":")))
        data = output.getvalue()
        if len(data) > 3 * 1024 * 1024:
            raise ValidationError("Selected report archive exceeds the bounded download size.")
        require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_EXPORT)
        return data
