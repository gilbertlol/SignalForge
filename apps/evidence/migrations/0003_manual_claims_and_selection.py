import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("evidence", "0002_organization_claims"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.RemoveConstraint(
            model_name="organizationclaim", name="organization_claim_unique_record_field"
        ),
        migrations.AlterField(
            model_name="organizationclaim",
            name="source_record",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="claims",
                to="discovery.sourcerecord",
            ),
        ),
        migrations.AddField(
            model_name="organizationclaim",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="organizationclaim", name="note", field=models.TextField(blank=True)
        ),
        migrations.AddConstraint(
            model_name="organizationclaim",
            constraint=models.UniqueConstraint(
                condition=models.Q(("source_record__isnull", False)),
                fields=("source_record", "field_name"),
                name="organization_claim_unique_record_field",
            ),
        ),
        migrations.AddField(
            model_name="organizationfieldresolution",
            name="is_manually_selected",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="organizationfieldresolution",
            name="selection_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="organizationfieldresolution",
            name="selected_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
