from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from tenancy.models import AuditEvent, AuditEventType, Organization, Project
from tenancy.services import Action, require_project_action

from .models import AIModel, AIProviderAccount, AIRoutingPolicy
from .services import _require_permission


def configure_ai_text_route(*, actor, project, model_id, account_id, fallback_model_ids,
                            max_output_tokens, max_cost_usd, timeout_seconds, revision, policy_id):
    from jobs.ai_text import _selection, validate_ai_text_input

    if (type(revision) is not int or revision < 0
        or (policy_id is not None and (type(policy_id) is not int or policy_id < 1))
        or type(model_id) is not int or model_id < 1
        or type(account_id) is not int or account_id < 1
        or type(fallback_model_ids) is not list or len(fallback_model_ids) > 2
        or any(type(value) is not int or value < 1 for value in fallback_model_ids)
        or len(set(fallback_model_ids)) != len(fallback_model_ids) or model_id in fallback_model_ids
        or type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 30):
        raise ValidationError("Choose a bounded AI routing policy.")
    data = validate_ai_text_input({"model_id": model_id, "account_id": account_id, "prompt": "x",
                                   "max_output_tokens": max_output_tokens, "max_cost_usd": max_cost_usd,
                                   "allow_free": False})
    with transaction.atomic():
        if project is not None:
            org = Organization.objects.select_for_update().get(pk=project.organization_id)
            project = Project.objects.select_for_update().get(pk=project.pk, organization=org)
            require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        current = AIRoutingPolicy.objects.select_for_update().filter(project=project, task_key="ai_text").first()
        if project is None:
            _require_permission(actor, "providers.change_airoutingpolicy" if current else "providers.add_airoutingpolicy")
        if policy_id != (current.pk if current else None) or revision != (current.revision if current else 0):
            raise ValidationError("Routing settings changed; refresh before saving.")
        model, account = _selection(data, organization_id=project.organization_id if project else None)
        if model.access_tier != AIModel.AccessTier.STANDARD or (project is None and account.organization_id is not None):
            raise ValidationError("Automatic routing requires verified standard access.")
        for fallback_id in fallback_model_ids:
            fallback_data = {**data, "model_id": fallback_id}
            fallback, candidate_account = _selection(fallback_data, organization_id=project.organization_id if project else None)
            if fallback.access_tier != AIModel.AccessTier.STANDARD or candidate_account.provider_id != model.provider_id:
                raise ValidationError("Fallback must use the same provider, account and standard access.")
        policy = current or AIRoutingPolicy(project=project, task_key="ai_text")
        policy.model = model
        policy.account = account
        policy.fallback_model_ids = fallback_model_ids
        policy.max_output_tokens = max_output_tokens
        policy.max_cost_usd = Decimal(max_cost_usd)
        policy.timeout_seconds = timeout_seconds
        policy.revision = revision + 1
        policy.save()
        AuditEvent.objects.create(organization=project.organization if project else None, project=project,
                                  actor=actor, event_type=AuditEventType.AI_ROUTING_UPDATED,
                                  details={"policy_id": policy.pk, "task_key": "ai_text",
                                           "revision": policy.revision, "model_id": model.pk,
                                           "account_id": account.pk, "fallback_model_ids": fallback_model_ids,
                                           "max_output_tokens": max_output_tokens,
                                           "max_cost_usd": str(policy.max_cost_usd),
                                           "timeout_seconds": timeout_seconds})
    return policy


def remove_ai_text_route(*, actor, project, revision, policy_id):
    if (type(revision) is not int or revision < 0
        or (policy_id is not None and (type(policy_id) is not int or policy_id < 1))):
        raise ValidationError("Refresh AI routing settings before removal.")
    with transaction.atomic():
        if project is not None:
            organization = Organization.objects.select_for_update().get(pk=project.organization_id)
            project = Project.objects.select_for_update().get(pk=project.pk, organization=organization)
            require_project_action(project=project, user=actor, action=Action.MANAGE_PROJECT)
        else:
            actor = _require_permission(actor, "providers.change_airoutingpolicy")
        policy = AIRoutingPolicy.objects.select_for_update().filter(project=project, task_key="ai_text").first()
        if policy is None:
            if revision != 0 or policy_id is not None:
                raise ValidationError("Routing settings changed; refresh before removal.")
            return False
        if policy.pk != policy_id or policy.revision != revision:
            raise ValidationError("Routing settings changed; refresh before removal.")
        policy_id = policy.pk
        policy.delete()
        AuditEvent.objects.create(organization=project.organization if project else None, project=project,
                                  actor=actor, event_type=AuditEventType.AI_ROUTING_UPDATED,
                                  details={"policy_id": policy_id, "task_key": "ai_text", "removed": True,
                                           "revision": revision})
    return True


def choose_ai_text_route(*, project, prompt, max_output_tokens, max_cost_usd):
    from jobs.ai_text import _selection

    policy = AIRoutingPolicy.objects.filter(project=project, task_key="ai_text").first()
    source = "project"
    if policy is None:
        policy = AIRoutingPolicy.objects.filter(project__isnull=True, task_key="ai_text").first()
        source = "system"
    if policy is None:
        raise ValidationError("No AI text default has been configured.")
    effective_tokens = min(max_output_tokens, policy.max_output_tokens)
    effective_cost = min(Decimal(max_cost_usd), policy.max_cost_usd)
    for index, model_id in enumerate([policy.model_id, *policy.fallback_model_ids]):
        data = {"model_id": model_id, "account_id": policy.account_id, "prompt": prompt,
                "max_output_tokens": effective_tokens, "max_cost_usd": f"{effective_cost:.6f}",
                "allow_free": False}
        try:
            model, account = _selection(data, organization_id=project.organization_id)
        except (ValidationError, PermissionDenied):
            continue
        if model.access_tier == AIModel.AccessTier.STANDARD and model.provider_id == policy.account.provider_id:
            return model, account, data, {"routing_source": source, "routing_policy_id": policy.pk,
                                          "routing_policy_revision": policy.revision, "fallback_index": index,
                                          "timeout_seconds": policy.timeout_seconds}
    raise ValidationError("No configured model meets current scope, capability and budget requirements.")
