import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.factories import UserFactory
from apps.organizations.models import Organization

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    client = APIClient()
    client.force_authenticate(user=UserFactory())
    return client


def test_create_organization_via_api(api_client):
    response = api_client.post("/api/v1/organizations/", {"name": "Acme", "domain": "acme.com"})

    assert response.status_code == 201
    assert response.data["dedupe_key"] == "acme.com"


def test_create_organization_is_dedup_aware(api_client):
    api_client.post("/api/v1/organizations/", {"name": "Acme", "domain": "acme.com"})
    api_client.post("/api/v1/organizations/", {"name": "Acme Inc.", "domain": "https://acme.com/"})

    assert Organization.objects.filter(dedupe_key="acme.com").count() == 1


def test_list_organizations_requires_authentication():
    response = APIClient().get("/api/v1/organizations/")

    assert response.status_code == 401 or response.status_code == 403
