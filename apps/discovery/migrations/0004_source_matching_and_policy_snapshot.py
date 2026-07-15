from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("discovery", "0003_parallel_provider_executions")]

    operations = [
        migrations.AddField(
            model_name="providerresult",
            name="policy_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="sourcerecord",
            name="match_confidence",
            field=models.DecimalField(blank=True, decimal_places=3, max_digits=4, null=True),
        ),
        migrations.AddField(
            model_name="sourcerecord",
            name="match_explanation",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="sourcerecord",
            name="match_method",
            field=models.CharField(
                blank=True,
                choices=[
                    ("created", "New organization"),
                    ("provider_id", "Provider identifier"),
                    ("domain", "Normalized domain"),
                    ("exact_name", "Exact normalized name"),
                ],
                max_length=20,
            ),
        ),
    ]
