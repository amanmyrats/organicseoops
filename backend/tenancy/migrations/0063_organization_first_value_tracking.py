from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('tenancy', '0062_organization_first_audit_tracking_and_more')]

    operations = [
        migrations.AddField(
            model_name='organization', name='first_value_tracking',
            field=models.CharField(blank=True, choices=[('bounded-audit-usefulness-ack-v1',
                'Prospective explicit audit usefulness acknowledgment')], editable=False, max_length=40, null=True),
        ),
        migrations.AddConstraint(
            model_name='organization',
            constraint=models.CheckConstraint(condition=models.Q(('first_value_tracking__isnull', True),
                ('first_value_tracking', 'bounded-audit-usefulness-ack-v1'), _connector='OR'),
                name='tenancy_first_value_tracking_valid'),
        ),
    ]
