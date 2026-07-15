from django.db import models

from apps.core.models import BaseModel, WorkspaceScopedModel


class HuntProfileStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    ARCHIVED = "archived", "Archived"


class CriterionOperator(models.TextChoices):
    AND = "AND", "And"
    OR = "OR", "Or"
    NOT = "NOT", "Not"


class CriterionCategory(models.TextChoices):
    INDUSTRY = "industry", "Industry"
    GEOGRAPHY = "geography", "Geography"
    COMPANY_SIZE = "company_size", "Company size"
    TECHNOLOGY = "technology", "Technology"
    HIRING_SIGNAL = "hiring_signal", "Hiring signal"
    GROWTH_SIGNAL = "growth_signal", "Growth signal"
    PAIN_INDICATOR = "pain_indicator", "Pain indicator"
    BUSINESS_MODEL = "business_model", "Business model"
    ESTIMATED_VALUE = "estimated_value", "Estimated value"
    DECISION_MAKER_ROLE = "decision_maker_role", "Decision-maker role"
    KEYWORD = "keyword", "Keyword"
    NEGATIVE_KEYWORD = "negative_keyword", "Negative keyword"
    CUSTOM_ATTRIBUTE = "custom_attribute", "Custom attribute"


class ScheduleFrequency(models.TextChoices):
    MANUAL = "manual", "Manual"
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"


class KeywordSet(WorkspaceScopedModel):
    """A reusable named keyword list (e.g. "CRM pain-point keywords").

    Workspace-scoped, not version-scoped: usable across many hunt profiles
    and versions, which is what makes hunt profiles "reusable" per the
    ticket title rather than each one redeclaring its own keyword lists.
    """

    name = models.CharField(max_length=255)
    keywords = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "name"], name="keywordset_unique_name_per_workspace"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class ValueSignal(WorkspaceScopedModel):
    """A reusable catalog entry for a deal-value heuristic (e.g. "uses paid ads")."""

    key = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    weight = models.IntegerField(default=1)

    class Meta:
        ordering = ["key"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "key"], name="valuesignal_unique_key_per_workspace"
            ),
        ]

    def __str__(self) -> str:
        return self.key


class CriterionGroup(BaseModel):
    """A node in the recursive AND/OR/NOT criteria tree.

    Built (and never edited) by `apps.hunting.services.create_version`.
    """

    operator = models.CharField(max_length=3, choices=CriterionOperator.choices)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    position = models.PositiveIntegerField(
        default=0, help_text="Order among sibling children; keeps clone/serialize deterministic."
    )

    class Meta:
        ordering = ["position"]

    def __str__(self) -> str:
        return self.operator


