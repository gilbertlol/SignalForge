from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import WorkspaceScopedModel


class OperatorType(models.TextChoices):
    HUMAN = "human", "Human"
    AI_AGENT = "ai_agent", "AI agent"
    CONTRACTOR = "contractor", "Contractor"
    SYSTEM = "system", "System service"


class Availability(models.TextChoices):
    AVAILABLE = "available", "Available"
    BUSY = "busy", "Busy"
    OFFLINE = "offline", "Offline"


class Operator(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    operator_type = models.CharField(max_length=30, choices=OperatorType.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="operators",
    )
    availability = models.CharField(
        max_length=20, choices=Availability.choices, default=Availability.AVAILABLE
    )
    capacity = models.PositiveSmallIntegerField(default=1)
    active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"],
                condition=models.Q(user__isnull=False),
                name="uniq_operator_workspace_user",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Team(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="uniq_task_team_name")
        ]


class TeamMembership(WorkspaceScopedModel):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    operator = models.ForeignKey(
        Operator, on_delete=models.CASCADE, related_name="team_memberships"
    )
    role = models.CharField(max_length=100, blank=True)
    assignment_weight = models.PositiveSmallIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "operator"], name="uniq_task_team_operator")
        ]


class AssignmentPool(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    operators = models.ManyToManyField(Operator, through="AssignmentPoolMember")
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="uniq_assignment_pool")
        ]


class AssignmentPoolMember(WorkspaceScopedModel):
    pool = models.ForeignKey(AssignmentPool, on_delete=models.CASCADE, related_name="memberships")
    operator = models.ForeignKey(
        Operator, on_delete=models.CASCADE, related_name="pool_memberships"
    )
    priority = models.PositiveSmallIntegerField(default=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["pool", "operator"], name="uniq_pool_operator")
        ]


class AgentProfile(WorkspaceScopedModel):
    operator = models.OneToOneField(
        Operator, on_delete=models.CASCADE, related_name="agent_profile"
    )
    name = models.CharField(max_length=255)
    purpose = models.TextField()
    enabled = models.BooleanField(default=True)


class AgentVersion(WorkspaceScopedModel):
    profile = models.ForeignKey(AgentProfile, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    instructions = models.TextField()
    model = models.ForeignKey(
        "integrations.ModelDefinition", null=True, blank=True, on_delete=models.PROTECT
    )
    active = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "version"], name="uniq_agent_version")
        ]


class ActionPolicy(models.TextChoices):
    DENY = "deny", "Denied"
    AUTONOMOUS = "autonomous", "Autonomous"
    APPROVAL_REQUIRED = "approval_required", "Approval required"
    HUMAN_ONLY = "human_only", "Human only"


class ToolPermission(WorkspaceScopedModel):
    agent_version = models.ForeignKey(
        AgentVersion, on_delete=models.CASCADE, related_name="tool_permissions"
    )
    tool_key = models.SlugField(max_length=100)
    policy = models.CharField(
        max_length=30, choices=ActionPolicy.choices, default=ActionPolicy.DENY
    )
    constraints = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["agent_version", "tool_key"], name="uniq_agent_tool_permission"
            )
        ]


class DataScope(WorkspaceScopedModel):
    agent_version = models.ForeignKey(
        AgentVersion, on_delete=models.CASCADE, related_name="data_scopes"
    )
    resource_type = models.SlugField(max_length=100)
    allowed_fields = models.JSONField(default=list)
    filters = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["agent_version", "resource_type"], name="uniq_agent_data_scope"
            )
        ]


class AssignmentStrategy(models.TextChoices):
    DIRECT = "direct", "Direct operator"
    TEAM = "team", "Team"
    POOL = "pool", "Assignment pool"
    FIRST_AVAILABLE = "first_available", "First available"
    HUMAN_AGENT_PAIR = "human_agent_pair", "Human-agent pair"


class WorkStatus(models.TextChoices):
    OPEN = "open", "Open"
    ASSIGNED = "assigned", "Assigned"
    IN_PROGRESS = "in_progress", "In progress"
    BLOCKED = "blocked", "Blocked"
    COMPLETED = "completed", "Completed"
    CANCELED = "canceled", "Canceled"


