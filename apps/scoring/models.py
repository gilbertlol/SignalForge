from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models import TimeStampedModel, Workspace, WorkspaceScopedModel

from .exceptions import ImmutableRecordError


class ScoreFamily(models.TextChoices):
    PROSPECT_QUALITY = "prospect_quality", "Prospect quality"
    SCORE_CONFIDENCE = "score_confidence", "Score confidence"
    OPPORTUNITY_SCORE = "opportunity_score", "Opportunity score"


class ScoringRule(WorkspaceScopedModel):
    """A single configurable, deterministic scoring rule.

    `conditions` is a small declarative spec (see `apps.scoring.services._matches`),
    not a general rules DSL. Rules are soft-deletable (inherited from BaseModel via
    WorkspaceScopedModel) — soft-deleting a rule is how it's retired; `version` is
    bumped by the update service whenever a rule's points/conditions change, and is
    copied into every `ScoreSnapshot.components` entry it contributes to, so historical
    explanations remain accurate even after a rule is later edited.
    """

    family = models.CharField(max_length=20, choices=ScoreFamily.choices)
    key = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    points = models.IntegerField(default=0)
    is_hard_disqualifier = models.BooleanField(default=False)
    conditions = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["family", "key"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "family", "key"],
                name="scoringrule_unique_key_per_workspace_family",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.family}:{self.key}"


class ScoreThreshold(WorkspaceScopedModel):
    """A labeling band for a score family, e.g. 'qualified' at value >= 70."""

    family = models.CharField(max_length=20, choices=ScoreFamily.choices)
    label = models.CharField(max_length=100)
    min_value = models.IntegerField()

    class Meta:
        ordering = ["family", "-min_value"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "family", "label"],
                name="scorethreshold_unique_label_per_workspace_family",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.family}:{self.label}>={self.min_value}"


class ScoreSnapshot(TimeStampedModel):
    """An immutable record of one scoring evaluation.

    Deliberately NOT a `BaseModel`/`WorkspaceScopedModel` subclass: those bring in
    soft-delete's `delete()` -> `save()` path, which would fight the immutability
    guard below. Snapshots are append-only history; nothing about them is ever
    edited or soft-deleted.

    Reproducibility comes from `components`: each fired rule's id/key/version/points
    is copied in at evaluation time, so this row is self-contained and unaffected by
    later edits to the `ScoringRule`s it referenced.
    """

    workspace = models.ForeignKey(Workspace, on_delete=models.PROTECT, related_name="+")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    subject = GenericForeignKey("content_type", "object_id")

    family = models.CharField(max_length=20, choices=ScoreFamily.choices)
    value = models.IntegerField()
    is_hard_disqualified = models.BooleanField(default=False)
    label = models.CharField(max_length=100, blank=True)
    components = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["content_type", "object_id", "family"]),
            models.Index(fields=["workspace"]),
        ]

    def __str__(self) -> str:
        return f"{self.family}={self.value} for {self.subject}"

    def save(self, *args, **kwargs):
        if ScoreSnapshot.objects.filter(pk=self.pk).exists():
            raise ImmutableRecordError("Score snapshots cannot be modified after creation.")
        super().save(*args, **kwargs)
