from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import AccessPermission
from apps.accounts.tests.factories import UserFactory
from apps.organizations.tests.factories import OrganizationFactory
from apps.risk.models import AcceptancePolicy, ControlType, RiskObservation, RiskProfile
from apps.risk.services import calculate_risk, ensure_categories

pytestmark = pytest.mark.django_db


def grant(user, key):
    permission, _ = AccessPermission.objects.get_or_create(key=key, defaults={"name": key})
    user.memberships.get().permission_grants.add(permission)


def client_for(*permissions):
    user = UserFactory()
    for permission in permissions:
        grant(user, permission)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user, user.memberships.get().workspace


def test_risk_api_requires_permission():
    client, user, _ = client_for()
    assert client.get("/api/v1/risk/profiles/").status_code == 403
    grant(user, "risk.access")
    assert client.get("/api/v1/risk/profiles/").status_code == 200


def test_profile_api_rejects_cross_workspace_relationships():
    client, _, _ = client_for("risk.access")
    foreign = OrganizationFactory()

    response = client.post(
        "/api/v1/risk/profiles/", {"organization": str(foreign.pk)}, format="json"
    )

    assert response.status_code == 400
    assert "workspace" in str(response.json()).lower()


def test_calculate_action_returns_read_only_explainable_snapshot():
    client, _, workspace = client_for("risk.access")
    organization = OrganizationFactory(workspace=workspace)
    profile = RiskProfile.objects.create(workspace=workspace, organization=organization)
    category = ensure_categories(workspace)["payment"]
    RiskObservation.objects.create(
        workspace=workspace,
        profile=profile,
        category=category,
        source="human",
        fact_type="observed",
        source_type="manual_review",
        source_id="payment-call",
        explanation="Client requested unusual payment terms",
        severity=Decimal("80"),
        probability=Decimal("70"),
        impact=Decimal("90"),
        confidence=Decimal("1"),
        observed_at=profile.created_at,
        confirmed=True,
    )

    response = client.post(f"/api/v1/risk/profiles/{profile.pk}/calculate/")

    assert response.status_code == 201
    assert response.json()["category_scores"]["payment"] == "80.00"
    snapshot_id = response.json()["id"]
    assert (
        client.patch(
            f"/api/v1/risk/snapshots/{snapshot_id}/", {"triggered_by": "rewrite"}, format="json"
        ).status_code
        == 405
    )


def test_control_decision_requires_approval_permission():
    client, user, workspace = client_for("risk.access")
    organization = OrganizationFactory(workspace=workspace)
    profile = RiskProfile.objects.create(workspace=workspace, organization=organization)
    category = ensure_categories(workspace)["payment"]
    RiskObservation.objects.create(
        workspace=workspace,
        profile=profile,
        category=category,
        source="human",
        fact_type="observed",
        source_type="manual_review",
        source_id="high-risk",
        explanation="Repeated payment concerns",
        severity=90,
        probability=90,
        impact=90,
        confidence=1,
        observed_at=profile.created_at,
        confirmed=True,
    )
    AcceptancePolicy.objects.create(
        workspace=workspace,
        name="Prepayment",
        category=category,
        threshold=70,
        control_type=ControlType.PREPAYMENT,
    )
    control = calculate_risk(profile, triggered_by="api-test").recommendations.get()

    url = f"/api/v1/risk/controls/{control.pk}/decide/"
    assert client.post(url, {"decision": "accepted"}, format="json").status_code == 403
    grant(user, "approvals.manage")
    response = client.post(url, {"decision": "accepted"}, format="json")
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


def test_portfolio_is_workspace_scoped():
    client, _, workspace = client_for("risk.access")
    visible = OrganizationFactory(workspace=workspace, name="Visible")
    hidden = OrganizationFactory(name="Hidden")
    RiskProfile.objects.create(workspace=workspace, organization=visible)
    RiskProfile.objects.create(workspace=hidden.workspace, organization=hidden)

    response = client.get("/api/v1/risk/portfolio/")

    assert response.status_code == 200
    assert [row["organization"] for row in response.json()] == ["Visible"]
