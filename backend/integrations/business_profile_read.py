"""Synchronous, metadata-free consent/read attempts. Never enqueue or retain responses."""
from datetime import timedelta
import hashlib
import re
import time

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from jobs.models import JobCancellation, JobRun, JobStatus, JobStep
from jobs.usage import UsageLimitError, reserve_usage, settle_usage, usage_denial
from providers.google_app import lock_google_application
from tenancy.models import Organization
from .business_profile import MEMORY_SECONDS, POLICY_VERSION
from .business_profile_oauth import (_current_authority, complete_business_oauth,
                                      refresh_business_grant, require_business_grant)
from .business_profile_tokens import exchange_business_code
from .business_profile_transport import read_authorized_business_profile
from .google_tokens import GoogleTokenError
from .models import BusinessProfileOAuthGrant, BusinessProfileOAuthIntent
from .oauth import OAuthStateError, _STATE, _session_digest
from .search_console_transport import SearchConsoleTransportError

HANDLER = "business_profile_request"
STAGES = {"consent": ("token_exchange",), "read": ("token_refresh", "accounts_list", "locations_list", "reviews_list")}


class BusinessRequestError(Exception):
    def __init__(self, category):
        self.category = category
        super().__init__(category)


def validate_business_job(job, *, current=False):
    data = job.input_snapshot
    if (type(data) is not dict or data.get("operation") not in STAGES
        or job.method_version != POLICY_VERSION or job.config_snapshot or job.output
        or job.schedule_id or job.retry_of_id or job.scheduled_for or not job.idempotency_key):
        raise ValidationError("Business Profile requests accept only metadata-free explicit attempts.")
    keys = {"operation", "policy_version", "accepted", "intent_id"} if data["operation"] == "consent" else {
        "operation", "policy_version", "accepted", "grant_id", "grant_revision"}
    if (set(data) != keys or data["policy_version"] != POLICY_VERSION or data["accepted"] is not True
        or any(type(data[key]) is not int or not 0 <= data[key] <= 2**63 - 1
               for key in keys - {"operation", "policy_version", "accepted"})
        or data.get("intent_id", data.get("grant_id")) < 1):
        raise ValidationError("Choose current consent or grant identifiers and accept the feature policy.")
    if current:
        _context(job, initiating=True)


def _context(job, *, initiating=False):
    data = job.input_snapshot
    if data["operation"] == "read":
        grant = BusinessProfileOAuthGrant.objects.filter(pk=data["grant_id"], project_id=job.project_id,
                                                         organization_id=job.organization_id).first()
        if grant is None:
            raise PermissionDenied
        require_business_grant(grant=grant, actor=job.actor, expected_revision=data["grant_revision"])
        return grant
    intent = BusinessProfileOAuthIntent.objects.filter(pk=data["intent_id"], project_id=job.project_id,
                                                       organization_id=job.organization_id).first()
    if (intent is None or intent.status != ("pending" if initiating else "consumed")
        or intent.expires_at <= timezone.now()):
        raise PermissionDenied
    _current_authority(intent, job.actor)
    return intent


def _checkpoint(job):
    current = JobRun.objects.get(pk=job.pk)
    if current.status != JobStatus.RUNNING or JobCancellation.objects.filter(job_id=job.pk).exists():
        raise BusinessRequestError("cancelled")
    _context(job)
    denied = usage_denial(job=job)
    if denied:
        raise UsageLimitError("Business Profile allowance unavailable.", category=denied)
    if timezone.now() >= job.created_at + timedelta(seconds=60):
        raise BusinessRequestError("request_expired")


def _begin(*, project, actor, data, request_key):
    if type(request_key) is not str or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", request_key):
        raise ValidationError("Use a bounded new business request key.")
    with transaction.atomic():
        lock_google_application()
        Organization.objects.select_for_update().get(pk=project.organization_id)
        if JobRun.objects.filter(project=project, handler=HANDLER, idempotency_key=request_key).exists():
            raise BusinessRequestError("request_already_attempted")
        # One client-wide bounded attempt, rather than quota-circumventing parallel tenant reads.
        if JobRun.objects.filter(handler=HANDLER, status=JobStatus.RUNNING).exists():
            raise BusinessRequestError("client_busy")
        job = JobRun.objects.create(organization_id=project.organization_id, project=project, actor=actor,
            handler=HANDLER, method_version=POLICY_VERSION, idempotency_key=request_key, input_snapshot=data)
        reserve_usage(job=job, provider="business_profile", units=len(STAGES[data["operation"]]))
        job.status = JobStatus.RUNNING
        job.save(update_fields=["status", "updated_at"])
    return job


def _before_request(job, stage):
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=job.organization_id)
        current = JobRun.objects.select_for_update(no_key=True).get(pk=job.pk)
        _checkpoint(current)
        sequence = current.steps.count() + 1
        stages = STAGES[current.input_snapshot["operation"]]
        if sequence > len(stages) or stages[sequence - 1] != stage:
            raise BusinessRequestError("request_already_attempted")
        # Commit attempted-request accounting before transport; unknown outcomes are never resent.
        JobStep.objects.create(job=current, sequence=sequence, name=stage, status=JobStep.Status.RUNNING)


