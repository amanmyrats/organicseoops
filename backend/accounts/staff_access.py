"""Current persisted-session staff assurance for explicit permission-scoped consumers."""
from types import SimpleNamespace

from django.contrib.auth import HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.core.exceptions import PermissionDenied
from django.utils.crypto import constant_time_compare


def require_staff_permissions(request, *, permissions):
    # Admin discovery precedes allauth's ready hook; import its flows only on use.
    from allauth.account.authentication import get_authentication_records
    from allauth.mfa.models import Authenticator
    from allauth.mfa.utils import is_mfa_enabled
    if not request.user.is_authenticated or not getattr(request, "session", None) or not request.session.session_key:
        raise PermissionDenied
    actor = get_user_model().objects.filter(pk=request.user.pk, is_active=True, is_staff=True).first()
    session = request.session.load()
    if (actor is None or not actor.has_perms(permissions)
        or session.get(SESSION_KEY) != str(actor.pk)
        or not constant_time_compare(session.get(HASH_SESSION_KEY, ""), actor.get_session_auth_hash())
        or not is_mfa_enabled(actor, types=[Authenticator.Type.TOTP])
        or not any(record.get("method") == "mfa" for record in get_authentication_records(SimpleNamespace(session=session)))):
        raise PermissionDenied
    return actor
