from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0037_firstauditvalueacknowledgment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="ProjectSummaryPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("frequency", models.CharField(choices=[("off", "Off"), ("weekly", "Weekly")], default="off", max_length=6)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenancy.project")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={"constraints": [
                models.UniqueConstraint(fields=("project", "user"), name="jobs_summary_pref_project_user_unique"),
                models.CheckConstraint(condition=models.Q(frequency__in=["off", "weekly"]), name="jobs_summary_pref_frequency_valid"),
                models.CheckConstraint(condition=models.Q(revision__gte=1), name="jobs_summary_pref_revision_positive"),
            ]},
        ),
    ]
