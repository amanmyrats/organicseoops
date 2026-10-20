import re
from datetime import timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, URLValidator
from django.db import models
from django.db.models import Exists, OuterRef, Q
from django.db.models.functions import Lower
from django.utils import timezone

from accounts.models import UserManager


def normalize_origin(value):
    if not isinstance(value, str):
        raise ValidationError("Enter a valid HTTP or HTTPS origin.")
    value = value.strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
        hostname = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError):
        raise ValidationError("Enter a valid HTTP or HTTPS origin.") from None
    scheme = parsed.scheme.lower()
    if (
        scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or "*" in hostname
    ):
        raise ValidationError("Enter a valid HTTP or HTTPS origin.")
    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and (scheme, port) not in {("http", 80), ("https", 443)}:
        host = f"{host}:{port}"
    normalized = f"{scheme}://{host}"
    URLValidator(schemes=["http", "https"])(normalized)
    return normalized


def normalize_name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Enter a name.")
    return value.strip()


class MembershipRole(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    MEMBER = "member", "Member"
    VIEWER = "viewer", "Viewer"


class OrganizationQuerySet(models.QuerySet):
    def for_user(self, user):
        if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
            return self.none()
        return self.filter(memberships__user=user, is_suspended=False, closed_at__isnull=True).distinct()


class Organization(models.Model):
    name = models.CharField(max_length=160)
    is_suspended = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True, blank=True)
    paid_activation_tracking = models.CharField(max_length=32, null=True, blank=True, editable=False,
        choices=[("first-active-observation-v1", "Prospective first active observation")])
    first_audit_tracking = models.CharField(max_length=40, null=True, blank=True, editable=False,
        choices=[("bounded-first-audit-completion-v1", "Prospective bounded audit completion")])
    first_value_tracking = models.CharField(max_length=40, null=True, blank=True, editable=False,
        choices=[("bounded-audit-usefulness-ack-v1", "Prospective explicit audit usefulness acknowledgment")])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrganizationQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(name__regex=r"\S"), name="tenancy_organization_name_nonblank"),
            models.CheckConstraint(condition=Q(closed_at__isnull=True) | Q(is_suspended=True),
                                   name="tenancy_closed_organization_suspended"),
            models.CheckConstraint(condition=Q(paid_activation_tracking__isnull=True)
                | Q(paid_activation_tracking="first-active-observation-v1"), name="tenancy_paid_tracking_valid"),
            models.CheckConstraint(condition=Q(first_audit_tracking__isnull=True)
                | Q(first_audit_tracking="bounded-first-audit-completion-v1"), name="tenancy_first_audit_tracking_valid"),
            models.CheckConstraint(condition=Q(first_value_tracking__isnull=True)
                | Q(first_value_tracking="bounded-audit-usefulness-ack-v1"), name="tenancy_first_value_tracking_valid"),
        ]
        ordering = ["name", "id"]

    def clean_fields(self, exclude=None):
        self.name = normalize_name(self.name)
        super().clean_fields(exclude=exclude)

    def save(self, *args, **kwargs):
        if not self._state.adding or self.pk is not None and Organization.objects.filter(pk=self.pk).exists():
            previous = Organization.objects.get(pk=self.pk)
            if any(getattr(self, field) != getattr(previous, field) for field in (
                "paid_activation_tracking", "first_audit_tracking", "first_value_tracking")):
                raise ValidationError("Prospective organization tracking cannot be backfilled or reset.")
        if self.pk and (previous := Organization.objects.filter(pk=self.pk, closed_at__isnull=False).first()) and (
            self.closed_at != previous.closed_at or not self.is_suspended
        ):
            raise ValidationError("A closed organization cannot be reopened.")
        self.name = normalize_name(self.name)
        self._meta.get_field("name").clean(self.name, self)
        return super().save(*args, **kwargs)


