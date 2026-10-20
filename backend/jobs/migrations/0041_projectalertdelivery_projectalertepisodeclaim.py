import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('jobs', '0040_projectalertpreference'),
        ('tenancy', '0064_public_analytics_epoch_observation'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ProjectAlertDelivery',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('preference_revision', models.PositiveIntegerField()),
                ('primary_address_id', models.PositiveBigIntegerField()),
                ('day_start', models.DateField()),
                ('source_metadata', models.JSONField()),
                ('source_fingerprint', models.CharField(max_length=64, validators=[django.core.validators.RegexValidator('^[0-9a-f]{64}$')])),
                ('state', models.CharField(choices=[('queued', 'Queued'), ('sending', 'Sending (outcome pending)'), ('sent', 'Transport accepted'), ('skipped', 'Skipped'), ('unknown', 'Outcome unknown (never replayed)')], default='queued', max_length=7)),
                ('error_category', models.CharField(blank=True, max_length=40)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('attempted_at', models.DateTimeField(blank=True, null=True)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('preference', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='jobs.projectalertpreference')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenancy.project')),
                ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={'constraints': [
                models.UniqueConstraint(fields=('project', 'recipient', 'day_start'), name='jobs_alert_delivery_day_unique'),
                models.CheckConstraint(condition=models.Q(preference_revision__gte=1, primary_address_id__gte=1), name='jobs_alert_delivery_binding_positive'),
                models.CheckConstraint(condition=models.Q(state__in=['queued', 'sending', 'sent', 'skipped', 'unknown']), name='jobs_alert_delivery_state_valid'),
                models.CheckConstraint(condition=(models.Q(state='queued', attempted_at__isnull=True, sent_at__isnull=True)
                    | models.Q(state__in=['sending', 'skipped', 'unknown'], attempted_at__isnull=False, sent_at__isnull=True)
                    | models.Q(state='sent', attempted_at__isnull=False, sent_at__isnull=False)), name='jobs_alert_delivery_timestamps'),
            ]},
        ),
        migrations.CreateModel(
            name='ProjectAlertEpisodeClaim',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('episode_key', models.CharField(max_length=64, validators=[django.core.validators.RegexValidator('^(crawl:[1-9][0-9]*|reconnect:[1-9][0-9]*:[1-9][0-9]*)$')])),
                ('delivery', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='jobs.projectalertdelivery')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='tenancy.project')),
                ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={'constraints': [
                models.UniqueConstraint(fields=('project', 'recipient', 'episode_key'), name='jobs_alert_episode_unique'),
                models.CheckConstraint(condition=models.Q(episode_key__regex='^(crawl:[1-9][0-9]*|reconnect:[1-9][0-9]*:[1-9][0-9]*)$'), name='jobs_alert_episode_key_valid'),
            ]},
        ),
    ]
