"""Liveness and readiness endpoints.

Responses intentionally contain only a status keyword per check — never
exception text, stack traces, or configuration values — so they are safe
to expose to orchestrators without leaking internals.
"""

import logging

import redis
from django.conf import settings
from django.db import connection
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
def live(request):
    """Confirms the application process is alive. Checks no dependencies."""
    return JsonResponse({"status": "ok"})


@require_GET
def ready(request):
    """Confirms the dependencies required to serve traffic are reachable."""
    checks: dict[str, str] = {}
    healthy = True

    try:
        connection.ensure_connection()
        checks["database"] = "ok"
    except OperationalError:
        logger.exception("Readiness check: database unavailable")
        checks["database"] = "unavailable"
        healthy = False

    try:
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        client.ping()
        checks["redis"] = "ok"
    except redis.RedisError:
        logger.exception("Readiness check: redis unavailable")
        checks["redis"] = "unavailable"
        healthy = False

    status_code = 200 if healthy else 503
    payload = {"status": "ok" if healthy else "unavailable", "checks": checks}
    return JsonResponse(payload, status=status_code)