class ProjectArtifactMutationAttempt(models.Model):
    """Restricted unresolved writer ownership; never expire based on age or lock absence."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    admission_pid = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)


class ProjectArtifactMutation(models.Model):
    class Operation(models.TextChoices):
        SAVE = "save", "Save"
        DELETE = "delete", "Delete"
        DELETE_VERSION = "delete_version", "Delete exact version"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    attempt = models.ForeignKey(ProjectArtifactMutationAttempt, on_delete=models.PROTECT, related_name="mutations")
    project_id = models.PositiveBigIntegerField()
    operation = models.CharField(max_length=16, choices=Operation.choices)
    storage_key = models.TextField()
    version_id = models.CharField(max_length=512, blank=True)
    storage_identity = models.JSONField()
    result_key = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(project_id__gt=0), name="tenancy_mutation_project_positive"),
            models.CheckConstraint(condition=Q(operation__in=["save", "delete", "delete_version"]),
                                   name="tenancy_mutation_operation_valid"),
            models.CheckConstraint(condition=(Q(operation="delete_version") & ~Q(version_id=""))
                | (Q(operation__in=["save", "delete"]) & Q(version_id="")),
                name="tenancy_mutation_version_valid"),
        ]


class TrialState(models.TextChoices):
    PENDING_REVIEW = "pending_review", "Pending review"
    ACTIVE = "active", "Active"
    EXPIRED = "expired", "Expired"
    READ_ONLY = "read_only", "Read only"
    SUSPENDED = "suspended", "Suspended"


class AutomaticTrialEligibility(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="automatic_trial_eligibility",
    )
    organization = models.OneToOneField(
        Organization,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="automatic_trial_eligibility",
    )
    offer_version = models.CharField(max_length=64)
    granted_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(offer_version__regex=r"\S"), name="tenancy_eligibility_offer_nonblank"),
        ]


class OrganizationTrial(models.Model):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="trial")
    automatic_eligibility = models.OneToOneField(
        AutomaticTrialEligibility,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="trial",
    )
    offer_version = models.CharField(max_length=64)
    state = models.CharField(max_length=24, choices=TrialState.choices)
    started_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    project_limit = models.PositiveSmallIntegerField()
    member_limit = models.PositiveSmallIntegerField()
    unit_limit = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.automatic_eligibility_id and (
            self.automatic_eligibility.organization_id != self.organization_id
            or self.automatic_eligibility.offer_version != self.offer_version
        ):
            raise ValidationError("Automatic trial eligibility must match the organization and offer.")
        super().clean()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(offer_version__regex=r"\S"), name="tenancy_trial_offer_nonblank"),
            models.CheckConstraint(condition=Q(state__in=TrialState.values), name="tenancy_trial_state_valid"),
            models.CheckConstraint(
                condition=(
                    Q(
                        state=TrialState.PENDING_REVIEW,
                        automatic_eligibility__isnull=True,
                        started_at__isnull=True,
                        ends_at__isnull=True,
                    )
                    | Q(
                        state__in=[TrialState.ACTIVE, TrialState.EXPIRED, TrialState.READ_ONLY, TrialState.SUSPENDED],
                        started_at__isnull=False,
                        ends_at__isnull=False,
                    )
                ),
                name="tenancy_trial_state_timestamps",
            ),
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gt=models.F("started_at")),
                name="tenancy_trial_end_after_start",
            ),
            models.CheckConstraint(
                condition=Q(project_limit__gt=0, member_limit__gt=0, unit_limit__gt=0),
                name="tenancy_trial_limits_positive",
            ),
        ]


class NoticeKind(models.TextChoices):
    TRIAL_ENDING = "trial_ending", "Trial ending"
    TRIAL_UNITS_EXHAUSTED = "trial_units_exhausted", "Trial units exhausted"
    PAYMENT_FAILED = "payment_failed", "Payment failed"
    PAID_UNITS_EXHAUSTED = "paid_units_exhausted", "Paid units exhausted"


class NoticeState(models.TextChoices):
    QUEUED = "queued", "Queued"
    SENDING = "sending", "Sending"
    SENT = "sent", "Sent"
    UNKNOWN = "unknown", "Unknown delivery"
    SKIPPED = "skipped", "Skipped"


class FeedbackKind(models.TextChoices):
    PERMANENT_BOUNCE = "permanent_bounce", "Permanent bounce"
    COMPLAINT = "complaint", "Complaint"


class EmailFeedbackReceipt(models.Model):
    event_id = models.CharField(max_length=200, unique=True)
    kind = models.CharField(max_length=20, choices=FeedbackKind.choices)
    addresses_digest = models.CharField(max_length=64)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=FeedbackKind.values), name="tenancy_email_feedback_kind_valid"),
            models.CheckConstraint(condition=Q(addresses_digest__regex=r"^[a-f0-9]{64}$"),
                                   name="tenancy_email_feedback_digest_valid"),
        ]


class EmailSuppression(models.Model):
    email_address = models.ForeignKey("account.EmailAddress", on_delete=models.CASCADE,
                                      related_name="organicseoops_suppressions")
    address_digest = models.CharField(max_length=64)
    reason = models.CharField(max_length=20, choices=FeedbackKind.choices)
    feedback = models.ForeignKey(EmailFeedbackReceipt, on_delete=models.PROTECT, related_name="suppressions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["email_address", "address_digest"], name="tenancy_email_suppression_address_unique"),
            models.CheckConstraint(condition=Q(address_digest__regex=r"^[a-f0-9]{64}$"),
                                   name="tenancy_email_suppression_digest_valid"),
            models.CheckConstraint(condition=Q(reason__in=FeedbackKind.values), name="tenancy_email_suppression_reason_valid"),
        ]


class OrganizationNotice(models.Model):

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="notices")
    trial = models.ForeignKey(OrganizationTrial, null=True, blank=True, on_delete=models.CASCADE, related_name="notices")
    source_receipt = models.ForeignKey("tenancy.PaddleWebhookReceipt", null=True, blank=True,
                                       on_delete=models.CASCADE, related_name="notices")
    subscription = models.ForeignKey("tenancy.PaddleSubscription", null=True, blank=True,
                                     on_delete=models.CASCADE, related_name="notices")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="organization_notices")
    kind = models.CharField(max_length=32, choices=NoticeKind.choices)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    paid_period_start = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=8, choices=NoticeState.choices, default=NoticeState.QUEUED)
    attempted_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    manual_retries = models.PositiveSmallIntegerField(default=0)
    error_category = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["trial", "recipient", "kind", "trial_ends_at"],
                                    name="tenancy_notice_unique_trial_recipient"),
            models.UniqueConstraint(fields=["source_receipt", "recipient", "kind"],
                                    name="tenancy_notice_unique_receipt_recipient"),
            models.UniqueConstraint(fields=["subscription", "recipient", "kind", "paid_period_start"],
                                    name="tenancy_notice_unique_paid_period_recipient"),
            models.CheckConstraint(condition=Q(kind__in=NoticeKind.values), name="tenancy_notice_kind_valid"),
            models.CheckConstraint(condition=(
                Q(kind__in=[NoticeKind.TRIAL_ENDING, NoticeKind.TRIAL_UNITS_EXHAUSTED],
                  trial__isnull=False, trial_ends_at__isnull=False,
                  source_receipt__isnull=True, subscription__isnull=True, paid_period_start__isnull=True) |
                Q(kind=NoticeKind.PAYMENT_FAILED, trial__isnull=True, trial_ends_at__isnull=True,
                  source_receipt__isnull=False, subscription__isnull=True, paid_period_start__isnull=True) |
                Q(kind=NoticeKind.PAID_UNITS_EXHAUSTED, trial__isnull=True, trial_ends_at__isnull=True,
                  source_receipt__isnull=True, subscription__isnull=False, paid_period_start__isnull=False)),
                name="tenancy_notice_source_shape"),
            models.CheckConstraint(condition=Q(state__in=NoticeState.values), name="tenancy_notice_state_valid"),
            models.CheckConstraint(condition=Q(manual_retries__lte=1), name="tenancy_notice_manual_retry_once"),
            models.CheckConstraint(condition=(Q(state=NoticeState.QUEUED, attempted_at__isnull=True, sent_at__isnull=True)
                | Q(state__in=[NoticeState.SENDING, NoticeState.UNKNOWN, NoticeState.SKIPPED], attempted_at__isnull=False,
                    sent_at__isnull=True)
                | Q(state=NoticeState.SENT, attempted_at__isnull=False, sent_at__isnull=False)),
                name="tenancy_notice_state_timestamps"),
        ]


class PaddleEnvironment(models.TextChoices):
    SANDBOX = "sandbox", "Sandbox"
    LIVE = "live", "Live"


class PaddleStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PAST_DUE = "past_due", "Past due"
    CANCELED = "canceled", "Canceled"
    PAUSED = "paused", "Paused"
    TRIALING = "trialing", "Trialing"


class PaddleSubscription(models.Model):

    organization = models.OneToOneField(Organization, on_delete=models.PROTECT, related_name="paddle_subscription")
    environment = models.CharField(max_length=8, choices=PaddleEnvironment.choices)
    customer_id = models.CharField(max_length=30)
    subscription_id = models.CharField(max_length=30)
    status = models.CharField(max_length=9, choices=PaddleStatus.choices)
    verified_at = models.DateTimeField(null=True, blank=True)
    period_starts_at = models.DateTimeField(null=True, blank=True)
    period_ends_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    grace_usage_starts_at = models.DateTimeField(null=True, blank=True)
    scheduled_cancel_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    disputed_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    currency_code = models.CharField(max_length=3, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["environment", "customer_id"], name="tenancy_paddle_customer_unique"),
            models.UniqueConstraint(fields=["environment", "subscription_id"], name="tenancy_paddle_subscription_unique"),
            models.CheckConstraint(condition=Q(environment__in=PaddleEnvironment.values), name="tenancy_paddle_environment_valid"),
            models.CheckConstraint(condition=Q(status__in=PaddleStatus.values), name="tenancy_paddle_status_valid"),
            models.CheckConstraint(condition=Q(customer_id__regex=r"^ctm_[a-z0-9]{26}$"), name="tenancy_paddle_customer_format"),
            models.CheckConstraint(condition=Q(subscription_id__regex=r"^sub_[a-z0-9]{26}$"), name="tenancy_paddle_subscription_format"),
            models.CheckConstraint(condition=(Q(verified_at__isnull=True, period_starts_at__isnull=True,
                                                 period_ends_at__isnull=True, failed_at__isnull=True,
                                                 grace_usage_starts_at__isnull=True,
                                                 scheduled_cancel_at__isnull=True, canceled_at__isnull=True,
                                                 disputed_at__isnull=True, refunded_at__isnull=True,
                                                 currency_code="")
                                              | Q(verified_at__isnull=False,
                                                  currency_code__regex=r"^[A-Z]{3}$")),
                                   name="tenancy_paddle_verified_fields_valid"),
            models.CheckConstraint(condition=Q(period_ends_at__isnull=True) | Q(period_ends_at__gt=models.F("period_starts_at")),
                                   name="tenancy_paddle_verified_period_valid"),
            models.CheckConstraint(condition=Q(grace_usage_starts_at__isnull=True) | Q(failed_at__isnull=True)
                                   | Q(grace_usage_starts_at__lte=models.F("failed_at")),
                                   name="tenancy_paddle_grace_starts_before_failure"),
        ]


class PaddleSubscriptionHistory(models.Model):
    """Prior fully canceled provider identity retained when an owner buys again."""

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="paddle_subscription_history")
    environment = models.CharField(max_length=8, choices=PaddleEnvironment.choices)
    customer_id = models.CharField(max_length=30)
    subscription_id = models.CharField(max_length=30)
    status = models.CharField(max_length=9, choices=PaddleStatus.choices)
    verified_at = models.DateTimeField()
    canceled_at = models.DateTimeField()
    refunded_at = models.DateTimeField(null=True, blank=True)
    disputed_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["environment", "subscription_id"], name="tenancy_paddle_history_subscription_unique"),
            models.CheckConstraint(condition=Q(environment__in=PaddleEnvironment.values, status=PaddleStatus.CANCELED),
                                   name="tenancy_paddle_history_canceled_only"),
            models.CheckConstraint(condition=Q(customer_id__regex=r"^ctm_[a-z0-9]{26}$",
                                               subscription_id__regex=r"^sub_[a-z0-9]{26}$"),
                                   name="tenancy_paddle_history_identity"),
        ]


class OrganizationBillingCancellation(models.Model):
    """One durable, non-replayable immediate provider cancellation for closure."""

    class State(models.TextChoices):
        RESERVED = "reserved", "Prepared, provider request not sent"
        SENDING = "sending", "Provider request attempted; outcome unknown"
        UNKNOWN = "unknown", "Provider outcome needs read-only reconciliation"
        CONFIRMED = "confirmed", "Provider cancellation observed"

    organization = models.OneToOneField(Organization, on_delete=models.PROTECT, related_name="billing_cancellation")
    subscription = models.ForeignKey(PaddleSubscription, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    environment = models.CharField(max_length=8, choices=PaddleEnvironment.choices)
    customer_id = models.CharField(max_length=30)
    provider_subscription_id = models.CharField(max_length=30)
    state = models.CharField(max_length=12, choices=State.choices, default=State.RESERVED)
    attempted_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    error_category = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(Q(state="reserved", attempted_at__isnull=True, confirmed_at__isnull=True)
                | Q(state__in=["sending", "unknown"], attempted_at__isnull=False, confirmed_at__isnull=True)
                | Q(state="confirmed", attempted_at__isnull=False, confirmed_at__isnull=False)),
                name="tenancy_billing_cancel_state_valid"),
            models.CheckConstraint(condition=Q(environment__in=PaddleEnvironment.values),
                                   name="tenancy_billing_cancel_env_valid"),
            models.CheckConstraint(condition=Q(customer_id__regex=r"^ctm_[a-z0-9]{26}$",
                                               provider_subscription_id__regex=r"^sub_[a-z0-9]{26}$"),
                                   name="tenancy_billing_cancel_identity_valid"),
        ]

    def clean(self):
        if (self.subscription_id and self.organization_id and self.subscription.organization_id != self.organization_id
            or self.environment != self.subscription.environment or self.customer_id != self.subscription.customer_id
            or self.provider_subscription_id != self.subscription.subscription_id):
            raise ValidationError("Provider cancellation must retain one owning subscription identity.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = OrganizationBillingCancellation.objects.get(pk=self.pk)
            if any(getattr(self, field) != getattr(previous, field) for field in (
                "organization_id", "subscription_id", "actor_id", "environment", "customer_id",
                "provider_subscription_id", "created_at",
            )) or self.state not in {
                self.State.RESERVED: {self.State.SENDING},
                self.State.SENDING: {self.State.UNKNOWN, self.State.CONFIRMED},
                self.State.UNKNOWN: {self.State.UNKNOWN, self.State.CONFIRMED},
                self.State.CONFIRMED: set(),
            }[previous.state]:
                raise ValidationError("Provider cancellation identity and one-way attempt state are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class OrganizationDeletionRun(models.Model):
    """Resumable active-store cleanup; a storage pass is not a deletion receipt."""

    class Source(models.TextChoices):
        OWNER_CLOSED = "owner_closed", "Deliberate owner closure"
        TRIAL_ELAPSED = "trial_elapsed", "Trial retention elapsed"
        PAID_CANCELED = "paid_canceled", "Paid cancellation retention elapsed"
        PAID_REFUNDED = "paid_refunded", "Refund retention elapsed"

    class State(models.TextChoices):
        PENDING = "pending", "Active storage and records remain"
        STORAGE_CLEARED = "storage_cleared", "Known artifact versions cleared; records remain"
        COMPLETE = "complete", "Active customer content deletion verified"

    organization = models.OneToOneField(Organization, on_delete=models.PROTECT, related_name="deletion_run")
    source = models.CharField(max_length=20, choices=Source.choices)
    eligible_at = models.DateTimeField()
    due_at = models.DateTimeField()
    project_ids = models.JSONField(default=list, blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    claimed_at = models.DateTimeField(null=True, blank=True)
    last_error_category = models.CharField(max_length=32, blank=True)
    storage_removed_count = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(due_at__gt=models.F("eligible_at")),
                                   name="tenancy_deletion_due_after_eligible"),
            models.CheckConstraint(condition=Q(state__in=["pending", "storage_cleared", "complete"]),
                                   name="tenancy_deletion_state_valid"),
            models.CheckConstraint(condition=Q(state="complete", completed_at__isnull=False)
                                   | Q(state__in=["pending", "storage_cleared"], completed_at__isnull=True),
                                   name="tenancy_deletion_completion_valid"),
        ]

    def clean(self):
        if (type(self.project_ids) is not list or len(self.project_ids) > 1000
            or any(type(pk) is not int or pk < 1 for pk in self.project_ids)
            or len(self.project_ids) != len(set(self.project_ids))):
            raise ValidationError("Deletion requires bounded exact project identities.")
        if self._state.adding and any(not Project.objects.filter(pk=pk, organization_id=self.organization_id).exists()
                                      for pk in self.project_ids):
            raise ValidationError("Deletion cannot include a foreign project.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = OrganizationDeletionRun.objects.get(pk=self.pk)
            if any(getattr(self, field) != getattr(previous, field) for field in (
                "organization_id", "source", "eligible_at", "due_at", "project_ids", "created_at",
            )) or self.state not in {
                self.State.PENDING: {self.State.PENDING, self.State.STORAGE_CLEARED},
                self.State.STORAGE_CLEARED: {self.State.STORAGE_CLEARED, self.State.COMPLETE,
                                             self.State.PENDING},
                self.State.COMPLETE: set(),
            }[previous.state] or (previous.state == self.State.STORAGE_CLEARED
                                  and self.state == self.State.PENDING
                                  and self.last_error_category != "artifact_reappeared"):
                raise ValidationError("Deletion scope and one-way progress are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class OrganizationCustomerExport(models.Model):
    """Private captured customer ZIP; parts are removable with the org's active data."""

    class State(models.TextChoices):
        PREPARING = "preparing", "Capturing private parts"
        READY = "ready", "Complete verified private capture"
        FAILED = "failed", "Capture needs review"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="customer_exports")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=64)
    format = models.CharField(max_length=24, default="bounded-zip-v1",
                              choices=[("bounded-zip-v1", "Bounded ZIP"), ("source-parts-v2", "Source parts"),
                                       ("coherent-parts-v3", "Internal coherent parts")])
    progress = models.JSONField(default=dict, blank=True, editable=False)
    state = models.CharField(max_length=12, choices=State.choices, default=State.PREPARING)
    size_bytes = models.PositiveBigIntegerField(default=0)
    content_sha256 = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_progress_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    expires_at = models.DateTimeField(null=True, blank=True, editable=False, db_index=True)
    expiry_policy_reference = models.CharField(max_length=64, blank=True, editable=False)

    @property
    def delivery_state(self):
        return "expired" if self.expires_at is not None and self.expires_at <= timezone.now() else self.state

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(Q(expires_at__isnull=True, expiry_policy_reference="")
                           | Q(state="ready", expires_at__isnull=False, completed_at__isnull=False,
                               expires_at__gt=models.F("completed_at"),
                               expiry_policy_reference__regex=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")),
                name="tenancy_customer_export_expiry_valid"),
            models.CheckConstraint(condition=Q(format__in=["bounded-zip-v1", "source-parts-v2", "coherent-parts-v3"]),
                                   name="tenancy_customer_export_format_valid"),
            models.UniqueConstraint(fields=["organization", "request_key"],
                                    name="tenancy_one_customer_export_request"),
            models.CheckConstraint(condition=(Q(state="ready", completed_at__isnull=False,
                                                content_sha256__regex=r"^[0-9a-f]{64}$", size_bytes__gt=0)
                                              | Q(state__in=["preparing", "failed"], completed_at__isnull=True,
                                                  content_sha256="", size_bytes=0)),
                                   name="tenancy_customer_export_state_valid"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            previous = OrganizationCustomerExport.objects.get(pk=self.pk)
            if (any(getattr(self, field) != getattr(previous, field)
                    for field in ("organization_id", "actor_id", "request_key", "created_at", "format"))
                or self.state not in {self.State.PREPARING: {self.State.READY, self.State.FAILED},
                                      self.State.READY: set(), self.State.FAILED: set()}[previous.state]):
                raise ValidationError("Customer export scope and terminal capture state are immutable.")
        if self.state == self.State.READY:
            from .customer_export_policy import reviewed_copy_lifetime
            reference, duration = reviewed_copy_lifetime()
            self.expiry_policy_reference = reference
            self.expires_at = self.completed_at + duration if duration else None
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = [*kwargs["update_fields"], "expires_at", "expiry_policy_reference"]
        self.full_clean()
        return super().save(*args, **kwargs)


class OrganizationCustomerExportPart(models.Model):
    export = models.ForeignKey(OrganizationCustomerExport, on_delete=models.CASCADE, related_name="parts")
    position = models.PositiveIntegerField()
    storage_key = models.CharField(max_length=512, editable=False)
    size_bytes = models.PositiveIntegerField()
    content_sha256 = models.CharField(max_length=64)
    source = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["export", "position"],
                                                name="tenancy_one_customer_export_part_position")]

    def clean(self):
        if (not self.export_id or not self.export.organization_id or not self.export.pk
            or not self.storage_key.startswith(
                f"organizations/{self.export.organization_id}/exports/{self.export.pk}/")
            or not re.fullmatch(r"[0-9a-f]{64}", self.content_sha256)
            or not 1 <= self.size_bytes <= settings.ARTIFACT_MAX_BYTES):
            raise ValidationError("Customer export part must have exact private ownership and integrity.")
        from config.artifacts import _validate_key
        _validate_key(self.storage_key)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("A captured customer export part is immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class PaddleSellerConfiguration(models.Model):
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    environment = models.CharField(max_length=8, choices=PaddleEnvironment.choices, unique=True)
    product_id = models.CharField(max_length=30)
    price_id = models.CharField(max_length=30)
    client_token = models.CharField(max_length=32, blank=True, editable=False)
    encrypted_api_key = models.TextField(blank=True, editable=False)
    encrypted_webhook_secret = models.TextField(blank=True, editable=False)
    state = models.CharField(max_length=8, choices=State.choices)
    rotated_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(environment__in=PaddleEnvironment.values),
                                   name="tenancy_paddle_seller_environment_valid"),
            models.CheckConstraint(condition=Q(product_id__regex=r"^pro_[a-z0-9]{26}$"),
                                   name="tenancy_paddle_seller_product_valid"),
            models.CheckConstraint(condition=Q(price_id__regex=r"^pri_[a-z0-9]{26}$"),
                                   name="tenancy_paddle_seller_price_valid"),
            models.CheckConstraint(condition=(Q(state="active", encrypted_api_key__startswith="v1:",
                                                encrypted_webhook_secret__startswith="v1:")
                                              | Q(state="revoked", encrypted_api_key="", encrypted_webhook_secret="")),
                                   name="tenancy_paddle_seller_state_valid"),
        ]

    def clean(self):
        if (self.environment not in PaddleEnvironment.values or self.state not in self.State.values
                or any(len(value) > 8192 for value in (self.encrypted_api_key, self.encrypted_webhook_secret))):
            raise ValidationError("Invalid seller configuration.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PaddleCheckoutAttempt(models.Model):
    class State(models.TextChoices):
        RESERVED = "reserved", "Reserved before provider request"
        SENDING = "sending", "Provider request attempted; outcome unknown"
        READY = "ready", "Provider transaction recorded, payment unverified"
        UNKNOWN = "unknown", "Provider outcome requires reconciliation"
        REJECTED = "rejected", "Definitively rejected without checkout"
        SETTLED = "settled", "Paid checkout superseded after full cancellation"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="paddle_checkout_attempts")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    environment = models.CharField(max_length=8, choices=PaddleEnvironment.choices)
    offer_version = models.CharField(max_length=64)
    product_id = models.CharField(max_length=30)
    price_id = models.CharField(max_length=30)
    request_key = models.CharField(max_length=64)
    state = models.CharField(max_length=12, choices=State.choices, default=State.RESERVED)
    transaction_id = models.CharField(max_length=30, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    paid_verified_at = models.DateTimeField(null=True, blank=True)
    paid_customer_id = models.CharField(max_length=30, blank=True)
    paid_subscription_id = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "request_key"], name="tenancy_paddle_checkout_request_unique"),
            models.UniqueConstraint(fields=["organization"], condition=Q(state__in=["reserved", "sending", "ready", "unknown"]),
                                    name="tenancy_paddle_one_unresolved_checkout"),
            models.UniqueConstraint(fields=["environment", "transaction_id"], condition=~Q(transaction_id=""),
                                    name="tenancy_paddle_checkout_transaction_unique"),
            models.CheckConstraint(condition=Q(environment__in=PaddleEnvironment.values), name="tenancy_checkout_env_valid"),
            models.CheckConstraint(condition=Q(offer_version="agency-launch-v1"), name="tenancy_checkout_offer_valid"),
            models.CheckConstraint(condition=Q(product_id__regex=r"^pro_[a-z0-9]{26}$",
                                               price_id__regex=r"^pri_[a-z0-9]{26}$"), name="tenancy_checkout_catalog_valid"),
            models.CheckConstraint(condition=Q(request_key__regex=r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$"),
                                   name="tenancy_checkout_request_key_valid"),
            models.CheckConstraint(condition=(Q(state="reserved", sent_at__isnull=True, transaction_id="")
                                              | Q(state__in=["sending", "unknown"], sent_at__isnull=False, transaction_id="")
                                              | Q(state="ready", sent_at__isnull=False,
                                                  transaction_id__regex=r"^txn_[a-z0-9]{26}$")
                                              | Q(state="settled", sent_at__isnull=False,
                                                  transaction_id__regex=r"^txn_[a-z0-9]{26}$",
                                                  paid_verified_at__isnull=False)
                                              | Q(state="rejected", transaction_id="")),
                                   name="tenancy_checkout_state_valid"),
            models.CheckConstraint(condition=(Q(paid_verified_at__isnull=True, paid_customer_id="", paid_subscription_id="")
                                              | Q(paid_verified_at__isnull=False, state__in=["ready", "settled"],
                                                  transaction_id__regex=r"^txn_[a-z0-9]{26}$",
                                                  paid_customer_id__regex=r"^ctm_[a-z0-9]{26}$")
                                              & (Q(paid_subscription_id="") |
                                                 Q(paid_subscription_id__regex=r"^sub_[a-z0-9]{26}$"))),
                                   name="tenancy_checkout_paid_evidence_valid"),
        ]

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PaddleCheckoutLinkReceipt(models.Model):
    """Restricted immutable first owner/browser acknowledgment, never payment evidence."""

    attempt = models.OneToOneField(PaddleCheckoutAttempt, on_delete=models.PROTECT, related_name="link_receipt")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="checkout_link_receipts")
    source = models.JSONField(editable=False)
    source_digest = models.CharField(max_length=64, editable=False)
    acknowledged_at = models.DateTimeField(editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(source_digest__regex=r"^[a-f0-9]{64}$"),
                                   name="tenancy_checkout_receipt_digest_valid"),
        ]

    def clean(self):
        from .paddle_checkout_delivery import checkout_link_delivery_source, checkout_source_digest
        if self.pk is not None or not self._state.adding:
            raise ValidationError("Checkout link receipts are immutable.")
        if (self.acknowledged_at is None or timezone.is_naive(self.acknowledged_at)
            or self.acknowledged_at > timezone.now()
            or self.source != checkout_link_delivery_source(organization=self.attempt.organization,
                actor=self.actor, attempt_id=self.attempt_id)
            or self.source_digest != checkout_source_digest(self.source)):
            raise ValidationError("Checkout link receipt must match its current source.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PaddleFirstActiveObservation(models.Model):
    """One prospective server observation, never a reconstructed provider activation date."""

    organization = models.OneToOneField(Organization, on_delete=models.PROTECT, related_name="first_paid_observation")
    attempt = models.ForeignKey(PaddleCheckoutAttempt, on_delete=models.PROTECT)
    receipt = models.ForeignKey("PaddleWebhookReceipt", on_delete=models.PROTECT)
    observed_at = models.DateTimeField(editable=False)
    source = models.JSONField(editable=False)
    source_digest = models.CharField(max_length=64, editable=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(source_digest__regex=r"^[a-f0-9]{64}$"),
                                              name="tenancy_paid_observation_digest_valid")]

    def clean(self):
        from .paddle_activation import first_active_observation_source
        from .paddle_checkout_delivery import checkout_source_digest
        if self.pk is not None or not self._state.adding:
            raise ValidationError("First active observations are immutable.")
        if (self.source != first_active_observation_source(organization=self.organization,
                attempt=self.attempt, receipt=self.receipt, observed_at=self.observed_at)
            or self.source_digest != checkout_source_digest(self.source)):
            raise ValidationError("First active observation must retain its exact reconciled source.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PaddleWebhookReceipt(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Verified and awaiting reconciliation"
        PROCESSING = "processing", "Reconciliation in progress"
        SUCCEEDED = "succeeded", "Provider state reconciled"
        FAILED = "failed", "Provider state needs retry"
        IGNORED = "ignored", "Signed event outside subscribed lifecycle"

    environment = models.CharField(max_length=8, choices=PaddleEnvironment.choices)
    event_id = models.CharField(max_length=30)
    notification_id = models.CharField(max_length=30)
    event_type = models.CharField(max_length=64)
    occurred_at = models.DateTimeField()
    entity_id = models.CharField(max_length=44)
    subscription_id = models.CharField(max_length=30, blank=True)
    customer_id = models.CharField(max_length=30, blank=True)
    raw_digest = models.CharField(max_length=64)
    state = models.CharField(max_length=12, choices=State.choices)
    attempts = models.PositiveSmallIntegerField(default=0)
    error_category = models.CharField(max_length=40, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    retry_after = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["environment", "event_id"], name="tenancy_paddle_unique_event"),
            models.CheckConstraint(condition=Q(environment__in=PaddleEnvironment.values), name="tenancy_paddle_event_environment"),
            models.CheckConstraint(condition=Q(event_id__regex=r"^evt_[a-z0-9]{26}$",
                                               notification_id__regex=r"^ntf_[a-z0-9]{26}$",
                                               raw_digest__regex=r"^[a-f0-9]{64}$"), name="tenancy_paddle_event_identity"),
            models.CheckConstraint(condition=(Q(subscription_id="", customer_id="") |
                                              Q(subscription_id__regex=r"^sub_[a-z0-9]{26}$",
                                                customer_id__regex=r"^ctm_[a-z0-9]{26}$")),
                                   name="tenancy_paddle_event_linked_identity"),
            models.CheckConstraint(condition=Q(state__in=["pending", "processing", "succeeded", "failed", "ignored"]),
                                   name="tenancy_paddle_event_state"),
            models.CheckConstraint(condition=Q(attempts__lte=3), name="tenancy_paddle_event_attempt_limit"),
            models.CheckConstraint(condition=(Q(state="pending", attempts=0, claimed_at__isnull=True,
                                                retry_after__isnull=True)
                                              | Q(state="processing", attempts__gte=1, claimed_at__isnull=False,
                                                  retry_after__isnull=True)
                                              | Q(state="failed", attempts__gte=1, claimed_at__isnull=False)
                                              | Q(state="succeeded", attempts__gte=1, claimed_at__isnull=False,
                                                  retry_after__isnull=True)
                                              | Q(state="ignored", attempts=0, claimed_at__isnull=True,
                                                  retry_after__isnull=True)),
                                   name="tenancy_paddle_event_claim_valid"),
        ]


