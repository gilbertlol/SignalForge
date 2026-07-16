from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db import models, transaction
from django.utils import timezone

from apps.accounts.models import Membership, User
from apps.audit.services import record

from .models import (
    ActionPolicy,
    AgentExecution,
    AgentProfile,
    AgentVersion,
    ApprovalRequest,
    ApprovalStatus,
    AssignmentStrategy,
    Availability,
    BudgetPolicy,
    DataScope,
    EscalationPolicy,
    ExecutionStatus,
    ExecutionStep,
    Operator,
    OperatorType,
    ToolPermission,
    WorkItem,
    WorkStatus,
)


class TaskPolicyError(RuntimeError):
    def __init__(self, message: str, *, execution: AgentExecution | None = None):
        super().__init__(message)
        self.execution = execution


def _same_workspace(workspace_id, *objects) -> None:
    if any(obj is not None and obj.workspace_id != workspace_id for obj in objects):
        raise TaskPolicyError("Cross-workspace references are not allowed")


def _active_workload(operator: Operator) -> int:
    return operator.assigned_work.filter(
        status__in=[WorkStatus.ASSIGNED, WorkStatus.IN_PROGRESS, WorkStatus.BLOCKED]
    ).count()


def _candidate_operators(work_item: WorkItem) -> list[Operator]:
    if work_item.assignment_strategy == AssignmentStrategy.TEAM:
        if work_item.team is None:
            raise TaskPolicyError("A team is required")
        queryset = Operator.objects.filter(team_memberships__team=work_item.team)
    elif work_item.assignment_strategy == AssignmentStrategy.POOL:
        if work_item.pool is None:
            raise TaskPolicyError("An assignment pool is required")
        queryset = Operator.objects.filter(pool_memberships__pool=work_item.pool)
    else:
        queryset = Operator.objects.filter(workspace=work_item.workspace)
    return list(
        queryset.filter(active=True, availability=Availability.AVAILABLE)
        .distinct()
        .order_by("created_at")
    )


@transaction.atomic
def assign_work(work_item: WorkItem) -> WorkItem:
    _same_workspace(
        work_item.workspace_id,
        work_item.assignee,
        work_item.team,
        work_item.pool,
        work_item.paired_human,
        work_item.paired_agent,
    )
    strategy = work_item.assignment_strategy
    if strategy == AssignmentStrategy.DIRECT:
        if work_item.assignee is None or not work_item.assignee.active:
            raise TaskPolicyError("An active direct assignee is required")
    elif strategy == AssignmentStrategy.HUMAN_AGENT_PAIR:
        if (
            work_item.paired_human is None
            or work_item.paired_human.operator_type
            not in {OperatorType.HUMAN, OperatorType.CONTRACTOR}
            or work_item.paired_agent is None
            or work_item.paired_agent.operator_type != OperatorType.AI_AGENT
        ):
            raise TaskPolicyError("A human and AI-agent pair is required")
        work_item.assignee = work_item.paired_human
    else:
        candidates = [
            operator
            for operator in _candidate_operators(work_item)
            if _active_workload(operator) < operator.capacity
        ]
        if not candidates:
            raise TaskPolicyError("No operator is currently available")
        work_item.assignee = min(candidates, key=lambda item: (_active_workload(item), item.name))
    work_item.status = WorkStatus.ASSIGNED
    work_item.claimed_at = timezone.now()
    work_item.save(update_fields=["assignee", "status", "claimed_at", "updated_at"])
    record(
        "work.assigned",
        actor=work_item.created_by,
        object_type="tasks.WorkItem",
        object_id=str(work_item.pk),
        metadata={"operator_id": str(work_item.assignee_id), "strategy": strategy},
    )
    return work_item


def _scoped_context(version: AgentVersion, resource_type: str, context: dict[str, Any]) -> dict:
    scope = DataScope.objects.filter(agent_version=version, resource_type=resource_type).first()
    if scope is None:
        raise TaskPolicyError("Agent has no data scope for this resource")
    allowed = set(scope.allowed_fields)
    return {key: value for key, value in context.items() if key in allowed}