class WorkItem(WorkspaceScopedModel):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=WorkStatus.choices, default=WorkStatus.OPEN)
    priority = models.PositiveSmallIntegerField(default=3)
    assignment_strategy = models.CharField(
        max_length=30, choices=AssignmentStrategy.choices, default=AssignmentStrategy.DIRECT
    )
    assignee = models.ForeignKey(
        Operator, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_work"
    )
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL)
    pool = models.ForeignKey(AssignmentPool, null=True, blank=True, on_delete=models.SET_NULL)
    paired_human = models.ForeignKey(
        Operator, null=True, blank=True, on_delete=models.SET_NULL, related_name="paired_human_work"
    )
    paired_agent = models.ForeignKey(
        Operator, null=True, blank=True, on_delete=models.SET_NULL, related_name="paired_agent_work"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    context_type = models.SlugField(max_length=100, blank=True)
    context_id = models.CharField(max_length=255, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class BudgetPolicy(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    operator = models.ForeignKey(
        Operator, null=True, blank=True, on_delete=models.CASCADE, related_name="budget_policies"
    )
    agent_profile = models.ForeignKey(
        AgentProfile,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="budget_policies",
    )
    daily_cost_cents = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    monthly_cost_cents = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    max_execution_cost_cents = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    max_execution_tokens = models.PositiveIntegerField(null=True, blank=True)
    max_concurrency = models.PositiveSmallIntegerField(default=1)
    enabled = models.BooleanField(default=True)


class EscalationPolicy(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    action_key = models.SlugField(max_length=100)
    minimum_confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    approval_team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL)
    enabled = models.BooleanField(default=True)


class ExecutionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    WAITING_APPROVAL = "waiting_approval", "Waiting for approval"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELED = "canceled", "Canceled"
    DENIED = "denied", "Denied"


class AgentExecution(WorkspaceScopedModel):
    work_item = models.ForeignKey(
        WorkItem, null=True, blank=True, on_delete=models.SET_NULL, related_name="executions"
    )
    operator = models.ForeignKey(Operator, on_delete=models.PROTECT, related_name="executions")
    agent_version = models.ForeignKey(AgentVersion, on_delete=models.PROTECT)
    action_key = models.SlugField(max_length=100)
    status = models.CharField(
        max_length=30, choices=ExecutionStatus.choices, default=ExecutionStatus.PENDING
    )
    context_type = models.SlugField(max_length=100, blank=True)
    context_id = models.CharField(max_length=255, blank=True)
    context_snapshot = models.JSONField(default=dict, blank=True)
    model_invocation = models.ForeignKey(
        "integrations.ModelInvocation", null=True, blank=True, on_delete=models.SET_NULL
    )
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost_cents = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    output = models.JSONField(default=dict, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    unauthorized_attempts = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    replay_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="replays"
    )


class ExecutionStep(WorkspaceScopedModel):
    execution = models.ForeignKey(AgentExecution, on_delete=models.CASCADE, related_name="steps")
    sequence = models.PositiveIntegerField()
    tool_key = models.SlugField(max_length=100, blank=True)
    status = models.CharField(max_length=30, choices=ExecutionStatus.choices)
    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    tokens = models.PositiveIntegerField(default=0)
    cost_cents = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    unauthorized = models.BooleanField(default=False)
    error = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["execution", "sequence"], name="uniq_execution_step")
        ]


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELED = "canceled", "Canceled"


class ApprovalRequest(WorkspaceScopedModel):
    execution = models.ForeignKey(
        AgentExecution, on_delete=models.CASCADE, related_name="approval_requests"
    )
    status = models.CharField(
        max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING
    )
    reason = models.TextField()
    requested_by = models.ForeignKey(
        Operator,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requested_approvals",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="execution_approvals",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)


class PerformanceMetric(WorkspaceScopedModel):
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name="metrics")
    execution = models.ForeignKey(
        AgentExecution, null=True, blank=True, on_delete=models.SET_NULL, related_name="metrics"
    )
    metric_key = models.SlugField(max_length=100)
    value = models.DecimalField(max_digits=12, decimal_places=4)
    outcome = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
