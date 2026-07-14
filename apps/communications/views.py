from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasWorkspacePermission
from apps.core.services import get_request_workspace

from .models import ChannelAccount, Conversation, Message
from .serializers import (
    ChannelAccountSerializer,
    ConversationSerializer,
    InboundEventSerializer,
    MessageSerializer,
)
from .services import SendBlocked, approve_message, send_message, synchronize_inbound


class WorkspaceViewSet(viewsets.ModelViewSet):
    permission_classes = [HasWorkspacePermission]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["workspace"] = get_request_workspace(self.request)
        return context


class ChannelAccountViewSet(WorkspaceViewSet):
    serializer_class = ChannelAccountSerializer
    required_workspace_permission = "settings.manage"

    def get_queryset(self):
        return ChannelAccount.objects.filter(
            workspace=get_request_workspace(self.request)
        ).order_by("name")

    @action(detail=True, methods=["post"], url_path="inbound-events")
    def inbound_event(self, request, pk=None):
        serializer = InboundEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        event_id = payload.pop("event_id")
        message = synchronize_inbound(account=self.get_object(), event_id=event_id, payload=payload)
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class ConversationViewSet(WorkspaceViewSet):
    serializer_class = ConversationSerializer
    required_workspace_permission = "communications.access"

    def get_queryset(self):
        return Conversation.objects.filter(workspace=get_request_workspace(self.request)).order_by(
            "-last_message_at", "-created_at"
        )

    @action(detail=True, methods=["get"])
    def messages(self, request, pk=None):
        return Response(MessageSerializer(self.get_object().messages.all(), many=True).data)


class MessageViewSet(WorkspaceViewSet):
    serializer_class = MessageSerializer

    def get_required_permission(self):
        return (
            "communications.send" if self.action in {"approve", "send"} else "communications.access"
        )

    @property
    def required_workspace_permission(self):
        return self.get_required_permission()

    def get_queryset(self):
        return Message.objects.filter(workspace=get_request_workspace(self.request)).order_by(
            "created_at"
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        message = approve_message(self.get_object(), request.user)
        return Response(self.get_serializer(message).data)

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        message = self.get_object()
        try:
            send_message(message, actor=request.user)
        except SendBlocked:
            message.refresh_from_db()
            return Response(self.get_serializer(message).data, status=status.HTTP_409_CONFLICT)
        return Response(self.get_serializer(message).data)
