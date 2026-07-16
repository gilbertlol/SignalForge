from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import WorkspaceScopedModel


class ProviderType(models.TextChoices):
    LOCAL_OPENAI = "local_openai", "Local OpenAI compatible"
    CLOUD_OPENAI = "cloud_openai", "Cloud OpenAI compatible"
    NATIVE = "native", "Native provider"


class PrivacyClass(models.TextChoices):
    LOCAL_ONLY = "local_only", "Local only"
    PRIVATE_CLOUD = "private_cloud", "Private cloud allowed"
    PUBLIC_CLOUD = "public_cloud", "Public cloud allowed"


class AIProvider(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    provider_key = models.SlugField(max_length=100)
    provider_type = models.CharField(max_length=30, choices=ProviderType.choices)
    enabled = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "provider_key"], name="uniq_ai_provider_workspace_key"
            )
        ]


class CredentialReference(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    encrypted_value = models.TextField()
    key_version = models.PositiveSmallIntegerField(default=1)
    last_rotated_at = models.DateTimeField(auto_now_add=True)

    def set_secret(self, value: str) -> None:
        from .crypto import encrypt_secret

        self.encrypted_value = encrypt_secret(value)

    def get_secret(self) -> str:
        from .crypto import decrypt_secret

        return decrypt_secret(self.encrypted_value)


class LeadSourceConfiguration(WorkspaceScopedModel):
    source_key = models.SlugField(max_length=100)
    name = models.CharField(max_length=255)
    base_url = models.URLField(default="https://api.apollo.io/api/v1/mixed_companies/search")
    credential = models.ForeignKey(
        CredentialReference,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="lead_source_configurations",
    )
    timeout_seconds = models.PositiveIntegerField(default=30)
    estimated_cost_per_page_cents = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "source_key"], name="uniq_lead_source_workspace_key"
            )
        ]


class LeadSourceHealthStatus(models.TextChoices):
    READY = "ready", "Ready"
    AUTH_FAILED = "auth_failed", "Authentication failed"
    RATE_LIMITED = "rate_limited", "Rate limited"
    QUOTA_EXHAUSTED = "quota_exhausted", "Quota exhausted"
    UNAVAILABLE = "unavailable", "Unavailable"


class LeadSourceHealthCheck(WorkspaceScopedModel):
    configuration = models.ForeignKey(
        LeadSourceConfiguration, on_delete=models.CASCADE, related_name="health_checks"
    )
    status = models.CharField(max_length=30, choices=LeadSourceHealthStatus.choices)
    was_successful = models.BooleanField(default=False)
    latency_ms = models.PositiveIntegerField(default=0)
    sanitized_error = models.CharField(max_length=255, blank=True)


class AIEndpoint(WorkspaceScopedModel):
    provider = models.ForeignKey(AIProvider, on_delete=models.CASCADE, related_name="endpoints")
    name = models.CharField(max_length=255)
    base_url = models.URLField(blank=True)
    credential = models.ForeignKey(
        CredentialReference, null=True, blank=True, on_delete=models.PROTECT
    )
    timeout_seconds = models.PositiveIntegerField(default=30)
    requests_per_minute = models.PositiveIntegerField(null=True, blank=True)
    privacy_class = models.CharField(
        max_length=30, choices=PrivacyClass.choices, default=PrivacyClass.PUBLIC_CLOUD
    )
    enabled = models.BooleanField(default=True)


class ModelCapability(WorkspaceScopedModel):
    key = models.SlugField(max_length=50)
    name = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "key"], name="uniq_model_capability_workspace_key"
            )
        ]


class ModelDefinition(WorkspaceScopedModel):
    endpoint = models.ForeignKey(AIEndpoint, on_delete=models.CASCADE, related_name="models")
    model_name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    context_limit = models.PositiveIntegerField(default=8192)
    input_cost_per_million = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    output_cost_per_million = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    capabilities = models.ManyToManyField(ModelCapability, blank=True, related_name="models")
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["endpoint", "model_name"], name="uniq_endpoint_model_name"
            )
        ]


