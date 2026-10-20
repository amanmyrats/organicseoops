from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_user_session_version"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="first_email_verified_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]
