from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseModel, WorkspaceScopedModel
from apps.hunting.models import HuntProfileVersion
from apps.organizations.models import Organization


class DiscoveryRunStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    PARTIAL = "partial", "Partial"
    CANCELED = "canceled", "Canceled"


class DiscoveryRunTrigger(models.TextChoices):
    MANUAL = "manual", "Manual"
    SCHEDULED = "scheduled", "Scheduled"


class SourceRecordStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    NORMALIZED = "normalized", "Normalized"
    DUPLICATE = "duplicate", "Duplicate"
    SUPPRESSED = "suppressed", "Suppressed"
    QUALIFIED = "qualified", "Qualified"
    REJECTED = "rejected", "Rejected"
    FAILED = "failed", "Failed"


class MatchMethod(models.TextChoices):
    CREATED = "created", "New organization"
    PROVIDER_ID = "provider_id", "Provider identifier"
    DOMAIN = "domain", "Normalized domain"
    EXACT_NAME = "exact_name", "Exact normalized name"


class ProviderResultStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    RETRYING = "retrying", "Retrying"
    SUCCEEDED = "succeeded", "Succeeded"
    EMPTY = "empty", "Empty"
    FAILED = "failed", "Failed"
    PARTIAL = "partial", "Partial"
    TIMED_OUT = "timed_out", "Timed out"
    RATE_LIMITED = "rate_limited", "Rate limited"
    CANCELED = "canceled", "Canceled"
    BUDGET_BLOCKED = "budget_blocked", "Budget blocked"


class EnrichmentRunStatus(models.TextChoices):
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


class DiscoveryRun(WorkspaceScopedModel):
    """One execution of the discover -> ... -> score pipeline for a HuntProfileVersion.

    Binds to a specific `HuntProfileVersion` (not just the profile) so a
    run's criteria stay reproducible even if the profile gets a new
    version later — the same reproducibility promise GOR-242 established.
    """

    hunt_profile_version = models.ForeignKey(
        HuntProfileVersion, on_delete=models.PROTECT, related_name="discovery_runs"
    )
    status = models.CharField(
        max_length=10, choices=DiscoveryRunStatus.choices, default=DiscoveryRunStatus.PENDING
    )
    trigger = models.CharField(max_length=10, choices=DiscoveryRunTrigger.choices)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    checkpoint = models.JSONField(default=dict, blank=True)
    error_summary = models.TextField(blank=True)
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="initiated_discovery_runs",
    )

    records_discovered = models.IntegerField(default=0)
    records_deduplicated = models.IntegerField(default=0)
    records_enriched = models.IntegerField(default=0)
    records_qualified = models.IntegerField(default=0)
    records_failed = models.IntegerField(default=0)
    cost_cents = models.IntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"DiscoveryRun({self.hunt_profile_version}, {self.status})"


class SourceRecord(BaseModel):
    """One candidate found by a provider (or entered manually / via CSV) within a run.

    `raw_payload` preserves exactly what the provider returned;
    `normalized_data` is the cleaned/mapped result of the normalize phase.
    Keeping them separate (rather than normalizing in place) means the
    original provider response is never lost. `status` is also the
    resumability mechanism for the pipeline: each phase only processes
    records still at that phase's entry status.
    """

    discovery_run = models.ForeignKey(
        DiscoveryRun, on_delete=models.CASCADE, related_name="source_records"
    )
    provider_result = models.ForeignKey(
        "ProviderResult", null=True, blank=True, on_delete=models.CASCADE, related_name="records"
    )
    source_key = models.CharField(max_length=100)
    external_id = models.CharField(max_length=255, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    normalized_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=10, choices=SourceRecordStatus.choices, default=SourceRecordStatus.PENDING
    )
    organization = models.ForeignKey(
        Organization, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    match_method = models.CharField(max_length=20, choices=MatchMethod.choices, blank=True)
    match_confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    match_explanation = models.TextField(blank=True)
    failure_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["discovery_run", "status"])]
        constraints = [
            models.UniqueConstraint(
                fields=["discovery_run", "source_key", "external_id"],
                condition=~models.Q(external_id=""),
                name="source_record_unique_external_id_per_run_source",
            )
        ]

    def __str__(self) -> str:
        return f"{self.source_key}:{self.external_id or self.id}"

    def save(self, *args, **kwargs):
        immutable_fields = (
            "discovery_run_id",
            "provider_result_id",
            "source_key",
            "external_id",
            "raw_payload",
        )
        if not self._state.adding:
            update_fields = kwargs.get("update_fields")
            checked_fields = immutable_fields
            if update_fields is not None:
                checked_fields = tuple(
                    field
                    for field in immutable_fields
                    if field.removesuffix("_id") in update_fields
                )
            if checked_fields:
                original = type(self).all_objects.get(pk=self.pk)
                if any(
                    getattr(original, field) != getattr(self, field) for field in checked_fields
                ):
                    raise ValidationError("Raw source identity and payload are immutable.")
        if self.organization_id:
            if self.organization.workspace_id != self.discovery_run.workspace_id:
                raise ValidationError("Source record and organization must share a workspace.")
        return super().save(*args, **kwargs)


class EnrichmentRun(BaseModel):
    """One enrichment-adapter attempt against a SourceRecord. Best-effort:
    a failure here doesn't fail the SourceRecord (see services.py)."""

    source_record = models.ForeignKey(
        SourceRecord, on_delete=models.CASCADE, related_name="enrichment_runs"
    )
    provider_key = models.CharField(max_length=100)
    status = models.CharField(max_length=10, choices=EnrichmentRunStatus.choices)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"{self.provider_key} enrichment for {self.source_record_id}"


class ProviderResult(BaseModel):
    """One provider's outcome within a run — what makes partial provider
    failure isolated and measurable rather than corrupting the whole run."""

    discovery_run = models.ForeignKey(
        DiscoveryRun, on_delete=models.CASCADE, related_name="provider_results"
    )
    provider_key = models.CharField(max_length=100)
    status = models.CharField(
        max_length=20, choices=ProviderResultStatus.choices, default=ProviderResultStatus.QUEUED
    )
    query_snapshot = models.JSONField(default=dict, blank=True)
    policy_snapshot = models.JSONField(default=dict, blank=True)
    max_records = models.IntegerField(null=True, blank=True)
    budget_cents = models.IntegerField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    celery_task_id = models.CharField(max_length=255, blank=True)
    records_returned = models.IntegerField(default=0)
    pages_requested = models.PositiveIntegerField(default=0)
    pages_returned = models.PositiveIntegerField(default=0)
    cost_cents = models.IntegerField(default=0)
    reported_cost_cents = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    failure_count = models.PositiveIntegerField(default=0)
    rate_limit_count = models.PositiveIntegerField(default=0)
    timeout_count = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["discovery_run", "provider_key"],
                name="provider_result_unique_source_per_run",
            )
        ]

    def __str__(self) -> str:
        return f"{self.provider_key}: {self.status}"


class SuppressionEntry(WorkspaceScopedModel):
    """A domain blocklist entry. Checked during dedupe; deactivate (rather
    than delete) to explicitly allow rediscovery again.
    """

    domain = models.CharField(max_length=255)
    reason = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "domain"], name="suppressionentry_unique_domain_per_workspace"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.domain} ({'active' if self.is_active else 'inactive'})"
