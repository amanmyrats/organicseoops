import json
from hashlib import sha256
from http import HTTPStatus
from tempfile import TemporaryFile

from allauth.account.internal.flows.email_verification import send_verification_email_to_address
from allauth.account.internal.flows import password_change as password_change_flow
from allauth.account.models import EmailAddress, EmailConfirmation
from allauth.core import ratelimit
from allauth.account.internal.flows.reauthentication import did_recently_authenticate
from allauth.usersessions.internal.flows.sessions import end_sessions
from allauth.usersessions.models import UserSession
from django.contrib.auth.password_validation import validate_password
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.forms import EmailField
from django.http import FileResponse, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from config.observability import redact

from .models import AccountEmailDelivery, User, UserManager
from .closure import close_personal_access
from .localization import product_email_language


def _write_personal_account_export(actor, output):
    from tenancy.models import OrganizationMembership

    header = {"version": "personal-account-export-v1", "scope": "own_account_not_organization_content",
        "recorded_at": timezone.now().isoformat(),
        "account": {"id": actor.pk, "email": actor.email, "first_name": actor.first_name,
                    "last_name": actor.last_name, "product_language": actor.product_language,
                    "registration_origin": actor.registration_origin,
                    "first_email_verified_at": (actor.first_email_verified_at.isoformat()
                                                if actor.first_email_verified_at else None)}}
    groups = {
        "emails": ({"email": row.email, "verified": row.verified, "primary": row.primary}
                   for row in EmailAddress.objects.filter(user=actor).order_by("pk").iterator(chunk_size=100)),
        "memberships": ({"organization_id": row.organization_id, "organization_name": row.organization.name,
                         "role": row.role} for row in OrganizationMembership.objects.filter(user=actor)
                        .select_related("organization").order_by("pk").iterator(chunk_size=100)),
        "mail_diagnostics": ({"purpose": row.purpose, "state": row.state,
                              "attempted_at": row.attempted_at.isoformat()}
                             for row in AccountEmailDelivery.objects.filter(address__user=actor)
                             .order_by("pk").iterator(chunk_size=100)),
        "sessions": ({"created_at": row.created_at.isoformat(), "ip": row.ip,
                      "last_seen_at": row.last_seen_at.isoformat(), "user_agent": redact(row.user_agent)}
                     for row in UserSession.objects.filter(user=actor).order_by("pk").iterator(chunk_size=100)),
    }
    digest = sha256()

    def write(text):
        data = text.encode("utf-8")
        output.write(data)
        digest.update(data)

    write(json.dumps(header, ensure_ascii=False, separators=(",", ":"))[:-1])
    for name, rows in groups.items():
        write(f',"{name}":[')
        for index, row in enumerate(rows):
            if index:
                write(",")
            write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        write("]")
    write("}")
    size = output.tell()
    output.seek(0)
    return size, digest.hexdigest()


