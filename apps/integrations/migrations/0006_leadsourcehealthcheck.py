import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0005_leadsourceconfiguration_config")]
    operations = [
        migrations.CreateModel(
            name="LeadSourceHealthCheck",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ready", "Ready"),
                            ("auth_failed", "Authentication failed"),
                            ("rate_limited", "Rate limited"),
                            ("quota_exhausted", "Quota exhausted"),
                            ("unavailable", "Unavailable"),
                        ],
                        max_length=30,
                    ),
                ),
                ("was_successful", models.BooleanField(default=False)),
                ("latency_ms", models.PositiveIntegerField(default=0)),
                ("sanitized_error", models.CharField(blank=True, max_length=255)),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="core.workspace",
                    ),
                ),
                (
                    "configuration",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="health_checks",
                        to="integrations.leadsourceconfiguration",
                    ),
                ),
            ],
            options={"abstract": False},
        ),
    ]
