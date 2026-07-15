from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hunting", "0001_initial")]
    operations = [
        migrations.AddField(model_name="sourcepolicy", name="reliability_weight", field=models.PositiveSmallIntegerField(default=50)),
        migrations.AddField(model_name="sourcepolicy", name="timeout_seconds", field=models.PositiveIntegerField(default=30)),
        migrations.AddField(model_name="sourcepolicy", name="max_retries", field=models.PositiveSmallIntegerField(default=2)),
        migrations.AddField(model_name="sourcepolicy", name="priority", field=models.PositiveSmallIntegerField(default=100)),
    ]
