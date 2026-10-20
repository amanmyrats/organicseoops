"""Own-project support record kernel; no registered intake, staff access or sending."""
import re
import unicodedata

from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from config.observability import redact
from .models import Organization, Project, SupportRequest


METHOD = "own-project-support-request-v2"
SCOPE = "own_retained_support_records_not_email_delivery_staff_response_or_job_access_authority"
FIELDS = ("id", "project_id", "requester_id", "job_id", "request_key", "category", "question", "no_sensitive_data", "created_at",
          "job__project_id", "job__organization_id", "project__organization_id")
COMMAND_FIELDS = frozenset({"request_key", "category", "question", "job_id", "no_sensitive_data"})


def _safe_id(value):
    if type(value) is not int or not 1 <= value < 2**53:
        raise ValidationError("Choose an exact support reference.")


def validate_support_command(command):
    if type(command) is not dict or set(command) != COMMAND_FIELDS:
        raise ValidationError("Provide one exact support request.")
    key, category, question = (command[name] for name in ("request_key", "category", "question"))
    if (type(key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,63}", key)
        or type(category) is not str or category not in SupportRequest.Category.values
        or command["no_sensitive_data"] is not True
        or type(question) is not str or not 1 <= len(question) <= 2000 or not question.strip()
        or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} and char not in "\n\t" for char in question)):
        raise ValidationError("Use a bounded plain-text question and confirm it contains no sensitive data.")
    if len(question.encode("utf-8")) > 8000 or redact(question) != question:
        raise ValidationError("Remove sensitive data from the support question.")
    if command["job_id"] is not None:
        _safe_id(command["job_id"])
    return dict(command)


def _row(row, assessed, *, detail=False):
    _safe_id(row["id"])
    validate_support_command({name: row[name] for name in COMMAND_FIELDS})
    if (timezone.is_naive(row["created_at"]) or row["created_at"] > assessed
        or (row["job_id"] is not None and (row["job__project_id"] != row["project_id"]
                                          or row["job__organization_id"] != row["project__organization_id"]))):
        raise ValidationError("Support request history needs review.")
    result = {"id": row["id"], "category": row["category"], "job_id": row["job_id"],
              "created_at": row["created_at"].isoformat(), "status": "received"}
    if detail:
        result["question"] = row["question"]
    return result


def create_support_request(*, project, actor, command):
    from jobs.support_job_reference import retained_project_job_reference
    from .services import Action, require_project_action
    command = validate_support_command(command)
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=project.organization_id)
        project = Project.objects.select_for_update().get(pk=project.pk, organization_id=project.organization_id)
        actor = get_user_model().objects.select_for_update().get(pk=actor.pk)
        require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
        queryset = SupportRequest.objects.filter(project=project, requester=actor, request_key=command["request_key"]).values(*FIELDS)
        original = queryset.first()
        if original:
            if {name: original[name] for name in COMMAND_FIELDS} != command:
                raise ValidationError("This request key already belongs to a different support question.")
        else:
            reference = None
            if command["job_id"] is not None:
                reference = retained_project_job_reference(project=project, actor=actor, job_id=command["job_id"])
                if reference["job"] is None:
                    raise ValidationError("Choose a retained job in the current project.")
            SupportRequest.objects.create(project=project, requester=actor, **command)
            original = queryset.get()
            if reference is not None and retained_project_job_reference(project=project, actor=actor, job_id=command["job_id"]) != reference:
                raise ValidationError("The retained job changed during support submission.")
        result = own_support_requests(project=project, actor=actor, request_id=original["id"])
        if queryset.first() != original:
            raise ValidationError("Support request changed during submission.")
        require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
        return result


def own_support_requests(*, project, actor, request_id=None):
    from .services import Action, require_project_action
    if request_id is not None:
        _safe_id(request_id)
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    assessed = timezone.now()
    queryset = SupportRequest.objects.filter(project=project, requester=actor).order_by("-created_at", "-pk").values(*FIELDS)
    if request_id is not None:
        queryset = queryset.filter(pk=request_id)
    original = list(queryset[:21])
    from .support_staff import support_update_history
    projected = [{**_row(row, assessed, detail=request_id is not None),
                  **support_update_history(row["id"], row["created_at"], assessed, detail=request_id is not None)} for row in original[:20]]
    result = {"method_version": METHOD, "project_id": project.pk, "actor_id": actor.pk, "scope": SCOPE}
    if request_id is None:
        result.update(requests=projected, has_more=len(original) > 20)
    else:
        result["request"] = projected[0] if projected else None
    if list(queryset[:21]) != original:
        raise ValidationError("Support request history changed during inspection.")
    require_project_action(project=project, user=actor, action=Action.VIEW_PROJECT)
    return result
