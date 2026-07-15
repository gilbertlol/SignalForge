import uuid

from django.db import migrations, models

PRESETS = [
    {
        "key": "local-businesses",
        "name": "Local businesses",
        "description": "Find place-based operators with public map and business listing signals.",
        "configuration": {
            "form_initial": {
                "use_google_places": True,
                "use_openstreetmap": True,
                "google_places_max_records": 40,
                "google_places_budget_cents": 25,
                "google_places_reliability_weight": 80,
                "openstreetmap_max_records": 40,
                "openstreetmap_budget_cents": 0,
                "openstreetmap_reliability_weight": 60,
                "reliability_weight": 70,
                "minimum_score": 10,
            },
            "filter_translations": {
                "geographies": "service area",
                "industries": "place category",
                "keyword": "customer search phrase",
            },
            "source_policies": [
                {"source_key": "google_places", "reliability_weight": 80, "budget_cents": 25},
                {"source_key": "openstreetmap", "reliability_weight": 60, "budget_cents": 0},
                {"source_key": "corporate_registry", "reliability_weight": 90, "enabled": False},
            ],
            "scoring_objective": "qualified local organizations per unit cost",
        },
        "source_guidance": [
            {
                "source_key": "google_places",
                "strengths": "Current place identity, category, location and contact signals.",
                "limitations": "Coverage and storage terms vary; estimated API cost.",
                "alternative": "OpenStreetMap",
            },
            {
                "source_key": "openstreetmap",
                "strengths": "Open public geographic coverage with explicit provenance.",
                "limitations": "Sparse commercial metadata and community-dependent freshness.",
                "alternative": "Manual or CSV evidence",
            },
            {
                "source_key": "corporate_registry",
                "strengths": "Authoritative legal identity and registration facts.",
                "limitations": "No registry lead-source integration is installed yet.",
                "alternative": "Manual or CSV evidence",
            },
        ],
    },
    {
        "key": "funded-growing-companies",
        "name": "Funded and growing companies",
        "description": "Prioritize firms showing funding and headcount-growth signals.",
        "configuration": {
            "form_initial": {
                "use_apollo": True,
                "apollo_max_records": 40,
                "apollo_budget_cents": 100,
                "apollo_reliability_weight": 70,
                "reliability_weight": 70,
                "minimum_score": 15,
            },
            "filter_translations": {
                "industries": "company keyword tags",
                "company_size": "employee range",
            },
            "source_policies": [
                {"source_key": "apollo", "reliability_weight": 70, "budget_cents": 100},
                {"source_key": "funding_data", "reliability_weight": 80, "enabled": False},
            ],
            "scoring_objective": "qualified growth-stage organizations",
        },
        "source_guidance": [
            {
                "source_key": "apollo",
                "strengths": "Organization filters, domains, industries and company metadata.",
                "limitations": "Paid plan and credential required; provider coverage varies.",
                "alternative": "Manual or CSV company lists",
            },
            {
                "source_key": "funding_data",
                "strengths": "Funding events and growth timing.",
                "limitations": "No funding-data integration is installed yet.",
                "alternative": "Manual or CSV evidence",
            },
        ],
    },
    {
        "key": "agencies-professional-services",
        "name": "Agencies and professional services",
        "description": "Find specialist service firms through company and public web signals.",
        "configuration": {
            "form_initial": {
                "use_apollo": True,
                "use_openstreetmap": True,
                "apollo_max_records": 30,
                "apollo_reliability_weight": 70,
                "openstreetmap_max_records": 30,
                "openstreetmap_reliability_weight": 50,
                "reliability_weight": 65,
                "minimum_score": 10,
            },
            "filter_translations": {
                "industries": "service specialization",
                "keyword": "website positioning phrase",
            },
            "source_policies": [
                {"source_key": "apollo", "reliability_weight": 70},
                {"source_key": "web_search", "reliability_weight": 50, "enabled": False},
            ],
            "scoring_objective": "unique qualified service firms",
        },
        "source_guidance": [
            {
                "source_key": "apollo",
                "strengths": "Structured company attributes and domains.",
                "limitations": "Paid credential and plan limits.",
                "alternative": "OpenStreetMap",
            },
            {
                "source_key": "web_search",
                "strengths": "Niche positioning and public website discovery.",
                "limitations": "No web-search lead-source integration is installed yet.",
                "alternative": "OpenStreetMap plus manual website analysis",
            },
        ],
    },
    {
        "key": "manufacturers",
        "name": "Manufacturers",
        "description": (
            "Build manufacturer lists from industry classifications and legal identity evidence."
        ),
        "configuration": {
            "form_initial": {
                "use_openstreetmap": True,
                "openstreetmap_max_records": 50,
                "openstreetmap_budget_cents": 0,
                "openstreetmap_reliability_weight": 60,
                "reliability_weight": 70,
                "minimum_score": 15,
            },
            "filter_translations": {
                "industries": "manufacturing classification",
                "geographies": "plant location",
            },
            "source_policies": [
                {"source_key": "industry_directory", "reliability_weight": 70, "enabled": False},
                {"source_key": "corporate_registry", "reliability_weight": 90, "enabled": False},
            ],
            "scoring_objective": "corroborated manufacturers",
        },
        "source_guidance": [
            {
                "source_key": "industry_directory",
                "strengths": "Industry-specific classifications and capabilities.",
                "limitations": "No directory integration is installed yet.",
                "alternative": "OpenStreetMap",
            },
            {
                "source_key": "corporate_registry",
                "strengths": "Legal identity and operating status.",
                "limitations": "No registry integration is installed yet.",
                "alternative": "Manual or CSV evidence",
            },
        ],
    },
    {
        "key": "government-suppliers",
        "name": "Government suppliers",
        "description": "Discover vendors through procurement activity and registry corroboration.",
        "configuration": {
            "form_initial": {"manual_only": True, "reliability_weight": 80, "minimum_score": 20},
            "filter_translations": {
                "industries": "procurement category",
                "geographies": "buying jurisdiction",
            },
            "source_policies": [
                {"source_key": "procurement_portal", "reliability_weight": 90, "enabled": False},
                {"source_key": "corporate_registry", "reliability_weight": 90, "enabled": False},
            ],
            "scoring_objective": "corroborated suppliers with procurement evidence",
        },
        "source_guidance": [
            {
                "source_key": "procurement_portal",
                "strengths": "Observed awards, tenders and buyer relationships.",
                "limitations": "No procurement portal integration is installed yet.",
                "alternative": "CSV export from a public portal",
            },
            {
                "source_key": "corporate_registry",
                "strengths": "Legal identity corroboration.",
                "limitations": "No registry integration is installed yet.",
                "alternative": "Manual evidence",
            },
        ],
    },
]


def seed_presets(apps, schema_editor):
    HuntPreset = apps.get_model("hunting", "HuntPreset")
    for preset in PRESETS:
        HuntPreset.objects.create(version=1, is_active=True, **preset)


def remove_presets(apps, schema_editor):
    apps.get_model("hunting", "HuntPreset").objects.filter(version=1).delete()


class Migration(migrations.Migration):
    dependencies = [("hunting", "0003_searchscope_provider_filters")]
    operations = [
        migrations.CreateModel(
            name="HuntPreset",
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
                ("key", models.SlugField(max_length=100)),
                ("version", models.PositiveIntegerField(default=1)),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("configuration", models.JSONField(default=dict)),
                ("source_guidance", models.JSONField(default=list)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ["name", "-version"]},
        ),
        migrations.AddConstraint(
            model_name="huntpreset",
            constraint=models.UniqueConstraint(
                fields=("key", "version"), name="huntpreset_unique_version"
            ),
        ),
        migrations.AddField(
            model_name="huntprofileversion",
            name="applied_preset_key",
            field=models.SlugField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="huntprofileversion",
            name="applied_preset_version",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(seed_presets, remove_presets),
    ]
