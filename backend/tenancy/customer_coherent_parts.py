"""Coherent retained content with one original view and fresh live authority."""
from contextlib import closing, contextmanager
from hashlib import sha256
from time import monotonic

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.utils import timezone
from psycopg import sql

from config.artifacts import ArtifactStorageError
from .customer_artifact_barrier import project_artifact_barrier, require_artifact_admission
from .artifacts import iter_project_artifact_keys
from .customer_source_parts import _artifact_pages, _initial_progress, _rows_page, encoded
from .models import Organization, Project
from .services import Action, require_organization_action

CONTENT_LIFETIME_SECONDS = 540  # Leave cleanup time before the capture task's 600s soft limit.
FORMAT = "coherent-parts-v3"
CONSISTENCY = "one_live_database_snapshot_and_admitted_visible_objects_not_legal_or_backup_export"
LOGFILE_FIELDS = ("pk", "project_id", "actor_id", "method_version", "input_snapshot", "config_snapshot")


def _logfile_window(jobs):
    digest, count, through = sha256(), 0, 0
    for job in jobs.order_by("pk").iterator(chunk_size=50):
        digest.update(encoded({field: getattr(job, field) for field in LOGFILE_FIELDS}))
        count += 1
        through = job.pk
    return {"count": count, "through": through, "sha256": digest.hexdigest()}


@contextmanager
def _content_snapshot(organization_id, deadline):
    if connection.vendor != "postgresql" or connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError("Coherent capture requires its own PostgreSQL transaction boundary.")
    with project_artifact_barrier(organization_id, shared=False, timeout_ms=_remaining_content_ms(deadline)) as owner:
        _remaining_content_ms(deadline)
        owner.set_autocommit(False)
        with owner.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL idle_in_transaction_session_timeout = '600s'")
            cursor.execute("SELECT pg_export_snapshot()")
            token = cursor.fetchone()[0]
        yield token


def _remaining_content_ms(deadline):
    remaining_ms = int((deadline - monotonic()) * 1000)
    if remaining_ms <= 0:
        raise ArtifactStorageError("Coherent content capture expired; its original view cannot resume.")
    return remaining_ms


@contextmanager
def _content_read(token, deadline):
    if connection.in_atomic_block or not connection.get_autocommit():
        raise RuntimeError("Content reads cannot share an authority transaction.")
    remaining_ms = _remaining_content_ms(deadline)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute(sql.SQL("SET TRANSACTION SNAPSHOT {}").format(sql.Literal(token)))
            cursor.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(remaining_ms)))
        yield


def _current_owner(organization_id, actor_id, *, check_sources=False, logfile_sources=None, logfile_window=None):
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization_id)
        actor = get_user_model().objects.get(pk=actor_id)
        require_organization_action(organization=organization, user=actor, action=Action.ORGANIZATION_EXPORT)
        if check_sources or logfile_sources is not None or logfile_window is not None:
            from jobs.bot_log_import import HANDLER, source_current
            from jobs.models import JobRun
            jobs = JobRun.objects.filter(organization=organization, handler=HANDLER)
            if logfile_window is not None and _logfile_window(jobs.filter(pk__lte=logfile_window["through"])) != logfile_window:
                raise PermissionDenied
            if logfile_sources is not None:
                originals = {row["pk"]: row for row in logfile_sources}
                jobs = list(jobs.filter(pk__in=originals))
                if len(jobs) != len(originals):
                    raise PermissionDenied
            else:
                jobs = jobs.iterator()
            for job in jobs:
                if logfile_sources is not None and any(
                    getattr(job, field) != value for field, value in originals[job.pk].items()
                ):
                    raise PermissionDenied
                if not source_current(job):
                    raise PermissionDenied


def _current_content(organization_id, actor_id, deadline):
    _current_owner(organization_id, actor_id)
    require_artifact_admission(organization_id, shared=False)
    _remaining_content_ms(deadline)


