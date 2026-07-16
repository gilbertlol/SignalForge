from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import record

from .models import (
    AlertEvent,
    AlertRule,
    DeliveryAttempt,
    DeliveryChannel,
    DeliveryStatus,
    EscalationHistory,
    EscalationPolicy,
    Notification,
    NotificationPriority,
    NotificationStatus,
    QuietHours,
    UserPreference,
)


class NotificationPolicyError(ValueError):
    pass


PRIORITY_RANK = {
    NotificationPriority.INFORMATIONAL: 0,
    NotificationPriority.LOW: 1,
    NotificationPriority.MEDIUM: 2,
    NotificationPriority.HIGH: 3,
    NotificationPriority.CRITICAL: 4,
}


def rule_matches(rule: AlertRule, payload: dict) -> bool:
    """Evaluate a small, data-driven condition language against an event payload."""
    for field, expected in rule.conditions.items():
        actual = payload.get(field)
        if isinstance(expected, dict):
            if "eq" in expected and actual != expected["eq"]:
                return False
            if "in" in expected and actual not in expected["in"]:
                return False
            if "gte" in expected and (actual is None or actual < expected["gte"]):
                return False
            if "lte" in expected and (actual is None or actual > expected["lte"]):
                return False
        elif actual != expected:
            return False
    return True


def _render_group_key(rule: AlertRule, payload: dict) -> str:
    if not rule.group_key_template:
        return ""
    try:
        return rule.group_key_template.format_map(payload)
    except KeyError as exc:
        raise NotificationPolicyError(f"Missing group key field: {exc.args[0]}") from exc


def _is_quiet(preference: QuietHours | None, at: datetime, priority: str) -> bool:
    if not preference or not preference.enabled:
        return False
    if priority == NotificationPriority.CRITICAL and preference.allow_critical:
        return False
    try:
        local = at.astimezone(ZoneInfo(preference.timezone))
    except ZoneInfoNotFoundError as exc:
        raise NotificationPolicyError("Quiet-hours timezone is invalid") from exc
    if local.weekday() not in preference.weekdays:
        return False
    if preference.start_time <= preference.end_time:
        return preference.start_time <= local.time() < preference.end_time
    return local.time() >= preference.start_time or local.time() < preference.end_time


def _eligible_channels(rule: AlertRule, recipient: User) -> list[str]:
    configured = list(rule.channels or [DeliveryChannel.IN_APP])
    preferences = {
        item.channel: item
        for item in UserPreference.objects.filter(
            workspace=rule.workspace, user=recipient, channel__in=configured
        )
    }
    eligible = []
    for channel in configured:
        preference = preferences.get(channel)
        if preference and (
            not preference.enabled
            or PRIORITY_RANK[rule.priority] < PRIORITY_RANK[preference.minimum_priority]
        ):
            continue
        eligible.append(channel)
    return eligible


@transaction.atomic
def emit_alert(
    *,
    rule: AlertRule,
    recipient: User,
    payload: dict,
    title: str,
    body: str,
    resource_type: str = "",
    resource_id: str = "",
    deduplication_key: str,
    at: datetime | None = None,
) -> Notification | None:
    if not rule.enabled or not rule_matches(rule, payload):
        return None
    if not recipient.memberships.filter(workspace=rule.workspace, is_active=True).exists():
        raise NotificationPolicyError("Recipient does not belong to this workspace")
    at = at or timezone.now()
    window_start = at - timedelta(minutes=rule.deduplication_window_minutes)
    duplicate = AlertEvent.objects.filter(
        workspace=rule.workspace,
        rule=rule,
        deduplication_key=deduplication_key,
        created_at__gte=window_start,
        suppressed=False,
    ).first()
    if duplicate:
        notification = duplicate.notifications.filter(recipient=recipient).first()
        if notification:
            notification.grouped_count += 1
            notification.save(update_fields=["grouped_count", "updated_at"])
        AlertEvent.objects.create(
            workspace=rule.workspace,
            rule=rule,
            event_type=rule.event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
            group_key=_render_group_key(rule, payload),
            deduplication_key=deduplication_key,
            suppressed=True,
            suppression_reason="duplicate",
        )
        return notification

    frequency_start = at - timedelta(minutes=rule.frequency_window_minutes)
    recent_count = AlertEvent.objects.filter(
        workspace=rule.workspace,
        rule=rule,
        created_at__gte=frequency_start,
        suppressed=False,
    ).count()
    suppressed = recent_count >= rule.frequency_limit
    event = AlertEvent.objects.create(
        workspace=rule.workspace,
        rule=rule,
        event_type=rule.event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload,
        group_key=_render_group_key(rule, payload),
        deduplication_key=deduplication_key,
        suppressed=suppressed,
        suppression_reason="frequency_limit" if suppressed else "",
    )
    if suppressed:
        return None

    notification = Notification.objects.create(
        workspace=rule.workspace,
        event=event,
        recipient=recipient,
        title=title,
        body=body,
        priority=rule.priority,
        requires_acknowledgement=rule.priority == NotificationPriority.CRITICAL,
        digest_eligible=rule.digest,
    )
    quiet_hours = QuietHours.objects.filter(workspace=rule.workspace, user=recipient).first()
    for channel in _eligible_channels(rule, recipient):
        quiet = _is_quiet(quiet_hours, at, rule.priority)
        DeliveryAttempt.objects.create(
            workspace=rule.workspace,
            notification=notification,
            channel=channel,
            status=DeliveryStatus.DEFERRED if quiet else DeliveryStatus.PENDING,
            next_attempt_at=quiet_hours_end(quiet_hours, at) if quiet else None,
        )
    record(
        "notification.created",
        object_type="notifications.Notification",
        object_id=str(notification.pk),
        metadata={"rule": str(rule.pk), "priority": rule.priority},
    )
    return notification


