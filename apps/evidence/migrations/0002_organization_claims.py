import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("discovery", "0003_parallel_provider_executions"),
        ("evidence", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizationClaim",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("source_key", models.CharField(max_length=100)),
                ("field_name", models.CharField(max_length=100)),
                ("value", models.JSONField()),
                ("normalized_value", models.TextField()),
                ("reliability", models.CharField(choices=[("low", "Low"), ("medium", "Medium"), ("high", "High")], default="medium", max_length=10)),
                ("observed_at", models.DateTimeField()),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="source_claims", to="organizations.organization")),
                ("source_record", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="claims", to="discovery.sourcerecord")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.workspace")),
            ],
            options={"ordering": ["field_name", "created_at"]},
        ),
        migrations.CreateModel(
            name="OrganizationFieldResolution",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("field_name", models.CharField(max_length=100)),
                ("corroboration_count", models.PositiveIntegerField(default=1)),
                ("distinct_value_count", models.PositiveIntegerField(default=1)),
                ("has_conflict", models.BooleanField(default=False)),
                ("explanation", models.TextField(blank=True)),
                ("resolved_at", models.DateTimeField()),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="field_resolutions", to="organizations.organization")),
                ("selected_claim", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="selected_by", to="evidence.organizationclaim")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="core.workspace")),
            ],
            options={"ordering": ["field_name"]},
        ),
        migrations.AddConstraint(model_name="organizationclaim", constraint=models.UniqueConstraint(fields=("source_record", "field_name"), name="organization_claim_unique_record_field")),
        migrations.AddIndex(model_name="organizationclaim", index=models.Index(fields=["organization", "field_name"], name="evidence_or_organiz_6ebb9d_idx")),
        migrations.AddConstraint(model_name="organizationfieldresolution", constraint=models.UniqueConstraint(fields=("organization", "field_name"), name="organization_resolution_unique_field")),
    ]