@require_POST
def personal_account_export(request):
    if not request.user.is_authenticated or not request.user.is_active:
        status, body = HTTPStatus.UNAUTHORIZED, {"message": "Authentication required."}
    elif not did_recently_authenticate(request):
        status, body = HTTPStatus.FORBIDDEN, {"message": "Reauthenticate before exporting personal data."}
    elif not ratelimit.consume(request, action="account_export", user=request.user):
        status, body = HTTPStatus.TOO_MANY_REQUESTS, {"message": "Too many account exports. Try again later."}
    else:
        try:
            if len(request.body) > 128:
                raise ValueError
            if request.content_type == "application/x-www-form-urlencoded":
                if set(request.POST) != {"csrfmiddlewaretoken"} or len(request.POST.getlist("csrfmiddlewaretoken")) != 1:
                    raise ValueError
            elif _json_object(request) != {}:
                raise ValueError
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError, ValueError):
            status, body = HTTPStatus.BAD_REQUEST, {"message": "Choose an own-account export."}
        else:
            from tenancy.models import AuditEvent, AuditEventType

            output = None
            try:
                with transaction.atomic():
                    actor = User.objects.select_for_update().get(pk=request.user.pk, is_active=True,
                                                                 closed_at__isnull=True)
                    output = TemporaryFile(mode="w+b")
                    size, digest = _write_personal_account_export(actor, output)
                    AuditEvent.objects.create(actor=actor, event_type=AuditEventType.ACCOUNT_EXPORTED,
                                              details={"size_bytes": size})
                response = FileResponse(output, content_type="application/json", as_attachment=True,
                                        filename="personal-account.json")
            except (OSError, DatabaseError, User.DoesNotExist):
                if output is not None:
                    output.close()
                status, body = HTTPStatus.SERVICE_UNAVAILABLE, {"message": "Account export is unavailable. Retry after reauthentication."}
            except Exception:
                if output is not None:
                    output.close()
                raise
            else:
                response["Cache-Control"] = "private, no-store"
                response["Referrer-Policy"] = "no-referrer"
                response["X-Robots-Tag"] = "noindex, nofollow"
                response["X-Content-Type-Options"] = "nosniff"
                response["Content-Security-Policy"] = "default-src 'none'"
                response["X-Content-SHA256"] = digest
                return response
    response = JsonResponse(body, status=status)
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@require_GET
def personal_account_closure_status(request):
    if not request.user.is_authenticated or not request.user.is_active:
        response = JsonResponse({"message": "Authentication required."}, status=HTTPStatus.UNAUTHORIZED)
    else:
        from tenancy.models import OrganizationMembership

        active_membership = OrganizationMembership.objects.filter(user=request.user,
                                                                  organization__closed_at__isnull=True).exists()
        response = JsonResponse({"action_available": settings.SELF_SERVICE_ACCOUNT_CLOSURE_ENABLED
                                 and not active_membership and not request.user.is_staff,
                                 "requires_org_exit": active_membership,
                                 "retained_identity": "restricted_policy_review_not_erased"})
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@require_POST
def personal_account_close(request):
    if not request.user.is_authenticated or not request.user.is_active:
        status, body = HTTPStatus.UNAUTHORIZED, {"message": "Authentication required."}
    elif not settings.SELF_SERVICE_ACCOUNT_CLOSURE_ENABLED:
        status, body = HTTPStatus.SERVICE_UNAVAILABLE, {"message": "Personal closure is not available."}
    elif not ratelimit.consume(request, action="account_close", user=request.user):
        status, body = HTTPStatus.TOO_MANY_REQUESTS, {"message": "Too many closure requests. Try again later."}
    else:
        try:
            if len(request.body) > 256 or _json_object(request) != {
                "acknowledge_restricted_identity_retention": True}:
                raise ValueError
            close_personal_access(actor=request.user, request=request)
        except PermissionDenied:
            status, body = HTTPStatus.FORBIDDEN, {"message": "Reauthenticate before closing personal access."}
        except ValidationError:
            status, body = HTTPStatus.CONFLICT, {"message": "Transfer ownership or leave active organizations first."}
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError, ValueError):
            status, body = HTTPStatus.BAD_REQUEST, {"message": "Acknowledge retained identity before closing."}
        else:
            status, body = HTTPStatus.ACCEPTED, {"state": "access_closed",
                         "retained_identity": "restricted_policy_review_not_erased",
                         "other_organization_data": "unchanged"}
    response = JsonResponse(body, status=status)
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_GET
def platform_email_deliveries(request):
    if not request.user.is_authenticated or not request.user.is_active:
        status, payload = HTTPStatus.UNAUTHORIZED, {"message": "Authentication required."}
    elif not request.user.is_staff or not request.user.has_perm("accounts.view_accountemaildelivery"):
        status, payload = HTTPStatus.FORBIDDEN, {"message": "Staff delivery permission required."}
    else:
        status, payload = HTTPStatus.GONE, {"message": "Global account-mail discovery retired. Inspect one exact current record."}
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _json_object(request):
    payload = json.loads(request.body)
    if not isinstance(payload, dict):
        raise ValueError
    return payload


