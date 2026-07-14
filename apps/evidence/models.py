import datetime

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseModel, Workspace
from apps.opportunities.models import Opportunity
from apps.organizations.models import Organization

ALLOWED_SUBJECT_MODELS = (Organization, Opportunity)


class SourceType(models.TextChoices):
    WEBSITE = "website", "Website"
    JOB_POSTING = "job_posting", "Job posting"
    NEWS = "news", "News"
    SOCIAL = "social", "Social"
    REVIEW = "review", "Review"
    MANUAL = "manual", "Manual"
    OTHER = "other", "Other"


class Reliability(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


class VerificationStatus(models.TextChoices):
    UNVERIFIED = "unverified", "Unverified"
    VERIFIED = "verified", "Verified"
    DISPUTED = "disputed", "Disputed"
    RETRACTED = "retracted", "Retracted"


class Evidence(BaseModel):
    """A single piece of provenance backing a claim about an Organization or Opportunity.

    `workspace` is denormalized (also reachable via `subject`) so evidence
    can be filtered/isolated directly without joining through the generic
    relation on every query.

    Freshness is deliberately *not* a stored field: persisting a static
    "how fresh is this" value would go stale the moment time passes. See
    `age_days`, which the scoring engine reads at evaluation time instead.
    """

    workspace = models.ForeignKey(Workspace, on_delete=models.PROTECT, related_name="+")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    subject = GenericForeignKey("content_type", "object_id")

    source_url = models.URLField(blank=True)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    observed_date = models.DateField()
    excerpt = models.TextField()
    reliability = models.CharField(max_length=10, choices=Reliability.choices)
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
    )
    is_inferred = models.BooleanField(
        default=False,
        help_text="False = directly observed claim, True = inferred/derived.",
    )

    class Meta:
        ordering = ["-observed_date"]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["workspace"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_source_type_display()} evidence for {self.subject}"

    @property
    def age_days(self) -> int:
        return (datetime.date.today() - self.observed_date).days

    def clean(self) -> None:
        super().clean()
        if self.content_type_id and self.content_type.model_class() not in ALLOWED_SUBJECT_MODELS:
            raise ValidationError(
                {"content_type": "Evidence can only attach to an Organization or Opportunity."}
            )
        if self.subject is not None and self.subject.workspace_id != self.workspace_id:
            raise ValidationError({"workspace": "Evidence workspace must match its subject's."})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