def quiet_hours_end(preference: QuietHours | None, at: datetime) -> datetime:
    if preference is None:
        return at
    local = at.astimezone(ZoneInfo(preference.timezone))
    end = datetime.combine(local.date(), preference.end_time, tzinfo=local.tzinfo)
    if end <= local:
        end += timedelta(days=1)
    return end.astimezone(UTC)


@dataclass
class DeliveryResult:
    external_id: str = ""


DeliveryAdapter = Callable[[DeliveryAttempt], DeliveryResult]


def _deliver_in_app(attempt: DeliveryAttempt) -> DeliveryResult:
    return DeliveryResult(external_id=str(attempt.notification_id))


def _deliver_email(attempt: DeliveryAttempt) -> DeliveryResult:
    notification = attempt.notification
    recipient = attempt.recipient or notification.recipient
    send_mail(
        notification.title,
        notification.body,
        None,
        [recipient.email],
        fail_silently=False,
    )
    return DeliveryResult()


DELIVERY_ADAPTERS: dict[str, DeliveryAdapter] = {
    DeliveryChannel.IN_APP: _deliver_in_app,
    DeliveryChannel.EMAIL: _deliver_email,
}


def register_delivery_adapter(channel: str, adapter: DeliveryAdapter) -> None:
    DELIVERY_ADAPTERS[channel] = adapter


def deliver(attempt: DeliveryAttempt, *, now: datetime | None = None) -> DeliveryAttempt:
    now = now or timezone.now()
    if attempt.status == DeliveryStatus.DELIVERED:
        return attempt
    if attempt.next_attempt_at and attempt.next_attempt_at > now:
        return attempt
    adapter = DELIVERY_ADAPTERS.get(attempt.channel)
    if adapter is None:
        attempt.status = DeliveryStatus.FAILED
        attempt.error = f"No delivery adapter registered for {attempt.channel}"
    else:
        try:
            result = adapter(attempt)
        except Exception as exc:  # adapters are external boundaries
            attempt.status = DeliveryStatus.FAILED
            attempt.error = str(exc)
            attempt.next_attempt_at = now + timedelta(minutes=min(60, 2**attempt.attempt_number))
        else:
            attempt.status = DeliveryStatus.DELIVERED
            attempt.external_id = result.external_id
            attempt.adapter = f"{adapter.__module__}.{adapter.__name__}"
            attempt.delivered_at = now
            attempt.error = ""
    attempt.save()
    notification = attempt.notification
    pending_channels = set(
        notification.delivery_attempts.exclude(status=DeliveryStatus.DELIVERED).values_list(
            "channel", flat=True
        )
    ) - set(
        notification.delivery_attempts.filter(status=DeliveryStatus.DELIVERED).values_list(
            "channel", flat=True
        )
    )
    if not pending_channels:
        attempt.notification.status = NotificationStatus.DELIVERED
        attempt.notification.save(update_fields=["status", "updated_at"])
    elif attempt.status == DeliveryStatus.FAILED:
        notification.status = NotificationStatus.FAILED
        notification.save(update_fields=["status", "updated_at"])
    return attempt


def retry_delivery(attempt: DeliveryAttempt) -> DeliveryAttempt:
    if attempt.status != DeliveryStatus.FAILED:
        raise NotificationPolicyError("Only failed deliveries can be retried")
    return DeliveryAttempt.objects.create(
        workspace=attempt.workspace,
        notification=attempt.notification,
        channel=attempt.channel,
        attempt_number=attempt.attempt_number + 1,
    )


