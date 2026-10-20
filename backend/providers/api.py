import json
import re
from decimal import Decimal, InvalidOperation
from http import HTTPStatus

from allauth.core import ratelimit
from django.db import IntegrityError
from django.db.models import Exists, OuterRef
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.debug import sensitive_variables, sensitive_post_parameters

from tenancy.models import Organization, Project
from tenancy.services import Action, require_organization_action, require_project_action

from .google_app import (google_analytics_oauth_client, google_business_oauth_client, google_oauth_client,
                         revoke_google_oauth_application, set_google_oauth_application)
from .models import AIModel, AIModelCapability, AIProvider, AIProviderAccount, AIProviderSecret, AIRoutingPolicy, GoogleOAuthApplication, OrganizationPerformanceKey, PerformanceAPIKey
from .routing import configure_ai_text_route, remove_ai_text_route
from .performance_key import (google_performance_key, revoke_organization_performance_key,
                              revoke_performance_key, set_organization_performance_key, set_performance_key)
from integrations.google_tokens import GoogleTokenError
from .services import (
    create_organization_provider_account, create_provider, create_stored_provider_account,
    configure_model, revoke_organization_provider_account, revoke_provider_account,
    set_organization_provider_secret, set_provider_secret,
)


def _response(data, status):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


def _staff(request, permission):
    return request.user.is_authenticated and request.user.is_active and request.user.is_staff and request.user.has_perm(permission)


def _payload(request, fields):
    if len(request.body) > 8192:
        raise ValueError
    data = json.loads(request.body)
    if type(data) is not dict or set(data) != fields:
        raise ValueError
    return data


