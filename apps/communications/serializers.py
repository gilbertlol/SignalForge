from rest_framework import serializers

from .models import ChannelAccount, Conversation, Message, MessageStatus


class WorkspaceSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        workspace = self.context["workspace"]
        for value in attrs.values():
            if hasattr(value, "workspace_id") and value.workspace_id != workspace.id:
                raise serializers.ValidationError("Related records must use the active workspace.")
        return attrs

    def create(self, validated_data):
        validated_data["workspace"] = self.context["workspace"]
        return super().create(validated_data)


class ChannelAccountSerializer(WorkspaceSerializer):
    class Meta:
        model = ChannelAccount
        fields = ["id", "name", "channel", "provider_key", "address", "enabled", "config"]


class ConversationSerializer(WorkspaceSerializer):
    class Meta:
        model = Conversation
        fields = [
            "id",
            "subject",
            "opportunity",
            "channel_account",
            "external_thread_id",
            "last_message_at",
            "closed_at",
            "created_at",
        ]
        read_only_fields = ["last_message_at", "created_at"]


class MessageSerializer(WorkspaceSerializer):
    class Meta:
        model = Message
        fields = [
            "id",
            "conversation",
            "parent",
            "direction",
            "channel",
            "sender",
            "recipients",
            "subject",
            "body_text",
            "status",
            "scheduled_at",
            "sent_at",
            "delivered_at",
            "approved_at",
            "approval_reasons",
            "reply_classification",
            "confidence",
            "contains_pricing",
            "contains_scope_commitment",
            "high_risk",
            "failure_reason",
            "send_attempts",
            "created_at",
        ]
        read_only_fields = [
            "sent_at",
            "delivered_at",
            "approved_at",
            "approval_reasons",
            "reply_classification",
            "failure_reason",
            "send_attempts",
            "created_at",
        ]

    def create(self, validated_data):
        if validated_data.get("direction") == "outbound":
            validated_data["status"] = MessageStatus.DRAFT
        return super().create(validated_data)


class InboundEventSerializer(serializers.Serializer):
    event_id = serializers.CharField(max_length=255)
    message_id = serializers.CharField(max_length=255)
    thread_id = serializers.CharField(max_length=255, required=False, allow_blank=True)
    sender = serializers.CharField(max_length=320)
    recipients = serializers.ListField(child=serializers.CharField(max_length=320))
    subject = serializers.CharField(required=False, allow_blank=True)
    body_text = serializers.CharField()