def _enforce_budget(profile: AgentProfile, operator: Operator) -> None:
    policies = BudgetPolicy.objects.filter(workspace=operator.workspace, enabled=True).filter(
        models.Q(operator__isnull=True) | models.Q(operator=operator)
    )
    policies = policies.filter(
        models.Q(agent_profile__isnull=True) | models.Q(agent_profile=profile)
    )
    now = timezone.now()
    for policy in policies:
        history = AgentExecution.objects.filter(
            workspace=operator.workspace,
            operator=operator,
            status=ExecutionStatus.SUCCEEDED,
        )
        if policy.daily_cost_cents is not None:
            spent = history.filter(created_at__gte=now - timedelta(days=1)).aggregate(
                value=models.Sum("cost_cents")
            )["value"] or Decimal(0)
            if spent >= policy.daily_cost_cents:
                raise TaskPolicyError("Daily agent budget exhausted")
        if policy.monthly_cost_cents is not None:
            spent = history.filter(
                created_at__year=now.year, created_at__month=now.month
            ).aggregate(value=models.Sum("cost_cents"))["value"] or Decimal(0)
            if spent >= policy.monthly_cost_cents:
                raise TaskPolicyError("Monthly agent budget exhausted")
        running = AgentExecution.objects.filter(
            operator=operator, status=ExecutionStatus.RUNNING
        ).count()
        if running >= policy.max_concurrency:
            raise TaskPolicyError("Agent concurrency limit reached")


def request_execution(
    *,
    profile: AgentProfile,
    action_key: str,
    context_type: str,
    context_id: str,
    context: dict[str, Any],
    work_item: WorkItem | None = None,
    confidence: Decimal | None = None,
) -> AgentExecution:
    operator = profile.operator
    _same_workspace(operator.workspace_id, profile, work_item)
    if (
        not profile.enabled
        or not operator.active
        or operator.operator_type != OperatorType.AI_AGENT
    ):
        raise TaskPolicyError("AI operator is unavailable")
    version = profile.versions.filter(active=True).order_by("-version").first()
    if version is None:
        raise TaskPolicyError("Agent has no active version")
    _enforce_budget(profile, operator)
    scoped_context = _scoped_context(version, context_type, context)
    permission = ToolPermission.objects.filter(agent_version=version, tool_key=action_key).first()
    policy = permission.policy if permission else ActionPolicy.DENY
    execution = AgentExecution.objects.create(
        workspace=operator.workspace,
        work_item=work_item,
        operator=operator,
        agent_version=version,
        action_key=action_key,
        context_type=context_type,
        context_id=context_id,
        context_snapshot=scoped_context,
        confidence=confidence,
    )
    if policy in {ActionPolicy.DENY, ActionPolicy.HUMAN_ONLY}:
        execution.status = ExecutionStatus.DENIED
        execution.unauthorized_attempts = 1
        execution.failure_reason = "Action is denied by policy"
        execution.finished_at = timezone.now()
        execution.save()
        ExecutionStep.objects.create(
            workspace=operator.workspace,
            execution=execution,
            sequence=1,
            tool_key=action_key,
            status=ExecutionStatus.DENIED,
            unauthorized=True,
            error="PolicyDenied",
        )
        record(
            "agent.execution_denied",
            object_type="tasks.AgentExecution",
            object_id=str(execution.pk),
            metadata={"action": action_key, "policy": policy},
        )
        raise TaskPolicyError("Action is denied by policy", execution=execution)
    needs_approval = policy == ActionPolicy.APPROVAL_REQUIRED
    escalation = EscalationPolicy.objects.filter(
        workspace=operator.workspace, action_key=action_key, enabled=True
    ).first()
    if escalation and (confidence is None or confidence < escalation.minimum_confidence):
        needs_approval = True
    if needs_approval:
        execution.status = ExecutionStatus.WAITING_APPROVAL
        execution.save(update_fields=["status", "updated_at"])
        ApprovalRequest.objects.create(
            workspace=operator.workspace,
            execution=execution,
            requested_by=operator,
            reason="Action policy requires human approval",
        )
    else:
        execution.status = ExecutionStatus.RUNNING
        execution.started_at = timezone.now()
        execution.save(update_fields=["status", "started_at", "updated_at"])
    record(
        "agent.execution_requested",
        object_type="tasks.AgentExecution",
        object_id=str(execution.pk),
        metadata={"action": action_key, "policy": policy},
    )
    return execution


