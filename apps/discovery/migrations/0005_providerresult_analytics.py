from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("discovery", "0004_source_matching_and_policy_snapshot")]
    operations = [
        migrations.AddField(
            model_name="providerresult",
            name="pages_requested",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="providerresult",
            name="pages_returned",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="providerresult",
            name="reported_cost_cents",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="providerresult",
            name="failure_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="providerresult",
            name="rate_limit_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="providerresult",
            name="timeout_count",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
