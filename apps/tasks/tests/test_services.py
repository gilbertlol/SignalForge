from decimal import Decimal

import pytest

from apps.accounts.models import AccessPermission
from apps.accounts.tests.factories import UserFactory
from apps.audit.models import AuditLogEntry
from apps.core.models import Workspace
from apps.tasks.models import (
    ActionPolicy,
    AgentExecution,
    AgentProfile,
    AgentVersion,
    ApprovalStatus,
    AssignmentPool,
    AssignmentPoolMember,
    AssignmentStrategy,
    BudgetPolicy,
    DataScope,
    ExecutionStatus,
    Operator,
    OperatorType,
    ToolPermission,
    WorkItem,
)
from apps.tasks.services import (
    TaskPolicyError,
    assign_work,
    cancel_execution,
    complete_execution,
    decide_approval,
    replay_execution,
    request_execution,
)

pytestmark = pytest.mark.django_db


def agent_fixture(workspace, *, policy=ActionPolicy.AUTONOMOUS):
    operator = Operator.objects.create(
        workspace=workspace,
        name="Research agent",
        operator_type=OperatorType.AI_AGENT,
        capacity=2,
    )
    profile = AgentProfile.objects.create(
        workspace=workspace, operator=operator, name="Research", purpose="Find prospects"
    )
    version = AgentVersion.objects.create(
        workspace=workspace,
        profile=profile,
        version=1,
        instructions="Use public evidence only.",
        active=True,
    )
    DataScope.objects.create(
        workspace=workspace,
        agent_version=version,
        resource_type="organization",
        allowed_fields=["name", "domain"],
    )
    if policy is not None:
        ToolPermission.objects.create(
            workspace=workspace,
            agent_version=version,
            tool_key="research",
            policy=policy,
        )
    return operator, profile, version


def test_pool_assignment_uses_available_operator_with_lowest_workload():
    workspace = Workspace.objects.create(name="Routing", slug="routing")
    busy = Operator.objects.create(
        workspace=workspace, name="Busy", operator_type=OperatorType.HUMAN, capacity=2
    )
    free = Operator.objects.create(
        workspace=workspace, name="Free", operator_type=OperatorType.CONTRACTOR, capacity=2
    )
    pool = AssignmentPool.objects.create(workspace=workspace, name="Researchers")
    for operator in (busy, free):
        AssignmentPoolMember.objects.create(workspace=workspace, pool=pool, operator=operator)
    WorkItem.objects.create(
        workspace=workspace,
        title="Existing",
        assignment_strategy=AssignmentStrategy.DIRECT,
        assignee=busy,
        status="in_progress",
    )
    work = WorkItem.objects.create(
        workspace=workspace,
        title="New research",
        assignment_strategy=AssignmentStrategy.POOL,
        pool=pool,
    )

    assign_work(work)

    assert work.assignee == free
    assert work.status == "assigned"
    assert AuditLogEntry.objects.filter(action="work.assigned").exists()


def test_human_agent_pair_requires_both_operator_types():
    workspace = Workspace.objects.create(name="Pair", slug="pair")
    human = Operator.objects.create(
        workspace=workspace, name="Human", operator_type=OperatorType.HUMAN
    )
    wrong = Operator.objects.create(
        workspace=workspace, name="Wrong", operator_type=OperatorType.SYSTEM
    )
    work = WorkItem.objects.create(
        workspace=workspace,
        title="Pair",
        assignment_strategy=AssignmentStrategy.HUMAN_AGENT_PAIR,
        paired_human=human,
        paired_agent=wrong,
    )

    with pytest.raises(TaskPolicyError, match="human and AI-agent"):
        assign_work(work)


def test_agent_permissions_are_deny_by_default_and_audited():
    workspace = Workspace.objects.create(name="Deny", slug="deny")
    _, profile, _ = agent_fixture(workspace, policy=None)

    with pytest.raises(TaskPolicyError) as denied:
        request_execution(
            profile=profile,
            action_key="send_email",
            context_type="organization",
            context_id="org-1",
            context={"name": "Acme"},
        )

    execution = denied.value.execution
    assert execution is not None
    assert execution.status == ExecutionStatus.DENIED
    assert execution.unauthorized_attempts == 1
    assert execution.steps.get().unauthorized is True
    assert AuditLogEntry.objects.filter(action="agent.execution_denied").exists()


