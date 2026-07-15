from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0002_leadsourceconfiguration")]

    operations = [
        migrations.AddField(
            model_name="leadsourceconfiguration",
            name="estimated_cost_per_page_cents",
            field=models.PositiveIntegerField(default=0),
        )
    ]
