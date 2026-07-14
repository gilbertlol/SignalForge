from unittest.mock import patch

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import AccessPermission
from apps.accounts.tests.factories import UserFactory
from apps.core.models import Workspace
from apps.hunting.models import HuntProfile
from apps.integrations.models import (
    AIEndpoint,
    AIProvider,
    CredentialReference,
    ProviderHealthCheck,
)
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


def grant_provider_management(user):
    permission, _ = AccessPermission.objects.get_or_create(
        key="providers.manage", defaults={"name": "Manage providers"}
    )
    user.memberships.get().permission_grants.add(permission)


@override_settings(SIGNALFORGE_CREDENTIAL_KEY="command-center-test-key-at-least-32-characters")
def test_provider_workspace_encrypts_and_never_renders_secret(client):
    user = UserFactory()
    grant_provider_management(user)
    client.force_login(user)

    response = client.post(
        reverse("command_center:create-credential"),
        {"name": "Cloud API", "secret": "never-render-this-secret"},
        follow=True,
    )

    credential = CredentialReference.objects.get(name="Cloud API")
    assert response.status_code == 200
    assert "never-render-this-secret" not in response.content.decode()
    assert "never-render-this-secret" not in credential.encrypted_value
    assert credential.get_secret() == "never-render-this-secret"


def test_endpoint_creation_rejects_cross_workspace_provider(client):
    user = UserFactory()
    grant_provider_management(user)
    other_workspace = Workspace.objects.create(name="Foreign AI", slug="foreign-ai")
    provider = AIProvider.objects.create(
        workspace=other_workspace,
        name="Foreign",
        provider_key="foreign",
        provider_type="mock",
    )
    client.force_login(user)

    response = client.post(
        reverse("command_center:create-endpoint"),
        {
            "provider": provider.id,
            "name": "Cross workspace",
            "timeout_seconds": 30,
            "privacy_class": "local_only",
        },
    )

    assert response.status_code == 404
    assert not AIEndpoint.objects.filter(name="Cross workspace").exists()


def test_mock_provider_connection_test_is_sanitized(client):
    user = UserFactory()
    grant_provider_management(user)
    workspace = user.memberships.get().workspace
    provider = AIProvider.objects.create(
        workspace=workspace,
        name="Mock local",
        provider_key="mock-local",
        provider_type="mock",
    )
    AIEndpoint.objects.create(
        workspace=workspace,
        provider=provider,
        name="Mock endpoint",
        privacy_class="local_only",
    )
    client.force_login(user)

    response = client.post(
        reverse("command_center:test-provider", kwargs={"pk": provider.pk}), follow=True
    )

    check = ProviderHealthCheck.objects.get(provider=provider)
    assert response.status_code == 200
    assert check.was_successful is True
    assert b"connection passed" in response.content
