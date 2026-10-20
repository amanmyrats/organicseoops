"""Owner-only temporary Paddle portal links; never persist or log signed portal URLs."""

import re
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import AuditEvent, AuditEventType, Organization, PaddleSellerConfiguration, PaddleSubscription
from .paddle_seller import paddle_seller_secrets
from .services import Action, require_organization_action


_PORTAL_HOSTS = {"sandbox": "sandbox-customer-portal.paddle.com", "live": "customer-portal.paddle.com"}


def parse_portal_link(*, response, environment, customer_id):
    if type(response) is not dict or type(response.get("data")) is not dict:
        raise ValidationError("Provider portal response is unavailable.")
    data = response["data"]
    urls = data.get("urls")
    general = urls.get("general") if type(urls) is dict else None
    url = general.get("overview") if type(general) is dict else None
    if (environment not in _PORTAL_HOSTS or data.get("customer_id") != customer_id
        or type(url) is not str or not 1 <= len(url) <= 2048
        or type(data.get("id")) is not str or not re.fullmatch(r"cpls_[a-z0-9]{26}", data["id"])):
        raise ValidationError("Provider portal session does not match this customer.")
    try:
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, strict_parsing=True)
    except ValueError:
        raise ValidationError("Provider portal link is unavailable.") from None
    if (any(ord(char) < 33 or char == "\\" for char in url)
        or parsed.scheme != "https" or parsed.netloc != _PORTAL_HOSTS[environment]
        or parsed.username or parsed.password or parsed.fragment
        or not re.fullmatch(r"/cpl_[a-z0-9]{26}", parsed.path)
        or set(query) != {"action", "token"} or query["action"] != ["overview"]
        or len(query["token"]) != 1 or not re.fullmatch(r"[A-Za-z0-9._-]{1,1024}", query["token"][0])):
        raise ValidationError("Provider portal link is unavailable.")
    return url


def create_organization_portal(*, organization, actor, subscription_get=None, portal_create=None):
    from .paddle_transport import paddle_portal_create, paddle_subscription_get

    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
        subscription = PaddleSubscription.objects.select_for_update().filter(organization=organization).first()
        seller = PaddleSellerConfiguration.objects.select_for_update().filter(
            environment=settings.PADDLE_ENVIRONMENT, state=PaddleSellerConfiguration.State.ACTIVE).first()
        if subscription is None or seller is None or subscription.environment != seller.environment:
            raise ValidationError("Billing portal is unavailable.")
        api_key, _webhook_secret = paddle_seller_secrets(seller.environment)
        identity = (subscription.pk, subscription.customer_id, subscription.subscription_id,
                    subscription.environment, seller.rotated_at)
    subscription_get = subscription_get or paddle_subscription_get
    portal_create = portal_create or paddle_portal_create
    response = subscription_get(environment=identity[3], subscription_id=identity[2], api_key=api_key)
    data = response.get("data") if type(response) is dict else None
    if (type(data) is not dict or data.get("id") != identity[2] or data.get("customer_id") != identity[1]
        or data.get("status") not in {"active", "past_due", "paused", "canceled"}):
        raise ValidationError("Provider subscription does not match this organization.")
    portal = portal_create(environment=identity[3], customer_id=identity[1],
                           subscription_id=identity[2], api_key=api_key)
    url = parse_portal_link(response=portal, environment=identity[3], customer_id=identity[1])
    with transaction.atomic():
        organization = Organization.objects.select_for_update().get(pk=organization.pk)
        require_organization_action(organization=organization, user=actor, action=Action.MANAGE_BILLING)
        current = PaddleSubscription.objects.select_for_update().filter(organization=organization).first()
        seller = PaddleSellerConfiguration.objects.select_for_update().filter(
            environment=identity[3], state=PaddleSellerConfiguration.State.ACTIVE).first()
        if (current is None or seller is None or (current.pk, current.customer_id,
            current.subscription_id, current.environment, seller.rotated_at) != identity):
            raise ValidationError("Billing ownership changed; refresh before opening the portal.")
        AuditEvent.objects.create(organization=organization, actor=actor,
            event_type=AuditEventType.BILLING_PORTAL_OPENED,
            details={"environment": identity[3], "subscription_id": identity[2]})
    return url
