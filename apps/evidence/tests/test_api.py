import datetime

import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.factories import UserFactory
from apps.core.services import get_default_workspace
from apps.organizations.tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    client = APIClient()
    client.force_authenticate(user=UserFactory())
    return client


def test_create_and_list_evidence_for_an_organization(api_client):
    org = OrganizationFactory(workspace=get_default_workspace())

    create_response = api_client.post(
        f"/api/v1/organizations/{org.id}/evidence/",
        {
            "source_type": "news",
            "observed_date": str(datetime.date.today()),
            "excerpt": "Raised a Series A.",
            "reliability": "high",
        },
    )
    assert create_response.status_code == 201
    assert create_response.data["age_days"] == 0

    list_response = api_client.get(f"/api/v1/organizations/{org.id}/evidence/")
    assert list_response.status_code == 200
    assert list_response.data["count"] == 1
