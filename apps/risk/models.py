from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import WorkspaceScopedModel


class RiskCategoryKey(models.TextChoices):
    PAYMENT = "payment", "Payment"
    DELIVERY = "delivery", "Delivery"
    RELATIONSHIP = "relationship", "Relationship"
    LEGAL_COMPLIANCE = "legal_compliance", "Legal / compliance"
    PROFITABILITY = "profitability", "Profitability"
    STRATEGIC = "strategic", "Strategic"
    SECURITY_PRIVACY = "security_privacy", "Security / privacy"
    FOUNDER_DEPENDENCY = "founder_dependency", "Founder dependency"


class RiskProfile(WorkspaceScopedModel):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="risk_profiles"
    )
    opportunity = models.ForeignKey(
        "opportunities.Opportunity", null=True, blank=True, on_delete=models.CASCADE
    )
    contract = models.ForeignKey(
        "finance.Contract", null=True, blank=True, on_delete=models.CASCADE
    )
    active = models.BooleanField(default=True)
    acceptance_threshold = models.DecimalField(max_digits=6, decimal_places=2, default=70)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "opportunity", "contract"],
                name="uniq_risk_profile_scope",
                nulls_distinct=False,
            )
        ]

    def __str__(self):
        return f"Risk profile: {self.organization}"


class RiskCategory(WorkspaceScopedModel):
    key = models.CharField(max_length=30, choices=RiskCategoryKey.choices)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    weight = models.DecimalField(max_digits=6, decimal_places=4, default=1)
    stale_after_days = models.PositiveIntegerField(default=90)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "key"], name="uniq_risk_category")
        ]

    def __str__(self):
        return self.name


class RiskFactor(WorkspaceScopedModel):
    category = models.ForeignKey(RiskCategory, on_delete=models.CASCADE, related_name="factors")
    key = models.SlugField(max_length=100)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    rule = models.JSONField(default=dict)
    weight = models.DecimalField(max_digits=6, decimal_places=4, default=1)
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["category", "key"], name="uniq_risk_factor")]

    def __str__(self):
        return self.name


class ObservationSource(models.TextChoices):
    DETERMINISTIC = "deterministic", "Deterministic rule"
    HUMAN = "human", "Human observation"
    AI_SUGGESTION = "ai_suggestion", "AI suggestion"


class FactType(models.TextChoices):
    OBSERVED = "observed", "Observed fact"
    INFERENCE = "inference", "Inference"
    OVERRIDE = "override", "Human override"