class FallbackPolicy(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    strategy = models.CharField(max_length=40, default="ordered")
    max_attempts = models.PositiveSmallIntegerField(default=3)


class ModelRoute(WorkspaceScopedModel):
    task_type = models.SlugField(max_length=50)
    name = models.CharField(max_length=255)
    model_definitions: models.ManyToManyField[ModelDefinition, ModelDefinition] = (
        models.ManyToManyField(ModelDefinition, through="ModelRouteEntry")
    )
    fallback_policy = models.ForeignKey(
        FallbackPolicy, null=True, blank=True, on_delete=models.SET_NULL
    )
    required_privacy_class = models.CharField(
        max_length=30, choices=PrivacyClass.choices, default=PrivacyClass.PUBLIC_CLOUD
    )
    is_default = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)


class ModelRouteEntry(models.Model):
    route = models.ForeignKey(ModelRoute, on_delete=models.CASCADE, related_name="entries")
    model = models.ForeignKey(ModelDefinition, on_delete=models.CASCADE)
    position = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["route", "position"], name="uniq_route_position"),
            models.UniqueConstraint(fields=["route", "model"], name="uniq_route_model"),
        ]

    def __str__(self) -> str:
        return f"{self.route.name}: {self.position}"


class UsagePolicy(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE
    )
    provider = models.ForeignKey(AIProvider, null=True, blank=True, on_delete=models.CASCADE)
    daily_budget_cents = models.PositiveIntegerField(null=True, blank=True)
    monthly_budget_cents = models.PositiveIntegerField(null=True, blank=True)
    max_concurrency = models.PositiveSmallIntegerField(default=1)
    enabled = models.BooleanField(default=True)


class PromptTemplate(WorkspaceScopedModel):
    key = models.SlugField(max_length=100)
    name = models.CharField(max_length=255)
    task_type = models.SlugField(max_length=50)
    current_version = models.ForeignKey(
        "PromptVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "key"], name="uniq_prompt_template_workspace_key"
            )
        ]


class PromptVersion(WorkspaceScopedModel):
    template = models.ForeignKey(PromptTemplate, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    system_prompt = models.TextField(blank=True)
    user_prompt_template = models.TextField()
    output_schema = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["template", "version"], name="uniq_prompt_template_version"
            )
        ]


class InvocationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


class ModelInvocation(WorkspaceScopedModel):
    route = models.ForeignKey(ModelRoute, null=True, on_delete=models.SET_NULL)
    model = models.ForeignKey(ModelDefinition, null=True, on_delete=models.SET_NULL)
    prompt_version = models.ForeignKey(
        PromptVersion, null=True, blank=True, on_delete=models.SET_NULL
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    task_type = models.SlugField(max_length=50)
    status = models.CharField(
        max_length=20, choices=InvocationStatus.choices, default=InvocationStatus.PENDING
    )
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    estimated_cost_cents = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    retry_count = models.PositiveSmallIntegerField(default=0)
    output_schema_valid = models.BooleanField(null=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    related_type = models.CharField(max_length=100, blank=True)
    related_id = models.CharField(max_length=255, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)


class ProviderHealthCheck(WorkspaceScopedModel):
    provider = models.ForeignKey(AIProvider, on_delete=models.CASCADE, related_name="health_checks")
    endpoint = models.ForeignKey(AIEndpoint, null=True, on_delete=models.SET_NULL)
    was_successful = models.BooleanField()
    latency_ms = models.PositiveIntegerField(default=0)
    capabilities = models.JSONField(default=list)
    sanitized_error = models.CharField(max_length=255, blank=True)


class GroundedSearchTrace(WorkspaceScopedModel):
    invocation = models.OneToOneField(
        ModelInvocation, on_delete=models.CASCADE, related_name="grounded_search_trace"
    )
    provider_key = models.SlugField(max_length=100)
    model_identifier = models.CharField(max_length=255)
    query = models.TextField()
    response_text = models.TextField()
    citations = models.JSONField(default=list)
    search_queries = models.JSONField(default=list)
    raw_metadata = models.JSONField(default=dict)
    search_cost_cents = models.DecimalField(max_digits=12, decimal_places=4, default=0)
