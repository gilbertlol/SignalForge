from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasWorkspacePermission
from apps.core.services import get_request_workspace

from .models import (
    AlertEvent,
    AlertRule,
    Dashboard,
    DashboardVisibility,
    DashboardWidget,
    DeliveryAttempt,
    EscalationPolicy,
    Notification,
    QuietHours,
    SavedFilter,
    UserPreference,
)
from .serializers import (
    AlertEventSerializer,
    AlertRuleSerializer,
    DashboardSerializer,
    DashboardWidgetSerializer,
    DeliveryAttemptSerializer,
    EscalationPolicySerializer,
    NotificationSerializer,
    QuietHoursSerializer,
    SavedFilterSerializer,
    UserPreferenceSerializer,
)
from .services import NotificationPolicyError, acknowledge, deliver, retry_delivery


class WorkspaceViewSet(viewsets.ModelViewSet):
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "settings.manage"

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["workspace"] = get_request_workspace(self.request)
        return context


class DashboardViewSet(WorkspaceViewSet):
    serializer_class = DashboardSerializer
    required_workspace_permission = "prospects.access"

    def get_queryset(self):
        workspace = get_request_workspace(self.request)
        role_ids = self.request.user.memberships.filter(workspace=workspace).values_list(
            "roles", flat=True
        )
        return Dashboard.objects.filter(workspace=workspace).filter(
            Q(visibility=DashboardVisibility.SHARED)
            | Q(owner=self.request.user)
            | Q(visibility=DashboardVisibility.ROLE_DEFAULT, role_id__in=role_ids)
        )

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class DashboardWidgetViewSet(WorkspaceViewSet):
    serializer_class = DashboardWidgetSerializer
    required_workspace_permission = "prospects.access"

    def get_queryset(self):
        visible = DashboardViewSet()
        visible.request = self.request
        return DashboardWidget.objects.filter(
            workspace=get_request_workspace(self.request), dashboard__in=visible.get_queryset()
        )


class SavedFilterViewSet(WorkspaceViewSet):
    serializer_class = SavedFilterSerializer
    required_workspace_permission = "prospects.access"

    def get_queryset(self):
        return SavedFilter.objects.filter(workspace=get_request_workspace(self.request)).filter(
            Q(owner=self.request.user) | Q(shared=True)
        )


class AlertRuleViewSet(WorkspaceViewSet):
    serializer_class = AlertRuleSerializer

    def get_queryset(self):
        return AlertRule.objects.filter(workspace=get_request_workspace(self.request)).order_by(
            "name"
        )


class AlertEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AlertEventSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "settings.manage"

    def get_queryset(self):
        return AlertEvent.objects.filter(workspace=get_request_workspace(self.request))


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [HasWorkspacePermission]

    def get_queryset(self):
        return (
            Notification.objects.filter(
                Q(recipient=self.request.user)
                | Q(escalation_history__escalated_to=self.request.user),
                workspace=get_request_workspace(self.request),
            )
            .prefetch_related("delivery_attempts", "escalation_history")
            .distinct()
        )

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        try:
            notification = acknowledge(self.get_object(), user=request.user)
        except NotificationPolicyError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response(self.get_serializer(notification).data)


class DeliveryAttemptViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DeliveryAttemptSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "settings.manage"

    def get_queryset(self):
        return DeliveryAttempt.objects.filter(workspace=get_request_workspace(self.request))

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        try:
            attempt = retry_delivery(self.get_object())
            if request.data.get("deliver_now", True):
                attempt = deliver(attempt)
        except NotificationPolicyError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(attempt).data, status=status.HTTP_201_CREATED)


class UserPreferenceViewSet(WorkspaceViewSet):
    serializer_class = UserPreferenceSerializer
    required_workspace_permission = None

    def get_queryset(self):
        return UserPreference.objects.filter(
            workspace=get_request_workspace(self.request), user=self.request.user
        )


class QuietHoursViewSet(WorkspaceViewSet):
    serializer_class = QuietHoursSerializer
    required_workspace_permission = None

    def get_queryset(self):
        return QuietHours.objects.filter(
            workspace=get_request_workspace(self.request), user=self.request.user
        )


class NotificationEscalationPolicyViewSet(WorkspaceViewSet):
    serializer_class = EscalationPolicySerializer

    def get_queryset(self):
        return EscalationPolicy.objects.filter(workspace=get_request_workspace(self.request))