def coherent_customer_row_pages(*, organization_id, actor_id):
    """Yield bounded bytes outside the content transaction; exhaust or close the iterator.

    Consumers must still recheck authority when committing parts/READY. These
    database pages do not establish stable storage membership or legal export.
    """
    deadline = monotonic() + CONTENT_LIFETIME_SECONDS
    with _content_snapshot(organization_id, deadline) as token:
        yield from _coherent_rows(token, deadline, organization_id, actor_id)
        _original_source_authority(token, deadline, organization_id, actor_id)


def coherent_customer_content_pages(*, organization_id, actor_id):
    """Internal rows and visible object chunks under one view; exhaust or close it.

    Private-part/READY authority, claims and recovery still belong to the capture
    consumer. This format is not registered as a complete or legal export.
    """
    with coherent_customer_content(organization_id=organization_id, actor_id=actor_id) as (pages, validate, lineage):
        yield from pages
        validate()


@contextmanager
def coherent_customer_content(*, organization_id, actor_id):
    """Keep the original holder live through the consumer's final publication."""
    deadline = monotonic() + CONTENT_LIFETIME_SECONDS
    with _content_snapshot(organization_id, deadline) as token:
        from jobs.bot_log_import import HANDLER
        from jobs.models import JobRun
        with _content_read(token, deadline):
            lineage = _logfile_window(JobRun.objects.filter(organization_id=organization_id, handler=HANDLER))
        def validate():
            _current_owner(organization_id, actor_id, check_sources=True, logfile_window=lineage)
            require_artifact_admission(organization_id, shared=False)
            _remaining_content_ms(deadline)
        with closing(_coherent_content_pages(token, deadline, organization_id, actor_id)) as pages:
            yield pages, validate, lineage


def _coherent_content_pages(token, deadline, organization_id, actor_id):
    yield from _coherent_rows(token, deadline, organization_id, actor_id)
    after = 0
    while True:
        with _content_read(token, deadline):
            project = Project.objects.filter(organization_id=organization_id, pk__gt=after).order_by("pk").first()
        if project is None:
            break
        count = 0
        with closing(iter_project_artifact_keys(project=project)) as keys:
            while True:
                _current_content(organization_id, actor_id, deadline)
                try:
                    key = next(keys)
                except StopIteration:
                    break
                with closing(_artifact_pages(project, key, count)) as parts:
                    while True:
                        _current_content(organization_id, actor_id, deadline)
                        try:
                            data, source = next(parts)
                        except StopIteration:
                            break
                        _current_content(organization_id, actor_id, deadline)
                        yield data, source
                count += 1
        _current_content(organization_id, actor_id, deadline)
        yield b"[]", {"kind": "project_artifacts_complete", "project_id": project.pk,
                       "visible_objects_observed": count, "observed_at": timezone.now().isoformat()}
        after = project.pk
    _original_source_authority(token, deadline, organization_id, actor_id)


def _coherent_rows(token, deadline, organization_id, actor_id):
    _current_owner(organization_id, actor_id, check_sources=True)
    with _content_read(token, deadline):
        organization = Organization.objects.get(pk=organization_id)
        progress = _initial_progress(organization)
    while progress["phase"] == "rows":
        with _content_read(token, deadline):
            data, source = _rows_page(organization, progress)
        _current_content(organization_id, actor_id, deadline)
        yield data, source


def _original_source_authority(token, deadline, organization_id, actor_id):
    # Live-only scans miss captured jobs that were subsequently removed.
    from jobs.bot_log_import import HANDLER
    from jobs.models import JobRun
    after = 0
    while True:
        with _content_read(token, deadline):
            originals = list(JobRun.objects.filter(organization_id=organization_id, handler=HANDLER,
                pk__gt=after).order_by("pk").values("pk", "project_id", "actor_id", "method_version",
                    "input_snapshot", "config_snapshot")[:50])
        if not originals:
            break
        _current_owner(organization_id, actor_id, logfile_sources=originals)
        after = originals[-1]["pk"]
    _current_owner(organization_id, actor_id, check_sources=True)
    require_artifact_admission(organization_id, shared=False)
    _remaining_content_ms(deadline)
