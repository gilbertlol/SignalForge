from rest_framework import serializers

from .models import (
    AlertEvent,
    AlertRule,
    Dashboard,
    DashboardWidget,
    DeliveryAttempt,
    EscalationHistory,
    EscalationPolicy,
    Notification,
    QuietHours,
    SavedFilter,
    UserPreference,
)


class WorkspaceSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        workspace = self.context["workspace"]
        for value in attrs.values():
            if hasattr(value, "workspace_id") and value.workspace_id != workspace.pk:
                raise serializers.ValidationError("Related records must use this workspace.")
        return attrs

    def create(self, validated_data):
        validated_data["workspace"] = self.context["workspace"]
        return super().create(validated_data)


class DashboardWidgetSerializer(WorkspaceSerializer):
    class Meta:
        model = DashboardWidget
        fields = [
            "id",
            "dashboard",
            "title",
            "kind",
            "position",
            "filters",
            "saved_filter",
            "drilldown_url",
            "refresh_interval_seconds",
        ]

    def validate_dashboard(self, dashboard):
        user = self.context["request"].user
        if dashboard.visibility == "personal" and dashboard.owner_id != user.pk:
            raise serializers.ValidationError("You cannot modify another user's dashboard.")
        membership = user.memberships.filter(workspace=dashboard.workspace, is_active=True).first()
        if dashboard.visibility != "personal" and not (
            user.is_superuser or membership and membership.has_permission("settings.manage")
        ):
            raise serializers.ValidationError("Shared dashboards require settings permission.")
        return dashboard


class DashboardSerializer(WorkspaceSerializer):
    widgets = DashboardWidgetSerializer(many=True, read_only=True)

    class Meta:
        model = Dashboard
        fields = [
            "id",
            "name",
            "description",
            "owner",
            "role",
            "visibility",
            "is_default",
            "widgets",
        ]
        read_only_fields = ["owner"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        visibility = attrs.get("visibility", getattr(self.instance, "visibility", "personal"))
        role = attrs.get("role", getattr(self.instance, "role", None))
        if visibility == "role_default" and role is None:
            raise serializers.ValidationError("Role-default dashboards require a role.")
        user = self.context["request"].user
        membership = user.memberships.filter(
            workspace=self.context["workspace"], is_active=True
        ).first()
        if visibility != "personal" and not (
            user.is_superuser or membership and membership.has_permission("settings.manage")
        ):
            raise serializers.ValidationError("Shared dashboards require settings permission.")
        return attrs


class SavedFilterSerializer(WorkspaceSerializer):
    class Meta:
        model = SavedFilter
        fields = ["id", "name", "owner", "resource_type", "criteria", "shared"]
        read_only_fields = ["owner"]

    def create(self, validated_data):
        validated_data["owner"] = self.context["request"].user
        return super().create(validated_data)


class AlertRuleSerializer(WorkspaceSerializer):
    class Meta:
        model = AlertRule
        fields = "__all__"
        read_only_fields = ["workspace"]


class AlertEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertEvent
        fields = "__all__"
        read_only_fields = fields


class DeliveryAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryAttempt
        fields = "__all__"
        read_only_fields = fields


class EscalationHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = EscalationHistory
        fields = "__all__"
        read_only_fields = fields


class NotificationSerializer(serializers.ModelSerializer):
    delivery_attempts = DeliveryAttemptSerializer(many=True, read_only=True)
    escalation_history = EscalationHistorySerializer(many=True, read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "event",
            "recipient",
            "title",
            "body",
            "priority",
            "status",
            "requires_acknowledgement",
            "acknowledged_at",
            "read_at",
            "grouped_count",
            "digest_eligible",
            "created_at",
            "delivery_attempts",
            "escalation_history",
        ]
        read_only_fields = fields


class UserPreferenceSerializer(WorkspaceSerializer):
    class Meta:
        model = UserPreference
        fields = [
            "id",
            "user",
            "channel",
            "enabled",
            "minimum_priority",
            "destination",
            "digest",
        ]
        read_only_fields = ["user"]

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)


class QuietHoursSerializer(WorkspaceSerializer):
    class Meta:
        model = QuietHours
        fields = [
            "id",
            "user",
            "timezone",
            "start_time",
            "end_time",
            "weekdays",
            "enabled",
            "allow_critical",
        ]
        read_only_fields = ["user"]

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)


class EscalationPolicySerializer(WorkspaceSerializer):
    class Meta:
        model = EscalationPolicy
        fields = "__all__"
        read_only_fields = ["workspace"]
