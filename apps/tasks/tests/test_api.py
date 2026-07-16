import pytest
from rest_framework.test import APIClient

from apps.accounts.models import AccessPermission
from apps.accounts.tests.factories import UserFactory
from apps.core.models import Workspace
from apps.tasks.models import (
    ActionPolicy,
    AgentExecution,
    AgentProfile,
    AgentVersion,
    ApprovalRequest,
    ApprovalStatus,
    DataScope,
    ExecutionStatus,
    Operator,
    OperatorType,
    ToolPermission,
)

pytestmark = pytest.mark.django_db


def grant(user, key):
    permission, _ = AccessPermission.objects.get_or_create(key=key, defaults={"name": key})
    user.memberships.get().permission_grants.add(permission)


def authenticated_client(*permissions):
    user = UserFactory()
    for permission in permissions:
        grant(user, permission)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user, user.memberships.get().workspace


def agent_stack(workspace, policy=ActionPolicy.AUTONOMOUS):
    operator = Operator.objects.create(
        workspace=workspace, name="Research agent", operator_type=OperatorType.AI_AGENT
    )
    profile = AgentProfile.objects.create(
        workspace=workspace, operator=operator, name="Research", purpose="Find evidence"
    )
    version = AgentVersion.objects.create(
        workspace=workspace, profile=profile, version=1, instructions="Research", active=True
    )
    ToolPermission.objects.create(
        workspace=workspace, agent_version=version, tool_key="research", policy=policy
    )
    DataScope.objects.create(
        workspace=workspace,
        agent_version=version,
        resource_type="organization",
        allowed_fields=["name"],
    )
    return profile, version


def test_operator_api_requires_agents_permission():
    client, user, _ = authenticated_client()
    assert client.get("/api/v1/operators/").status_code == 403

    grant(user, "agents.manage")
    assert client.get("/api/v1/operators/").status_code == 200


def test_operator_api_is_workspace_scoped():
    client, _, workspace = authenticated_client("agents.manage")
    Operator.objects.create(workspace=workspace, name="Visible", operator_type=OperatorType.HUMAN)
    other = Workspace.objects.create(name="Other", slug="tasks-api-other")
    Operator.objects.create(workspace=other, name="Hidden", operator_type=OperatorType.HUMAN)

    response = client.get("/api/v1/operators/")

    assert [item["name"] for item in response.json()["results"]] == ["Visible"]


def test_agent_profile_rejects_human_operator():
    client, _, workspace = authenticated_client("agents.manage")
    human = Operator.objects.create(
        workspace=workspace, name="Human", operator_type=OperatorType.HUMAN
    )

    response = client.post(
        "/api/v1/agent-profiles/",
        {"operator": str(human.pk), "name": "Invalid", "purpose": "No"},
        format="json",
    )

    assert response.status_code == 400
    assert "AI agent" in str(response.json())


def test_agent_execute_denial_is_audited():
    client, _, workspace = authenticated_client("agents.manage")
    profile, _ = agent_stack(workspace)

    response = client.post(
        f"/api/v1/agent-profiles/{profile.pk}/execute/",
        {
            "action_key": "unlisted_tool",
            "context_type": "organization",
            "context_id": "acme",
            "context": {"name": "Acme", "secret": "hidden"},
        },
        format="json",
    )

    assert response.status_code == 403
    execution = AgentExecution.objects.get(pk=response.json()["execution_id"])
    assert execution.status == ExecutionStatus.DENIED
    assert execution.unauthorized_attempts == 1


def test_approval_decision_parses_false_string_as_rejection():
    client, user, workspace = authenticated_client("agents.manage", "approvals.manage")
    profile, version = agent_stack(workspace, ActionPolicy.APPROVAL_REQUIRED)
    operator = profile.operator
    execution = AgentExecution.objects.create(
        workspace=workspace,
        operator=operator,
        agent_version=version,
        action_key="research",
        status=ExecutionStatus.WAITING_APPROVAL,
    )
    approval = ApprovalRequest.objects.create(
        workspace=workspace, execution=execution, reason="Review"
    )

    response = client.post(
        f"/api/v1/agent-approvals/{approval.pk}/decide/",
        {"approve": "false"},
        format="json",
    )

    assert response.status_code == 200
    approval.refresh_from_db()
    execution.refresh_from_db()
    assert approval.status == ApprovalStatus.REJECTED
    assert approval.decided_by == user
    assert execution.status == ExecutionStatus.DENIED
