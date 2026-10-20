"""Dedicated GBP scope and purpose/project-bound refresh material; no environment credential fallback."""
from urllib.parse import urlsplit

from cryptography.fernet import InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError
from django.views.decorators.debug import sensitive_variables

from providers.services import _provider_cipher
from .business_profile import SCOPE
from .google_tokens import GoogleTokenError, _credential, _parse_tokens, post_google_revoke_form, post_google_token_form

CALLBACK_PATH = "/api/integrations/google-business-profile/oauth/callback/"


class BusinessTokenRejected(GoogleTokenError):
    """Categorical failure carrying only syntactically revocable material to the private capture layer."""
    def __init__(self, category, revocable_token):
        self.revocable_token = revocable_token
        super().__init__(category)


@sensitive_variables()
def _business_tokens(payload, *, needs_refresh):
    material = None
    if type(payload) is dict:
        for key in ("refresh_token", "access_token"):
            try:
                material = _credential(payload.get(key))
                break
            except GoogleTokenError:
                pass
    try:
        return _parse_tokens(payload, needs_refresh=needs_refresh, expected_scope=SCOPE)
    except GoogleTokenError as error:
        if material is not None:
            raise BusinessTokenRejected(error.category, material) from None
        raise


def configured_business_redirect_uri(value):
    if (type(value) is not str or not 1 <= len(value) <= 512
        or any(ord(char) < 33 or ord(char) > 126 or char == "\\" for char in value)):
        raise ValidationError("Business Profile OAuth callback is unavailable.")
    try:
        parsed = urlsplit(value)
        valid_host = (parsed.scheme == "https" and bool(parsed.hostname) and parsed.port in {None, 443}) or (
            settings.DEBUG and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
            and parsed.port in {None, 80, 4200, 18000})
    except ValueError:
        valid_host = False
    if (not valid_host or parsed.username or parsed.password or parsed.path != CALLBACK_PATH
        or parsed.query or parsed.fragment):
        raise ValidationError("Business Profile OAuth callback is unavailable.")
    return value


def _prefix(organization_id, project_id):
    if any(type(value) is not int or not 1 <= value <= 2**63 - 1 for value in (organization_id, project_id)):
        raise GoogleTokenError("credential_unavailable")
    return f"gbp-refresh-v1:{organization_id}:{project_id}:"


def _cipher():
    try:
        return _provider_cipher()
    except (ValidationError, ValueError, TypeError, AttributeError):
        raise GoogleTokenError("credential_unavailable") from None


@sensitive_variables()
def encrypt_business_refresh_token(token, *, organization_id, project_id):
    _credential(token)
    return "v1:" + _cipher().encrypt((_prefix(organization_id, project_id) + token).encode()).decode()


@sensitive_variables()
def decrypt_business_refresh_token(encrypted, *, organization_id, project_id):
    prefix = _prefix(organization_id, project_id)
    if type(encrypted) is not str or not encrypted.startswith("v1:") or len(encrypted) > 8192:
        raise GoogleTokenError("credential_unavailable")
    try:
        value = _cipher().decrypt(encrypted[3:].encode()).decode()
        if not value.startswith(prefix):
            raise ValueError
        return _credential(value[len(prefix):])
    except (InvalidToken, ValueError, UnicodeError):
        raise GoogleTokenError("credential_unavailable") from None


@sensitive_variables()
def exchange_business_code(*, code, client_id, client_secret, redirect_uri, transport=post_google_token_form):
    redirect_uri = configured_business_redirect_uri(redirect_uri)
    _credential(code, limit=2048)
    _credential(client_id, limit=512)
    _credential(client_secret, limit=512)
    return _business_tokens(transport(form={"code": code, "client_id": client_id, "client_secret": client_secret,
        "grant_type": "authorization_code", "redirect_uri": redirect_uri}), needs_refresh=True)


@sensitive_variables()
def refresh_business_tokens(*, encrypted_refresh, organization_id, project_id, client_id, client_secret,
                            transport=post_google_token_form):
    _credential(client_id, limit=512)
    _credential(client_secret, limit=512)
    token = decrypt_business_refresh_token(encrypted_refresh, organization_id=organization_id, project_id=project_id)
    return _business_tokens(transport(form={"refresh_token": token, "client_id": client_id,
        "client_secret": client_secret, "grant_type": "refresh_token"}), needs_refresh=False)


@sensitive_variables()
def revoke_business_tokens(*, encrypted_refresh, organization_id, project_id, transport=post_google_revoke_form):
    token = decrypt_business_refresh_token(encrypted_refresh, organization_id=organization_id, project_id=project_id)
    if transport(token=token) is not True:
        raise GoogleTokenError("revocation_unconfirmed")
    return True
