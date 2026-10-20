# Generated from Django 6.1.1 dry-run output on 2026-10-05.
import django.core.validators
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('jobs', '0048_passive_redirect_finding_source'),
        ('tenancy', '0080_staff_first_active_inspection_audit'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='opportunity', name='passive_source_sha256',
            field=models.CharField(blank=True, default='', max_length=64,
                validators=[django.core.validators.RegexValidator('^[0-9a-f]{64}$')]),
        ),
        migrations.AddConstraint(
            model_name='opportunity',
            constraint=models.CheckConstraint(condition=models.Q(('passive_source_sha256', ''),
                ('passive_source_sha256__regex', '^[0-9a-f]{64}$'), _connector='OR'),
                name='jobs_opportunity_passive_digest_shape'),
        ),
    ]
