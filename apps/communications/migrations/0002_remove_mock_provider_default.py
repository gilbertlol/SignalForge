from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("communications", "0001_initial")]
    operations = [migrations.AlterField(model_name="channelaccount", name="provider_key", field=models.SlugField(max_length=100))]
