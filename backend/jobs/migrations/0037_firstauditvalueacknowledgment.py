import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('jobs', '0036_firstboundedauditcompletion'),
        ('tenancy', '0063_organization_first_value_tracking'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='FirstAuditValueAcknowledgment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('acknowledged_at', models.DateTimeField(editable=False)),
                ('source', models.JSONField(editable=False)),
                ('source_digest', models.CharField(editable=False, max_length=64)),
                ('action_review', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='jobs.actionreview')),
                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='jobs.jobrun')),
                ('organization', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                    related_name='first_audit_value', to='tenancy.organization')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenancy.project')),
            ],
            options={'constraints': [models.CheckConstraint(condition=models.Q(('source_digest__regex', '^[a-f0-9]{64}$')),
                name='jobs_first_value_digest_valid')]},
        ),
    ]
