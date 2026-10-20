import hashlib
from contextlib import contextmanager

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from tenancy.models import AuditEvent, AuditEventType, Organization, ProjectOriginVerification
from tenancy.services import (
    Action,
    ORIGIN_VERIFICATION_PATH,
    project_has_origin,
    require_project_action,
)

from .crawling import CrawlScope, FetchDenied, FetchError, SafeFetcher
from .models import JobCancellation, JobRun, JobStatus, JobStep
from .usage import settle_usage, usage_denial


METHOD_VERSION = "origin-http-file-v1"


def validate_origin_verification_input(data):
    if not isinstance(data, dict) or set(data) != {"verification_id"}:
        raise ValidationError("Check the origin verification input.")
    if type(data["verification_id"]) is not int or data["verification_id"] < 1:
        raise ValidationError("Check the origin verification input.")
    return data


def queue_origin_verification(*, verification, actor, idempotency_key):
    from .services import queue_job

    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=verification.organization_id)
        verification = ProjectOriginVerification.objects.select_for_update().select_related(
            "project", "project__organization"
        ).filter(
            pk=verification.pk,
            organization_id=verification.organization_id,
            project_id=verification.project_id,
        ).first()
        if verification is None:
            raise ValidationError("This origin verification is unavailable.")
        require_project_action(project=verification.project, user=actor, action=Action.MANAGE_PROJECT)
        if (
            verification.state != ProjectOriginVerification.State.PENDING
            or not project_has_origin(verification.project, verification.origin)
        ):
            raise ValidationError("This origin verification is not pending for a current project origin.")
        return queue_job(
            project=verification.project,
            actor=actor,
            handler="verify_project_origin",
            input_snapshot={"verification_id": verification.pk},
            idempotency_key=idempotency_key,
            config_snapshot={"challenge_digest": verification.challenge_digest},
        )


def execute_origin_verification(job_id, *, fetcher_factory=None):
    with _execution_lock(job_id) as acquired:
        if not acquired:
            return False
        try:
            return _execute_origin_verification(job_id, fetcher_factory=fetcher_factory)
        except Exception:
            return _finish(job_id, error_category="handler_failed")


