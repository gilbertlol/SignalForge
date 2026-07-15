import logging

from celery import chord, shared_task
from django.utils import timezone

from apps.hunting.models import HuntProfileStatus, ScheduleFrequency, SchedulePolicy

from .models import DiscoveryRun, DiscoveryRunTrigger
from .services import (
    execute_provider_search,
    finalize_run,
    prepare_provider_executions,
    start_run,
)

logger = logging.getLogger(__name__)


@shared_task(name="discovery.run_discovery", acks_late=True)
def run_discovery_task(discovery_run_id: str) -> str:
    run = DiscoveryRun.objects.get(id=discovery_run_id)
    executions = prepare_provider_executions(run)
    if not executions:
        finalize_run(run.id)
        run.refresh_from_db()
        return run.status

    policies = {
        p.source_key: p for p in run.hunt_profile_version.source_policies.filter(is_enabled=True)
    }
    header = []
    for execution in executions:
        if execution.status == "skipped":
            continue
        policy = policies.get(execution.provider_key)
        signature = run_provider_task.s(str(execution.id))
        if policy:
            signature = signature.set(
                soft_time_limit=policy.timeout_seconds,
                time_limit=policy.timeout_seconds + 5,
                priority=max(0, min(9, 9 - min(policy.priority, 9))),
            )
        header.append(signature)
    if header:
        chord(header)(finalize_discovery_task.s(str(run.id)))
    else:
        finalize_run(run.id)
    run.refresh_from_db()
    return run.status


@shared_task(bind=True, name="discovery.run_provider", acks_late=True, max_retries=10)
def run_provider_task(self, provider_result_id: str) -> str:
    execution = execute_provider_search(provider_result_id)
    if self.request.id and execution.celery_task_id != self.request.id:
        execution.celery_task_id = self.request.id
        execution.save(update_fields=["celery_task_id", "updated_at"])
    policy = execution.discovery_run.hunt_profile_version.source_policies.filter(
        source_key=execution.provider_key, is_enabled=True
    ).first()
    if (
        execution.status in {"failed", "rate_limited"}
        and policy
        and execution.attempt_count <= policy.max_retries
    ):
        execution.status = "retrying"
        execution.save(update_fields=["status", "updated_at"])
        raise self.retry(
            countdown=min(60, 2**execution.attempt_count),
            max_retries=policy.max_retries,
        )
    return str(execution.id)


@shared_task(name="discovery.finalize_run", acks_late=True)
def finalize_discovery_task(_provider_result_ids: list[str], discovery_run_id: str) -> str:
    return finalize_run(discovery_run_id).status


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
