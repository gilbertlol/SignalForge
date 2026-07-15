import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.factories import UserFactory
from apps.discovery.models import SourceRecord
from apps.discovery.tests.factories import DiscoveryRunFactory
from apps.evidence.services import record_organization_claims
from apps.hunting.services import create_version
from apps.hunting.tests.factories import HuntProfileFactory
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


def test_organization_provenance_endpoint_is_read_only_and_attributed(api_client):
    create = api_client.post(
        "/api/v1/organizations/", {"name": "Provenance Co", "domain": "provenance.test"}
    )
    organization = Organization.objects.get(pk=create.data["id"])
    profile = HuntProfileFactory(workspace=organization.workspace)
    version = create_version(
        profile,
        criteria={
            "type": "group",
            "operator": "AND",
            "children": [
                {
                    "type": "criterion",
                    "category": "custom_attribute",
                    "field": "domain",
                    "op": "neq",
                    "value": "",
                }
            ],
        },
    )
    run = DiscoveryRunFactory(workspace=organization.workspace, hunt_profile_version=version)
    record = SourceRecord.objects.create(
        discovery_run=run,
        source_key="registry",
        external_id="registry-1",
        normalized_data={"name": "Provenance Co", "domain": "provenance.test"},
        organization=organization,
    )
    record_organization_claims(record)

    response = api_client.get(f"/api/v1/organizations/{organization.id}/provenance/")

    assert response.status_code == 200
    assert {claim["source_key"] for claim in response.data["claims"]} == {"registry"}
    assert response.data["resolutions"][0]["selected_claim"]["source_key"] == "registry"
