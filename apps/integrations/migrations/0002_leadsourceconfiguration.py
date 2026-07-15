import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="LeadSourceConfiguration",
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
                ("source_key", models.SlugField(max_length=100)),
                ("name", models.CharField(max_length=255)),
                (
                    "base_url",
                    models.URLField(
                        default="https://api.apollo.io/api/v1/mixed_companies/search"
                    ),
                ),
                ("timeout_seconds", models.PositiveIntegerField(default=30)),
                ("enabled", models.BooleanField(default=True)),
                (
                    "credential",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lead_source_configurations",
                        to="integrations.credentialreference",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="core.workspace",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="leadsourceconfiguration",
            constraint=models.UniqueConstraint(
                fields=("workspace", "source_key"), name="uniq_lead_source_workspace_key"
            ),
        ),
    ]
