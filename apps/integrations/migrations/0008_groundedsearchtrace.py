from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [("integrations", "0007_alter_leadsourceconfiguration_credential")]

    operations = [
        migrations.CreateModel(
            name="GroundedSearchTrace",
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
                ("provider_key", models.SlugField(max_length=100)),
                ("model_identifier", models.CharField(max_length=255)),
                ("query", models.TextField()),
                ("response_text", models.TextField()),
                ("citations", models.JSONField(default=list)),
                ("search_queries", models.JSONField(default=list)),
                ("raw_metadata", models.JSONField(default=dict)),
                (
                    "search_cost_cents",
                    models.DecimalField(decimal_places=4, default=0, max_digits=12),
                ),
                (
                    "invocation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="grounded_search_trace",
                        to="integrations.modelinvocation",
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
            options={"abstract": False},
        )
    ]