class OrganizationMembership(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organization_memberships",
    )
    role = models.CharField(max_length=16, choices=MembershipRole.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"], name="tenancy_unique_organization_user"),
            models.CheckConstraint(condition=Q(role__in=MembershipRole.values), name="tenancy_membership_role_valid"),
        ]


def retained_content_window(*, organization_prefix="", now=None):
    """The selected 90-day post-lapse project-data/export access window."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=90)
    paid = organization_prefix + "paddle_subscription__"
    trial = organization_prefix + "trial__"
    refunded = Q(**{paid + "refunded_at__gt": cutoff, paid + "refunded_at__lte": now})
    cancelled = Q(**{paid + "status": PaddleStatus.CANCELED,
                     paid + "canceled_at__gt": cutoff, paid + "canceled_at__lte": now})
    ongoing = Q(**{paid + "status__in": [status for status in PaddleStatus.values
                                         if status != PaddleStatus.CANCELED]})
    paid_access = Q(**{paid + "verified_at__lte": now,
                       paid + "environment": settings.PADDLE_ENVIRONMENT}) & (
        refunded | Q(**{paid + "refunded_at__isnull": True}) & (ongoing | cancelled))
    trial_access = Q(**{paid + "verified_at__isnull": True,
                        organization_prefix + "trial__isnull": False}) & (
        Q(**{trial + "ends_at__isnull": True}) | Q(**{trial + "ends_at__gt": cutoff}))
    return paid_access | trial_access


class ProjectQuerySet(models.QuerySet):
    def for_user(self, user):
        if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
            return self.none()
        memberships = OrganizationMembership.objects.filter(
            organization_id=OuterRef("organization_id"),
            user_id=user.pk,
        )
        owner_memberships = memberships.filter(role=MembershipRole.OWNER)
        project_memberships = ProjectMembership.objects.filter(
            project_id=OuterRef("pk"),
            organization_membership__organization_id=OuterRef("organization_id"),
            organization_membership__user_id=user.pk,
        )
        return self.filter(organization__is_suspended=False, organization__closed_at__isnull=True).filter(
            retained_content_window(organization_prefix="organization__")
        ).annotate(
            _has_organization_access=Exists(memberships),
            _is_organization_owner=Exists(owner_memberships),
            _has_project_access=Exists(project_memberships),
        ).filter(
            _has_organization_access=True,
        ).filter(
            Q(access_restricted=False) | Q(_is_organization_owner=True) | Q(_has_project_access=True)
        )


class Project(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(max_length=160)
    canonical_origin = models.CharField(max_length=512)
    access_restricted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProjectQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "canonical_origin"],
                name="tenancy_unique_organization_canonical_origin",
            ),
            models.CheckConstraint(condition=Q(name__regex=r"\S"), name="tenancy_project_name_nonblank"),
        ]
        ordering = ["name", "id"]

    def clean_fields(self, exclude=None):
        self.name = normalize_name(self.name)
        self.canonical_origin = normalize_origin(self.canonical_origin)
        super().clean_fields(exclude=exclude)

    def clean(self):
        if (
            self.organization_id
            and self.canonical_origin
            and DomainAlias.objects.filter(
                organization_id=self.organization_id,
                origin=self.canonical_origin,
            ).exists()
        ):
            raise ValidationError("The canonical origin is already configured as an alias.")

    def save(self, *args, **kwargs):
        self.name = normalize_name(self.name)
        self.canonical_origin = normalize_origin(self.canonical_origin)
        self._meta.get_field("name").clean(self.name, self)
        self.clean()
        return super().save(*args, **kwargs)


def _string_list(value, label, *, limit=50, item_limit=240):
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(item, str) for item in value):
        raise ValidationError(f"{label} must be a list of at most {limit} values.")
    cleaned = [item.strip() for item in value]
    if any(not item or len(item) > item_limit for item in cleaned) or len(cleaned) != len(set(cleaned)):
        raise ValidationError(f"{label} must contain unique non-empty values of at most {item_limit} characters.")
    return cleaned


class ProjectConfiguration(models.Model):
    MUTABLE_FIELDS = frozenset({
        "target_country", "target_languages", "business_goal", "timezone", "audience", "offer", "brand_voice",
        "seed_topics", "prohibited_claims", "conversion_goals", "brand_aliases", "competitor_origins",
        "research_allowed_origins", "research_blocked_origins", "crawl_page_limit", "business_locations",
        "rss_feed_urls",
        "service_areas", "contact_details", "business_hours", "profile_urls", "local_eligibility_notes",
        "measurement_notes",
        "ignored_query_parameters", "pagination_query_parameters", "facet_query_parameters", "query_variant_limit",
        "source_choice", "current_step",
    })

    class Step(models.TextChoices):
        BASICS = "basics", "Website and goals"
        SOURCE = "source", "Data source"
        ADVANCED = "advanced", "Advanced settings"
        COMPLETE = "complete", "Complete"

    class SourceChoice(models.TextChoices):
        UNDECIDED = "undecided", "Not selected"
        CONNECT_SEARCH_CONSOLE = "connect_search_console", "Connect Search Console"
        IMPORT_SEARCH_CONSOLE = "import_search_console", "Import Search Console CSV"
        SKIP = "skip", "Skip for now"
        SYNTHETIC_DEMO = "synthetic_demo", "Synthetic demo"

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="configuration")
    target_country = models.CharField(max_length=80, blank=True)
    target_languages = models.JSONField(default=list, blank=True)
    business_goal = models.CharField(max_length=240, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    audience = models.TextField(max_length=2000, blank=True)
    offer = models.TextField(max_length=2000, blank=True)
    brand_voice = models.TextField(max_length=2000, blank=True)
    seed_topics = models.JSONField(default=list, blank=True)
    prohibited_claims = models.JSONField(default=list, blank=True)
    conversion_goals = models.JSONField(default=list, blank=True)
    brand_aliases = models.JSONField(default=list, blank=True)
    measurement_notes = models.TextField(max_length=2000, blank=True)
    competitor_origins = models.JSONField(default=list, blank=True)
    research_allowed_origins = models.JSONField(default=list, blank=True)
    research_blocked_origins = models.JSONField(default=list, blank=True)
    rss_feed_urls = models.JSONField(default=list, blank=True)
    crawl_page_limit = models.PositiveIntegerField(null=True, blank=True)
    ignored_query_parameters = models.JSONField(default=list, blank=True)
    pagination_query_parameters = models.JSONField(default=list, blank=True)
    facet_query_parameters = models.JSONField(default=list, blank=True)
    query_variant_limit = models.PositiveSmallIntegerField(default=5)
    business_locations = models.JSONField(default=list, blank=True)
    service_areas = models.JSONField(default=list, blank=True)
    contact_details = models.TextField(max_length=2000, blank=True)
    business_hours = models.TextField(max_length=2000, blank=True)
    profile_urls = models.JSONField(default=list, blank=True)
    local_eligibility_notes = models.TextField(max_length=2000, blank=True)
    source_choice = models.CharField(max_length=32, choices=SourceChoice.choices, default=SourceChoice.UNDECIDED)
    current_step = models.CharField(max_length=16, choices=Step.choices, default=Step.BASICS)
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(source_choice__in=["undecided", "connect_search_console", "import_search_console", "skip", "synthetic_demo"]),
                name="tenancy_project_configuration_source_valid",
            ),
            models.CheckConstraint(
                condition=Q(current_step__in=["basics", "source", "advanced", "complete"]),
                name="tenancy_project_configuration_step_valid",
            ),
            models.CheckConstraint(
                condition=Q(crawl_page_limit__isnull=True) | Q(crawl_page_limit__gte=1, crawl_page_limit__lte=100000),
                name="tenancy_project_configuration_crawl_limit_valid",
            ),
            models.CheckConstraint(
                condition=Q(query_variant_limit__gte=1, query_variant_limit__lte=25),
                name="tenancy_project_configuration_query_variant_limit_valid",
            ),
        ]

    def clean(self):
        self.target_country = self.target_country.strip()
        self.business_goal = self.business_goal.strip()
        self.measurement_notes = self.measurement_notes.strip()
        self.timezone = self.timezone.strip()
        self.target_languages = _string_list(self.target_languages, "Target languages", limit=10, item_limit=35)
        if any(not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", item) for item in self.target_languages):
            raise ValidationError("Use language tags such as en, tr, or en-US.")
        for field, label in (
            ("seed_topics", "Seed topics"),
            ("prohibited_claims", "Prohibited claims"),
            ("conversion_goals", "Conversion goals"),
            ("brand_aliases", "Brand aliases"),
            ("business_locations", "Business locations"),
            ("service_areas", "Service areas"),
        ):
            setattr(self, field, _string_list(getattr(self, field), label))
        for field, label in (
            ("competitor_origins", "Competitor origins"),
            ("research_allowed_origins", "Allowed research origins"),
            ("research_blocked_origins", "Blocked research origins"),
        ):
            normalized = [normalize_origin(value) for value in _string_list(getattr(self, field), label)]
            if len(normalized) != len(set(normalized)):
                raise ValidationError(f"{label} must contain unique origins.")
            setattr(self, field, normalized)
        if set(self.research_allowed_origins) & set(self.research_blocked_origins):
            raise ValidationError("A research origin cannot be both allowed and blocked.")
        feeds = _string_list(self.rss_feed_urls, "RSS feed URLs", limit=5, item_limit=512)
        for value in feeds:
            try:
                parsed = urlsplit(value)
                origin = normalize_origin(f"{parsed.scheme}://{parsed.netloc}")
            except (ValueError, ValidationError):
                raise ValidationError("Feed URLs require a configured allowed HTTPS origin without secrets or fragments.") from None
            if (
                parsed.scheme != "https" or parsed.port not in (None, 443)
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or "\\" in value
                or any(ord(character) < 32 for character in value)
                or origin not in self.research_allowed_origins
                or origin in self.research_blocked_origins
            ):
                raise ValidationError("Feed URLs require a configured allowed HTTPS origin without secrets or fragments.")
            URLValidator(schemes=["https"])(value)
        self.rss_feed_urls = feeds
        urls = _string_list(self.profile_urls, "Profile URLs", item_limit=512)
        for value in urls:
            try:
                parsed = urlsplit(value)
                hostname = parsed.hostname
            except ValueError:
                raise ValidationError("Profile URLs must be public HTTP or HTTPS links without credentials or fragments.") from None
            if parsed.scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValidationError("Profile URLs must be public HTTP or HTTPS links without credentials or fragments.")
            URLValidator(schemes=["http", "https"])(value)
        self.profile_urls = urls
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValidationError("Enter a valid IANA timezone such as UTC or Europe/Istanbul.") from None
        if self.crawl_page_limit is not None and not 1 <= self.crawl_page_limit <= 100000:
            raise ValidationError("The crawl page limit must be between 1 and 100000.")
        parameter_groups = []
        for field, label in (
            ("ignored_query_parameters", "Ignored query parameters"),
            ("pagination_query_parameters", "Pagination query parameters"),
            ("facet_query_parameters", "Facet query parameters"),
        ):
            submitted = getattr(self, field)
            values = _string_list(submitted, label, item_limit=100)
            if values != submitted:
                raise ValidationError(f"{label} must use exact names without surrounding whitespace.")
            if any(any(ord(character) < 33 or ord(character) > 126 or character in "&=#" for character in value)
                   for value in values):
                raise ValidationError(f"{label} must use exact visible parameter names without separators.")
            setattr(self, field, values)
            parameter_groups.extend(values)
        if len(parameter_groups) != len(set(parameter_groups)):
            raise ValidationError("A query parameter can belong to only one rule category.")
        if type(self.query_variant_limit) is not int or not 1 <= self.query_variant_limit <= 25:
            raise ValidationError("The query variant limit must be between 1 and 25.")
        if self.current_step != self.Step.BASICS and (
            not self.target_country or not self.target_languages or not self.business_goal
        ):
            raise ValidationError("Complete the country, language, and business goal before continuing.")
        if self.current_step in {self.Step.ADVANCED, self.Step.COMPLETE} and self.source_choice == self.SourceChoice.UNDECIDED:
            raise ValidationError("Choose a source path before continuing.")


class ProjectMembership(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="project_memberships")
    organization_membership = models.ForeignKey(
        OrganizationMembership,
        on_delete=models.CASCADE,
        related_name="project_memberships",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "organization_membership"],
                name="tenancy_unique_project_membership",
            ),
        ]

    def clean(self):
        if (
            self.project_id
            and self.organization_membership_id
            and self.project.organization_id != self.organization_membership.organization_id
        ):
            raise ValidationError("Project access must stay within one organization.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class DomainAlias(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="domain_aliases")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="domain_aliases")
    origin = models.CharField(max_length=512)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "origin"],
                name="tenancy_unique_organization_alias_origin",
            ),
        ]
        ordering = ["origin", "id"]

    def clean_fields(self, exclude=None):
        self.origin = normalize_origin(self.origin)
        super().clean_fields(exclude=exclude)

    def clean(self):
        if self.project_id and self.organization_id:
            if self.project.organization_id != self.organization_id:
                raise ValidationError("Domain aliases must stay within one organization.")
            if self.origin == self.project.canonical_origin:
                raise ValidationError("A domain alias must differ from the canonical origin.")
            if Project.objects.filter(
                organization_id=self.organization_id,
                canonical_origin=self.origin,
            ).exclude(pk=self.project_id).exists():
                raise ValidationError("The domain alias is already configured as a canonical origin.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ProjectOriginVerification(models.Model):
    class Method(models.TextChoices):
        HTTP_FILE = "http_file", "HTTP file"

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        REVOKED = "revoked", "Revoked"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="origin_verifications")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="origin_verifications")
    origin = models.CharField(max_length=512)
    method = models.CharField(max_length=16, choices=Method.choices, default=Method.HTTP_FILE)
    challenge_digest = models.CharField(max_length=64, validators=[RegexValidator(r"^[0-9a-f]{64}$")])
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    verified_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "origin"], name="tenancy_unique_project_origin_verification"),
            models.CheckConstraint(condition=Q(method="http_file"), name="tenancy_origin_verification_method_valid"),
            models.CheckConstraint(
                condition=(
                    Q(state="pending", verified_at__isnull=True, revoked_at__isnull=True)
                    | Q(state="verified", verified_at__isnull=False, revoked_at__isnull=True)
                    | Q(state="revoked", revoked_at__isnull=False)
                ),
                name="tenancy_origin_verification_state_valid",
            ),
        ]
        ordering = ["origin", "id"]

    def clean_fields(self, exclude=None):
        self.origin = normalize_origin(self.origin)
        super().clean_fields(exclude=exclude)

    def clean(self):
        if self.project_id and self.organization_id and self.project.organization_id != self.organization_id:
            raise ValidationError("Origin verification must stay within one organization.")
        if self._state.adding and self.project_id and self.origin:
            allowed = self.origin == self.project.canonical_origin or DomainAlias.objects.filter(
                project_id=self.project_id,
                organization_id=self.organization_id,
                origin=self.origin,
            ).exists()
            if not allowed:
                raise ValidationError("Origin verification must target the project's current domain or alias.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class InvitationState(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    REVOKED = "revoked", "Revoked"
    EXPIRED = "expired", "Expired"


class OrganizationInvitation(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=MembershipRole.choices)
    inviter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_organization_invitations",
    )
    token_digest = models.CharField(max_length=64, unique=True)
    state = models.CharField(max_length=16, choices=InvitationState.choices, default=InvitationState.PENDING)
    expires_at = models.DateTimeField()
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="accepted_organization_invitations",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revoked_organization_invitations",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=Q(state=InvitationState.PENDING),
                name="tenancy_unique_pending_invitation",
            ),
            models.CheckConstraint(condition=Q(role__in=MembershipRole.values), name="tenancy_invitation_role_valid"),
            models.CheckConstraint(condition=Q(state__in=InvitationState.values), name="tenancy_invitation_state_valid"),
            models.CheckConstraint(
                condition=Q(email=Lower("email")) & Q(email__regex=r"^\S+$"),
                name="tenancy_invitation_email_canonical",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        state=InvitationState.PENDING,
                        accepted_by__isnull=True,
                        accepted_at__isnull=True,
                        revoked_by__isnull=True,
                        revoked_at__isnull=True,
                        expired_at__isnull=True,
                    )
                    | Q(
                        state=InvitationState.ACCEPTED,
                        accepted_by__isnull=False,
                        accepted_at__isnull=False,
                        revoked_by__isnull=True,
                        revoked_at__isnull=True,
                        expired_at__isnull=True,
                    )
                    | Q(
                        state=InvitationState.REVOKED,
                        accepted_by__isnull=True,
                        accepted_at__isnull=True,
                        revoked_at__isnull=False,
                        expired_at__isnull=True,
                    )
                    | Q(
                        state=InvitationState.EXPIRED,
                        accepted_by__isnull=True,
                        accepted_at__isnull=True,
                        revoked_by__isnull=True,
                        revoked_at__isnull=True,
                        expired_at__isnull=False,
                    )
                ),
                name="tenancy_invitation_terminal_state_valid",
            ),
        ]
        ordering = ["email", "id"]

    def clean_fields(self, exclude=None):
        self.email = UserManager.normalize_email(self.email)
        super().clean_fields(exclude=exclude)

    def save(self, *args, **kwargs):
        self.email = UserManager.normalize_email(self.email)
        self._meta.get_field("email").clean(self.email, self)
        return super().save(*args, **kwargs)


class InvitationProject(models.Model):
    invitation = models.ForeignKey(
        OrganizationInvitation,
        on_delete=models.CASCADE,
        related_name="project_grants",
    )
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="invitation_grants")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["invitation", "project"], name="tenancy_unique_invitation_project"),
        ]

    def clean(self):
        if (
            self.invitation_id
            and self.project_id
            and self.invitation.organization_id != self.project.organization_id
        ):
            raise ValidationError("Invitation project access must stay within one organization.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class AuditEventType(models.TextChoices):
    TRIAL_GRANTED = "trial.granted", "Trial granted"
    TRIAL_REVIEW_REQUIRED = "trial.review_required", "Trial review required"
    TRIAL_APPROVED = "trial.approved", "Trial approved"
    TRIAL_EXTENDED = "trial.extended", "Trial extended"
    NOTICE_RETRY_REQUESTED = "notice.retry_requested", "Unknown notice delivery retry requested"
    EMAIL_SUPPRESSION_CLEARED = "email.suppression_cleared", "Email suppression cleared after review"
    INVITATION_CREATED = "invitation.created", "Invitation created"
    INVITATION_ACCEPTED = "invitation.accepted", "Invitation accepted"
    INVITATION_REVOKED = "invitation.revoked", "Invitation revoked"
    INVITATION_EXPIRED = "invitation.expired", "Invitation expired"
    MEMBERSHIP_ROLE_CHANGED = "membership.role_changed", "Membership role changed"
    MEMBERSHIP_REMOVED = "membership.removed", "Membership removed"
    PROJECT_ACCESS_CHANGED = "project.access_changed", "Project access changed"
    OWNERSHIP_PROPOSED = "ownership.proposed", "Ownership proposed"
    OWNERSHIP_ACCEPTED = "ownership.accepted", "Ownership accepted"
    OWNERSHIP_CANCELLED = "ownership.cancelled", "Ownership cancelled"
    MEMBERSHIP_LEFT = "membership.left", "Membership left"
    ORGANIZATION_SUSPENDED = "organization.suspended", "Organization suspended"
    ORGANIZATION_CLOSED = "organization.closed", "Owner closed organization access"
    ORGANIZATION_RETENTION_ELAPSED = "organization.retention_elapsed", "Customer content retention expired"
    ORGANIZATION_EXPORT_ACCESSED = "organization.export_accessed", "Owner accessed customer export part"
    ACCOUNT_EXPORTED = "account.exported", "Account owner exported personal data"
    ACCOUNT_CLOSED = "account.closed", "Account owner closed personal access"
    ACCOUNT_LOGGED_IN = "account.logged_in", "Account signed in"
    ACCOUNT_LOGGED_OUT = "account.logged_out", "Account signed out"
    ACCOUNT_PASSWORD_CHANGED = "account.password_changed", "Account password changed"
    ACCOUNT_PASSWORD_RESET = "account.password_reset", "Account password reset"
    ACCOUNT_EMAIL_VERIFIED = "account.email_verified", "Account email verified"
    ACCOUNT_EMAIL_CHANGED = "account.email_changed", "Account primary email changed"
    JOB_QUEUED = "job.queued", "Job admitted to queue"
    JOB_CANCEL_REQUESTED = "job.cancel_requested", "Job cancellation requested"
    USER_SUSPENDED = "user.suspended", "User suspended"
    STAFF_MFA_ADDED = "staff.mfa_added", "Staff MFA added"
    STAFF_MFA_REMOVED = "staff.mfa_removed", "Staff MFA removed"
    STAFF_MFA_RECOVERY_RESET = "staff.mfa_recovery_reset", "Staff MFA recovery reset"
    STAFF_MFA_RECOVERY_USED = "staff.mfa_recovery_used", "Staff MFA recovery used"
    ORIGIN_VERIFICATION_CREATED = "origin_verification.created", "Origin verification created"
    ORIGIN_VERIFICATION_VERIFIED = "origin_verification.verified", "Origin verification verified"
    ORIGIN_VERIFICATION_REVOKED = "origin_verification.revoked", "Origin verification revoked"
    PROVIDER_ACCOUNT_CREATED = "provider_account.created", "Provider account created"
    PROVIDER_ACCOUNT_ROTATED = "provider_account.rotated", "Provider account rotated"
    PROVIDER_ACCOUNT_REVOKED = "provider_account.revoked", "Provider account revoked"
    PLATFORM_CREDENTIAL_UPDATED = "platform_credential.updated", "Platform credential updated"
    PLATFORM_CREDENTIAL_REVOKED = "platform_credential.revoked", "Platform credential revoked"
    BILLING_CHECKOUT_RESERVED = "billing.checkout_reserved", "Checkout attempt reserved"
    BILLING_CHECKOUT_ATTEMPTED = "billing.checkout_attempted", "Checkout provider request attempted"
    BILLING_CHECKOUT_UNKNOWN = "billing.checkout_unknown", "Checkout outcome unknown"
    BILLING_CHECKOUT_READY = "billing.checkout_ready", "Checkout link recorded; payment unverified"
    BILLING_CHECKOUT_LINK_ACKNOWLEDGED = "billing.checkout_link_acknowledged", "Owner browser acknowledged checkout link"
    BILLING_PORTAL_OPENED = "billing.portal_opened", "Temporary billing portal session created"
    BILLING_PAYMENT_VERIFIED = "billing.payment_verified", "Current Paddle payment verified"
    BILLING_SUBSCRIPTION_RECONCILED = "billing.subscription_reconciled", "Current Paddle subscription reconciled"
    BILLING_CANCELLATION_PREPARED = "billing.cancellation_prepared", "Closure billing cancellation reserved"
    BILLING_CANCELLATION_ATTEMPTED = "billing.cancellation_attempted", "Closure billing cancellation attempted"
    BILLING_CANCELLATION_UNKNOWN = "billing.cancellation_unknown", "Closure billing cancellation needs reconciliation"
    BILLING_CANCELLATION_CONFIRMED = "billing.cancellation_confirmed", "Closure billing cancellation confirmed"
    BILLING_ADJUSTMENT_REVIEWED = "billing.adjustment_reviewed", "Current Paddle adjustment reviewed"
    BILLING_RECONCILIATION_RETRY = "billing.reconciliation_retry", "Billing receipt retry requested"
    INTEGRATION_CREDENTIAL_UPDATED = "integration_credential.updated", "Integration credential updated"
    INTEGRATION_CREDENTIAL_REVOKED = "integration_credential.revoked", "Integration credential revoked"
    AI_ROUTING_UPDATED = "ai_routing.updated", "AI routing updated"
    SOURCE_DISABLED = "source.disabled", "CSV source disabled"
    SOURCE_ENABLED = "source.enabled", "CSV source enabled"
    GOOGLE_OAUTH_CONNECTED = "google_oauth.connected", "Search Console OAuth connected"
    GOOGLE_OAUTH_REVOKED = "google_oauth.revoked", "Search Console OAuth revoked"
    GOOGLE_OAUTH_REVOCATION_REQUESTED = "google_oauth.revocation_requested", "Search Console OAuth revocation requested"
    GOOGLE_OAUTH_RECONNECT_REQUIRED = "google_oauth.reconnect_required", "Search Console OAuth reconnect required"
    GA4_PROPERTY_SELECTED = "ga4.property_selected", "GA4 web property selected"
    GA4_SOURCE_CONNECTED = "ga4.source_connected", "GA4 source connected"
    GA4_REVOCATION_REQUESTED = "ga4.revocation_requested", "GA4 revocation requested"
    GA4_REVOKED = "ga4.revoked", "GA4 credential revoked"
    GA4_RECONNECT_REQUIRED = "ga4.reconnect_required", "GA4 reconnect required"
    GA4_MEASUREMENT_REVIEWED = "ga4.measurement_reviewed", "GA4 measurement definition reviewed"
    REPORT_SHARE_CREATED = "report.share_created", "One private report bearer share created"
    REPORT_SHARE_REVOKED = "report.share_revoked", "Report share revoked"
    SUPPORT_REQUEST_ACCESSED = "support.request_accessed", "Staff accessed scoped support request"
    SUPPORT_REQUEST_UPDATED = "support.request_updated", "Staff updated scoped support request"
    STAFF_JOB_INSPECTED = "job.staff_inspected", "Staff inspected exact scoped job status"
    STAFF_USAGE_INSPECTED = "usage.staff_inspected", "Staff inspected exact scoped internal units"
    STAFF_AI_USAGE_INSPECTED = "ai_usage.staff_inspected", "Staff inspected exact scoped AI observations"
    STAFF_NOTICE_INSPECTED = "notice.staff_inspected", "Staff inspected exact organization notice transport"
    STAFF_ACCOUNT_MAIL_INSPECTED = "account_mail.staff_inspected", "Staff inspected exact current account-mail record"
    STAFF_EMAIL_FEEDBACK_INSPECTED = "email_feedback.staff_inspected", "Staff inspected exact retained email feedback"
    STAFF_BILLING_RECEIPT_INSPECTED = "billing_receipt.staff_inspected", "Staff inspected exact retained billing receipt"
    STAFF_TRIAL_INSPECTED = "trial.staff_inspected", "Staff inspected exact retained organization trial"
    STAFF_SUBSCRIPTION_INSPECTED = "subscription.staff_inspected", "Staff inspected exact retained linked subscription"
    STAFF_SUBSCRIPTION_HISTORY_INSPECTED = "subscription_history.staff_inspected", "Staff inspected exact retained archived subscription"
    STAFF_CANCELLATION_INSPECTED = "billing_cancellation.staff_inspected", "Staff inspected exact retained closure cancellation"
    STAFF_CHECKOUT_INSPECTED = "checkout.staff_inspected", "Staff inspected exact retained checkout attempt"
    STAFF_CHECKOUT_LINK_INSPECTED = "checkout_link.staff_inspected", "Staff inspected exact retained checkout link acknowledgment"
    STAFF_FIRST_ACTIVE_INSPECTED = "first_active.staff_inspected", "Staff inspected exact retained first active observation"


class OwnershipTransfer(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="ownership_transfers")
    from_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="transfers_sent")
    to_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="transfers_received")
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization"], condition=Q(state="pending"), name="tenancy_one_pending_transfer"
            ),
            models.CheckConstraint(condition=~Q(from_user=models.F("to_user")), name="tenancy_distinct_transfer_users"),
            models.CheckConstraint(
                condition=(Q(state="accepted", accepted_at__isnull=False) | Q(state__in=["pending", "cancelled"], accepted_at__isnull=True)),
                name="tenancy_accepted_transfer_timestamp",
            ),
        ]


class AuditEvent(models.Model):
    organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.PROTECT, related_name="audit_events")
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.PROTECT, related_name="audit_events")
    event_type = models.CharField(max_length=48, choices=AuditEventType.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="acted_audit_events",
    )
    subject_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="subject_audit_events",
    )
    invitation = models.ForeignKey(
        OrganizationInvitation,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    details = models.JSONField(default=dict)
    request_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class PublicAnalyticsConsentEpoch(models.Model):
    """Global pseudonymous optional choice, never joined to customer/account data."""
    proof_digest = models.CharField(max_length=64, unique=True, editable=False)
    policy_digest = models.CharField(max_length=64, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField(editable=False, db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(proof_digest__regex=r"^[0-9a-f]{64}$")
                & Q(policy_digest__regex=r"^[0-9a-f]{64}$"), name="tenancy_public_epoch_digests"),
            models.CheckConstraint(condition=Q(expires_at=models.F("created_at") + timedelta(minutes=15)),
                                   name="tenancy_public_epoch_lifetime"),
            models.CheckConstraint(condition=Q(revoked_at__isnull=True) | Q(revoked_at__gte=models.F("created_at")),
                                   name="tenancy_public_epoch_revoked_time"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Public consent epochs cannot be rewritten.")
        self.full_clean()
        return super().save(*args, **kwargs)


class PublicAnalyticsObservation(models.Model):
    class Event(models.TextChoices):
        PAGE = "public_page_view", "Browser-reported public route observation"
        CTA = "public_cta_selected", "Browser-reported public CTA observation"

    epoch = models.ForeignKey(PublicAnalyticsConsentEpoch, on_delete=models.CASCADE, related_name="observations")
    event_id = models.CharField(max_length=24, choices=Event.choices, editable=False)
    route_id = models.CharField(max_length=32, editable=False)
    locale = models.CharField(max_length=2, choices=[("en", "English"), ("tr", "Turkish")], editable=False)
    cta_id = models.CharField(max_length=64, blank=True, editable=False)
    html_sha256 = models.CharField(max_length=64, editable=False)
    occurred_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["epoch", "event_id", "route_id", "locale", "cta_id"],
                                    name="tenancy_public_observation_once"),
            models.CheckConstraint(condition=Q(route_id__regex=r"^[A-Z][A-Z0-9_]{0,31}$")
                & Q(locale__in=["en", "tr"]) & Q(html_sha256__regex=r"^[0-9a-f]{64}$"),
                name="tenancy_public_observation_shape"),
            models.CheckConstraint(condition=Q(event_id="public_page_view", cta_id="")
                | (Q(event_id="public_cta_selected") & Q(cta_id__regex=r"^[a-z][a-z0-9_]{0,63}$")),
                name="tenancy_public_observation_event"),
        ]

    def clean(self):
        super().clean()
        if self.epoch_id and (self.epoch.revoked_at is not None
            or not self.epoch.created_at <= self.occurred_at < self.epoch.expires_at
            or timezone.now() >= self.epoch.expires_at):
            raise ValidationError("Public observation requires a current consent epoch.")

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Public observations cannot be rewritten.")
        self.full_clean()
        return super().save(*args, **kwargs)


class PublicContactRequest(models.Model):
    """Anonymous enquiry, never organization membership or verified reply authority."""
    browser_key_hash = models.CharField(max_length=64)
    request_key = models.CharField(max_length=64)
    category = models.CharField(max_length=16)
    language = models.CharField(max_length=2)
    reply_email = models.EmailField(max_length=254)
    question = models.CharField(max_length=2000)
    no_sensitive_data = models.BooleanField()
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["browser_key_hash", "request_key"], name="tenancy_contact_once"),
            models.CheckConstraint(condition=Q(browser_key_hash__regex=r"^[0-9a-f]{64}$"), name="tenancy_contact_browser"),
            models.CheckConstraint(condition=Q(request_key__regex=r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$"), name="tenancy_contact_key"),
            models.CheckConstraint(condition=Q(category__in=["sales", "support", "privacy", "accessibility"]), name="tenancy_contact_category"),
            models.CheckConstraint(condition=Q(language__in=["en", "tr"]), name="tenancy_contact_language"),
            models.CheckConstraint(condition=Q(no_sensitive_data=True) & ~Q(question=""), name="tenancy_contact_declaration"),
            models.CheckConstraint(condition=Q(expires_at__gt=models.F("created_at")), name="tenancy_contact_expiry"),
        ]

    def clean(self):
        super().clean()
        from .public_contact import FIELDS, validate_contact_command
        validate_contact_command({name: getattr(self, name) for name in FIELDS})
        if (timezone.is_naive(self.created_at) or timezone.is_naive(self.expires_at)
            or self.created_at > timezone.now() or self.expires_at <= self.created_at):
            raise ValidationError("Contact request dates need review.")

    def save(self, *args, **kwargs):
        if not self._state.adding or (self.pk and type(self).objects.filter(pk=self.pk).exists()):
            raise ValidationError("Contact requests cannot be rewritten.")
        # Let database uniqueness arbitrate concurrent get_or_create calls.
        self.full_clean(validate_unique=False, validate_constraints=False)
        return super().save(*args, **kwargs)


class SupportRequest(models.Model):
    """Immutable customer prose, not an external ticket or detailed job access grant."""
    class Category(models.TextChoices):
        JOB = "job", "Job"
        BILLING = "account_billing", "Account or billing"
        SOURCES = "data_sources", "Data sources"
        ACCESSIBILITY = "accessibility", "Accessibility"
        OTHER = "other", "Other"

    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    job = models.ForeignKey("jobs.JobRun", null=True, blank=True, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=64)
    category = models.CharField(max_length=16, choices=Category.choices)
    question = models.CharField(max_length=2000)
    no_sensitive_data = models.BooleanField()
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "requester", "request_key"], name="tenancy_support_request_once"),
            models.CheckConstraint(condition=Q(request_key__regex=r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$"),
                                   name="tenancy_support_request_key"),
            models.CheckConstraint(condition=Q(category__in=["job", "account_billing", "data_sources", "accessibility", "other"]),
                                   name="tenancy_support_request_category"),
            models.CheckConstraint(condition=Q(no_sensitive_data=True) & ~Q(question=""), name="tenancy_support_request_declaration"),
        ]

    def clean(self):
        super().clean()
        from .support_requests import validate_support_command
        validate_support_command({"request_key": self.request_key, "category": self.category, "question": self.question,
                                  "job_id": self.job_id, "no_sensitive_data": self.no_sensitive_data})
        from jobs.models import JobRun
        if (timezone.is_naive(self.created_at) or self.created_at > timezone.now()
            or (self.job_id and not JobRun.objects.filter(pk=self.job_id, project_id=self.project_id,
                                                        organization_id=self.project.organization_id).exists())):
            raise ValidationError("Support request binding needs review.")

    def save(self, *args, **kwargs):
        if not self._state.adding or (self.pk and type(self).objects.filter(pk=self.pk).exists()):
            raise ValidationError("Support requests cannot be rewritten.")
        self.full_clean()
        return super().save(*args, **kwargs)


class SupportRequestUpdate(models.Model):
    """Append-only customer-visible staff responses; audit records contain no prose."""
    request = models.ForeignKey(SupportRequest, on_delete=models.PROTECT, related_name="updates")
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=[("received", "Received"), ("in_progress", "In progress"), ("resolved", "Resolved")])
    response = models.CharField(max_length=2000)
    request_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["request", "revision"], name="tenancy_support_update_revision"),
            models.UniqueConstraint(fields=["request", "request_key"], name="tenancy_support_update_once"),
            models.CheckConstraint(condition=Q(revision__gte=1, revision__lt=2**31), name="tenancy_support_update_positive"),
            models.CheckConstraint(condition=Q(status__in=["received", "in_progress", "resolved"]), name="tenancy_support_update_status"),
            models.CheckConstraint(condition=Q(request_key__regex=r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$") & ~Q(response=""),
                                   name="tenancy_support_update_shape"),
        ]

    def clean(self):
        super().clean()
        from .support_staff import validate_staff_update
        validate_staff_update({"request_key": self.request_key, "expected_revision": self.revision - 1,
                               "status": self.status, "response": self.response})
        if (timezone.is_naive(self.created_at) or self.created_at > timezone.now()
            or self.created_at < self.request.created_at):
            raise ValidationError("Support response dates need review.")

    def save(self, *args, **kwargs):
        if not self._state.adding or (self.pk and type(self).objects.filter(pk=self.pk).exists()):
            raise ValidationError("Support responses require a new immutable revision.")
        self.full_clean()
        return super().save(*args, **kwargs)
