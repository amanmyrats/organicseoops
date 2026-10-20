from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_user_first_email_verified_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="registration_origin",
            field=models.CharField(
                blank=True,
                choices=[("self_service", "Self-service")],
                editable=False,
                max_length=12,
                null=True,
            ),
        ),
    ]
