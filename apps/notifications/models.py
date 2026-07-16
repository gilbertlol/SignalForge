from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import WorkspaceScopedModel


def all_weekdays():
    return [0, 1, 2, 3, 4, 5, 6]


class DashboardVisibility(models.TextChoices):
    PERSONAL = "personal", "Personal"
    SHARED = "shared", "Shared"
    ROLE_DEFAULT = "role_default", "Role default"


class Dashboard(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE
    )
    role = models.ForeignKey("accounts.Role", null=True, blank=True, on_delete=models.CASCADE)
    visibility = models.CharField(
        max_length=20, choices=DashboardVisibility.choices, default=DashboardVisibility.PERSONAL
    )
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="uniq_dashboard_name")
        ]


class SavedFilter(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    resource_type = models.SlugField(max_length=100)
    criteria = models.JSONField(default=dict)
    shared = models.BooleanField(default=False)


class WidgetKind(models.TextChoices):
    LEAD_GENERATION = "lead_generation", "Lead generation"
    OUTREACH = "outreach", "Outreach"
    PIPELINE = "pipeline", "Pipeline"
    FINANCE = "finance", "Finance"
    TEAM_CAPACITY = "team_capacity", "Team capacity"
    RISK = "risk", "Risk"
    AGENT_PERFORMANCE = "agent_performance", "Agent performance"


class DashboardWidget(WorkspaceScopedModel):
    dashboard = models.ForeignKey(Dashboard, on_delete=models.CASCADE, related_name="widgets")
    title = models.CharField(max_length=255)
    kind = models.CharField(max_length=40, choices=WidgetKind.choices)
    position = models.PositiveSmallIntegerField(default=0)
    filters = models.JSONField(default=dict, blank=True)
    saved_filter = models.ForeignKey(SavedFilter, null=True, blank=True, on_delete=models.SET_NULL)
    drilldown_url = models.CharField(max_length=500)
    refresh_interval_seconds = models.PositiveIntegerField(default=300)

    class Meta:
        ordering = ["position", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["dashboard", "position"], name="uniq_dashboard_widget_position"
            )
        ]


class NotificationPriority(models.TextChoices):
    INFORMATIONAL = "informational", "Informational"
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class DeliveryChannel(models.TextChoices):
    IN_APP = "in_app", "In app"
    EMAIL = "email", "Email"
    SLACK = "slack", "Slack"
    DISCORD = "discord", "Discord"
    DESKTOP = "desktop", "Desktop"
    SMS = "sms", "SMS"


class AlertRule(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    event_type = models.SlugField(max_length=100)
    conditions = models.JSONField(default=dict, blank=True)
    priority = models.CharField(
        max_length=20,
        choices=NotificationPriority.choices,
        default=NotificationPriority.MEDIUM,
    )
    channels = models.JSONField(default=list)
    group_key_template = models.CharField(max_length=255, blank=True)
    deduplication_window_minutes = models.PositiveIntegerField(default=60)
    frequency_limit = models.PositiveIntegerField(default=20)
    frequency_window_minutes = models.PositiveIntegerField(default=60)
    digest = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="uniq_alert_rule_name")
        ]


class AlertEvent(WorkspaceScopedModel):
    rule = models.ForeignKey(AlertRule, on_delete=models.PROTECT, related_name="events")
    event_type = models.SlugField(max_length=100)
    resource_type = models.SlugField(max_length=100, blank=True)
    resource_id = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict)
    group_key = models.CharField(max_length=255, blank=True)
    deduplication_key = models.CharField(max_length=255)
    suppressed = models.BooleanField(default=False)
    suppression_reason = models.CharField(max_length=100, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["workspace", "deduplication_key", "created_at"],
                name="notification_dedup_idx",
            )
        ]


class NotificationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DELIVERED = "delivered", "Delivered"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    FAILED = "failed", "Failed"
    SUPPRESSED = "suppressed", "Suppressed"


class Notification(WorkspaceScopedModel):
    event = models.ForeignKey(AlertEvent, on_delete=models.CASCADE, related_name="notifications")
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    title = models.CharField(max_length=255)
    body = models.TextField()
    priority = models.CharField(max_length=20, choices=NotificationPriority.choices)
    status = models.CharField(
        max_length=20, choices=NotificationStatus.choices, default=NotificationStatus.PENDING
    )
    requires_acknowledgement = models.BooleanField(default=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    grouped_count = models.PositiveIntegerField(default=1)
    digest_eligible = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]


class DeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DEFERRED = "deferred", "Deferred"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"


class DeliveryAttempt(WorkspaceScopedModel):
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="delivery_attempts"
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE
    )
    channel = models.CharField(max_length=20, choices=DeliveryChannel.choices)
    status = models.CharField(
        max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    attempt_number = models.PositiveSmallIntegerField(default=1)
    adapter = models.CharField(max_length=100, blank=True)
    external_id = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["notification", "channel", "attempt_number"],
                name="uniq_delivery_attempt",
            )
        ]


class UserPreference(WorkspaceScopedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    channel = models.CharField(max_length=20, choices=DeliveryChannel.choices)
    enabled = models.BooleanField(default=True)
    minimum_priority = models.CharField(
        max_length=20,
        choices=NotificationPriority.choices,
        default=NotificationPriority.INFORMATIONAL,
    )
    destination = models.CharField(max_length=500, blank=True)
    digest = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user", "channel"], name="uniq_user_channel_preference"
            )
        ]


class QuietHours(WorkspaceScopedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    timezone = models.CharField(max_length=100, default="UTC")
    start_time = models.TimeField()
    end_time = models.TimeField()
    weekdays = models.JSONField(default=all_weekdays)
    enabled = models.BooleanField(default=True)
    allow_critical = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"], name="uniq_workspace_user_quiet_hours"
            )
        ]


class EscalationPolicy(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    rule = models.ForeignKey(AlertRule, null=True, blank=True, on_delete=models.CASCADE)
    priority = models.CharField(
        max_length=20, choices=NotificationPriority.choices, default=NotificationPriority.CRITICAL
    )
    acknowledge_within_minutes = models.PositiveIntegerField(default=15)
    escalate_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    channels = models.JSONField(default=list)
    enabled = models.BooleanField(default=True)


class EscalationHistory(WorkspaceScopedModel):
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="escalation_history"
    )
    policy = models.ForeignKey(EscalationPolicy, on_delete=models.PROTECT)
    escalated_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=255)


class NotificationMetric(WorkspaceScopedModel):
    rule = models.ForeignKey(AlertRule, null=True, blank=True, on_delete=models.SET_NULL)
    metric_key = models.SlugField(max_length=100)
    value = models.DecimalField(max_digits=14, decimal_places=4)
    measured_at = models.DateTimeField()
    metadata = models.JSONField(default=dict, blank=True)
