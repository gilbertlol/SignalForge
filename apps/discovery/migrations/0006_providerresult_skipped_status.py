from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("discovery", "0005_providerresult_analytics")]
    operations = [
        migrations.AlterField(
            model_name="providerresult",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("retrying", "Retrying"),
                    ("succeeded", "Succeeded"),
                    ("empty", "Empty"),
                    ("failed", "Failed"),
                    ("partial", "Partial"),
                    ("timed_out", "Timed out"),
                    ("rate_limited", "Rate limited"),
                    ("canceled", "Canceled"),
                    ("budget_blocked", "Budget blocked"),
                    ("skipped", "Skipped — unavailable"),
                ],
                default="queued",
                max_length=20,
            ),
        ),
    ]
