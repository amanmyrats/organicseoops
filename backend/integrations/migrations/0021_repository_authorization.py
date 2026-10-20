from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("integrations", "0020_serp_configuration"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name="RepositoryApplication", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("key", models.CharField(default="primary", editable=False, max_length=8, unique=True)),
            ("app_id", models.PositiveBigIntegerField()), ("client_id", models.CharField(max_length=128)),
            ("redirect_uri", models.URLField(max_length=512)), ("encrypted_secrets", models.TextField(editable=False)),
            ("revision", models.PositiveIntegerField(default=1)), ("updated_at", models.DateTimeField(auto_now=True)),
        ]),
        migrations.CreateModel(name="RepositoryConsent", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("app_revision", models.PositiveIntegerField()), ("repository", models.CharField(max_length=140)),
            ("repository_id", models.PositiveBigIntegerField()), ("commit_sha", models.CharField(max_length=40)),
            ("state_digest", models.CharField(max_length=64, unique=True)), ("session_digest", models.CharField(max_length=64)),
            ("encrypted_verifier", models.TextField(blank=True)), ("status", models.CharField(default="pending", max_length=12)),
            ("expires_at", models.DateTimeField()), ("used_at", models.DateTimeField(blank=True, null=True)),
            ("user_reported_revoked_at", models.DateTimeField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ("application", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="integrations.repositoryapplication")),
            ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenancy.organization")),
            ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenancy.project")),
        ], options={"constraints": [models.CheckConstraint(condition=models.Q(status="pending", used_at__isnull=True, encrypted_verifier__startswith="v1:")
            | models.Q(status__in=["consumed", "denied"], used_at__isnull=False, encrypted_verifier=""), name="integrations_repository_consent_state")]}),
        migrations.CreateModel(name="RepositoryGrant", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("repository", models.CharField(max_length=140)), ("repository_id", models.PositiveBigIntegerField()),
            ("commit_sha", models.CharField(max_length=40)), ("github_user_id", models.PositiveBigIntegerField(blank=True, null=True)),
            ("installation_id", models.PositiveBigIntegerField(blank=True, null=True)), ("encrypted_tokens", models.TextField(blank=True)),
            ("expires_at", models.DateTimeField()),
            ("state", models.CharField(choices=[("active", "Active"), ("revocation_pending", "Revocation pending"), ("revoked", "Revoked")], default="revocation_pending", max_length=24)),
            ("revision", models.PositiveIntegerField(default=0)), ("revoked_at", models.DateTimeField(blank=True, null=True)),
            ("revocation_evidence", models.CharField(blank=True, max_length=48)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ("application", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="integrations.repositoryapplication")),
            ("consent", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to="integrations.repositoryconsent")),
            ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenancy.organization")),
            ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenancy.project")),
        ], options={"constraints": [models.CheckConstraint(condition=models.Q(state__in=["active", "revocation_pending"],
            encrypted_tokens__startswith="v1:", revoked_at__isnull=True)
            | models.Q(state="revoked", encrypted_tokens="", revoked_at__isnull=False), name="integrations_repository_grant_state")]}),
    ]
