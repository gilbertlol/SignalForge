import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.factories import UserFactory
from apps.contacts.models import Contact

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    client = APIClient()
    client.force_authenticate(user=UserFactory())
    return client


def test_create_contact_via_api(api_client):
    response = api_client.post(
        "/api/v1/contacts/",
        {"first_name": "Jamie", "last_name": "Rivera", "email": "Jamie@Example.com"},
    )

    assert response.status_code == 201
    assert response.data["dedupe_key"] == "jamie@example.com"


def test_create_contact_is_dedup_aware_on_email(api_client):
    api_client.post("/api/v1/contacts/", {"email": "jamie@example.com"})
    api_client.post("/api/v1/contacts/", {"email": "Jamie@Example.com"})

    assert Contact.objects.filter(dedupe_key="jamie@example.com").count() == 1


def test_create_contact_without_email_is_not_deduped(api_client):
    api_client.post("/api/v1/contacts/", {"first_name": "A"})
    api_client.post("/api/v1/contacts/", {"first_name": "B"})

    assert Contact.objects.filter(dedupe_key="").count() == 2