@require_http_methods(["GET", "POST"])
def platform_providers(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if request.method == "GET":
        if not _staff(request, "providers.view_aiprovider") or not _staff(request, "providers.view_aiprovideraccount"):
            return _response({"message": "Staff provider permission required."}, HTTPStatus.FORBIDDEN)
        providers = list(AIProvider.objects.order_by("pk")[:101])
        accounts = list(AIProviderAccount.objects.filter(organization__isnull=True).annotate(
            _stored=Exists(AIProviderSecret.objects.filter(account_id=OuterRef("pk"))),
        ).order_by("pk")[:101])
        return _response({"providers": [{"id": provider.pk, "name": provider.name, "kind": provider.kind,
                                         "key": provider.key, "enabled": provider.enabled} for provider in providers[:100]],
                          "accounts": [{"id": account.pk, "provider_id": account.provider_id,
                                        "label": account.label, "state": account.state,
                                        "stored": account._stored} for account in accounts[:100]],
                          "has_more": len(providers) > 100 or len(accounts) > 100}, HTTPStatus.OK)
    if not _staff(request, "providers.add_aiprovider"):
        return _response({"message": "Staff provider permission required."}, HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="platform_provider_secret", user=request.user):
        return _response({"message": "Too many provider changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        payload = _payload(request, {"key", "name", "kind", "base_url"})
        provider = create_provider(actor=request.user, key=payload["key"], name=payload["name"],
                                   kind=payload["kind"], base_url=payload["base_url"], enabled=True)
    except PermissionDenied:
        return _response({"message": "Staff provider permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError, IntegrityError):
        return _response({"message": "Check the provider configuration."}, HTTPStatus.BAD_REQUEST)
    return _response({"id": provider.pk}, HTTPStatus.CREATED)


@require_http_methods(["GET", "POST"])
def platform_models(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if request.method == "GET":
        if not _staff(request, "providers.view_aimodel"):
            return _response({"message": "Staff model permission required."}, HTTPStatus.FORBIDDEN)
        models = list(AIModel.objects.order_by("pk")[:101])
        return _response({"models": [{"id": model.pk, "provider_id": model.provider_id,
                                      "identifier": model.identifier, "name": model.name,
                                      "capabilities": model.capabilities, "enabled": model.enabled,
                                      "max_output_tokens": model.max_output_tokens,
                                      "capability_source": model.capability_source,
                                      "capabilities_verified_at": model.capabilities_verified_at.isoformat()
                                      if model.capabilities_verified_at else None,
                                      "input_price_usd_per_million": str(model.input_price_usd_per_million)
                                      if model.input_price_usd_per_million is not None else None,
                                      "output_price_usd_per_million": str(model.output_price_usd_per_million)
                                      if model.output_price_usd_per_million is not None else None,
                                      "pricing_source": model.pricing_source, "access_tier": model.access_tier,
                                      "privacy_policy_url": model.privacy_policy_url} for model in models[:100]],
                          "has_more": len(models) > 100,
                          "capability_choices": AIModelCapability.values}, HTTPStatus.OK)
    if not (_staff(request, "providers.add_aimodel") or _staff(request, "providers.change_aimodel")):
        return _response({"message": "Staff model permission required."}, HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="platform_provider_secret", user=request.user):
        return _response({"message": "Too many model changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        data = _payload(request, {"provider_id", "identifier", "name", "capabilities", "max_output_tokens",
                                  "capability_source", "enabled", "input_price_usd_per_million",
                                  "output_price_usd_per_million", "pricing_source", "access_tier", "privacy_policy_url"})
        if type(data["provider_id"]) is not int or data["provider_id"] < 1 or type(data["enabled"]) is not bool:
            raise ValueError
        if data["max_output_tokens"] is not None and (type(data["max_output_tokens"]) is not int
                                                   or not 1 <= data["max_output_tokens"] <= 1_000_000):
            raise ValueError
        prices = (data["input_price_usd_per_million"], data["output_price_usd_per_million"])
        if any(value is not None and (type(value) is not str or not value or len(value) > 12
                                      or not re.fullmatch(r"\d{1,5}(?:\.\d{1,4})?", value))
               for value in prices):
            raise ValueError
        if (prices[0] is None) != (prices[1] is None):
            raise ValueError
        prices = tuple(Decimal(value) if value is not None else None for value in prices)
        provider = AIProvider.objects.filter(pk=data["provider_id"]).first()
        if provider is None:
            return _response({"message": "Provider not found."}, HTTPStatus.NOT_FOUND)
        model = configure_model(actor=request.user, provider=provider, identifier=data["identifier"],
                                name=data["name"], capabilities=data["capabilities"],
                                max_output_tokens=data["max_output_tokens"],
                                capability_source=data["capability_source"],
                                capabilities_verified_at=timezone.now() if data["capability_source"] else None,
                                input_price_usd_per_million=prices[0], output_price_usd_per_million=prices[1],
                                pricing_source=data["pricing_source"],
                                pricing_verified_at=timezone.now() if prices[0] is not None else None,
                                access_tier=data["access_tier"], privacy_policy_url=data["privacy_policy_url"],
                                enabled=data["enabled"])
    except PermissionDenied:
        return _response({"message": "Staff model permission required."}, HTTPStatus.FORBIDDEN)
    except (ValueError, TypeError, UnicodeError, InvalidOperation, ValidationError, IntegrityError):
        return _response({"message": "Check model capability evidence and limits."}, HTTPStatus.BAD_REQUEST)
    return _response({"id": model.pk}, HTTPStatus.OK)


def _route_payload(route):
    if route is None:
        return None
    return {"id": route.pk, "project_id": route.project_id, "model_id": route.model_id,
            "account_id": route.account_id, "fallback_model_ids": route.fallback_model_ids,
            "max_output_tokens": route.max_output_tokens, "max_cost_usd": str(route.max_cost_usd),
            "timeout_seconds": route.timeout_seconds, "revision": route.revision}


def _save_route(request, project):
    try:
        data = _payload(request, {"model_id", "account_id", "fallback_model_ids", "max_output_tokens",
                                  "max_cost_usd", "timeout_seconds", "revision", "policy_id"})
        policy = configure_ai_text_route(actor=request.user, project=project, **data)
    except PermissionDenied:
        return _response({"message": "Routing permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError, IntegrityError):
        return _response({"message": "Check the selected model, account, fallback and cost limits; refresh stale settings."},
                         HTTPStatus.CONFLICT)
    return _response({"policy": _route_payload(policy)}, HTTPStatus.OK)


def _remove_route(request, project):
    try:
        data = _payload(request, {"revision", "policy_id"})
        removed = remove_ai_text_route(actor=request.user, project=project,
                                       revision=data["revision"], policy_id=data["policy_id"])
    except PermissionDenied:
        return _response({"message": "Routing permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError):
        return _response({"message": "Routing settings changed; refresh before removal."}, HTTPStatus.CONFLICT)
    fallback = AIRoutingPolicy.objects.filter(project__isnull=True).first() if project else None
    return _response({"removed": removed, "policy": None, "effective": _route_payload(fallback)}, HTTPStatus.OK)


@require_http_methods(["GET", "POST", "DELETE"])
def platform_ai_routing(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if request.method == "GET":
        if not _staff(request, "providers.view_airoutingpolicy"):
            return _response({"message": "Staff routing permission required."}, HTTPStatus.FORBIDDEN)
        return _response({"policy": _route_payload(AIRoutingPolicy.objects.filter(project__isnull=True).first())},
                         HTTPStatus.OK)
    if not ratelimit.consume(request, action="platform_provider_secret", user=request.user):
        return _response({"message": "Too many routing changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    if request.method == "DELETE":
        return _remove_route(request, None)
    return _save_route(request, None)


@require_http_methods(["GET", "POST", "DELETE"])
def project_ai_routing(request, organization_id, project_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    project = Project.objects.for_user(request.user).filter(pk=project_id, organization_id=organization_id).first()
    if project is None:
        return _response({"message": "Project not found."}, HTTPStatus.NOT_FOUND)
    try:
        require_project_action(project=project, user=request.user,
                               action=Action.VIEW_PROJECT if request.method == "GET" else Action.MANAGE_PROJECT)
    except PermissionDenied:
        return _response({"message": "Project routing permission required."}, HTTPStatus.FORBIDDEN)
    if request.method == "GET":
        own = AIRoutingPolicy.objects.filter(project=project).first()
        system = AIRoutingPolicy.objects.filter(project__isnull=True).first() if own is None else None
        return _response({"policy": _route_payload(own), "effective": _route_payload(own or system)}, HTTPStatus.OK)
    if not ratelimit.consume(request, action="organization_provider_secret", user=request.user):
        return _response({"message": "Too many routing changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    if request.method == "DELETE":
        return _remove_route(request, project)
    return _save_route(request, project)


@require_http_methods(["POST"])
def platform_provider_accounts(request, provider_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if not _staff(request, "providers.add_aiprovideraccount") or not _staff(request, "providers.change_aiprovideraccount"):
        return _response({"message": "Staff provider permission required."}, HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="platform_provider_secret", user=request.user):
        return _response({"message": "Too many provider changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    provider = AIProvider.objects.filter(pk=provider_id).first()
    if provider is None:
        return _response({"message": "Provider not found."}, HTTPStatus.NOT_FOUND)
    try:
        payload = _payload(request, {"label", "secret"})
        account = create_stored_provider_account(actor=request.user, provider=provider,
                                                  label=payload["label"], secret=payload["secret"])
    except PermissionDenied:
        return _response({"message": "Staff provider permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError, IntegrityError):
        return _response({"message": "Check the provider account and encryption configuration."}, HTTPStatus.BAD_REQUEST)
    return _response({"id": account.pk, "configured": True}, HTTPStatus.CREATED)


@require_http_methods(["POST", "DELETE"])
def platform_provider_credential(request, provider_id, account_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if not request.user.is_staff or not request.user.has_perm("providers.change_aiprovideraccount"):
        return _response({"message": "Staff provider permission required."}, HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="platform_provider_secret", user=request.user):
        return _response({"message": "Too many provider changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    account = AIProviderAccount.objects.filter(pk=account_id, provider_id=provider_id,
                                               organization__isnull=True).first()
    if account is None:
        return _response({"message": "Provider account not found."}, HTTPStatus.NOT_FOUND)
    if request.method == "DELETE":
        try:
            _account, revoked = revoke_provider_account(actor=request.user, account=account)
        except PermissionDenied:
            return _response({"message": "Staff provider permission required."}, HTTPStatus.FORBIDDEN)
        return _response({"revoked": revoked}, HTTPStatus.OK)
    try:
        payload = _payload(request, {"secret"})
        set_provider_secret(actor=request.user, account=account, secret=payload["secret"])
    except PermissionDenied:
        return _response({"message": "Staff provider permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, UnicodeError, TypeError):
        return _response({"message": "Check the provider credential and encryption configuration."}, HTTPStatus.BAD_REQUEST)
    return _response({"configured": True, "account_id": account.pk}, HTTPStatus.OK)


def _organization(request, organization_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return None
    return Organization.objects.for_user(request.user).filter(pk=organization_id).first()


@sensitive_post_parameters()
@sensitive_variables()
@require_http_methods(["GET", "POST", "DELETE"])
def platform_youtube_key(request):
    from allauth.account.authentication import get_authentication_records
    from allauth.mfa.models import Authenticator
    from allauth.mfa.utils import is_mfa_enabled
    from .models import YouTubeAPIKey
    from .youtube_key import set_youtube_key, revoke_youtube_key
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    if (not request.user.is_staff or not is_mfa_enabled(request.user, types=[Authenticator.Type.TOTP])
        or not any(row.get("method") == "mfa" for row in get_authentication_records(request))):
        return _response({"message": "Current staff MFA is required."}, HTTPStatus.FORBIDDEN)
    record = YouTubeAPIKey.objects.filter(key="primary").first()
    permission = ("providers.view_youtubeapikey" if request.method == "GET" else
        "providers.change_youtubeapikey" if record else "providers.add_youtubeapikey")
    if not _staff(request, permission):
        return _response({"message": "YouTube settings permission required."}, HTTPStatus.FORBIDDEN)
    if request.method == "GET":
        return _response({"state": record.state if record else "unconfigured",
            "api_project": record.api_project if record else "", "daily_limit": record.daily_limit if record else None}, HTTPStatus.OK)
    if not ratelimit.consume(request, action="platform_provider_secret", user=request.user):
        return _response({"message": "Too many provider changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if request.method == "DELETE":
            _record, changed = revoke_youtube_key(actor=request.user)
            return _response({"revoked": changed}, HTTPStatus.OK)
        data = _payload(request, {"api_key", "api_project", "daily_limit"})
        set_youtube_key(actor=request.user, value=data["api_key"], api_project=data["api_project"], daily_limit=data["daily_limit"])
    except PermissionDenied:
        return _response({"message": "YouTube settings permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError, IntegrityError):
        return _response({"message": "Check the dedicated key, original API project, encryption and daily ceiling."}, HTTPStatus.CONFLICT)
    return _response({"configured": True}, HTTPStatus.OK)


@require_http_methods(["GET", "POST"])
def organization_provider_accounts(request, organization_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    organization = _organization(request, organization_id)
    if organization is None:
        return _response({"message": "Organization not found."}, HTTPStatus.NOT_FOUND)
    try:
        require_organization_action(organization=organization, user=request.user,
                                    action=Action.MANAGE_PROVIDER_CREDENTIAL)
    except PermissionDenied:
        return _response({"message": "Organization provider permission required."}, HTTPStatus.FORBIDDEN)
    if request.method == "GET":
        providers = list(AIProvider.objects.filter(enabled=True).order_by("pk")[:101])
        accounts = list(AIProviderAccount.objects.filter(organization=organization).annotate(
            _stored=Exists(AIProviderSecret.objects.filter(account_id=OuterRef("pk"))),
        ).order_by("pk")[:101])
        return _response({"providers": [{"id": row.pk, "name": row.name, "kind": row.kind} for row in providers[:100]],
                          "accounts": [{"id": row.pk, "provider_id": row.provider_id, "label": row.label,
                                        "state": row.state, "stored": row._stored} for row in accounts[:100]],
                          "has_more": len(providers) > 100 or len(accounts) > 100}, HTTPStatus.OK)
    if not ratelimit.consume(request, action="organization_provider_secret", user=request.user):
        return _response({"message": "Too many provider changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        payload = _payload(request, {"provider_id", "label", "secret"})
        if type(payload["provider_id"]) is not int:
            raise ValueError
        provider = AIProvider.objects.filter(pk=payload["provider_id"], enabled=True).first()
        if provider is None:
            raise ValueError
        account = create_organization_provider_account(actor=request.user, organization=organization,
                                                        provider=provider, label=payload["label"],
                                                        secret=payload["secret"])
    except PermissionDenied:
        return _response({"message": "Organization provider permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError, IntegrityError):
        return _response({"message": "Check the organization provider credential."}, HTTPStatus.BAD_REQUEST)
    return _response({"id": account.pk, "configured": True}, HTTPStatus.CREATED)


@require_http_methods(["POST", "DELETE"])
def organization_provider_credential(request, organization_id, account_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    organization = _organization(request, organization_id)
    if organization is None:
        return _response({"message": "Organization not found."}, HTTPStatus.NOT_FOUND)
    account = AIProviderAccount.objects.filter(pk=account_id, organization=organization).first()
    if account is None:
        return _response({"message": "Provider account not found."}, HTTPStatus.NOT_FOUND)
    if not ratelimit.consume(request, action="organization_provider_secret", user=request.user):
        return _response({"message": "Too many provider changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if request.method == "DELETE":
            _account, revoked = revoke_organization_provider_account(actor=request.user, organization=organization,
                                                                      account=account)
            return _response({"revoked": revoked}, HTTPStatus.OK)
        payload = _payload(request, {"secret"})
        set_organization_provider_secret(actor=request.user, organization=organization, account=account,
                                         secret=payload["secret"])
    except PermissionDenied:
        return _response({"message": "Organization provider permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, TypeError, UnicodeError):
        return _response({"message": "Check the organization provider credential."}, HTTPStatus.BAD_REQUEST)
    return _response({"configured": True, "account_id": account.pk}, HTTPStatus.OK)


@require_http_methods(["GET", "POST", "DELETE"])
def platform_google_oauth_app(request, key="primary"):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    record = GoogleOAuthApplication.objects.filter(key=key).first()
    if request.method == "GET":
        if not _staff(request, "providers.view_googleoauthapplication"):
            return _response({"message": "Staff application permission required."}, HTTPStatus.FORBIDDEN)
        if record is None:
            try:
                {"primary": google_oauth_client, "analytics": google_analytics_oauth_client,
                 "business_profile": google_business_oauth_client}[key]()
                state = "environment_reference"
            except (GoogleTokenError, ValidationError):
                state = "unconfigured"
        else:
            state = record.state
        return _response({"state": state,
                          "redirect_uri": record.redirect_uri if record and record.state == record.State.ACTIVE else ""},
                         HTTPStatus.OK)
    permission = "providers.change_googleoauthapplication" if record else "providers.add_googleoauthapplication"
    if not _staff(request, permission):
        return _response({"message": "Staff application permission required."}, HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="platform_provider_secret", user=request.user):
        return _response({"message": "Too many provider changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if request.method == "DELETE":
            _record, changed = revoke_google_oauth_application(actor=request.user, key=key)
            return _response({"revoked": changed}, HTTPStatus.OK)
        payload = _payload(request, {"client_id", "client_secret", "redirect_uri"})
        set_google_oauth_application(actor=request.user, client_id=payload["client_id"],
                                      client_secret=payload["client_secret"], redirect_uri=payload["redirect_uri"],
                                      key=key)
    except PermissionDenied:
        return _response({"message": "Staff application permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, GoogleTokenError, ValueError, UnicodeError, TypeError, IntegrityError):
        return _response({"message": "Check the Google application settings and disconnect pending grants first."},
                         HTTPStatus.CONFLICT)
    return _response({"configured": True}, HTTPStatus.OK)


@require_http_methods(["GET", "POST", "DELETE"])
def platform_google_analytics_app(request):
    return platform_google_oauth_app(request, key="analytics")


@require_http_methods(["GET", "POST", "DELETE"])
def platform_google_business_app(request):
    return platform_google_oauth_app(request, key="business_profile")


@require_http_methods(["GET", "POST", "DELETE"])
def platform_performance_key(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    record = PerformanceAPIKey.objects.filter(key="primary").first()
    if request.method == "GET":
        if not _staff(request, "providers.view_performanceapikey"):
            return _response({"message": "Staff performance permission required."}, HTTPStatus.FORBIDDEN)
        if record is None:
            try:
                google_performance_key()
                state = "environment_reference"
            except ValidationError:
                state = "unconfigured"
        else:
            state = record.state
        return _response({"state": state}, HTTPStatus.OK)
    permission = "providers.change_performanceapikey" if record else "providers.add_performanceapikey"
    if not _staff(request, permission):
        return _response({"message": "Staff performance permission required."}, HTTPStatus.FORBIDDEN)
    if not ratelimit.consume(request, action="platform_provider_secret", user=request.user):
        return _response({"message": "Too many provider changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if request.method == "DELETE":
            _record, changed = revoke_performance_key(actor=request.user)
            return _response({"revoked": changed}, HTTPStatus.OK)
        payload = _payload(request, {"api_key"})
        set_performance_key(actor=request.user, value=payload["api_key"])
    except PermissionDenied:
        return _response({"message": "Staff performance permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, UnicodeError, TypeError, IntegrityError):
        return _response({"message": "Check the performance API key and encryption configuration."},
                         HTTPStatus.CONFLICT)
    return _response({"configured": True}, HTTPStatus.OK)


@require_http_methods(["GET", "POST", "DELETE"])
def organization_performance_key(request, organization_id):
    if not request.user.is_authenticated or not request.user.is_active:
        return _response({"message": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
    organization = _organization(request, organization_id)
    if organization is None:
        return _response({"message": "Organization not found."}, HTTPStatus.NOT_FOUND)
    try:
        require_organization_action(organization=organization, user=request.user,
                                    action=Action.MANAGE_PROVIDER_CREDENTIAL)
    except PermissionDenied:
        return _response({"message": "Organization performance permission required."}, HTTPStatus.FORBIDDEN)
    if request.method == "GET":
        record = OrganizationPerformanceKey.objects.filter(organization=organization).first()
        return _response({"state": record.state if record else "unconfigured"}, HTTPStatus.OK)
    if not ratelimit.consume(request, action="organization_provider_secret", user=request.user):
        return _response({"message": "Too many provider changes."}, HTTPStatus.TOO_MANY_REQUESTS)
    try:
        if request.method == "DELETE":
            _record, changed = revoke_organization_performance_key(actor=request.user, organization=organization)
            return _response({"revoked": changed}, HTTPStatus.OK)
        payload = _payload(request, {"api_key"})
        set_organization_performance_key(actor=request.user, organization=organization, value=payload["api_key"])
    except PermissionDenied:
        return _response({"message": "Organization performance permission required."}, HTTPStatus.FORBIDDEN)
    except (ValidationError, ValueError, UnicodeError, TypeError, IntegrityError):
        return _response({"message": "Check the organization performance credential."}, HTTPStatus.CONFLICT)
    return _response({"configured": True}, HTTPStatus.OK)
