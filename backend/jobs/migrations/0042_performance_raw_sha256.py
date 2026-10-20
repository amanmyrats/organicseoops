import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('jobs', '0041_projectalertdelivery_projectalertepisodeclaim')]

    operations = [
        migrations.AddField(
            model_name='performanceobservationsnapshot',
            name='raw_sha256',
            field=models.CharField(blank=True, editable=False, max_length=64, null=True,
                                   validators=[django.core.validators.RegexValidator('^[0-9a-f]{64}$')]),
        ),
        migrations.AddConstraint(
            model_name='performanceobservationsnapshot',
            constraint=models.CheckConstraint(
                condition=models.Q(raw_sha256__isnull=True) | models.Q(raw_sha256__regex='^[0-9a-f]{64}$'),
                name='jobs_performance_raw_sha_valid',
            ),
        ),
    ]
