from rest_framework import serializers

from .models import (
    AgentExecution,
    AgentProfile,
    AgentVersion,
    ApprovalRequest,
    AssignmentPool,
    BudgetPolicy,
    DataScope,
    ExecutionStep,
    Operator,
    PerformanceMetric,
    Team,
    ToolPermission,
    WorkItem,
)


class WorkspaceSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        workspace = self.context["workspace"]
        for value in attrs.values():
            values = value if isinstance(value, list | tuple) else [value]
            for item in values:
                if hasattr(item, "workspace_id") and item.workspace_id != workspace.id:
                    raise serializers.ValidationError("Related records must use this workspace.")
        return attrs

    def create(self, validated_data):
        validated_data["workspace"] = self.context["workspace"]
        return super().create(validated_data)


class OperatorSerializer(WorkspaceSerializer):
    workload = serializers.SerializerMethodField()

    class Meta:
        model = Operator
        fields = [
            "id",
            "name",
            "operator_type",
            "user",
            "availability",
            "capacity",
            "active",
            "metadata",
            "workload",
        ]

    def get_workload(self, instance):
        return instance.assigned_work.filter(
            status__in=["assigned", "in_progress", "blocked"]
        ).count()


class TeamSerializer(WorkspaceSerializer):
    class Meta:
        model = Team
        fields = ["id", "name", "description", "active"]


class AssignmentPoolSerializer(WorkspaceSerializer):
    class Meta:
        model = AssignmentPool
        fields = ["id", "name", "description", "operators", "active"]
        read_only_fields = ["operators"]


class WorkItemSerializer(WorkspaceSerializer):
    class Meta:
        model = WorkItem
        fields = [
            "id",
            "title",
            "description",
            "status",
            "priority",
            "assignment_strategy",
            "assignee",
            "team",
            "pool",
            "paired_human",
            "paired_agent",
            "context_type",
            "context_id",
            "due_at",
            "claimed_at",
            "completed_at",
            "created_at",
        ]
        read_only_fields = ["claimed_at", "completed_at", "created_at"]

    def create(self, validated_data):
        request = self.context.get("request")
        validated_data["created_by"] = request.user if request else None
        return super().create(validated_data)


class AgentVersionSerializer(WorkspaceSerializer):
    class Meta:
        model = AgentVersion
        fields = ["id", "profile", "version", "instructions", "model", "active"]


class AgentProfileSerializer(WorkspaceSerializer):
    versions = AgentVersionSerializer(many=True, read_only=True)

    class Meta:
        model = AgentProfile
        fields = ["id", "operator", "name", "purpose", "enabled", "versions"]

    def validate_operator(self, operator):
        if operator.operator_type != "ai_agent":
            raise serializers.ValidationError("Agent profiles require an AI agent operator.")
        return operator


class ToolPermissionSerializer(WorkspaceSerializer):
    class Meta:
        model = ToolPermission
        fields = ["id", "agent_version", "tool_key", "policy", "constraints"]


class DataScopeSerializer(WorkspaceSerializer):
    class Meta:
        model = DataScope
        fields = ["id", "agent_version", "resource_type", "allowed_fields", "filters"]


class BudgetPolicySerializer(WorkspaceSerializer):
    class Meta:
        model = BudgetPolicy
        fields = "__all__"
        read_only_fields = ["workspace"]


class ExecutionStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExecutionStep
        fields = [
            "sequence",
            "tool_key",
            "status",
            "input",
            "output",
            "tokens",
            "cost_cents",
            "unauthorized",
            "error",
        ]


class ApprovalRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalRequest
        fields = [
            "id",
            "execution",
            "status",
            "reason",
            "requested_by",
            "decided_by",
            "decided_at",
            "decision_note",
        ]
        read_only_fields = fields


class AgentExecutionSerializer(serializers.ModelSerializer):
    steps = ExecutionStepSerializer(many=True, read_only=True)
    approval_requests = ApprovalRequestSerializer(many=True, read_only=True)

    class Meta:
        model = AgentExecution
        fields = [
            "id",
            "work_item",
            "operator",
            "agent_version",
            "action_key",
            "status",
            "context_type",
            "context_id",
            "context_snapshot",
            "model_invocation",
            "input_tokens",
            "output_tokens",
            "cost_cents",
            "confidence",
            "output",
            "failure_reason",
            "unauthorized_attempts",
            "started_at",
            "finished_at",
            "canceled_at",
            "replay_of",
            "steps",
            "approval_requests",
        ]


class PerformanceMetricSerializer(WorkspaceSerializer):
    class Meta:
        model = PerformanceMetric
        fields = ["id", "operator", "execution", "metric_key", "value", "outcome", "metadata"]
