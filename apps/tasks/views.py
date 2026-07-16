from decimal import Decimal

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasWorkspacePermission
from apps.core.services import get_request_workspace

from .models import (
    AgentExecution,
    AgentProfile,
    AgentVersion,
    ApprovalRequest,
    AssignmentPool,
    BudgetPolicy,
    DataScope,
    Operator,
    PerformanceMetric,
    Team,
    ToolPermission,
    WorkItem,
)
from .serializers import (
    AgentExecutionSerializer,
    AgentProfileSerializer,
    AgentVersionSerializer,
    ApprovalRequestSerializer,
    AssignmentPoolSerializer,
    BudgetPolicySerializer,
    DataScopeSerializer,
    OperatorSerializer,
    PerformanceMetricSerializer,
    TeamSerializer,
    ToolPermissionSerializer,
    WorkItemSerializer,
)
from .services import (
    TaskPolicyError,
    assign_work,
    cancel_execution,
    decide_approval,
    replay_execution,
    request_execution,
)


class WorkspaceViewSet(viewsets.ModelViewSet):
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "agents.manage"

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["workspace"] = get_request_workspace(self.request)
        return context

    def policy_error(self, exc):
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class OperatorViewSet(WorkspaceViewSet):
    serializer_class = OperatorSerializer

    def get_queryset(self):
        return Operator.objects.filter(workspace=get_request_workspace(self.request)).order_by(
            "name"
        )


class TeamViewSet(WorkspaceViewSet):
    serializer_class = TeamSerializer

    def get_queryset(self):
        return Team.objects.filter(workspace=get_request_workspace(self.request)).order_by("name")


class AssignmentPoolViewSet(WorkspaceViewSet):
    serializer_class = AssignmentPoolSerializer

    def get_queryset(self):
        return AssignmentPool.objects.filter(
            workspace=get_request_workspace(self.request)
        ).order_by("name")


class WorkItemViewSet(WorkspaceViewSet):
    serializer_class = WorkItemSerializer

    def get_queryset(self):
        return WorkItem.objects.filter(workspace=get_request_workspace(self.request)).order_by(
            "status", "priority", "created_at"
        )

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        try:
            work_item = assign_work(self.get_object())
        except TaskPolicyError as exc:
            return self.policy_error(exc)
        return Response(self.get_serializer(work_item).data)


class AgentProfileViewSet(WorkspaceViewSet):
    serializer_class = AgentProfileSerializer

    def get_queryset(self):
        return AgentProfile.objects.filter(
            workspace=get_request_workspace(self.request)
        ).select_related("operator")

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        required = {"action_key", "context_type", "context_id", "context"}
        if not required.issubset(request.data):
            raise serializers.ValidationError(f"Required fields: {', '.join(sorted(required))}")
        work_item = None
        if request.data.get("work_item"):
            work_item = WorkItem.objects.filter(
                workspace=get_request_workspace(request), pk=request.data["work_item"]
            ).first()
            if work_item is None:
                raise serializers.ValidationError("Unknown work item")
        try:
            execution = request_execution(
                profile=self.get_object(),
                action_key=request.data["action_key"],
                context_type=request.data["context_type"],
                context_id=request.data["context_id"],
                context=request.data["context"],
                work_item=work_item,
                confidence=Decimal(str(request.data["confidence"]))
                if request.data.get("confidence") is not None
                else None,
            )
        except TaskPolicyError as exc:
            data = {"detail": str(exc)}
            if exc.execution:
                data["execution_id"] = str(exc.execution.pk)
            return Response(data, status=status.HTTP_403_FORBIDDEN)
        return Response(AgentExecutionSerializer(execution).data, status=status.HTTP_201_CREATED)


class AgentVersionViewSet(WorkspaceViewSet):
    serializer_class = AgentVersionSerializer

    def get_queryset(self):
        return AgentVersion.objects.filter(workspace=get_request_workspace(self.request))


class ToolPermissionViewSet(WorkspaceViewSet):
    serializer_class = ToolPermissionSerializer

    def get_queryset(self):
        return ToolPermission.objects.filter(workspace=get_request_workspace(self.request))


class DataScopeViewSet(WorkspaceViewSet):
    serializer_class = DataScopeSerializer

    def get_queryset(self):
        return DataScope.objects.filter(workspace=get_request_workspace(self.request))


class BudgetPolicyViewSet(WorkspaceViewSet):
    serializer_class = BudgetPolicySerializer

    def get_queryset(self):
        return BudgetPolicy.objects.filter(workspace=get_request_workspace(self.request))


class AgentExecutionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AgentExecutionSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "agents.manage"

    def get_queryset(self):
        return AgentExecution.objects.filter(
            workspace=get_request_workspace(self.request)
        ).prefetch_related("steps", "approval_requests")

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        try:
            execution = cancel_execution(self.get_object(), actor=request.user)
        except TaskPolicyError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(execution).data)

    @action(detail=True, methods=["post"])
    def replay(self, request, pk=None):
        try:
            execution = replay_execution(self.get_object())
        except TaskPolicyError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(execution).data, status=status.HTTP_201_CREATED)


class ApprovalRequestViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ApprovalRequestSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "approvals.manage"

    def get_queryset(self):
        return ApprovalRequest.objects.filter(workspace=get_request_workspace(self.request))

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        decision = serializers.BooleanField().run_validation(request.data.get("approve"))
        try:
            approval = decide_approval(
                self.get_object(),
                decided_by=request.user,
                approve=decision,
                note=request.data.get("note", ""),
            )
        except TaskPolicyError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response(self.get_serializer(approval).data)


class PerformanceMetricViewSet(WorkspaceViewSet):
    serializer_class = PerformanceMetricSerializer

    def get_queryset(self):
        return PerformanceMetric.objects.filter(workspace=get_request_workspace(self.request))
