from unittest.mock import patch

import pytest
import redis
from django.db.utils import OperationalError
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_live_is_always_ok(client):
    response = client.get(reverse("health:live"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_ok_when_dependencies_are_healthy(client):
    with patch("apps.core.health.views.redis.Redis.from_url") as mock_redis:
        mock_redis.return_value.ping.return_value = True
        response = client.get(reverse("health:ready"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok", "redis": "ok"}


def test_ready_reports_503_when_database_unavailable(client):
    with (
        patch(
            "apps.core.health.views.connection.ensure_connection",
            side_effect=OperationalError("connection refused"),
        ),
        patch("apps.core.health.views.redis.Redis.from_url") as mock_redis,
    ):
        mock_redis.return_value.ping.return_value = True
        response = client.get(reverse("health:ready"))

    assert response.status_code == 503
    body = response.json()
    assert body["checks"]["database"] == "unavailable"
    assert "connection refused" not in response.content.decode()


def test_ready_reports_503_when_redis_unavailable(client):
    with patch(
        "apps.core.health.views.redis.Redis.from_url",
        side_effect=redis.ConnectionError("boom"),
    ):
        response = client.get(reverse("health:ready"))

    assert response.status_code == 503
    body = response.json()
    assert body["checks"]["redis"] == "unavailable"
    assert "boom" not in response.content.decode()
