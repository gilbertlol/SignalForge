from django.contrib import admin

from .models import (
    AlertEvent,
    AlertRule,
    Dashboard,
    DashboardWidget,
    DeliveryAttempt,
    EscalationHistory,
    EscalationPolicy,
    Notification,
    NotificationMetric,
    QuietHours,
    SavedFilter,
    UserPreference,
)

admin.site.register(
    [
        Dashboard,
        DashboardWidget,
        SavedFilter,
        AlertRule,
        AlertEvent,
        Notification,
        DeliveryAttempt,
        UserPreference,
        QuietHours,
        EscalationPolicy,
        EscalationHistory,
        NotificationMetric,
    ]
)