def test_context_is_reduced_to_explicit_data_scope():
    workspace = Workspace.objects.create(name="Scope", slug="scope")
    _, profile, _ = agent_fixture(workspace)

    execution = request_execution(
        profile=profile,
        action_key="research",
        context_type="organization",
        context_id="org-1",
        context={"name": "Acme", "domain": "acme.test", "private_notes": "secret"},
    )

    assert execution.status == ExecutionStatus.RUNNING
    assert execution.context_snapshot == {"name": "Acme", "domain": "acme.test"}


def test_unknown_resource_scope_blocks_execution():
    workspace = Workspace.objects.create(name="No scope", slug="no-scope")
    _, profile, _ = agent_fixture(workspace)

    with pytest.raises(TaskPolicyError, match="no data scope"):
        request_execution(
            profile=profile,
            action_key="research",
            context_type="finance",
            context_id="invoice-1",
            context={"amount": 100},
        )

    assert not AgentExecution.objects.exists()


def test_approval_required_action_waits_for_authorized_human():
    approver = UserFactory()
    membership = approver.memberships.get()
    workspace = membership.workspace
    permission, _ = AccessPermission.objects.get_or_create(
        key="approvals.manage", defaults={"name": "Manage approvals"}
    )
    membership.permission_grants.add(permission)
    _, profile, _ = agent_fixture(workspace, policy=ActionPolicy.APPROVAL_REQUIRED)
    execution = request_execution(
        profile=profile,
        action_key="research",
        context_type="organization",
        context_id="org-1",
        context={"name": "Acme"},
    )

    approval = execution.approval_requests.get()
    assert execution.status == ExecutionStatus.WAITING_APPROVAL
    decide_approval(approval, decided_by=approver, approve=True, note="Reviewed")
    execution.refresh_from_db()
    assert approval.status == ApprovalStatus.APPROVED
    assert execution.status == ExecutionStatus.RUNNING


def test_user_without_permission_cannot_approve():
    user = UserFactory()
    workspace = user.memberships.get().workspace
    _, profile, _ = agent_fixture(workspace, policy=ActionPolicy.APPROVAL_REQUIRED)
    execution = request_execution(
        profile=profile,
        action_key="research",
        context_type="organization",
        context_id="org-1",
        context={"name": "Acme"},
    )

    with pytest.raises(TaskPolicyError, match="permission"):
        decide_approval(execution.approval_requests.get(), decided_by=user, approve=True)


def test_daily_budget_prevents_new_execution():
    workspace = Workspace.objects.create(name="Budget", slug="agent-budget")
    operator, profile, version = agent_fixture(workspace)
    BudgetPolicy.objects.create(
        workspace=workspace,
        name="Daily cap",
        operator=operator,
        daily_cost_cents=Decimal("1.0000"),
    )
    AgentExecution.objects.create(
        workspace=workspace,
        operator=operator,
        agent_version=version,
        action_key="research",
        status=ExecutionStatus.SUCCEEDED,
        cost_cents=Decimal("1.0000"),
    )

    with pytest.raises(TaskPolicyError, match="budget exhausted"):
        request_execution(
            profile=profile,
            action_key="research",
            context_type="organization",
            context_id="org-1",
            context={"name": "Acme"},
        )


def test_execution_budget_marks_overspend_as_failed():
    workspace = Workspace.objects.create(name="Execution budget", slug="execution-budget")
    operator, profile, _ = agent_fixture(workspace)
    BudgetPolicy.objects.create(
        workspace=workspace,
        name="Per execution",
        operator=operator,
        max_execution_tokens=10,
        max_execution_cost_cents=Decimal("0.5000"),
    )
    execution = request_execution(
        profile=profile,
        action_key="research",
        context_type="organization",
        context_id="org-1",
        context={"name": "Acme"},
    )

    complete_execution(
        execution,
        output={"result": "ignored"},
        input_tokens=8,
        output_tokens=8,
        cost_cents=Decimal("0.7500"),
    )

    assert execution.status == ExecutionStatus.FAILED
    assert execution.failure_reason == "Execution budget exceeded"


def test_cancel_and_replay_preserve_lineage_and_context():
    workspace = Workspace.objects.create(name="Replay", slug="replay")
    _, profile, _ = agent_fixture(workspace)
    original = request_execution(
        profile=profile,
        action_key="research",
        context_type="organization",
        context_id="org-1",
        context={"name": "Acme", "private_notes": "secret"},
    )
    cancel_execution(original)

    replay = replay_execution(original)

    assert original.status == ExecutionStatus.CANCELED
    assert replay.replay_of == original
    assert replay.context_snapshot == {"name": "Acme"}
