import pytest
from rest_framework.test import APIClient

from apps.accounts.models import AccessPermission, Role
from apps.accounts.tests.factories import UserFactory
from apps.core.models import Workspace
from apps.notifications.models import Dashboard, DashboardVisibility

pytestmark = pytest.mark.django_db


def grant(user, key):
    permission, _ = AccessPermission.objects.get_or_create(key=key, defaults={"name": key})
    user.memberships.get().permission_grants.add(permission)


def test_dashboard_api_isolates_personal_shared_and_role_defaults():
    user = UserFactory()
    workspace = user.memberships.get().workspace
    grant(user, "prospects.access")
    role = Role.objects.create(workspace=workspace, name="Scout")
    user.memberships.get().roles.add(role)
    other_user = UserFactory(workspace_membership=workspace)
    Dashboard.objects.create(
        workspace=workspace, name="Mine", owner=user, visibility=DashboardVisibility.PERSONAL
    )
    Dashboard.objects.create(
        workspace=workspace,
        name="Private other",
        owner=other_user,
        visibility=DashboardVisibility.PERSONAL,
    )
    Dashboard.objects.create(
        workspace=workspace, name="Shared", visibility=DashboardVisibility.SHARED
    )
    Dashboard.objects.create(
        workspace=workspace,
        name="Scout default",
        role=role,
        visibility=DashboardVisibility.ROLE_DEFAULT,
    )
    foreign_workspace = Workspace.objects.create(name="Foreign", slug="notification-foreign")
    Dashboard.objects.create(
        workspace=foreign_workspace, name="Foreign", visibility=DashboardVisibility.SHARED
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/v1/dashboards/")

    assert response.status_code == 200
    assert {item["name"] for item in response.json()["results"]} == {
        "Mine",
        "Shared",
        "Scout default",
    }


def test_alert_rules_require_settings_permission():
    user = UserFactory()
    client = APIClient()
    client.force_authenticate(user=user)

    assert client.get("/api/v1/alert-rules/").status_code == 403
    grant(user, "settings.manage")
    assert client.get("/api/v1/alert-rules/").status_code == 200


def test_personal_dashboard_owner_cannot_be_spoofed():
    user = UserFactory()
    workspace = user.memberships.get().workspace
    other = UserFactory(workspace_membership=workspace)
    grant(user, "prospects.access")
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/v1/dashboards/",
        {
            "name": "My board",
            "owner": str(other.pk),
            "visibility": DashboardVisibility.PERSONAL,
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["owner"] == str(user.pk)
