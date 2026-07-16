from datetime import UTC, datetime, time, timedelta

import pytest
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.notifications.models import (
    AlertEvent,
    AlertRule,
    DeliveryChannel,
    DeliveryStatus,
    EscalationHistory,
    EscalationPolicy,
    NotificationPriority,
    NotificationStatus,
    QuietHours,
    UserPreference,
)
from apps.notifications.services import (
    DELIVERY_ADAPTERS,
    NotificationPolicyError,
    acknowledge,
    deliver,
    emit_alert,
    escalate_unacknowledged,
    retry_delivery,
    rule_matches,
    send_daily_digests,
)

pytestmark = pytest.mark.django_db


def make_rule(workspace, **overrides):
    values = {
        "name": "High-value lead",
        "event_type": "lead.qualified",
        "conditions": {"score": {"gte": 80}},
        "priority": NotificationPriority.HIGH,
        "channels": [DeliveryChannel.IN_APP],
    }
    values.update(overrides)
    return AlertRule.objects.create(workspace=workspace, **values)


def test_data_driven_rule_conditions():
    user = UserFactory()
    rule = make_rule(user.memberships.get().workspace)

    assert rule_matches(rule, {"score": 90}) is True
    assert rule_matches(rule, {"score": 70}) is False


def test_duplicate_alert_is_grouped_and_suppressed():
    user = UserFactory()
    workspace = user.memberships.get().workspace
    rule = make_rule(workspace)

    first = emit_alert(
        rule=rule,
        recipient=user,
        payload={"score": 90},
        title="Acme qualified",
        body="Strong signal",
        deduplication_key="acme-qualified",
    )
    second = emit_alert(
        rule=rule,
        recipient=user,
        payload={"score": 91},
        title="Acme qualified again",
        body="Another signal",
        deduplication_key="acme-qualified",
    )

    first.refresh_from_db()
    assert second == first
    assert first.grouped_count == 2
    assert AlertEvent.objects.filter(suppressed=True, suppression_reason="duplicate").count() == 1


def test_quiet_hours_defer_noncritical_delivery():
    user = UserFactory()
    workspace = user.memberships.get().workspace
    rule = make_rule(workspace)
    QuietHours.objects.create(
        workspace=workspace,
        user=user,
        timezone="UTC",
        start_time=time(22),
        end_time=time(7),
    )

    notification = emit_alert(
        rule=rule,
        recipient=user,
        payload={"score": 90},
        title="Late signal",
        body="Wait until morning",
        deduplication_key="late-signal",
        at=datetime(2026, 7, 16, 23, tzinfo=UTC),
    )

    attempt = notification.delivery_attempts.get()
    assert attempt.status == DeliveryStatus.DEFERRED
    assert attempt.next_attempt_at == datetime(2026, 7, 17, 7, tzinfo=UTC)


def test_failed_delivery_can_be_retried(monkeypatch):
    user = UserFactory()
    workspace = user.memberships.get().workspace
    rule = make_rule(workspace)
    notification = emit_alert(
        rule=rule,
        recipient=user,
        payload={"score": 90},
        title="Signal",
        body="Delivery boundary",
        deduplication_key="delivery-test",
    )
    attempt = notification.delivery_attempts.get()

    def broken(_attempt):
        raise RuntimeError("adapter offline")

    monkeypatch.setitem(DELIVERY_ADAPTERS, DeliveryChannel.IN_APP, broken)
    deliver(attempt)
    retry = retry_delivery(attempt)

    assert attempt.status == DeliveryStatus.FAILED
    assert attempt.error == "adapter offline"
    assert retry.attempt_number == 2
    assert retry.status == DeliveryStatus.PENDING


def test_critical_notification_escalates_once_when_unacknowledged():
    recipient = UserFactory()
    workspace = recipient.memberships.get().workspace
    manager = UserFactory(workspace_membership=workspace)
    rule = make_rule(
        workspace, priority=NotificationPriority.CRITICAL, conditions={}, name="Critical risk"
    )
    notification = emit_alert(
        rule=rule,
        recipient=recipient,
        payload={},
        title="Critical risk",
        body="Acknowledge this",
        deduplication_key="critical-risk",
    )
    notification.created_at = timezone.now() - timedelta(minutes=20)
    notification.save(update_fields=["created_at"])
    EscalationPolicy.objects.create(
        workspace=workspace,
        name="Critical escalation",
        rule=rule,
        escalate_to=manager,
        acknowledge_within_minutes=15,
    )

    assert escalate_unacknowledged() == [notification]
    assert escalate_unacknowledged() == []
    assert EscalationHistory.objects.filter(notification=notification).count() == 1
    assert notification.delivery_attempts.filter(recipient=manager).exists()


def test_only_recipient_can_acknowledge():
    recipient = UserFactory()
    workspace = recipient.memberships.get().workspace
    other = UserFactory(workspace_membership=workspace)
    rule = make_rule(workspace, priority=NotificationPriority.CRITICAL, conditions={})
    notification = emit_alert(
        rule=rule,
        recipient=recipient,
        payload={},
        title="Critical",
        body="Decision required",
        deduplication_key="recipient-only",
    )

    with pytest.raises(NotificationPolicyError):
        acknowledge(notification, user=other)
    acknowledge(notification, user=recipient)

    assert notification.status == NotificationStatus.ACKNOWLEDGED


def test_daily_digest_groups_eligible_notifications(mailoutbox):
    user = UserFactory()
    workspace = user.memberships.get().workspace
    UserPreference.objects.create(
        workspace=workspace,
        user=user,
        channel=DeliveryChannel.EMAIL,
        digest=True,
        destination="digest@example.com",
    )
    rule = make_rule(
        workspace,
        conditions={},
        channels=[DeliveryChannel.IN_APP],
        digest=True,
        name="Digest rule",
    )
    for index in range(2):
        emit_alert(
            rule=rule,
            recipient=user,
            payload={},
            title=f"Digest alert {index}",
            body="Summary",
            deduplication_key=f"digest-{index}",
        )

    assert send_daily_digests() == 1
    assert len(mailoutbox) == 1
    assert "2 alerts" in mailoutbox[0].subject
