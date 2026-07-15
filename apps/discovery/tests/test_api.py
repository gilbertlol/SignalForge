import io

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


def _active_profile_id(api_client):
    org = OrganizationFactory(workspace=get_default_workspace())
    response = api_client.post(
        "/api/v1/hunt-profiles/",
        {
            "name": "API discovery test profile",
            "criteria": {
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
            "result_threshold": {"min_total_score": 0},
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data["id"], org


def test_create_discovery_run_via_api_executes_synchronously_under_eager_celery(api_client):
    profile_id, _org = _active_profile_id(api_client)

    response = api_client.post(
        "/api/v1/discovery-runs/", {"hunt_profile": profile_id}, format="json"
    )

    assert response.status_code == 201, response.data
    assert response.data["status"] == "succeeded"
    assert response.data["records_discovered"] == 5


def test_review_queue_is_source_records_filtered_by_qualified_status(api_client):
    profile_id, _org = _active_profile_id(api_client)
    run_response = api_client.post(
        "/api/v1/discovery-runs/", {"hunt_profile": profile_id}, format="json"
    )
    run_id = run_response.data["id"]

    response = api_client.get(f"/api/v1/discovery-runs/{run_id}/source-records/?status=qualified")

    assert response.status_code == 200
    assert len(response.data) == 5
    assert all(r["status"] == "qualified" for r in response.data)


def test_run_source_scorecards_are_machine_readable(api_client):
    profile_id, _org = _active_profile_id(api_client)
    run_response = api_client.post(
        "/api/v1/discovery-runs/", {"hunt_profile": profile_id}, format="json"
    )

    response = api_client.get(
        f"/api/v1/discovery-runs/{run_response.data['id']}/source-scorecards/"
    )

    assert response.status_code == 200
    assert response.data["scorecards"][0]["source_key"] == "demo"
    assert response.data["scorecards"][0]["sample_warning"]
    assert response.data["recommendation"]["is_directional"] is True


def test_manual_source_record_endpoint(api_client):
    profile_id, _org = _active_profile_id(api_client)
    run_response = api_client.post(
        "/api/v1/discovery-runs/", {"hunt_profile": profile_id}, format="json"
    )
    run_id = run_response.data["id"]

    response = api_client.post(
        f"/api/v1/discovery-runs/{run_id}/source-records/manual/",
        {"name": "Manual Entry Co", "domain": "manualentryco.com"},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["source_key"] == "manual"
    assert response.data["status"] == "normalized"


def test_import_csv_endpoint(api_client):
    profile_id, _org = _active_profile_id(api_client)
    run_response = api_client.post(
        "/api/v1/discovery-runs/", {"hunt_profile": profile_id}, format="json"
    )
    run_id = run_response.data["id"]

    csv_file = io.BytesIO(b"name,domain\nCsv Upload Co,csvuploadco.com\n")
    csv_file.name = "leads.csv"

    response = api_client.post(
        f"/api/v1/discovery-runs/{run_id}/source-records/import-csv/",
        {"file": csv_file},
        format="multipart",
    )

    assert response.status_code == 201, response.data
    assert len(response.data) == 1
    assert response.data[0]["source_key"] == "csv_import"


def test_cancel_rejects_an_already_finished_run(api_client):
    profile_id, _org = _active_profile_id(api_client)
    run_response = api_client.post(
        "/api/v1/discovery-runs/", {"hunt_profile": profile_id}, format="json"
    )
    run_id = run_response.data["id"]
    assert run_response.data["status"] == "succeeded"

    cancel_response = api_client.post(f"/api/v1/discovery-runs/{run_id}/cancel/")

    assert cancel_response.status_code == 400


def test_retry_on_a_succeeded_run_is_idempotent(api_client):
    profile_id, _org = _active_profile_id(api_client)
    run_response = api_client.post(
        "/api/v1/discovery-runs/", {"hunt_profile": profile_id}, format="json"
    )
    run_id = run_response.data["id"]

    retry_response = api_client.post(f"/api/v1/discovery-runs/{run_id}/retry/")

    assert retry_response.status_code == 200
    assert retry_response.data["status"] == "succeeded"
    assert retry_response.data["records_discovered"] == 5
