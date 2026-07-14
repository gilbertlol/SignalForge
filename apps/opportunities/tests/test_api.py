import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.factories import UserFactory
from apps.core.services import get_default_workspace
from apps.opportunities.tests.factories import OpportunityFactory
from apps.organizations.tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    client = APIClient()
    client.force_authenticate(user=UserFactory())
    return client


def test_create_opportunity_via_api(api_client):
    org = OrganizationFactory(workspace=get_default_workspace())

    response = api_client.post(
        "/api/v1/opportunities/",
        {"organization": str(org.id), "title": "Q3 outbound"},
    )

    assert response.status_code == 201
    assert response.data["status"] == "identified"
    assert response.data["contacted"] is False


def test_filter_opportunities_by_status(api_client):
    workspace = get_default_workspace()
    OpportunityFactory(workspace=workspace, status="identified")
    OpportunityFactory(workspace=workspace, status="won")

    response = api_client.get("/api/v1/opportunities/", {"status": "won"})

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["status"] == "won"
