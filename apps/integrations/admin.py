from django import forms
from django.contrib import admin

from .models import (
    AIEndpoint,
    AIProvider,
    CredentialReference,
    FallbackPolicy,
    LeadSourceConfiguration,
    ModelCapability,
    ModelDefinition,
    ModelInvocation,
    ModelRoute,
    ModelRouteEntry,
    PromptTemplate,
    PromptVersion,
    ProviderHealthCheck,
    UsagePolicy,
)


class CredentialAdminForm(forms.ModelForm):
    secret = forms.CharField(widget=forms.PasswordInput(render_value=False), required=False)

    class Meta:
        model = CredentialReference
        fields = ["workspace", "name", "secret"]

    def clean_secret(self):
        secret = self.cleaned_data["secret"]
        if not self.instance.pk and not secret:
            raise forms.ValidationError("A secret is required.")
        return secret

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data["secret"]:
            instance.set_secret(self.cleaned_data["secret"])
        if commit:
            instance.save()
        return instance


@admin.register(CredentialReference)
class CredentialReferenceAdmin(admin.ModelAdmin):
    form = CredentialAdminForm
    list_display = ["name", "workspace", "key_version", "last_rotated_at"]


for model in (
    AIProvider,
    AIEndpoint,
    ModelCapability,
    ModelDefinition,
    FallbackPolicy,
    ModelRoute,
    ModelRouteEntry,
    UsagePolicy,
    PromptTemplate,
    PromptVersion,
    ModelInvocation,
    ProviderHealthCheck,
    LeadSourceConfiguration,
):
    admin.site.register(model)
