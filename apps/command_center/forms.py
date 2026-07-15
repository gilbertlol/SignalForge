from django import forms

from apps.hunting.models import HuntProfileStatus
from apps.integrations.models import PrivacyClass, ProviderType
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
    use_openstreetmap = forms.BooleanField(required=False, initial=True, label="OpenStreetMap businesses")
    openstreetmap_max_records = forms.IntegerField(min_value=1, max_value=100, initial=25, required=False)
    openstreetmap_budget_cents = forms.IntegerField(min_value=0, required=False)
    use_apollo = forms.BooleanField(required=False, label="Apollo Organization Search")
    apollo_max_records = forms.IntegerField(min_value=1, max_value=100, initial=10, required=False)
    apollo_budget_cents = forms.IntegerField(min_value=0, required=False)
    manual_only = forms.BooleanField(required=False, label="Manual/CSV only (no automatic source)")
    reliability_weight = forms.IntegerField(min_value=0, max_value=100, initial=50, required=False)
    timeout_seconds = forms.IntegerField(min_value=5, max_value=300, initial=30, required=False)
    max_retries = forms.IntegerField(min_value=0, max_value=10, initial=2, required=False)
    activate_now = forms.BooleanField(required=False, initial=True)

    def clean(self):
        cleaned = super().clean()
        selected = any(cleaned.get(key) for key in ("use_openstreetmap", "use_apollo"))
        if cleaned.get("manual_only") and selected:
            self.add_error("manual_only", "Manual-only profiles cannot enable automatic sources.")
        elif not cleaned.get("manual_only") and not selected:
            raise forms.ValidationError("Select at least one source or choose manual/CSV only.")
        if cleaned.get("use_openstreetmap") and not cleaned.get("geographies"):
            self.add_error("geographies", "Add at least one geography for OpenStreetMap.")
        for key in ("openstreetmap", "apollo"):
            if cleaned.get(f"use_{key}") and not cleaned.get(f"{key}_max_records"):
                self.add_error(f"{key}_max_records", "Set a record limit for this source.")
        return cleaned

    def source_policies(self):
        policies = []
        for key in ("openstreetmap", "apollo"):
            if self.cleaned_data.get(f"use_{key}"):
                policy = {
                    "source_key": key,
                    "max_records": self.cleaned_data[f"{key}_max_records"],
                    "reliability_weight": self.cleaned_data.get("reliability_weight") or 50,
                    "timeout_seconds": self.cleaned_data.get("timeout_seconds") or 30,
                    "max_retries": 2 if self.cleaned_data.get("max_retries") is None else self.cleaned_data["max_retries"],
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


class AIEndpointForm(forms.Form):
    provider = forms.UUIDField()
    name = forms.CharField(max_length=255)
    base_url = forms.URLField(required=False, assume_scheme="http")
    credential = forms.UUIDField(required=False)
    timeout_seconds = forms.IntegerField(min_value=1, max_value=300, initial=30)
    privacy_class = forms.ChoiceField(choices=PrivacyClass.choices)


class AIModelForm(forms.Form):
    endpoint = forms.UUIDField()
    model_name = forms.CharField(max_length=255)
    display_name = forms.CharField(max_length=255)
    context_limit = forms.IntegerField(min_value=1, initial=8192)
    input_cost_per_million = forms.DecimalField(min_value=0, initial=0)
    output_cost_per_million = forms.DecimalField(min_value=0, initial=0)
