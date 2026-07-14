import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


def test_ping_is_publicly_reachable(api_client):
    response = api_client.get("/api/v1/ping/")

    assert response.status_code == 200
    assert response.json() == {"service": "signalforge", "status": "ok"}
