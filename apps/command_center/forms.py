from urllib.parse import urlparse

from django import forms

from apps.evidence.models import Reliability
from apps.hunting.models import HuntProfileStatus
from apps.integrations.models import (
    AIEndpoint,
    AIProvider,
    CredentialReference,
    ModelDefinition,
    PrivacyClass,
    ProviderType,
)
from apps.opportunities.models import OpportunityStatus


class HuntProfileForm(forms.Form):
    preset = forms.UUIDField(required=False, widget=forms.HiddenInput)
    name = forms.CharField(max_length=255)
    description = forms.CharField(widget=forms.Textarea, required=False)
    require_domain = forms.BooleanField(required=False, initial=True)
    minimum_score = forms.IntegerField(min_value=0, initial=10)
    location_type = forms.ChoiceField(
        choices=[
            ("city", "City"),
            ("region", "Region / state / province"),
            ("country", "Country"),
            ("radius", "Radius around a point"),
        ],
        initial="city",
        label="Location type",
        required=False,
    )
    geographies = forms.CharField(
        required=False,
        label="Location",
        help_text="For example: Montreal, California, or France.",
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
    openstreetmap_reliability_weight = forms.IntegerField(
        min_value=0, max_value=100, required=False
    )
    use_searxng = forms.BooleanField(required=False, label="SearXNG web discovery")
    searxng_max_records = forms.IntegerField(min_value=1, max_value=50, initial=20, required=False)
    searxng_budget_cents = forms.IntegerField(min_value=0, required=False, initial=0)
    searxng_reliability_weight = forms.IntegerField(min_value=0, max_value=100, required=False)
    use_apollo = forms.BooleanField(required=False, label="Apollo Organization Search")
    apollo_max_records = forms.IntegerField(min_value=1, max_value=100, initial=10, required=False)
    apollo_budget_cents = forms.IntegerField(min_value=0, required=False)
    apollo_reliability_weight = forms.IntegerField(min_value=0, max_value=100, required=False)
    use_google_places = forms.BooleanField(required=False, label="Google Places")
    google_places_max_records = forms.IntegerField(
        min_value=1, max_value=60, initial=20, required=False
    )
    google_places_budget_cents = forms.IntegerField(min_value=0, required=False)
    google_places_reliability_weight = forms.IntegerField(
        min_value=0, max_value=100, required=False
    )
    manual_only = forms.BooleanField(required=False, label="Manual/CSV only (no automatic source)")
    reliability_weight = forms.IntegerField(min_value=0, max_value=100, initial=50, required=False)
    timeout_seconds = forms.IntegerField(min_value=5, max_value=300, initial=30, required=False)
    max_retries = forms.IntegerField(min_value=0, max_value=10, initial=2, required=False)
    activate_now = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, source_availability=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_availability = source_availability or {}
        for key in ("searxng", "apollo", "google_places"):
            availability = self.source_availability.get(key)
            if availability is None or availability.ready:
                continue
            self.initial[f"use_{key}"] = False
            for field_name in (
                f"use_{key}",
                f"{key}_max_records",
                f"{key}_budget_cents",
                f"{key}_reliability_weight",
            ):
                self.fields[field_name].disabled = True

    def clean(self):
        cleaned = super().clean()
        for key in ("searxng", "apollo", "google_places"):
            availability = self.source_availability.get(key)
            if cleaned.get(f"use_{key}") and availability and not availability.ready:
                self.add_error(f"use_{key}", availability.reason)
        selected = any(
            cleaned.get(key)
            for key in (
                "use_openstreetmap",
                "use_searxng",
                "use_apollo",
                "use_google_places",
            )
        )
        if cleaned.get("manual_only") and selected:
            self.add_error("manual_only", "Manual-only profiles cannot enable automatic sources.")
        elif not cleaned.get("manual_only") and not selected:
            raise forms.ValidationError("Select at least one source or choose manual/CSV only.")
        location_type = cleaned.get("location_type") or "city"
        if (
            cleaned.get("use_openstreetmap")
            and location_type != "radius"
            and not cleaned.get("geographies")
        ):
            self.add_error("geographies", "Add at least one geography for OpenStreetMap.")
        if location_type == "radius" and not (
            cleaned.get("use_openstreetmap") or cleaned.get("use_google_places")
        ):
            self.add_error(
                "use_openstreetmap",
                "Select OpenStreetMap or Google Places for a radius search.",
            )
        coordinates = (cleaned.get("center_latitude"), cleaned.get("center_longitude"))
        if any(value is not None for value in coordinates) and not all(
            value is not None for value in coordinates
        ):
            self.add_error("center_latitude", "Provide both latitude and longitude.")
        if location_type == "radius" and not all(value is not None for value in coordinates):
            self.add_error("center_latitude", "A radius search needs latitude and longitude.")
        if cleaned.get("radius_meters") and not all(value is not None for value in coordinates):
            self.add_error("radius_meters", "A radius requires center coordinates.")
        if location_type == "radius" and not cleaned.get("radius_meters"):
            self.add_error("radius_meters", "Set the search radius.")
        for key in ("openstreetmap", "searxng", "apollo", "google_places"):
            if cleaned.get(f"use_{key}") and not cleaned.get(f"{key}_max_records"):
                self.add_error(f"{key}_max_records", "Set a record limit for this source.")
        return cleaned

    def source_policies(self):
        policies = []
        for key in ("openstreetmap", "searxng", "apollo", "google_places"):
            if self.cleaned_data.get(f"use_{key}"):
                policy = {
                    "source_key": key,
                    "max_records": self.cleaned_data[f"{key}_max_records"],
                    "reliability_weight": self.cleaned_data.get(f"{key}_reliability_weight")
                    or self.cleaned_data.get("reliability_weight")
                    or 50,
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


class OrganizationCreateForm(forms.Form):
    name = forms.CharField(max_length=255)
    domain = forms.CharField(max_length=255, required=False)
    industry = forms.CharField(max_length=255, required=False)
    location = forms.CharField(max_length=255, required=False)
    employee_count = forms.IntegerField(min_value=0, required=False)
    website_url = forms.URLField(required=False, assume_scheme="https")
    phone = forms.CharField(max_length=100, required=False)
    notes = forms.CharField(widget=forms.Textarea, required=False)


class ManualClaimForm(forms.Form):
    field_name = forms.ChoiceField(
        choices=[
            ("name", "Name"),
            ("domain", "Domain"),
            ("industry", "Industry"),
            ("location", "Location"),
            ("employee_count", "Employee count"),
            ("website_url", "Website"),
            ("phone", "Phone"),
            ("notes", "Notes"),
        ]
    )
    value = forms.CharField(widget=forms.Textarea)
    reliability = forms.ChoiceField(choices=Reliability.choices, initial=Reliability.HIGH)
    note = forms.CharField(
        widget=forms.Textarea, help_text="Why this value is being added or corrected."
    )


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


class SearXNGConfigurationForm(forms.Form):
    base_url = forms.CharField(
        help_text="Base instance URL, for example http://searxng:8080.",
    )
    access_token = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Optional bearer token for a private instance.",
    )
    language = forms.CharField(max_length=20, initial="auto")
    timeout_seconds = forms.IntegerField(min_value=1, max_value=120, initial=20)
    enabled = forms.BooleanField(required=False, initial=True)

    def clean_base_url(self):
        value = self.cleaned_data["base_url"]
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise forms.ValidationError("Enter a complete HTTP or HTTPS instance URL.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise forms.ValidationError(
                "Use only the instance base URL; credentials, query strings and fragments "
                "are not allowed."
            )
        return value.rstrip("/")


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


class ResearchRouteForm(forms.Form):
    task_type = forms.ChoiceField(
        choices=[
            ("research_query_planning", "Research query planning"),
            ("organization_extraction", "Organization extraction"),
            ("evidence_classification", "Evidence classification"),
            ("hunt_fit_summary", "Hunt-fit summary"),
        ]
    )
    model = forms.ModelChoiceField(queryset=ModelDefinition.objects.none())
    required_privacy_class = forms.ChoiceField(
        choices=PrivacyClass.choices, initial=PrivacyClass.LOCAL_ONLY
    )

    def __init__(self, *args, workspace=None, **kwargs):
        super().__init__(*args, **kwargs)
        if workspace is not None:
            model_field = self.fields["model"]
            assert isinstance(model_field, forms.ModelChoiceField)
            model_field.queryset = ModelDefinition.objects.filter(
                workspace=workspace, enabled=True, endpoint__enabled=True
            ).select_related("endpoint__provider")
