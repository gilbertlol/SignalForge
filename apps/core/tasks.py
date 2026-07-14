import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="core.debug_task")
def debug_task() -> str:
    """Trivial task proving Celery app wiring (broker, worker, serialization)."""
    logger.info("debug_task executed")
    return "pong"
