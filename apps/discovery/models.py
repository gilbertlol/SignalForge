from django.conf import settings
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


class ProviderResultStatus(models.TextChoices):
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    PARTIAL = "partial", "Partial"


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
    failure_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["discovery_run", "status"])]

    def __str__(self) -> str:
        return f"{self.source_key}:{self.external_id or self.id}"


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
    status = models.CharField(max_length=10, choices=ProviderResultStatus.choices)
    records_returned = models.IntegerField(default=0)
    cost_cents = models.IntegerField(default=0)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

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
