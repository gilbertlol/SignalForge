from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0004_remove_mock_provider_choice")]
    operations = [
        migrations.AddField(
            model_name="leadsourceconfiguration",
            name="config",
            field=models.JSONField(blank=True, default=dict),
        )
    ]
