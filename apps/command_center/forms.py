from django import forms

from apps.hunting.models import HuntProfileStatus
from apps.integrations.models import (
    AIEndpoint,
    AIProvider,
    CredentialReference,
    PrivacyClass,
    ProviderType,
)
from apps.opportunities.models import OpportunityStatus


class HuntProfileForm(forms.Form):
    name = forms.CharField(max_length=255)
    description = forms.CharField(widget=forms.Textarea, required=False)
    require_domain = forms.BooleanField(required=False, initial=True)
    minimum_score = forms.IntegerField(min_value=0, initial=10)
    geographies = forms.CharField(
        required=False,
        help_text="Comma-separated cities, regions, or countries (required for OpenStreetMap).",
    )
    industries = forms.CharField(
        required=False,
        help_text="Comma-separated niche/category keywords, for example dentist, accountant.",
    )
    keyword = forms.CharField(
        required=False, help_text="Optional search phrase, used by sources such as Google Places."
    )
    included_type = forms.SlugField(
        required=False, help_text="Optional Google Places Table A type, for example dentist."
    )
    center_latitude = forms.DecimalField(
        min_value=-90, max_value=90, required=False, decimal_places=6
    )
    center_longitude = forms.DecimalField(
        min_value=-180, max_value=180, required=False, decimal_places=6
    )
    radius_meters = forms.IntegerField(min_value=1, max_value=50000, required=False)
    use_openstreetmap = forms.BooleanField(
        required=False, initial=True, label="OpenStreetMap businesses"
    )
    openstreetmap_max_records = forms.IntegerField(
        min_value=1, max_value=100, initial=25, required=False
    )
    openstreetmap_budget_cents = forms.IntegerField(min_value=0, required=False)
    use_apollo = forms.BooleanField(required=False, label="Apollo Organization Search")
    apollo_max_records = forms.IntegerField(min_value=1, max_value=100, initial=10, required=False)
    apollo_budget_cents = forms.IntegerField(min_value=0, required=False)
    use_google_places = forms.BooleanField(required=False, label="Google Places")
    google_places_max_records = forms.IntegerField(
        min_value=1, max_value=60, initial=20, required=False
    )
    google_places_budget_cents = forms.IntegerField(min_value=0, required=False)
    manual_only = forms.BooleanField(required=False, label="Manual/CSV only (no automatic source)")
    reliability_weight = forms.IntegerField(min_value=0, max_value=100, initial=50, required=False)
    timeout_seconds = forms.IntegerField(min_value=5, max_value=300, initial=30, required=False)
    max_retries = forms.IntegerField(min_value=0, max_value=10, initial=2, required=False)
    activate_now = forms.BooleanField(required=False, initial=True)

    def clean(self):
        cleaned = super().clean()
        selected = any(
            cleaned.get(key) for key in ("use_openstreetmap", "use_apollo", "use_google_places")
        )
        if cleaned.get("manual_only") and selected:
            self.add_error("manual_only", "Manual-only profiles cannot enable automatic sources.")
        elif not cleaned.get("manual_only") and not selected:
            raise forms.ValidationError("Select at least one source or choose manual/CSV only.")
        if cleaned.get("use_openstreetmap") and not cleaned.get("geographies"):
            self.add_error("geographies", "Add at least one geography for OpenStreetMap.")
        coordinates = (cleaned.get("center_latitude"), cleaned.get("center_longitude"))
        if any(value is not None for value in coordinates) and not all(
            value is not None for value in coordinates
        ):
            self.add_error("center_latitude", "Provide both latitude and longitude.")
        if cleaned.get("radius_meters") and not all(value is not None for value in coordinates):
            self.add_error("radius_meters", "A radius requires center coordinates.")
        for key in ("openstreetmap", "apollo", "google_places"):
            if cleaned.get(f"use_{key}") and not cleaned.get(f"{key}_max_records"):
                self.add_error(f"{key}_max_records", "Set a record limit for this source.")
        return cleaned

    def source_policies(self):
        policies = []
        for key in ("openstreetmap", "apollo", "google_places"):
            if self.cleaned_data.get(f"use_{key}"):
                policy = {
                    "source_key": key,
                    "max_records": self.cleaned_data[f"{key}_max_records"],
                    "reliability_weight": self.cleaned_data.get("reliability_weight") or 50,
                    "timeout_seconds": self.cleaned_data.get("timeout_seconds") or 30,
                    "max_retries": 2
                    if self.cleaned_data.get("max_retries") is None
                    else self.cleaned_data["max_retries"],
                    "priority": len(policies) + 1,
                }
                budget = self.cleaned_data.get(f"{key}_budget_cents")
                if budget is not None:
                    policy["budget_cents"] = budget
                policies.append(policy)
        if self.cleaned_data.get("manual_only"):
            policies.append({"source_key": "manual", "is_enabled": False})
        return policies


