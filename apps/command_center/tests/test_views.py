from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.accounts.models import AccessPermission
from apps.accounts.tests.factories import UserFactory
from apps.core.models import Workspace
from apps.hunting.models import HuntProfile
from apps.opportunities.tests.factories import OpportunityFactory
from apps.organizations.tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


def test_command_center_requires_login(client):
    response = client.get(reverse("command_center:dashboard"))

    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")


def test_command_center_renders_operational_summary(client):
    user = UserFactory()
    workspace = user.memberships.get().workspace
    OrganizationFactory(workspace=workspace, name="Visible Company")
    client.force_login(user)

    response = client.get(reverse("command_center:dashboard"))

    assert response.status_code == 200
    assert response.context["organization_count"] == 1
    assert b"Command center" in response.content


def test_organization_detail_cannot_cross_workspace(client):
    user = UserFactory()
    forbidden_workspace = Workspace.objects.create(name="Forbidden", slug="forbidden-ui")
    secret = OrganizationFactory(workspace=forbidden_workspace)
    client.force_login(user)

    response = client.get(reverse("command_center:organization-detail", kwargs={"pk": secret.pk}))

    assert response.status_code == 404


def test_inbox_requires_communications_permission(client):
    user = UserFactory()
    client.force_login(user)

    assert client.get(reverse("command_center:inbox")).status_code == 403

    permission, _ = AccessPermission.objects.get_or_create(
        key="communications.access", defaults={"name": "Access communications"}
    )
    user.memberships.get().permission_grants.add(permission)

    assert client.get(reverse("command_center:inbox")).status_code == 200


def test_permission_aware_navigation_hides_inbox(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("command_center:dashboard"))

    assert b"Unified inbox" not in response.content


def test_create_hunt_profile_builds_version_and_activates(client):
    user = UserFactory()
    client.force_login(user)

    response = client.post(
        reverse("command_center:create-hunt-profile"),
        {
            "name": "Toronto agencies",
            "description": "Local automation agencies",
            "require_domain": "on",
            "minimum_score": 12,
            "maximum_records": 20,
            "activate_now": "on",
        },
    )

    assert response.status_code == 302
    profile = HuntProfile.objects.get(name="Toronto agencies")
    assert profile.status == "active"
    assert profile.current_version is not None
    assert profile.current_version.source_policies.get().max_records == 20


@patch("apps.command_center.views.run_discovery_task.delay")
def test_start_discovery_dispatches_workspace_scoped_run(mock_delay, client):
    user = UserFactory()
    client.force_login(user)
    client.post(
        reverse("command_center:create-hunt-profile"),
        {"name": "Runnable", "minimum_score": 1, "maximum_records": 5},
    )
    profile = HuntProfile.objects.get(name="Runnable")

    response = client.post(reverse("command_center:start-discovery", kwargs={"pk": profile.pk}))

    assert response.status_code == 302
    run = profile.current_version.discovery_runs.get()
    assert run.workspace == user.memberships.get().workspace
    mock_delay.assert_called_once_with(str(run.id))


def test_pipeline_status_transition_is_workspace_scoped(client):
    user = UserFactory()
    workspace = user.memberships.get().workspace
    opportunity = OpportunityFactory(workspace=workspace, status="identified")
    client.force_login(user)

    response = client.post(
        reverse("command_center:opportunity-status", kwargs={"pk": opportunity.pk}),
        {"status": "qualified"},
    )

    opportunity.refresh_from_db()
    assert response.status_code == 302
    assert opportunity.status == "qualified"
