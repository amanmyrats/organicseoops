"""D152 unregistered prospective kernel. Actual publication configuration defaults off."""
from datetime import timedelta
from hashlib import sha256
import logging
import re
import secrets
from time import monotonic

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .models import PublicAnalyticsConsentEpoch, PublicAnalyticsObservation
from .public_analytics_policy import load_public_analytics_policy
from .public_analytics_source import CONSENT_VERSION, public_observation_source

METHOD = "public-consent-epoch-v1"
ERROR = "Public analytics is unavailable."


def _current_policy():
    try:
        return load_public_analytics_policy()
    except ValueError:
        raise ValidationError(ERROR) from None


@sensitive_variables()
def _proof_digest(proof):
    if type(proof) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{43}", proof):
        raise ValidationError(ERROR)
    return sha256(proof.encode("ascii")).hexdigest()


@sensitive_variables()
def _locked_epoch(proof):
    epoch = PublicAnalyticsConsentEpoch.objects.select_for_update().filter(proof_digest=_proof_digest(proof)).first()
    if epoch is None:
        raise ValidationError(ERROR)
    return epoch


def _eligible(epoch, digest):
    if epoch.policy_digest != digest or epoch.revoked_at is not None or not epoch.created_at <= timezone.now() < epoch.expires_at:
        raise ValidationError(ERROR)


@transaction.atomic
@sensitive_variables()
def issue_public_analytics_epoch(*, allowed, consent_version):
    if allowed is not True or consent_version != CONSENT_VERSION:
        raise ValidationError(ERROR)
    _content, digest = _current_policy()
    proof, now = secrets.token_urlsafe(32), timezone.now()
    epoch = PublicAnalyticsConsentEpoch.objects.create(proof_digest=_proof_digest(proof), policy_digest=digest,
                                                       created_at=now, expires_at=now + timedelta(minutes=15))
    _eligible(epoch, _current_policy()[1])
    return {"method": METHOD, "consent_version": CONSENT_VERSION, "receipt_proof": proof,
            "expires_at": epoch.expires_at.isoformat(), "policy_digest": digest}


@transaction.atomic
@sensitive_variables()
def record_public_observation(*, receipt_proof, candidate):
    epoch = _locked_epoch(receipt_proof)
    content, digest = _current_policy()
    _eligible(epoch, digest)
    try:
        source = public_observation_source(candidate, policy_content=content, expected_policy_digest=digest, current_choice=True)
    except ValueError:
        raise ValidationError(ERROR) from None
    key = {"epoch": epoch, "event_id": source["event_id"], "route_id": source["route_id"],
           "locale": source["locale"], "cta_id": source.get("cta_id", "")}
    observation = PublicAnalyticsObservation.objects.filter(**key).first()
    if observation is None:
        observation = PublicAnalyticsObservation.objects.create(**key, html_sha256=source["html_sha256"], occurred_at=timezone.now())
    elif observation.html_sha256 != source["html_sha256"]:
        raise ValidationError(ERROR)
    _eligible(epoch, _current_policy()[1])
    return {"method": "public-observation-receipt-v1", "state": "recorded", "event_id": observation.event_id,
            "route_id": observation.route_id, "locale": observation.locale,
            "occurred_at": observation.occurred_at.isoformat(),
            **({"cta_id": observation.cta_id} if observation.cta_id else {})}


@transaction.atomic
@sensitive_variables()
def withdraw_public_analytics_epoch(*, receipt_proof):
    # Policy loss/expiry cannot obstruct withdrawal. Unknown already-purged proof is idempotent.
    epoch = PublicAnalyticsConsentEpoch.objects.select_for_update().filter(proof_digest=_proof_digest(receipt_proof)).first()
    if epoch is not None:
        epoch.observations.all().delete()
        if epoch.revoked_at is None:
            PublicAnalyticsConsentEpoch.objects.filter(pk=epoch.pk, revoked_at__isnull=True).update(revoked_at=timezone.now())
    return {"method": METHOD, "state": "withdrawn"}


@transaction.atomic
def purge_expired_public_analytics_epochs(*, limit=100):
    """One bounded expiry batch; the later hourly runner must drain and monitor deadlines."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValidationError(ERROR)
    ids = list(PublicAnalyticsConsentEpoch.objects.select_for_update(skip_locked=True).filter(
        expires_at__lte=timezone.now()).order_by("expires_at", "pk").values_list("pk", flat=True)[:limit])
    PublicAnalyticsConsentEpoch.objects.filter(pk__in=ids).delete()
    return len(ids)


def public_analytics_cleanup_status():
    now = timezone.now()
    expired = PublicAnalyticsConsentEpoch.objects.filter(expires_at__lte=now)
    return {"expired_pending": expired.exists(),
            "deadline_missed": expired.filter(created_at__lte=now - timedelta(minutes=75)).exists()}


def drain_expired_public_analytics_epochs():
    """Bound each invocation, continue remaining work rather than wait another hour."""
    before = public_analytics_cleanup_status()
    started = monotonic()
    for _ in range(100):
        removed = purge_expired_public_analytics_epochs(limit=500)
        if removed == 0 or monotonic() - started >= 25:
            break
    status = public_analytics_cleanup_status()
    if before["deadline_missed"] or status["deadline_missed"]:
        logging.getLogger(__name__).error("public_analytics.cleanup_overdue")
    return status


def retained_public_observation_counts():
    """Separate short-lived public grain, never an operational acquisition funnel."""
    try:
        digest = _current_policy()[1]
    except ValidationError:
        digest = None
    now = timezone.now()
    observations = PublicAnalyticsObservation.objects.filter(epoch__policy_digest=digest,
        epoch__created_at__lte=now, epoch__expires_at__gt=now, epoch__revoked_at__isnull=True)
    counts = {event: {"state": "derivable" if digest else "unavailable",
                      "grain": "consent_epoch_route_locale" + ("_cta" if event == "public_cta_selected" else ""),
                      "count": observations.filter(event_id=event).count() if digest else None}
              for event in ("public_page_view", "public_cta_selected")}
    # Do not return a count under an authority displaced during the reads.
    if digest is not None and _current_policy()[1] != digest:
        raise ValidationError(ERROR)
    return {"dictionary_version": "acquisition-v1", "basis": "current_unexpired_public_consent_epochs",
            "funnel_rates_available": False, "milestones": counts, "cleanup": public_analytics_cleanup_status()}
