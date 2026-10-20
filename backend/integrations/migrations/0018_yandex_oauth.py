import django.core.validators
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0017_searchanalyticsquerypagesnapshot"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(name="YandexOAuthApplication", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("key", models.CharField(default="primary", editable=False, max_length=8, unique=True)),
            ("client_id", models.CharField(max_length=128)), ("redirect_uri", models.URLField(max_length=512)),
            ("encrypted_secret", models.TextField(editable=False, max_length=8192)),
            ("revision", models.PositiveIntegerField(default=1)), ("updated_at", models.DateTimeField(auto_now=True)),
        ], options={"constraints": [models.CheckConstraint(condition=models.Q(key="primary", encrypted_secret__startswith="v1:"), name="integrations_yandex_app_valid")]}),
        migrations.CreateModel(name="YandexOAuthIntent", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("app_revision", models.PositiveIntegerField()), ("origin", models.URLField(max_length=512)),
            ("state_digest", models.CharField(max_length=64, unique=True, validators=[django.core.validators.RegexValidator(r"^[0-9a-f]{64}$")])),
            ("session_digest", models.CharField(max_length=64, validators=[django.core.validators.RegexValidator(r"^[0-9a-f]{64}$")])),
            ("encrypted_verifier", models.TextField(blank=True, max_length=8192)),
            ("device_id", models.UUIDField(default=uuid.uuid4, editable=False)),
            ("status", models.CharField(choices=[("pending", "Pending"), ("consumed", "Consumed"), ("denied", "Denied")], default="pending", max_length=12)),
            ("expires_at", models.DateTimeField()), ("used_at", models.DateTimeField(blank=True, null=True)),
            ("user_reported_revoked_at", models.DateTimeField(blank=True, null=True)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ("application", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="integrations.yandexoauthapplication")),
            ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenancy.organization")),
            ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenancy.project")),
        ], options={"constraints": [models.CheckConstraint(condition=models.Q(status="pending", used_at__isnull=True, encrypted_verifier__startswith="v1:")
            | models.Q(status__in=["consumed", "denied"], used_at__isnull=False, encrypted_verifier=""), name="integrations_yandex_intent_valid")]}),
        migrations.CreateModel(name="YandexOAuthGrant", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("origin", models.URLField(max_length=512)), ("user_id", models.CharField(blank=True, max_length=20)),
            ("host_id", models.CharField(blank=True, max_length=512)), ("encrypted_tokens", models.TextField(blank=True, max_length=16384)),
            ("expires_at", models.DateTimeField()), ("scope", models.CharField(default="webmaster:hostinfo", max_length=128)),
            ("state", models.CharField(choices=[("active", "Active"), ("reconnect_required", "Reconnect required"), ("revocation_pending", "Revocation pending"), ("revoked", "Revoked")], default="revocation_pending", max_length=24)),
            ("revision", models.PositiveIntegerField(default=0)), ("revoked_at", models.DateTimeField(blank=True, null=True)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ("application", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="integrations.yandexoauthapplication")),
            ("intent", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to="integrations.yandexoauthintent")),
            ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenancy.organization")),
            ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenancy.project")),
        ], options={"constraints": [models.CheckConstraint(condition=models.Q(state__in=["active", "reconnect_required", "revocation_pending"], revoked_at__isnull=True, encrypted_tokens__startswith="v1:")
            | models.Q(state="revoked", revoked_at__isnull=False, encrypted_tokens="", user_id="", host_id=""), name="integrations_yandex_grant_valid")]}),
    ]
