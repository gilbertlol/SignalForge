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


_TREE = {
    "type": "group",
    "operator": "AND",
    "children": [
        {
            "type": "criterion",
            "category": "custom_attribute",
            "field": "domain",
            "op": "neq",
            "value": "",
            "weight": 10,
        }
    ],
}


def test_create_hunt_profile_via_api(api_client):
    response = api_client.post(
        "/api/v1/hunt-profiles/",
        {"name": "SaaS companies", "description": "Test thesis", "criteria": _TREE},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["status"] == "draft"
    assert response.data["current_version"]["version_number"] == 1
    assert response.data["current_version"]["criteria"]["operator"] == "AND"


def test_full_lifecycle_create_dry_run_activate_pause_archive_clone(api_client):
    workspace = get_default_workspace()
    org = OrganizationFactory(workspace=workspace, domain="acme.com", name="Acme")

    create_response = api_client.post(
        "/api/v1/hunt-profiles/",
        {"name": "Test profile", "criteria": _TREE},
        format="json",
    )
    assert create_response.status_code == 201
    profile_id = create_response.data["id"]

    dry_run_response = api_client.post(f"/api/v1/hunt-profiles/{profile_id}/dry-run/")
    assert dry_run_response.status_code == 200
    matched_ids = {r["organization_id"] for r in dry_run_response.data["results"] if r["matched"]}
    assert str(org.id) in matched_ids

    activate_response = api_client.post(f"/api/v1/hunt-profiles/{profile_id}/activate/")
    assert activate_response.status_code == 200
    assert activate_response.data["status"] == "active"

    pause_response = api_client.post(f"/api/v1/hunt-profiles/{profile_id}/pause/")
    assert pause_response.data["status"] == "paused"

    archive_response = api_client.post(f"/api/v1/hunt-profiles/{profile_id}/archive/")
    assert archive_response.data["status"] == "archived"

    clone_response = api_client.post(
        f"/api/v1/hunt-profiles/{profile_id}/clone/", {"name": "Cloned profile"}
    )
    assert clone_response.status_code == 201
    assert clone_response.data["status"] == "draft"
    assert clone_response.data["id"] != profile_id


def test_versions_action_lists_and_creates(api_client):
    create_response = api_client.post(
        "/api/v1/hunt-profiles/",
        {"name": "Versioned profile", "criteria": _TREE},
        format="json",
    )
    profile_id = create_response.data["id"]

    list_response = api_client.get(f"/api/v1/hunt-profiles/{profile_id}/versions/")
    assert list_response.status_code == 200
    assert len(list_response.data) == 1

    create_version_response = api_client.post(
        f"/api/v1/hunt-profiles/{profile_id}/versions/",
        {"criteria": {"type": "group", "operator": "OR", "children": _TREE["children"]}},
        format="json",
    )
    assert create_version_response.status_code == 201
    assert create_version_response.data["version_number"] == 2

    list_response_again = api_client.get(f"/api/v1/hunt-profiles/{profile_id}/versions/")
    assert len(list_response_again.data) == 2
