from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from .models import DeliveryAttempt, DeliveryStatus
from .services import deliver, escalate_unacknowledged, send_daily_digests


@shared_task(name="notifications.dispatch_due_deliveries")
def dispatch_due_deliveries() -> int:
    now = timezone.now()
    attempts = DeliveryAttempt.objects.filter(
        status__in=[DeliveryStatus.PENDING, DeliveryStatus.DEFERRED]
    ).filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
    delivered = 0
    for attempt in attempts.select_related("notification__recipient")[:500]:
        if deliver(attempt, now=now).status == DeliveryStatus.DELIVERED:
            delivered += 1
    return delivered


@shared_task(name="notifications.escalate_unacknowledged")
def escalate_notifications() -> int:
    return len(escalate_unacknowledged())


@shared_task(name="notifications.send_daily_digests")
def daily_notification_digests() -> int:
    return send_daily_digests()
