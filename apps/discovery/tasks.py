import logging

from celery import shared_task
from django.utils import timezone

from apps.hunting.models import HuntProfileStatus, ScheduleFrequency, SchedulePolicy

from .models import DiscoveryRun, DiscoveryRunTrigger
from .services import execute_run, start_run

logger = logging.getLogger(__name__)


@shared_task(name="discovery.run_discovery")
def run_discovery_task(discovery_run_id: str) -> str:
    run = DiscoveryRun.objects.get(id=discovery_run_id)
    execute_run(run)
    return run.status


@shared_task(name="discovery.dispatch_scheduled_discoveries")
def dispatch_scheduled_discoveries() -> int:
    """Hourly Beat entry: start a scheduled run for any profile whose
    SchedulePolicy calls for a daily run that hasn't started yet today.

    Deliberately a plain DB query on a static hourly schedule rather than
    per-profile dynamic Celery Beat entries (which would need the
    django-celery-beat package) — one query does the same job.
    """
    today = timezone.now().date()
    dispatched = 0
    policies = SchedulePolicy.objects.filter(
        is_enabled=True, frequency=ScheduleFrequency.DAILY
    ).select_related("profile")
    for policy in policies:
        profile = policy.profile
        version = profile.current_version
        if profile.status != HuntProfileStatus.ACTIVE or version is None:
            continue
        already_ran_today = DiscoveryRun.objects.filter(
            hunt_profile_version__profile=profile,
            trigger=DiscoveryRunTrigger.SCHEDULED,
            created_at__date=today,
        ).exists()
        if already_ran_today:
            continue
        run = start_run(version, trigger=DiscoveryRunTrigger.SCHEDULED)
        run_discovery_task.delay(str(run.id))
        dispatched += 1
        logger.info("Dispatched scheduled discovery run", extra={"discovery_run_id": str(run.id)})
    return dispatched