@transaction.atomic
def decide_approval(
    approval: ApprovalRequest, *, decided_by: User, approve: bool, note: str = ""
) -> ApprovalRequest:
    membership = Membership.objects.filter(
        workspace=approval.workspace, user=decided_by, is_active=True
    ).first()
    if membership is None or not membership.has_permission("approvals.manage"):
        raise TaskPolicyError("Approval permission is required")
    if approval.status != ApprovalStatus.PENDING:
        raise TaskPolicyError("Approval was already decided")
    approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    approval.decided_by = decided_by
    approval.decided_at = timezone.now()
    approval.decision_note = note
    approval.save()
    execution = approval.execution
    execution.status = ExecutionStatus.RUNNING if approve else ExecutionStatus.DENIED
    if approve:
        execution.started_at = timezone.now()
    else:
        execution.finished_at = timezone.now()
        execution.failure_reason = "Human approval rejected"
    execution.save()
    record(
        "agent.approval_decided",
        actor=decided_by,
        object_type="tasks.ApprovalRequest",
        object_id=str(approval.pk),
        metadata={"decision": approval.status},
    )
    return approval


@transaction.atomic
def complete_execution(
    execution: AgentExecution,
    *,
    output: dict[str, Any],
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_cents: Decimal = Decimal(0),
    confidence: Decimal | None = None,
) -> AgentExecution:
    if execution.status != ExecutionStatus.RUNNING:
        raise TaskPolicyError("Only running executions can complete")
    policy = (
        BudgetPolicy.objects.filter(
            workspace=execution.workspace,
            enabled=True,
        )
        .filter(
            models.Q(operator__isnull=True) | models.Q(operator=execution.operator),
            models.Q(agent_profile__isnull=True)
            | models.Q(agent_profile=execution.agent_version.profile),
        )
        .order_by("created_at")
        .first()
    )
    total_tokens = input_tokens + output_tokens
    if policy and (
        (policy.max_execution_tokens is not None and total_tokens > policy.max_execution_tokens)
        or (
            policy.max_execution_cost_cents is not None
            and cost_cents > policy.max_execution_cost_cents
        )
    ):
        execution.status = ExecutionStatus.FAILED
        execution.failure_reason = "Execution budget exceeded"
    else:
        execution.status = ExecutionStatus.SUCCEEDED
        execution.output = output
    execution.input_tokens = input_tokens
    execution.output_tokens = output_tokens
    execution.cost_cents = cost_cents
    execution.confidence = confidence
    execution.finished_at = timezone.now()
    execution.save()
    return execution


@transaction.atomic
def cancel_execution(execution: AgentExecution, *, actor: User | None = None) -> AgentExecution:
    if execution.status in {
        ExecutionStatus.SUCCEEDED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELED,
        ExecutionStatus.DENIED,
    }:
        raise TaskPolicyError("Execution is already terminal")
    execution.status = ExecutionStatus.CANCELED
    execution.canceled_at = timezone.now()
    execution.finished_at = execution.canceled_at
    execution.save()
    execution.approval_requests.filter(status=ApprovalStatus.PENDING).update(
        status=ApprovalStatus.CANCELED, decided_at=timezone.now()
    )
    record(
        "agent.execution_canceled",
        actor=actor,
        object_type="tasks.AgentExecution",
        object_id=str(execution.pk),
    )
    return execution


def replay_execution(execution: AgentExecution) -> AgentExecution:
    if execution.status not in {
        ExecutionStatus.SUCCEEDED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELED,
        ExecutionStatus.DENIED,
    }:
        raise TaskPolicyError("Only terminal executions can be replayed")
    replay = request_execution(
        profile=execution.agent_version.profile,
        action_key=execution.action_key,
        context_type=execution.context_type,
        context_id=execution.context_id,
        context=execution.context_snapshot,
        work_item=execution.work_item,
        confidence=execution.confidence,
    )
    replay.replay_of = execution
    replay.save(update_fields=["replay_of", "updated_at"])
    return replay