def finish_business_attempt(job, *, error="", stale_before=None):
    with transaction.atomic():
        lock_google_application()
        Organization.objects.select_for_update().get(pk=job.organization_id)
        current = JobRun.objects.select_for_update(no_key=True).get(pk=job.pk)
        if current.status != JobStatus.RUNNING or stale_before is not None and current.updated_at > stale_before:
            return False
        if not error:
            _checkpoint(current)
            if current.steps.count() != len(STAGES[current.input_snapshot["operation"]]):
                raise BusinessRequestError("request_outcome_unknown")
            if current.input_snapshot["operation"] == "read":
                grant = BusinessProfileOAuthGrant.objects.select_for_update().get(pk=current.input_snapshot["grant_id"])
                if grant.state == "pending_selection":
                    grant.state, grant.revision = "active", grant.revision + 1
                    grant.save(update_fields=["state", "revision", "updated_at"])
        current.status = JobStatus.FAILED if error else JobStatus.SUCCEEDED
        current.error_category = error
        current.save(update_fields=["status", "error_category", "updated_at"])
        settle_usage(job=current, actual_units=current.steps.count())
        return True


def _failure(job, error):
    category = (error.category if isinstance(error, (BusinessRequestError, GoogleTokenError,
        SearchConsoleTransportError, UsageLimitError)) else "actor_or_source_revoked"
        if isinstance(error, PermissionDenied) else "credential_or_scope_unavailable"
        if isinstance(error, (ValidationError, OAuthStateError)) else "request_outcome_unknown")
    finish_business_attempt(job, error=category)
    return BusinessRequestError(category)


@sensitive_variables()
def read_business_profile(*, project, actor, grant_id, grant_revision, policy_version, accepted, request_key,
                          refresh=None, collect=read_authorized_business_profile, clock=time.monotonic):
    deadline = clock() + 25  # Fits the deployed API's default 30-second process timeout.
    job = _begin(project=project, actor=actor, request_key=request_key, data={"operation": "read", "grant_id": grant_id,
        "grant_revision": grant_revision, "policy_version": policy_version, "accepted": accepted})
    try:
        grant = _context(job)
        if deadline - clock() < 10:  # Token transport has its own fixed ten-second maximum.
            raise BusinessRequestError("timeout")
        tokens = refresh_business_grant(grant=grant, actor=actor, expected_revision=grant_revision,
            before_request=lambda stage: _before_request(job, stage), **({"refresh": refresh} if refresh else {}))
        _checkpoint(job)
        if clock() >= deadline:
            raise BusinessRequestError("timeout")
        payload = collect(project=project, actor=actor, selection=dict(grant.intent.selection), access_token=tokens.access_token,
            checkpoint=lambda: _checkpoint(job), before_request=lambda stage: _before_request(job, stage),
            clock=clock, deadline=deadline)
        if not finish_business_attempt(job):
            raise BusinessRequestError("request_outcome_unknown")
        return {"project_id": project.pk, "job_id": job.pk, "grant_id": grant.pk,
            "grant_revision": grant_revision + int(grant.state == "pending_selection"), "policy_version": POLICY_VERSION,
            "collected_at": timezone.now().isoformat(),
            "expires_at": (job.created_at + timedelta(seconds=MEMORY_SECONDS)).isoformat(), "result": payload,
            "reserved_units": 4, "actual_units": 4}
    except Exception as error:
        raise _failure(job, error) from None


@sensitive_variables()
def complete_business_consent(*, actor, session_key, state, callback_url, code, exchange=exchange_business_code):
    if type(state) is not str or not _STATE.fullmatch(state):
        raise OAuthStateError("Business Profile consent is invalid or expired.")
    intent = BusinessProfileOAuthIntent.objects.select_related("project").filter(
        state_digest=hashlib.sha256(state.encode()).hexdigest(), actor=actor,
        session_digest=_session_digest(session_key), redirect_uri=callback_url, status="pending").first()
    if intent is None:
        raise OAuthStateError("Business Profile consent is invalid or expired.")
    job = _begin(project=intent.project, actor=actor, request_key=f"consent-{intent.pk}", data={"operation": "consent",
        "intent_id": intent.pk, "policy_version": POLICY_VERSION, "accepted": True})
    def counted_exchange(**kwargs):
        _before_request(job, "token_exchange")
        return exchange(**kwargs)
    try:
        grant = complete_business_oauth(actor=actor, session_key=session_key, state=state, callback_url=callback_url,
                                        code=code, exchange=counted_exchange)
        if not finish_business_attempt(job):
            raise BusinessRequestError("request_outcome_unknown")
        return grant
    except Exception as error:
        raise _failure(job, error) from None


def recover_business_attempts(*, limit=100, stale_seconds=90):
    if type(limit) is not int or not 1 <= limit <= 100 or type(stale_seconds) is not int or stale_seconds < 90:
        raise ValidationError("Choose bounded business attempt recovery.")
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    jobs = JobRun.objects.filter(handler=HANDLER, status=JobStatus.RUNNING, updated_at__lte=cutoff).order_by("pk")[:limit]
    return sum(finish_business_attempt(job, error="request_outcome_unknown", stale_before=cutoff) for job in jobs)
