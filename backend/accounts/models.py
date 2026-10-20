from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower
from django.utils.crypto import salted_hmac


def user_display(user):
    return user.email


class UserManager(BaseUserManager):
    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email):
        # Application identity is case-insensitive across the entire address.
        # Preserve dots and plus tags; provider-specific alias merging is unsafe.
        return super().normalize_email(email).strip().lower()

    def get_by_natural_key(self, username):
        return self.get(email=self.normalize_email(username))

    async def aget_by_natural_key(self, username):
        return await self.aget(email=self.normalize_email(username))

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    @transaction.atomic
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields["is_staff"] is not True or extra_fields["is_superuser"] is not True:
            raise ValueError("A superuser must have is_staff=True and is_superuser=True.")
        user = self.create_user(email, password, **extra_fields)
        from allauth.account.models import EmailAddress

        EmailAddress.objects.update_or_create(
            user=user,
            email=user.email,
            defaults={"primary": True, "verified": True},
        )
        return user


class User(AbstractUser):
    class RegistrationOrigin(models.TextChoices):
        SELF_SERVICE = "self_service", "Self-service"

    class ProductLanguage(models.TextChoices):
        ENGLISH = "en", "English"
        TURKISH = "tr", "Turkish"

    username = None
    email = models.EmailField("email address", unique=True)
    first_email_verified_at = models.DateTimeField(null=True, blank=True, editable=False)
    registration_origin = models.CharField(
        max_length=12, choices=RegistrationOrigin.choices, null=True, blank=True, editable=False,
    )
    product_language = models.CharField(max_length=2, choices=ProductLanguage.choices, default=ProductLanguage.ENGLISH)
    session_version = models.CharField(max_length=32, default="", blank=True, editable=False)
    closed_at = models.DateTimeField(null=True, blank=True, editable=False)
    identity_erased_at = models.DateTimeField(null=True, blank=True, editable=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    class Meta:
        constraints = [
            # Bulk/update/raw writes must not bypass normalized unique identity.
            models.CheckConstraint(
                condition=models.Q(email=Lower("email")) & models.Q(email__regex=r"^\S+$"),
                name="accounts_user_email_canonical",
            ),
            models.CheckConstraint(
                condition=models.Q(product_language__in=["en", "tr"]),
                name="accounts_user_product_language_valid",
            ),
            models.CheckConstraint(condition=models.Q(closed_at__isnull=True) | models.Q(is_active=False),
                                   name="accounts_closed_user_inactive"),
            models.CheckConstraint(condition=models.Q(identity_erased_at__isnull=True)
                | (models.Q(closed_at__isnull=False, is_active=False, first_name="", last_name="",
                            email__regex=r"^closed-[0-9a-f]{32}@accounts\.invalid$",
                            first_email_verified_at__isnull=True, registration_origin__isnull=True,
                            last_login__isnull=True) & models.Q(identity_erased_at__gte=models.F("closed_at"))),
                                   name="accounts_erased_user_closed"),
        ]

    def clean_fields(self, exclude=None):
        self.email = UserManager.normalize_email(self.email)
        super().clean_fields(exclude=exclude)

    def save(self, *args, **kwargs):
        if self.pk and (previous := User.objects.filter(pk=self.pk, closed_at__isnull=False).first()):
            if self.closed_at != previous.closed_at or self.is_active:
                raise ValidationError("A closed account cannot be reactivated.")
            if previous.identity_erased_at is not None and (
                self.identity_erased_at != previous.identity_erased_at or self.email != previous.email
            ):
                raise ValidationError("An erased account identity cannot be restored.")
        self.email = UserManager.normalize_email(self.email)
        self._meta.get_field("email").clean(self.email, self)
        return super().save(*args, **kwargs)

    def _get_session_auth_hash(self, secret=None):
        if not self.session_version:
            return super()._get_session_auth_hash(secret=secret)
        return salted_hmac(
            "django.contrib.auth.models.AbstractBaseUser.get_session_auth_hash",
            f"{self.password}:{self.session_version}",
            secret=secret,
            algorithm="sha256",
        ).hexdigest()


class EmailDeliveryState(models.TextChoices):
    ATTEMPTED = "attempted", "Attempted"
    RETURNED = "transport_returned", "Mail transport returned"
    UNKNOWN = "unknown", "Outcome unknown"
    SUPPRESSED = "suppressed", "Current address suppressed"


class RetainedTrialIdentity(models.Model):
    """Restricted, expiring abuse control; not anonymous or organization-owned."""
    digest = models.CharField(max_length=64, unique=True, editable=False)
    key_id = models.CharField(max_length=64, editable=False)
    policy_reference = models.CharField(max_length=64, editable=False)
    expires_at = models.DateTimeField(db_index=True, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(digest__regex=r"^[0-9a-f]{64}$"),
                                   name="accounts_trial_identity_digest_valid"),
            models.CheckConstraint(condition=models.Q(key_id__regex=r"^[0-9a-f]{64}$"),
                                   name="accounts_trial_identity_key_valid"),
            models.CheckConstraint(condition=models.Q(policy_reference__regex=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"),
                                   name="accounts_trial_identity_policy_valid"),
        ]


class AccountEmailDelivery(models.Model):

    address = models.ForeignKey("account.EmailAddress", on_delete=models.CASCADE,
                                related_name="organicseoops_delivery_attempts")
    purpose = models.CharField(max_length=40)
    state = models.CharField(max_length=20, choices=EmailDeliveryState.choices, default=EmailDeliveryState.ATTEMPTED)
    attempted_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(state__in=EmailDeliveryState.values),
                                   name="accounts_email_delivery_state_valid"),
            models.CheckConstraint(condition=(models.Q(state=EmailDeliveryState.ATTEMPTED, finished_at__isnull=True)
                | models.Q(state__in=[EmailDeliveryState.RETURNED, EmailDeliveryState.UNKNOWN,
                                      EmailDeliveryState.SUPPRESSED],
                           finished_at__isnull=False)), name="accounts_email_delivery_finished_valid"),
        ]
