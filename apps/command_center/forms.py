from django import forms

from apps.hunting.models import HuntProfileStatus
from apps.integrations.models import PrivacyClass, ProviderType
from apps.opportunities.models import OpportunityStatus


class HuntProfileForm(forms.Form):
    name = forms.CharField(max_length=255)
    description = forms.CharField(widget=forms.Textarea, required=False)
    require_domain = forms.BooleanField(required=False, initial=True)
    minimum_score = forms.IntegerField(min_value=0, initial=10)
    maximum_records = forms.IntegerField(min_value=1, max_value=1000, initial=25)
    lead_source = forms.ChoiceField(
        choices=[("demo", "Demo data"), ("apollo", "Apollo Organization Search")],
        required=False,
        initial="demo",
    )
    activate_now = forms.BooleanField(required=False, initial=True)


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