class HuntCriterion(BaseModel):
    """A leaf condition in the criteria tree.

    Semantics (the ticket names these concepts but doesn't fully specify
    their interaction, so this is a documented decision, not an accident):
    the tree's AND/OR/NOT determines the base match. Independently of
    that, any matched `is_hard_disqualifier` leaf excludes the candidate
    outright, and every `is_required` leaf must match regardless of which
    branch of the tree it sits in. `weight` sums across matched
    non-disqualifier leaves into a total compared against the version's
    `ResultThreshold.min_total_score`.

    Cross-workspace consistency for `keyword_set`/`value_signal` is not
    enforced at this layer (it would require walking group -> version ->
    profile -> workspace on every save); `services.create_version` is the
    only construction path and is trusted to pass same-workspace references.
    """

    group = models.ForeignKey(CriterionGroup, on_delete=models.CASCADE, related_name="criteria")
    category = models.CharField(max_length=30, choices=CriterionCategory.choices)
    field = models.CharField(max_length=255)
    op = models.CharField(max_length=10)
    value = models.JSONField(null=True, blank=True)
    weight = models.IntegerField(default=1)
    is_required = models.BooleanField(default=False)
    is_hard_disqualifier = models.BooleanField(default=False)
    keyword_set = models.ForeignKey(
        KeywordSet, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    value_signal = models.ForeignKey(
        ValueSignal, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    position = models.PositiveIntegerField(
        default=0, help_text="Order among sibling criteria; keeps clone/serialize deterministic."
    )

    class Meta:
        ordering = ["position"]

    def __str__(self) -> str:
        return f"{self.category}:{self.field} {self.op}"


class HuntProfile(WorkspaceScopedModel):
    """A reusable business-acquisition thesis: what to hunt for and how to judge candidates.

    Mutation happens only through `apps.hunting.services` — there is no
    "edit criteria in place" path. To change what a profile hunts for,
    `services.create_version()` builds an entirely new
    `HuntProfileVersion`; the old version is untouched, so a future
    DiscoveryRun (GOR-235) that recorded which version it used stays
    reproducible forever.
    """

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=10, choices=HuntProfileStatus.choices, default=HuntProfileStatus.DRAFT
    )
    current_version = models.ForeignKey(
        "HuntProfileVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class HuntProfileVersion(BaseModel):
    """One immutable snapshot of a HuntProfile's full criteria tree and config.

    Built in a single transaction by `services.create_version()`. Nothing
    under a version (its `CriterionGroup`/`HuntCriterion` tree,
    `SearchScope`, `SourcePolicy`, `ExclusionRule`, `ResultThreshold`) is
    ever updated afterward — there is simply no update path for any of
    them, by convention rather than a runtime guard (a version is a
    multi-row tree built incrementally, so a single-row `save()` guard
    like `ScoreSnapshot`'s would fight normal construction).
    """

    profile = models.ForeignKey(HuntProfile, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField()
    root_group = models.ForeignKey(CriterionGroup, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "version_number"],
                name="huntprofileversion_unique_per_profile",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.profile.name} v{self.version_number}"


class SearchScope(BaseModel):
    """Coarse pre-filter data for a future discovery provider query (GOR-235) —
    distinct from the fine-grained match tree used to judge individual candidates.
    """

    version = models.OneToOneField(
        HuntProfileVersion, on_delete=models.CASCADE, related_name="search_scope"
    )
    industries = models.JSONField(default=list, blank=True)
    geographies = models.JSONField(default=list, blank=True)
    company_size_min = models.IntegerField(null=True, blank=True)
    company_size_max = models.IntegerField(null=True, blank=True)

    def __str__(self) -> str:
        return f"scope for {self.version}"


class SourcePolicy(BaseModel):
    """Per-provider budget/config for a version.

    `source_key` is a free string, not a FK to a concrete adapter — no
    `LeadSourceAdapter` implementation exists yet to reference (GOR-235).
    """

    version = models.ForeignKey(
        HuntProfileVersion, on_delete=models.CASCADE, related_name="source_policies"
    )
    source_key = models.CharField(max_length=100)
    is_enabled = models.BooleanField(default=True)
    max_records = models.IntegerField(null=True, blank=True)
    budget_cents = models.IntegerField(null=True, blank=True)
    reliability_weight = models.PositiveSmallIntegerField(default=50)
    timeout_seconds = models.PositiveIntegerField(default=30)
    max_retries = models.PositiveSmallIntegerField(default=2)
    priority = models.PositiveSmallIntegerField(default=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["version", "source_key"], name="sourcepolicy_unique_per_version"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_key} ({self.version})"


class ExclusionRule(BaseModel):
    """A blocklist condition: any match excludes the candidate, independent of the criteria tree."""

    version = models.ForeignKey(
        HuntProfileVersion, on_delete=models.CASCADE, related_name="exclusion_rules"
    )
    field = models.CharField(max_length=255)
    op = models.CharField(max_length=10)
    value = models.JSONField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)

    def __str__(self) -> str:
        return f"exclude {self.field} {self.op}"


class SchedulePolicy(WorkspaceScopedModel):
    """Schedule configuration for a HuntProfile. Persists across versions —
    a profile keeps its cadence as its criteria evolve.

    Pure config: no Celery Beat wiring yet, since there's no discovery
    task to schedule until GOR-235 exists.
    """

    profile = models.OneToOneField(
        HuntProfile, on_delete=models.CASCADE, related_name="schedule_policy"
    )
    frequency = models.CharField(
        max_length=10, choices=ScheduleFrequency.choices, default=ScheduleFrequency.MANUAL
    )
    is_enabled = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.profile.name}: {self.frequency}"


class ResultThreshold(BaseModel):
    """Qualification thresholds for a version's dry-run/discovery results."""

    version = models.OneToOneField(
        HuntProfileVersion, on_delete=models.CASCADE, related_name="result_threshold"
    )
    min_total_score = models.IntegerField(default=0)
    min_evidence_confidence = models.IntegerField(null=True, blank=True)

    def __str__(self) -> str:
        return f"threshold for {self.version}"