def acknowledge(notification: Notification, *, user: User) -> Notification:
    allowed = (
        notification.recipient_id == user.pk
        or notification.escalation_history.filter(escalated_to=user).exists()
    )
    if not allowed:
        raise NotificationPolicyError("Only a recipient can acknowledge this notification")
    notification.status = NotificationStatus.ACKNOWLEDGED
    notification.acknowledged_at = timezone.now()
    notification.read_at = notification.read_at or notification.acknowledged_at
    notification.save(update_fields=["status", "acknowledged_at", "read_at", "updated_at"])
    return notification


def escalate_unacknowledged(*, now: datetime | None = None) -> list[Notification]:
    now = now or timezone.now()
    escalated = []
    for policy in EscalationPolicy.objects.filter(enabled=True).select_related("escalate_to"):
        cutoff = now - timedelta(minutes=policy.acknowledge_within_minutes)
        notifications = Notification.objects.filter(
            workspace=policy.workspace,
            priority=policy.priority,
            requires_acknowledgement=True,
            acknowledged_at__isnull=True,
            created_at__lte=cutoff,
        )
        if policy.rule_id:
            notifications = notifications.filter(event__rule=policy.rule)
        for notification in notifications.exclude(escalation_history__policy=policy):
            history = EscalationHistory.objects.create(
                workspace=notification.workspace,
                notification=notification,
                policy=policy,
                escalated_to=policy.escalate_to,
                reason="Acknowledgement deadline exceeded",
            )
            for channel in policy.channels or [DeliveryChannel.IN_APP]:
                DeliveryAttempt.objects.create(
                    workspace=notification.workspace,
                    notification=notification,
                    recipient=policy.escalate_to,
                    channel=channel,
                    attempt_number=notification.delivery_attempts.filter(channel=channel).count()
                    + 1,
                )
            record(
                "notification.escalated",
                actor=policy.escalate_to,
                object_type="notifications.EscalationHistory",
                object_id=str(history.pk),
            )
            escalated.append(notification)
    return escalated


def notification_metrics(workspace) -> dict:
    delivered = DeliveryAttempt.objects.filter(workspace=workspace, status=DeliveryStatus.DELIVERED)
    failed = DeliveryAttempt.objects.filter(workspace=workspace, status=DeliveryStatus.FAILED)
    noisy = (
        AlertEvent.objects.filter(workspace=workspace, suppressed=True)
        .values("rule__name")
        .annotate(count=Count("id"))
        .order_by("-count")[:5]
    )
    acknowledgement_seconds = [
        (item.acknowledged_at - item.created_at).total_seconds()
        for item in Notification.objects.filter(
            workspace=workspace, acknowledged_at__isnull=False
        ).only("created_at", "acknowledged_at")
    ]
    return {
        "volume": Notification.objects.filter(workspace=workspace).count(),
        "delivery_failures": failed.count(),
        "delivered": delivered.count(),
        "noisy_rules": list(noisy),
        "acknowledged": Notification.objects.filter(
            workspace=workspace, acknowledged_at__isnull=False
        ).count(),
        "average_acknowledgement_seconds": (
            sum(acknowledgement_seconds) / len(acknowledgement_seconds)
            if acknowledgement_seconds
            else None
        ),
    }


def send_daily_digests() -> int:
    sent = 0
    preferences = UserPreference.objects.filter(
        enabled=True, digest=True, channel=DeliveryChannel.EMAIL
    ).select_related("user", "workspace")
    for preference in preferences:
        notifications = list(
            Notification.objects.filter(
                workspace=preference.workspace,
                recipient=preference.user,
                digest_eligible=True,
                status=NotificationStatus.PENDING,
            ).order_by("created_at")
        )
        if not notifications:
            continue
        lines = [f"- [{item.get_priority_display()}] {item.title}" for item in notifications]
        send_mail(
            f"SignalForge daily digest — {len(notifications)} alerts",
            "\n".join(lines),
            None,
            [preference.destination or preference.user.email],
            fail_silently=False,
        )
        now = timezone.now()
        for notification in notifications:
            attempt_number = (
                notification.delivery_attempts.filter(channel=DeliveryChannel.EMAIL).count() + 1
            )
            DeliveryAttempt.objects.create(
                workspace=preference.workspace,
                notification=notification,
                channel=DeliveryChannel.EMAIL,
                status=DeliveryStatus.DELIVERED,
                attempt_number=attempt_number,
                adapter="daily_digest",
                delivered_at=now,
            )
            notification.status = NotificationStatus.DELIVERED
            notification.save(update_fields=["status", "updated_at"])
        sent += 1
    return sent