@require_http_methods(["GET", "POST"])
def product_language(request):
    if not request.user.is_authenticated or not request.user.is_active:
        response = JsonResponse({"message": "Authentication required."}, status=HTTPStatus.UNAUTHORIZED)
    else:
        if request.method == "POST":
            try:
                if len(request.body) > 128:
                    raise ValueError
                payload = _json_object(request)
                if set(payload) != {"language"} or payload["language"] not in User.ProductLanguage.values:
                    raise ValueError
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError, ValueError):
                response = JsonResponse({"message": "Choose English or Turkish."}, status=HTTPStatus.BAD_REQUEST)
                response["Cache-Control"] = "private, no-store"
                return response
            request.user.product_language = payload["language"]
            request.user.save(update_fields=["product_language"])
        response = JsonResponse({"language": request.user.product_language,
                                 "current_ui_language": "en",
                                 "current_email_language": product_email_language(request.user)})
    response["Cache-Control"] = "private, no-store"
    return response


@require_GET
def verification_status(request):
    key = request.headers.get("x-email-verification-key", "").strip().lower()
    confirmation = None
    if 0 < len(key) <= 64:
        confirmation = EmailConfirmation.objects.select_related("email_address").filter(key=key).first()

    if not confirmation or confirmation.sent is None:
        state = "invalid"
    elif confirmation.email_address.verified:
        state = "used"
    elif confirmation.key_expired():
        state = "expired"
    else:
        state = "pending"
    return JsonResponse({"state": state})


@require_POST
def resend_verification(request):
    try:
        payload = _json_object(request)
        email = UserManager.normalize_email(EmailField().clean(payload.get("email")))
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError, ValueError, ValidationError):
        return JsonResponse(
            {"errors": [{"param": "email", "message": "Enter a valid email address."}]},
            status=HTTPStatus.BAD_REQUEST,
        )

    address = EmailAddress.objects.filter(email=email, verified=False).select_related("user").first()
    if address is None:
        address = EmailAddress(email=email)
    sent = send_verification_email_to_address(
        request,
        address,
        skip_enumeration_mails=True,
    )
    if not sent:
        response = JsonResponse(
            {"message": "Please wait before requesting another verification email."},
            status=HTTPStatus.TOO_MANY_REQUESTS,
        )
        response["Retry-After"] = "180"
        return response
    return JsonResponse(
        {"message": "If verification is available, a new email has been sent."},
        status=HTTPStatus.ACCEPTED,
    )


@require_POST
def change_password(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return JsonResponse({"message": "Authentication required."}, status=HTTPStatus.UNAUTHORIZED)
    if not ratelimit.consume(request, action="change_password", user=request.user):
        return JsonResponse({"message": "Too many password changes. Try again later."},
                            status=HTTPStatus.TOO_MANY_REQUESTS)
    try:
        payload = _json_object(request)
        current_password = payload.get("current_password")
        new_password = payload.get("new_password")
        if not isinstance(current_password, str) or not isinstance(new_password, str):
            raise ValueError
        if not request.user.check_password(current_password):
            raise ValidationError("invalid current password")
        validate_password(new_password, request.user)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError, ValueError, ValidationError):
        return JsonResponse(
            {"message": "Check your current password and the new password requirements."},
            status=HTTPStatus.BAD_REQUEST,
        )

    sessions = list(UserSession.objects.filter(user=request.user))
    password_change_flow.change_password(request.user, new_password)
    password_change_flow.finalize_password_change(request, request.user)
    end_sessions(request, sessions)
    return HttpResponse(status=HTTPStatus.NO_CONTENT)


@require_POST
def logout_all(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return JsonResponse({"message": "Authentication required."}, status=HTTPStatus.UNAUTHORIZED)
    if not ratelimit.consume(request, action="logout_all", user=request.user):
        return JsonResponse({"message": "Too many sign-out requests. Try again later."},
                            status=HTTPStatus.TOO_MANY_REQUESTS)
    end_sessions(request, list(UserSession.objects.filter(user=request.user)))
    return HttpResponse(status=HTTPStatus.NO_CONTENT)
