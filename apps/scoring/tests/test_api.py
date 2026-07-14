import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.factories import UserFactory
from apps.core.services import get_default_workspace
from apps.organizations.tests.factories import OrganizationFactory
from apps.scoring.models import ScoreFamily
from apps.scoring.tests.factories import ScoringRuleFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    client = APIClient()
    client.force_authenticate(user=UserFactory())
    return client


def test_explain_before_any_score_is_computed_returns_404(api_client):
    org = OrganizationFactory(workspace=get_default_workspace())

    response = api_client.get(
        f"/api/v1/organizations/{org.id}/scores/{ScoreFamily.PROSPECT_QUALITY}/explain/"
    )

    assert response.status_code == 404


def test_recompute_then_explain_round_trip(api_client):
    workspace = get_default_workspace()
    org = OrganizationFactory(workspace=workspace, domain="acme.com")
    ScoringRuleFactory(
        workspace=workspace,
        family=ScoreFamily.PROSPECT_QUALITY,
        key="has_domain",
        points=15,
        conditions={"field": "domain", "op": "neq", "value": ""},
    )

    recompute_response = api_client.post(
        f"/api/v1/organizations/{org.id}/scores/{ScoreFamily.PROSPECT_QUALITY}/recompute/"
    )
    assert recompute_response.status_code == 201
    assert recompute_response.data["value"] == 15

    explain_response = api_client.get(
        f"/api/v1/organizations/{org.id}/scores/{ScoreFamily.PROSPECT_QUALITY}/explain/"
    )
    assert explain_response.status_code == 200
    assert explain_response.data == recompute_response.data


def test_unknown_family_returns_400(api_client):
    org = OrganizationFactory(workspace=get_default_workspace())

    response = api_client.post(f"/api/v1/organizations/{org.id}/scores/not_a_family/recompute/")

    assert response.status_code == 400
