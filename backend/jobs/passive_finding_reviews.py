"""Explicit private human priority, never measured severity or approved remediation."""
from datetime import datetime
import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from tenancy.models import Organization, Project
from tenancy.services import Action, require_project_action
from . import passive_finding_review_source as source
from .models import Opportunity
from .passive_header_findings import _row_pin


METHOD = "passive-human-prioritization-v1"
JUDGMENT_FIELDS = ("priority", "estimated_effort", "business_relevance", "review_reason")


def _reader(family):
    if family == "header": return source.current_header_review_source
    if family == "resource": return source.current_resource_review_source
    if family == "tls": return source.current_tls_review_source
    if family == "redirect": return source.current_redirect_review_source
    if family == "redirect_chain": return source.current_redirect_chain_review_source
    raise ValidationError("Choose one fixed passive decision source.")


def _finding_contract(finding):
    for family in ("header", "resource", "tls", "redirect", "redirect_chain"):
        job_id = getattr(finding, f"source_passive_{family}_id")
        if job_id: return family, job_id
    raise ValidationError("Choose genuine materialized passive evidence.")


def validate_passive_opportunity(review):
    if type(review.passive_source_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", review.passive_source_sha256):
        raise ValidationError("Inspect and bind the original passive source before human prioritization.")
    family, job_id = _finding_contract(review.finding)
    current = _reader(family)(project=review.project, actor=review.actor, job_id=job_id, finding_id=review.finding_id)
    if current["source_sha256"] != review.passive_source_sha256:
        raise ValidationError("The inspected original passive source changed.")


def record_header_priority(**kwargs): return _record(family="header", **kwargs)
def record_resource_priority(**kwargs): return _record(family="resource", **kwargs)
def record_tls_priority(**kwargs): return _record(family="tls", **kwargs)
def record_redirect_priority(**kwargs): return _record(family="redirect", **kwargs)
def record_redirect_chain_priority(**kwargs): return _record(family="redirect_chain", **kwargs)


def current_header_priority(**kwargs): return _current(family="header", **kwargs)
def current_resource_priority(**kwargs): return _current(family="resource", **kwargs)
def current_tls_priority(**kwargs): return _current(family="tls", **kwargs)
def current_redirect_priority(**kwargs): return _current(family="redirect", **kwargs)
def current_redirect_chain_priority(**kwargs): return _current(family="redirect_chain", **kwargs)


def _latest(project, finding_id):
    return Opportunity.objects.filter(project=project, finding_id=finding_id).order_by("-revision").values().first()


def _validate_latest(project, finding_id, original, latest):
    if latest is None: return
    review = Opportunity.objects.get(pk=latest["id"], project=project, finding_id=finding_id)
    review.full_clean()
    if (review.passive_source_sha256 != original["source_sha256"]
        or not datetime.fromisoformat(original["finding"]["detected_at"]) <= review.created_at <= timezone.now()):
        raise ValidationError("Current human priority differs from the original passive source.")


def _final(project, actor, job_id, finding_id, read, original, latest):
    _validate_latest(project, finding_id, original, latest)
    if read(project=project, actor=actor, job_id=job_id, finding_id=finding_id) != original:
        raise PermissionDenied
    if _row_pin(_latest(project, finding_id)) != _row_pin(latest):
        raise PermissionDenied
    # Unchanged decision rows cannot retain authority across their final slow read.
    if read(project=project, actor=actor, job_id=job_id, finding_id=finding_id) != original:
        raise PermissionDenied
    if latest:
        reviewer = Opportunity.objects.select_related("actor").filter(pk=latest["id"], project=project).first()
        if reviewer is None: raise PermissionDenied
        require_project_action(project=project, user=reviewer.actor, action=Action.MANAGE_PROJECT)


def _record(*, family, project, actor, job_id, finding_id, source_sha256, expected_revision,
            priority, estimated_effort, business_relevance, reason):
    if (type(expected_revision) is not int or not 0 <= expected_revision < 65535
        or type(source_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", source_sha256)
        or any(type(value) is not str for value in (priority, estimated_effort, business_relevance))
        or priority not in Opportunity.Priority.values or estimated_effort not in {"unknown", "small", "medium", "large"}
        or business_relevance not in {"unknown", "low", "medium", "high"}
        or type(reason) is not str or not 1 <= len(reason.strip()) <= 240):
        raise ValidationError("Choose a bounded human judgment and the exact inspected source revision.")
    read = _reader(family)
    judgment = dict(zip(JUDGMENT_FIELDS, (priority, estimated_effort, business_relevance, reason.strip())))
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
        original = read(project=project, actor=actor, job_id=job_id, finding_id=finding_id)
        if original["source_sha256"] != source_sha256: raise PermissionDenied
        latest = _latest(project, finding_id)
        _validate_latest(project, finding_id, original, latest)
        revision = latest["revision"] if latest else 0
        if revision != expected_revision:
            if not (latest and revision == expected_revision + 1 and latest["actor_id"] == actor.pk
                and latest["passive_source_sha256"] == source_sha256
                and all(latest[key] == value for key, value in judgment.items())):
                raise ValidationError("Human priority changed; reload its latest revision.")
            review = Opportunity.objects.get(pk=latest["id"], project=project)
        else:
            review = Opportunity.objects.create(project=project, actor=actor, finding_id=finding_id,
                passive_source_sha256=source_sha256, revision=revision + 1, **judgment)
            latest = {field.attname: getattr(review, field.attname) for field in Opportunity._meta.concrete_fields}
        _final(project, actor, job_id, finding_id, read, original, latest)
        return review


def _current(*, family, project, actor, job_id, finding_id):
    read = _reader(family)
    original = read(project=project, actor=actor, job_id=job_id, finding_id=finding_id)
    latest = _latest(project, finding_id)
    _validate_latest(project, finding_id, original, latest)
    result = {"method_version": METHOD, "source": original, "decision": None if latest is None else {
        key: latest[key] for key in ("id", "revision", *JUDGMENT_FIELDS)},
        "reviewed_at": latest["created_at"].isoformat() if latest else None,
        "interpretation": "human_priority_not_measured_risk_severity_recommendation_approval_or_page_action"}
    _final(project, actor, job_id, finding_id, read, original, latest)
    return result