def _execute_origin_verification(job_id, *, fetcher_factory):
    with transaction.atomic():
        organization_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
        if organization_id is None:
            return False
        Organization.objects.select_for_update().get(pk=organization_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").filter(pk=job_id).first()
        if job is None or job.handler != "verify_project_origin" or job.status not in {
            JobStatus.QUEUED, JobStatus.RUNNING,
        }:
            return False
        data = validate_origin_verification_input(job.input_snapshot)
        verification = ProjectOriginVerification.objects.select_for_update().filter(
            pk=data["verification_id"],
            organization_id=job.organization_id,
            project=job.project,
        ).first()
        denial = _denial(job, verification)
        if denial:
            job.status = JobStatus.CANCELLED
            job.error_category = denial
            job.save(update_fields=["status", "error_category", "updated_at"])
        else:
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.RUNNING
                job.save(update_fields=["status", "updated_at"])
            JobStep.objects.update_or_create(
                job=job,
                sequence=1,
                defaults={
                    "name": "Verify project origin",
                    "status": JobStep.Status.RUNNING,
                    "progress_percent": 10,
                    "output": {"verification_id": verification.pk, "origin": verification.origin},
                },
            )
            origin = verification.origin
            expected_digest = job.config_snapshot["challenge_digest"]
    if denial:
        settle_usage(job=job, actual_units=0)
        return True

    scope = CrawlScope.for_project(job.project)
    fetcher = fetcher_factory(scope) if fetcher_factory else SafeFetcher(
        scope,
        timeout=10,
        max_redirects=0,
        max_bytes=256,
    )
    challenge_url = f"{origin}{ORIGIN_VERIFICATION_PATH}"
    try:
        response = fetcher.fetch(
            challenge_url,
            before_request=lambda url: _check_request(job_id, verification.pk, url),
        )
    except VerificationStopped as stopped:
        return _finish(job_id, cancelled=True, error_category=str(stopped))
    except FetchError as error:
        return _finish(job_id, error_category=f"verification_{error.code}"[:64])
    if response.status != 200:
        return _finish(job_id, error_category="verification_http_status")
    if hashlib.sha256(response.body).hexdigest() != expected_digest:
        return _finish(job_id, error_category="verification_mismatch")
    return _finish(job_id, expected_digest=expected_digest)


class VerificationStopped(Exception):
    pass


def _check_request(job_id, verification_id, url):
    job = JobRun.objects.select_related("project", "actor").filter(pk=job_id).first()
    verification = ProjectOriginVerification.objects.filter(
        pk=verification_id,
        project_id=job.project_id if job else None,
    ).first()
    denial = _denial(job, verification)
    if not denial:
        try:
            CrawlScope.for_project(job.project).validate_url(url)
        except FetchDenied:
            denial = "scope_revoked"
    if denial:
        raise VerificationStopped(denial)


def _denial(job, verification):
    if job is None or verification is None:
        return "verification_unavailable"
    if JobCancellation.objects.filter(job=job).exists():
        return "cancelled"
    try:
        require_project_action(project=job.project, user=job.actor, action=Action.MANAGE_PROJECT)
    except PermissionDenied:
        return "actor_revoked"
    if verification.state != ProjectOriginVerification.State.PENDING:
        return "verification_unavailable"
    if job.config_snapshot != {"challenge_digest": verification.challenge_digest}:
        return "verification_stale"
    if not project_has_origin(job.project, verification.origin):
        return "scope_revoked"
    return usage_denial(job=job)


def _finish(job_id, *, expected_digest="", cancelled=False, error_category=""):
    with transaction.atomic():
        organization_id = JobRun.objects.filter(pk=job_id).values_list("organization_id", flat=True).first()
        if organization_id is None:
            return False
        Organization.objects.select_for_update().get(pk=organization_id)
        job = JobRun.objects.select_for_update(no_key=True).select_related("project", "actor").get(pk=job_id)
        if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return True
        verification = ProjectOriginVerification.objects.select_for_update().filter(
            pk=job.input_snapshot.get("verification_id"),
            organization_id=job.organization_id,
            project=job.project,
        ).first()
        denial = _denial(job, verification)
        if denial:
            cancelled = True
            error_category = denial
        succeeded = bool(expected_digest and verification and verification.challenge_digest == expected_digest)
        if job.status == JobStatus.QUEUED and not cancelled:
            job.status = JobStatus.RUNNING
            job.save(update_fields=["status", "updated_at"])
        if succeeded and not cancelled:
            verification.state = ProjectOriginVerification.State.VERIFIED
            verification.verified_at = timezone.now()
            verification.save(update_fields=["state", "verified_at", "updated_at"])
            AuditEvent.objects.create(
                organization=job.organization,
                project=job.project,
                event_type=AuditEventType.ORIGIN_VERIFICATION_VERIFIED,
                actor=job.actor,
                details={"verification_id": verification.pk, "origin": verification.origin, "job_id": job.pk},
            )
            job.status = JobStatus.SUCCEEDED
            job.error_category = ""
        elif cancelled:
            job.status = JobStatus.CANCELLED
            job.error_category = error_category
        else:
            job.status = JobStatus.FAILED
            job.error_category = error_category or "verification_failed"
        job.output = {
            "verification_id": verification.pk if verification else None,
            "origin": verification.origin if verification else "",
            "result": "verified" if job.status == JobStatus.SUCCEEDED else "not_verified",
        }
        job.save(update_fields=["status", "error_category", "output", "updated_at"])
        JobStep.objects.update_or_create(
            job=job,
            sequence=1,
            defaults={
                "name": "Verify project origin",
                "status": JobStep.Status.SUCCEEDED if succeeded and not cancelled else JobStep.Status.FAILED,
                "progress_percent": 100,
                "output": job.output,
                "error_category": job.error_category,
            },
        )
    settle_usage(job=job, actual_units=0)
    return True


@contextmanager
def _execution_lock(job_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [-int(job_id)])
        acquired = cursor.fetchone()[0]
    try:
        yield acquired
    finally:
        if acquired:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [-int(job_id)])
