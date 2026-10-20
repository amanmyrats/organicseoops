from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0019_yandex_sync")]
    operations = [migrations.CreateModel(name="SerpConfiguration", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("key", models.CharField(default="primary", editable=False, max_length=8, unique=True)),
        ("encrypted_credentials", models.TextField(editable=False)),
        ("enabled", models.BooleanField(default=False)),
        ("revision", models.PositiveIntegerField(default=1, editable=False)),
        ("locations", models.JSONField(default=dict, help_text='Reviewed Google location codes mapped to labels, e.g. {"2840": "United States"}.')),
        ("languages", models.JSONField(default=dict, help_text='Reviewed Google language codes mapped to labels, e.g. {"en": "English"}.')),
        ("estimated_task_cost_usd", models.DecimalField(decimal_places=6, max_digits=10)),
        ("monthly_exposure_usd", models.DecimalField(decimal_places=6, max_digits=10)),
        ("budget_month", models.CharField(blank=True, editable=False, max_length=7)),
        ("reserved_exposure_usd", models.DecimalField(decimal_places=6, default=0, editable=False, max_digits=12)),
        ("reviewed_until", models.DateTimeField(help_text="Recheck provider capabilities/pricing within 30 days. This is an estimate, not a provider-enforced charge cap.")),
        ("updated_at", models.DateTimeField(auto_now=True)),
    ])]
