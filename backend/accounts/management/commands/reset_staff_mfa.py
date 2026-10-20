import secrets

from allauth.mfa.models import Authenticator
from allauth.usersessions.models import UserSession
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tenancy.models import AuditEvent, AuditEventType


class Command(BaseCommand):
    help = "Reset another staff user's MFA after an authorized lost-factor recovery review."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--actor", required=True, help="Active superuser approving the recovery")
        parser.add_argument("--reason", required=True)
        parser.add_argument("--confirm-email", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        email = User.objects.normalize_email(options["email"])
        actor_email = User.objects.normalize_email(options["actor"])
        reason = options["reason"].strip()
        if options["confirm_email"] != email or not reason:
            raise CommandError("Target confirmation and a nonblank reason are required.")

        try:
            actor = User.objects.get(email=actor_email, is_active=True, is_superuser=True)
            target = User.objects.select_for_update().get(email=email, is_active=True, is_staff=True)
        except User.DoesNotExist as error:
            raise CommandError("Active operator and target staff accounts are required.") from error
        if actor.pk == target.pk:
            raise CommandError("A different active superuser must approve staff MFA recovery.")

        deleted, _ = Authenticator.objects.filter(user=target).delete()
        if not deleted:
            raise CommandError("The target staff account has no MFA factors to reset.")
        target.session_version = secrets.token_hex(16)
        target.save(update_fields=["session_version"])
        for session in UserSession.objects.filter(user=target):
            session.end()
        AuditEvent.objects.create(
            event_type=AuditEventType.STAFF_MFA_RECOVERY_RESET,
            actor=actor,
            subject_user=target,
            details={"operation": "lost_factor_reset", "reason": reason[:250]},
        )
        self.stdout.write(self.style.SUCCESS(f"MFA reset for {target.email}; fresh enrollment is required."))
