import hashlib

from django.db import migrations, models


def populate_canonical_hashes(apps, schema_editor):
    observation_model = apps.get_model("discovery", "WebPageObservation")
    for observation in observation_model.objects.all().iterator():
        observation.canonical_sha256 = hashlib.sha256(
            observation.canonical_url.encode()
        ).hexdigest()
        observation.save(update_fields=["canonical_sha256"])


class Migration(migrations.Migration):
    dependencies = [("discovery", "0007_webpageobservation_and_more")]

    operations = [
        migrations.RemoveConstraint(
            model_name="webpageobservation",
            name="web_observation_unique_content",
        ),
        migrations.AddField(
            model_name="webpageobservation",
            name="canonical_sha256",
            field=models.CharField(max_length=64, null=True),
        ),
        migrations.RunPython(populate_canonical_hashes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="webpageobservation",
            name="canonical_sha256",
            field=models.CharField(max_length=64),
        ),
        migrations.AddConstraint(
            model_name="webpageobservation",
            constraint=models.UniqueConstraint(
                fields=("workspace", "canonical_sha256", "content_sha256"),
                name="web_observation_unique_content",
            ),
        ),
    ]
