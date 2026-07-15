from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("discovery", "0002_discoveryrun_initiated_by")]

    operations = [
        migrations.AlterField(
            model_name="providerresult",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "Queued"), ("running", "Running"),
                    ("retrying", "Retrying"), ("succeeded", "Succeeded"),
                    ("empty", "Empty"), ("failed", "Failed"),
                    ("partial", "Partial"), ("timed_out", "Timed out"),
                    ("rate_limited", "Rate limited"), ("canceled", "Canceled"),
                    ("budget_blocked", "Budget blocked"),
                ],
                default="queued",
                max_length=20,
            ),
        ),
        migrations.AddField(model_name="providerresult", name="query_snapshot", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="providerresult", name="max_records", field=models.IntegerField(blank=True, null=True)),
        migrations.AddField(model_name="providerresult", name="budget_cents", field=models.IntegerField(blank=True, null=True)),
        migrations.AddField(model_name="providerresult", name="attempt_count", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="providerresult", name="celery_task_id", field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(
            model_name="sourcerecord",
            name="provider_result",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="records", to="discovery.providerresult"),
        ),
        migrations.AddConstraint(
            model_name="providerresult",
            constraint=models.UniqueConstraint(fields=("discovery_run", "provider_key"), name="provider_result_unique_source_per_run"),
        ),
        migrations.AddConstraint(
            model_name="sourcerecord",
            constraint=models.UniqueConstraint(condition=~models.Q(external_id=""), fields=("discovery_run", "source_key", "external_id"), name="source_record_unique_external_id_per_run_source"),
        ),
    ]
