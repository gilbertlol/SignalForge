from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hunting", "0002_sourcepolicy_execution_controls")]
    operations = [
        migrations.AddField(
            model_name="searchscope",
            name="keyword",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="searchscope",
            name="included_type",
            field=models.SlugField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="searchscope",
            name="center_latitude",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
        migrations.AddField(
            model_name="searchscope",
            name="center_longitude",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
        ),
        migrations.AddField(
            model_name="searchscope",
            name="radius_meters",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
