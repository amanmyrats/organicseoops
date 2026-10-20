from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.auth_backends import AuthenticationBackend
from allauth.mfa.adapter import DefaultMFAAdapter
from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import override
from allauth.account.models import EmailAddress

from .models import AccountEmailDelivery, EmailDeliveryState, User, UserManager
from .localization import product_email_language


class EmailAuthenticationBackend(AuthenticationBackend):
    def authenticate(self, request, **credentials):
        for field in ("email", "username"):
            if credentials.get(field):
                credentials[field] = UserManager.normalize_email(credentials[field])
        return super().authenticate(request, **credentials)


class AccountAdapter(DefaultAccountAdapter):
    def clean_email(self, email):
        return UserManager.normalize_email(email)

    def render_mail(self, template_prefix, email, context, headers=None):
        addresses = (list(EmailAddress.objects.filter(email=UserManager.normalize_email(email))
                          .select_related("user").order_by("pk")[:2]) if isinstance(email, str) else [])
        language = product_email_language(addresses[0].user if len(addresses) == 1 else None)
        with override(language):
            message = super().render_mail(template_prefix, email, context, headers=headers)
        if language == "tr":
            message.subject = f"{message.subject} (Türkçe taslak)"
        return message

    def send_mail(self, template_prefix, email, context):
        from tenancy.email_feedback import is_email_suppressed
        canonical = UserManager.normalize_email(email)
        addresses = list(EmailAddress.objects.filter(email=canonical).order_by("pk")[:2])
        purpose = template_prefix.rsplit("/", 1)[-1][:40]
        receipt = (AccountEmailDelivery.objects.create(address=addresses[0], purpose=purpose)
                   if len(addresses) == 1 else None)
        if is_email_suppressed(canonical):
            if receipt:
                receipt.state = EmailDeliveryState.SUPPRESSED
                receipt.finished_at = timezone.now()
                receipt.save(update_fields=["state", "finished_at"])
            return
        try:
            result = super().send_mail(template_prefix, email, context)
        except Exception:
            if receipt:
                receipt.state = EmailDeliveryState.UNKNOWN
                receipt.finished_at = timezone.now()
                receipt.save(update_fields=["state", "finished_at"])
            raise
        if receipt:
            receipt.state = EmailDeliveryState.RETURNED
            receipt.finished_at = timezone.now()
            receipt.save(update_fields=["state", "finished_at"])
        return result

    def save_user(self, request, user, form, commit=True):
        user.registration_origin = User.RegistrationOrigin.SELF_SERVICE
        return super().save_user(request, user, form, commit=commit)

    @transaction.atomic
    def confirm_email(self, request, email_address):
        user = User.objects.select_for_update().filter(
            pk=email_address.user_id, is_active=True, closed_at__isnull=True).first()
        if user is None:
            return False
        try:
            email_address.refresh_from_db(
                from_queryset=EmailAddress.objects.select_for_update().filter(user_id=user.pk))
        except EmailAddress.DoesNotExist:
            return False
        if email_address.verified:
            return False
        email_address.user = user
        previously_verified_primary = email_address.__class__.objects.filter(
            user_id=email_address.user_id,
            primary=True,
            verified=True,
        ).exclude(pk=email_address.pk).exists()
        confirmed = super().confirm_email(request, email_address)
        if confirmed and email_address.primary and not previously_verified_primary:
            User.objects.filter(pk=email_address.user_id, first_email_verified_at__isnull=True).update(
                first_email_verified_at=timezone.now(),
            )
        return confirmed


class StaffMFAAdapter(DefaultMFAAdapter):
    def _cipher(self):
        return MultiFernet([Fernet(key.encode()) for key in settings.MFA_ENCRYPTION_KEYS])

    def encrypt(self, text):
        return f"v1:{self._cipher().encrypt(text.encode()).decode()}"

    def decrypt(self, encrypted_text):
        version, separator, token = encrypted_text.partition(":")
        if separator != ":" or version != "v1":
            raise ValueError("Unsupported MFA secret encryption version")
        return self._cipher().decrypt(token.encode()).decode()

    def is_mfa_enabled(self, user, types=None):
        return bool(getattr(user, "is_staff", False) and super().is_mfa_enabled(user, types=types))

    def can_delete_authenticator(self, authenticator):
        return not authenticator.user.is_staff
