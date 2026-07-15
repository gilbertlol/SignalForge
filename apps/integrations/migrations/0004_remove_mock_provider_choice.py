from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("integrations", "0003_leadsourceconfiguration_estimated_cost")]
    operations = [migrations.AlterField(model_name="aiprovider", name="provider_type", field=models.CharField(choices=[("local_openai", "Local OpenAI compatible"), ("cloud_openai", "Cloud OpenAI compatible"), ("native", "Native provider")], max_length=30))]
