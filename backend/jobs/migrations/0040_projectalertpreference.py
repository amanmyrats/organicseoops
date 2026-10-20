from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0039_projectsummarydelivery"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="ProjectAlertPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("frequency", models.CharField(choices=[("off", "Off"), ("daily", "Daily")], default="off", max_length=5)),
                ("crawl_failure", models.BooleanField(default=False)),
                ("integration_health", models.BooleanField(default=False)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenancy.project")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={"constraints": [
                models.UniqueConstraint(fields=("project", "user"), name="jobs_alert_pref_project_user_unique"),
                models.CheckConstraint(condition=models.Q(frequency__in=["off", "daily"]), name="jobs_alert_pref_frequency_valid"),
                models.CheckConstraint(condition=models.Q(revision__gte=1), name="jobs_alert_pref_revision_positive"),
                models.CheckConstraint(condition=models.Q(frequency="off") | models.Q(crawl_failure=True) | models.Q(integration_health=True),
                                       name="jobs_alert_pref_daily_source"),
            ]},
        ),
    ]
