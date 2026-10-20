from http import HTTPStatus

from allauth.core import ratelimit
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.db.models import Count, Max, Sum
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from config.artifacts import ArtifactStorageError, ArtifactValidationError

from .api import _authenticated, _error, _payload, _response
from .customer_snapshot import (reserve_bounded_customer_snapshot, current_customer_snapshot,
                                discard_failed_customer_snapshot, private_snapshot_part)
from .models import Organization, OrganizationCustomerExport, OrganizationCustomerExportPart
from .services import Action, require_organization_action


def _organization(request, organization_id):
    return Organization.objects.for_user(request.user).filter(pk=organization_id).first()


@require_http_methods(["GET", "POST"])
def organization_customer_snapshot(request, organization_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = _organization(request, organization_id)
    if organization is None:
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    if request.method == "GET":
        if not ratelimit.consume(request, action="organization_export_snapshot_read", user=request.user):
            return _error("Too many export requests. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
        try:
            require_organization_action(organization=organization, user=request.user,
                                        action=Action.ORGANIZATION_EXPORT)
        except PermissionDenied:
            return _error("Owner export unavailable.", status=HTTPStatus.FORBIDDEN)
        rows = list(OrganizationCustomerExport.objects.filter(organization=organization,
            format__in=["bounded-zip-v1", "source-parts-v2", "coherent-parts-v3"]).order_by("-pk")[:4])
        if len(rows) > 3:
            return _error("Private export history requires review.", status=HTTPStatus.SERVICE_UNAVAILABLE)
        response = _response({"organization_id": organization.pk,
            "scope": "bounded_capture_history_not_complete_export",
            "snapshots": [{"id": row.pk, "state": row.delivery_state, "format": row.format,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "created_at": row.created_at.isoformat(),
                "manifest_path": (f"/api/organizations/{organization.pk}/export/snapshots/{row.pk}/"
                                  if row.delivery_state == row.State.READY else None)} for row in rows]})
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response
    if not ratelimit.consume(request, action="organization_export_snapshot", user=request.user):
        return _error("Too many export requests. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if len(request.body) > 256:
            raise ValidationError("Choose one private export request.")
        body = _payload(request, allowed={"request_key", "format"}, required={"request_key"})
        snapshot = reserve_bounded_customer_snapshot(organization=organization, actor=request.user,
            request_key=body["request_key"], format=body.get("format", "bounded-zip-v1"))
    except PermissionDenied:
        return _error("Owner export unavailable.", status=HTTPStatus.FORBIDDEN)
    except ValidationError:
        return _error("Private capture exceeds local limits or needs review.", status=HTTPStatus.CONFLICT)
    except (ArtifactStorageError, ArtifactValidationError, RuntimeError):
        return _error("Private export capture is unavailable.", status=HTTPStatus.SERVICE_UNAVAILABLE)
    response = _response({"organization_id": organization.pk, "snapshot_id": snapshot.pk,
                            "state": snapshot.delivery_state, "format": snapshot.format,
                            "expires_at": snapshot.expires_at.isoformat() if snapshot.expires_at else None,
                            "scope": ("sequential_source_parts_not_transactional" if snapshot.format == "source-parts-v2"
                                      else "coherent_customer_content_only" if snapshot.format == "coherent-parts-v3"
                                      else "bounded_customer_content_only"),
                           "manifest_path": (f"/api/organizations/{organization.pk}/export/snapshots/{snapshot.pk}/"
                                             if snapshot.delivery_state == snapshot.State.READY else None)},
                          status=HTTPStatus.ACCEPTED if snapshot.state == snapshot.State.PREPARING else HTTPStatus.OK)
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@require_GET
def organization_snapshot_manifest(request, organization_id, snapshot_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = _organization(request, organization_id)
    if organization is None:
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="organization_export_snapshot_read", user=request.user):
        return _error("Too many export requests. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        snapshot = current_customer_snapshot(organization=organization, actor=request.user,
                                             snapshot_id=snapshot_id)
    except PermissionDenied:
        return _error("Private snapshot unavailable.", status=HTTPStatus.NOT_FOUND)
    except (ArtifactStorageError, ArtifactValidationError):
        return _error("Private snapshot manifest requires review.", status=HTTPStatus.SERVICE_UNAVAILABLE)
    if snapshot.format in {"source-parts-v2", "coherent-parts-v3"}:
        from .customer_source_parts import CONSISTENCY, descriptor
        coherent = snapshot.format == "coherent-parts-v3"
        if coherent:
            from .customer_coherent_parts import CONSISTENCY
        try:
            position = request.GET.get("position", "0")
            if not position.isascii() or not position.isdecimal() or len(position) > 12:
                raise ValueError
            position = int(position)
            if set(request.GET) - {"position"} or len(request.GET.getlist("position")) > 1:
                raise ValueError
        except ValueError:
            return _error("Choose a bounded manifest page.", status=HTTPStatus.BAD_REQUEST)
        totals = snapshot.parts.aggregate(count=Count("pk"), size=Sum("size_bytes"), last=Max("position"))
        if (not totals["count"] or totals["size"] != snapshot.size_bytes
            or totals["last"] != totals["count"] - 1 or position >= totals["count"]):
            return _error("Private snapshot manifest requires review.", status=HTTPStatus.SERVICE_UNAVAILABLE)
        rows = list(snapshot.parts.filter(position__gte=position).order_by("position")[:50])
        parts = [{**descriptor(row), "download_path":
            f"/api/organizations/{organization.pk}/export/snapshots/{snapshot.pk}/parts/{row.position}/"} for row in rows]
        response = _response({"version": snapshot.format, "organization_id": organization.pk,
            "snapshot_id": snapshot.pk,
            "expires_at": snapshot.expires_at.isoformat() if snapshot.expires_at else None,
            "legal_export_complete": False, "scope": ("coherent_customer_content_only" if coherent
                                                   else "sequential_source_parts_not_transactional"),
            "consistency": CONSISTENCY, "capture_window": {"started_at": snapshot.progress["started_at"],
                "completed_at": snapshot.completed_at.isoformat()},
            "size_bytes": snapshot.size_bytes, "sha256": snapshot.content_sha256,
            "integrity": "sha256_chain_of_canonical_part_descriptors_from_32_zero_bytes",
            "part_count": totals["count"], "parts": parts,
            "next_position": rows[-1].position + 1 if rows[-1].position + 1 < totals["count"] else None,
            "excluded": ["restricted_billing_and_audit", "platform_and_oauth_credentials", "hidden_s3_and_backup_versions"]
                        + (["rows_created_after_content_snapshot"] if coherent else
                           ["rows_created_after_initial_high_water_ids", "concurrent_changes_outside_observed_windows"])})
        if coherent:
            try:
                current_customer_snapshot(organization=organization, actor=request.user, snapshot_id=snapshot_id)
            except PermissionDenied:
                return _error("Private snapshot unavailable.", status=HTTPStatus.NOT_FOUND)
            except (ArtifactStorageError, ArtifactValidationError):
                return _error("Private snapshot manifest requires review.", status=HTTPStatus.SERVICE_UNAVAILABLE)
        if snapshot.delivery_state != snapshot.State.READY:
            return _error("Private snapshot unavailable.", status=HTTPStatus.NOT_FOUND)
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response
    parts = list(OrganizationCustomerExportPart.objects.filter(export=snapshot).order_by("position"))
    if (not parts or sum(row.size_bytes for row in parts) != snapshot.size_bytes
        or any(row.position != index for index, row in enumerate(parts))):
        return _error("Private snapshot manifest requires review.", status=HTTPStatus.SERVICE_UNAVAILABLE)
    response = _response({"version": "bounded-organization-snapshot-v1", "organization_id": organization.pk,
        "snapshot_id": snapshot.pk,
        "expires_at": snapshot.expires_at.isoformat() if snapshot.expires_at else None,
        "legal_export_complete": False, "scope": "captured_bounded_customer_content_not_legal_or_backup_export",
        "captured_at": snapshot.completed_at.isoformat(), "size_bytes": snapshot.size_bytes,
        "sha256": snapshot.content_sha256, "parts": [{"position": row.position,
            "size_bytes": row.size_bytes, "sha256": row.content_sha256,
            "download_path": (f"/api/organizations/{organization.pk}/export/snapshots/{snapshot.pk}/"
                              f"parts/{row.position}/")} for row in parts],
        "excluded": ["restricted_billing_and_audit", "platform_and_oauth_credentials", "hidden_s3_and_backup_versions"]})
    if snapshot.delivery_state != snapshot.State.READY:
        return _error("Private snapshot unavailable.", status=HTTPStatus.NOT_FOUND)
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@require_GET
def organization_snapshot_part(request, organization_id, snapshot_id, position):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = _organization(request, organization_id)
    if organization is None:
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="organization_export_snapshot_read", user=request.user):
        return _error("Too many export requests. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        data, checksum = private_snapshot_part(organization=organization, actor=request.user,
                                                snapshot_id=snapshot_id, position=position)
    except PermissionDenied:
        return _error("Private snapshot part unavailable.", status=HTTPStatus.NOT_FOUND)
    except (ArtifactStorageError, ArtifactValidationError):
        return _error("Private snapshot part is unavailable.", status=HTTPStatus.SERVICE_UNAVAILABLE)
    response = HttpResponse(data, content_type="application/octet-stream")
    format = OrganizationCustomerExport.objects.filter(pk=snapshot_id, organization=organization).values_list(
        "format", flat=True).first()
    extension = "zip" if format in {"source-parts-v2", "coherent-parts-v3"} else "zip.part"
    response["Content-Disposition"] = f'attachment; filename="organization-{organization.pk}-snapshot-{snapshot_id}-{position}.{extension}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'"
    response["X-Content-SHA256"] = checksum
    return response


@require_POST
def organization_discard_failed_snapshot(request, organization_id, snapshot_id):
    if not _authenticated(request):
        return _error("Authentication required.", status=HTTPStatus.UNAUTHORIZED)
    organization = _organization(request, organization_id)
    if organization is None:
        return _error("Organization unavailable.", status=HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="organization_export_snapshot_discard", user=request.user):
        return _error("Too many export cleanup requests. Try again later.", status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if len(request.body) > 128 or _payload(request, allowed=set(), required=set()) != {}:
            raise ValidationError("Choose one failed capture.")
        state, removed = discard_failed_customer_snapshot(organization=organization, actor=request.user,
                                                           snapshot_id=snapshot_id)
    except PermissionDenied:
        return _error("Failed private capture unavailable.", status=HTTPStatus.NOT_FOUND)
    except ValidationError:
        return _error("Choose a failed capture only.", status=HTTPStatus.CONFLICT)
    except (ArtifactStorageError, ArtifactValidationError):
        return _error("Private cleanup is unavailable; retry after review.", status=HTTPStatus.SERVICE_UNAVAILABLE)
    response = _response({"organization_id": organization.pk, "snapshot_id": snapshot_id,
                          "state": state, "removed": removed},
                         status=HTTPStatus.OK if state == "discarded" else HTTPStatus.ACCEPTED)
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