class ProfileActionForm(forms.Form):
    action = forms.ChoiceField(
        choices=[
            (HuntProfileStatus.ACTIVE, "Activate"),
            (HuntProfileStatus.PAUSED, "Pause"),
            (HuntProfileStatus.ARCHIVED, "Archive"),
        ]
    )


class OpportunityStatusForm(forms.Form):
    status = forms.ChoiceField(choices=OpportunityStatus.choices)


class AIProviderForm(forms.Form):
    name = forms.CharField(max_length=255)
    provider_key = forms.SlugField(max_length=100)
    provider_type = forms.ChoiceField(choices=ProviderType.choices)


class CredentialForm(forms.Form):
    name = forms.CharField(max_length=255)
    secret = forms.CharField(widget=forms.PasswordInput(render_value=False))


class ApolloConfigurationForm(forms.Form):
    name = forms.CharField(max_length=255, initial="Apollo Organization Search")
    api_key = forms.CharField(widget=forms.PasswordInput(render_value=False))
    timeout_seconds = forms.IntegerField(min_value=1, max_value=120, initial=30)
    estimated_cost_per_page_cents = forms.IntegerField(
        min_value=0,
        initial=0,
        help_text="Optional estimate for hunt-budget enforcement; check your Apollo plan.",
    )
    enabled = forms.BooleanField(required=False, initial=True)


class GooglePlacesConfigurationForm(forms.Form):
    api_key = forms.CharField(widget=forms.PasswordInput(render_value=False))
    timeout_seconds = forms.IntegerField(min_value=1, max_value=120, initial=30)
    estimated_cost_per_page_cents = forms.IntegerField(min_value=0, initial=4)
    storage_permitted = forms.BooleanField(
        label="My Google Maps agreement permits storing returned Places content",
        help_text="Required: standard terms generally permit indefinite storage of Place IDs only.",
    )
    enabled = forms.BooleanField(required=False, initial=True)


class AIEndpointForm(forms.Form):
    provider = forms.ModelChoiceField(
        queryset=AIProvider.objects.none(), empty_label="Select a provider"
    )
    name = forms.CharField(max_length=255)
    base_url = forms.URLField(required=False, assume_scheme="http")
    credential = forms.ModelChoiceField(
        queryset=CredentialReference.objects.none(), required=False, empty_label="No credential"
    )
    timeout_seconds = forms.IntegerField(min_value=1, max_value=300, initial=30)
    privacy_class = forms.ChoiceField(choices=PrivacyClass.choices)

    def __init__(self, *args, workspace=None, **kwargs):
        super().__init__(*args, **kwargs)
        if workspace is not None:
            provider_field = self.fields["provider"]
            credential_field = self.fields["credential"]
            assert isinstance(provider_field, forms.ModelChoiceField)
            assert isinstance(credential_field, forms.ModelChoiceField)
            provider_field.queryset = AIProvider.objects.filter(workspace=workspace)
            credential_field.queryset = CredentialReference.objects.filter(workspace=workspace)


class AIModelForm(forms.Form):
    endpoint = forms.ModelChoiceField(
        queryset=AIEndpoint.objects.none(), empty_label="Select an endpoint"
    )
    model_name = forms.CharField(max_length=255)
    display_name = forms.CharField(max_length=255)
    context_limit = forms.IntegerField(min_value=1, initial=8192)
    input_cost_per_million = forms.DecimalField(min_value=0, initial=0)
    output_cost_per_million = forms.DecimalField(min_value=0, initial=0)

    def __init__(self, *args, workspace=None, **kwargs):
        super().__init__(*args, **kwargs)
        if workspace is not None:
            endpoint_field = self.fields["endpoint"]
            assert isinstance(endpoint_field, forms.ModelChoiceField)
            endpoint_field.queryset = AIEndpoint.objects.filter(workspace=workspace).select_related(
                "provider"
            )