class RiskObservation(WorkspaceScopedModel):
    profile = models.ForeignKey(RiskProfile, on_delete=models.CASCADE, related_name="observations")
    category = models.ForeignKey(RiskCategory, on_delete=models.PROTECT)
    factor = models.ForeignKey(RiskFactor, null=True, blank=True, on_delete=models.PROTECT)
    source = models.CharField(max_length=30, choices=ObservationSource.choices)
    fact_type = models.CharField(max_length=20, choices=FactType.choices)
    evidence = models.ForeignKey(
        "evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT
    )
    source_type = models.CharField(max_length=100, blank=True)
    source_id = models.CharField(max_length=255, blank=True)
    explanation = models.TextField()
    severity = models.DecimalField(max_digits=6, decimal_places=2)
    probability = models.DecimalField(max_digits=6, decimal_places=2)
    impact = models.DecimalField(max_digits=6, decimal_places=2)
    confidence = models.DecimalField(max_digits=5, decimal_places=4)
    observed_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    confirmed = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    def clean(self):
        super().clean()
        if self.source == ObservationSource.AI_SUGGESTION and not self.evidence_id:
            raise ValidationError({"evidence": "AI suggestions require evidence."})
        if not self.evidence_id and not (self.source_type and self.source_id):
            raise ValidationError("Observations require evidence or a traceable source record.")
        if self.evidence_id and self.evidence.workspace_id != self.workspace_id:
            raise ValidationError({"evidence": "Evidence must use this workspace."})
        for field in ["severity", "probability", "impact"]:
            value = getattr(self, field)
            if value < 0 or value > 100:
                raise ValidationError({field: "Use a value from 0 to 100."})
        if self.confidence < 0 or self.confidence > 1:
            raise ValidationError({"confidence": "Use a value from 0 to 1."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class RiskSnapshot(WorkspaceScopedModel):
    profile = models.ForeignKey(RiskProfile, on_delete=models.PROTECT, related_name="snapshots")
    category_scores = models.JSONField()
    components = models.JSONField()
    controls = models.JSONField(default=list)
    calculated_at = models.DateTimeField()
    calculation_version = models.CharField(max_length=50)
    triggered_by = models.CharField(max_length=100)

    class Meta:
        ordering = ["-calculated_at"]

    def save(self, *args, **kwargs):
        if self.pk and type(self).all_objects.filter(pk=self.pk).exists():
            raise ValidationError("Risk snapshots are immutable; calculate a new snapshot.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Risk snapshots cannot be deleted.")


class ControlType(models.TextChoices):
    DEPOSIT = "deposit", "Deposit"
    PREPAYMENT = "prepayment", "Prepayment"
    PAID_DISCOVERY = "paid_discovery", "Paid discovery"
    MILESTONE_BILLING = "milestone_billing", "Milestone billing"
    SCOPE_LIMIT = "scope_limit", "Scope limit"
    SENIOR_REVIEW = "senior_review", "Senior review"
    RESTRICTED_AUTOMATION = "restricted_automation", "Restricted automation"
    REJECTION = "rejection", "Reject client"


class RecommendationStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    IMPLEMENTED = "implemented", "Implemented"


class ControlRecommendation(WorkspaceScopedModel):
    profile = models.ForeignKey(
        RiskProfile, on_delete=models.CASCADE, related_name="recommendations"
    )
    snapshot = models.ForeignKey(
        RiskSnapshot, on_delete=models.PROTECT, related_name="recommendations"
    )
    category = models.ForeignKey(RiskCategory, on_delete=models.PROTECT)
    control_type = models.CharField(max_length=30, choices=ControlType.choices)
    rationale = models.TextField()
    threshold = models.DecimalField(max_digits=6, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=RecommendationStatus.choices, default="proposed"
    )
    requires_approval = models.BooleanField(default=False)


class Mitigation(WorkspaceScopedModel):
    profile = models.ForeignKey(RiskProfile, on_delete=models.CASCADE, related_name="mitigations")
    recommendation = models.ForeignKey(
        ControlRecommendation, null=True, blank=True, on_delete=models.SET_NULL
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class Override(WorkspaceScopedModel):
    profile = models.ForeignKey(RiskProfile, on_delete=models.CASCADE, related_name="overrides")
    category = models.ForeignKey(RiskCategory, on_delete=models.PROTECT)
    score = models.DecimalField(max_digits=6, decimal_places=2)
    reason = models.TextField()
    evidence = models.ForeignKey(
        "evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    effective_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.pk and type(self).all_objects.filter(pk=self.pk).exists():
            raise ValidationError("Overrides are append-only; create a new override.")
        return super().save(*args, **kwargs)


class Review(WorkspaceScopedModel):
    profile = models.ForeignKey(RiskProfile, on_delete=models.CASCADE, related_name="reviews")
    snapshot = models.ForeignKey(RiskSnapshot, on_delete=models.PROTECT)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decision = models.CharField(
        max_length=20,
        choices=[("accepted", "Accepted"), ("changes_requested", "Changes requested")],
    )
    notes = models.TextField(blank=True)
    reviewed_at = models.DateTimeField()


class AcceptancePolicy(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    category = models.ForeignKey(RiskCategory, null=True, blank=True, on_delete=models.CASCADE)
    threshold = models.DecimalField(max_digits=6, decimal_places=2)
    control_type = models.CharField(max_length=30, choices=ControlType.choices)
    requires_approval = models.BooleanField(default=True)
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return self.name
