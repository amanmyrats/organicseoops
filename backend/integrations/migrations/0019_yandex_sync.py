import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0018_yandex_oauth")]
    operations = [
        migrations.AddField(model_name="yandexoauthgrant", name="connection",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="integrations.integrationconnection")),
        migrations.AddField(model_name="yandexoauthgrant", name="refresh_started_at",
            field=models.DateTimeField(blank=True, null=True)),
    ]
