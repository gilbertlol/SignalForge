from unittest.mock import patch

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import AccessPermission
from apps.accounts.tests.factories import UserFactory
from apps.core.models import Workspace
from apps.discovery.models import (
    DiscoveryRunStatus,
    ProviderResult,
    ProviderResultStatus,
    SourceRecord,
)
from apps.discovery.services import start_run
from apps.hunting.models import HuntProfile
from apps.hunting.services import create_version
from apps.integrations.models import (
    AIEndpoint,
    AIProvider,
    CredentialReference,
    LeadSourceConfiguration,
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
            "use_openstreetmap": "on",
            "openstreetmap_max_records": 20,
            "geographies": "Toronto",
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
        {
            "name": "Runnable",
            "minimum_score": 1,
            "use_openstreetmap": "on",
            "openstreetmap_max_records": 5,
            "geographies": "Toronto",
        },
    )
    profile = HuntProfile.objects.get(name="Runnable")

    response = client.post(reverse("command_center:start-discovery", kwargs={"pk": profile.pk}))

    assert response.status_code == 302
    run = profile.current_version.discovery_runs.get()
    assert run.workspace == user.memberships.get().workspace
    mock_delay.assert_called_once_with(str(run.id))


@patch("apps.command_center.views.run_discovery_task.delay")
def test_profile_without_source_policies_is_not_runnable(mock_delay, client):
    user = UserFactory()
    profile = HuntProfile.objects.create(workspace=user.memberships.get().workspace, name="Legacy")
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
                    "weight": 1,
                }
            ],
        },
    )
    profile.current_version = version
    profile.save(update_fields=["current_version", "updated_at"])
    client.force_login(user)

    page = client.get(reverse("command_center:hunt-profiles"))
    response = client.post(reverse("command_center:start-discovery", kwargs={"pk": profile.pk}))

    assert b"Manual/CSV only" in page.content
    assert response.status_code == 302
    assert not version.discovery_runs.exists()
    mock_delay.assert_not_called()


@patch("apps.command_center.views.run_discovery_task.delay")
def test_start_discovery_rejects_unconfigured_live_source(mock_delay, client):
    user = UserFactory()
    client.force_login(user)
    client.post(
        reverse("command_center:create-hunt-profile"),
        {
            "name": "Needs Apollo",
            "minimum_score": 1,
            "use_apollo": "on",
            "apollo_max_records": 5,
        },
    )
    profile = HuntProfile.objects.get(name="Needs Apollo")

    response = client.post(
        reverse("command_center:start-discovery", kwargs={"pk": profile.pk}), follow=True
    )

    assert response.status_code == 200
    assert b"Apollo" in response.content
    assert not profile.current_version.discovery_runs.exists()
    mock_delay.assert_not_called()


def test_run_monitor_renders_independent_provider_outcomes(client):
    user = UserFactory()
    client.force_login(user)
    client.post(
        reverse("command_center:create-hunt-profile"),
        {
            "name": "Monitored",
            "minimum_score": 1,
            "use_openstreetmap": "on",
            "openstreetmap_max_records": 5,
            "geographies": "Toronto",
        },
    )
    profile = HuntProfile.objects.get(name="Monitored")
    run = start_run(profile.current_version, trigger="manual", initiated_by=user)
    run.status = DiscoveryRunStatus.RUNNING
    run.save()
    ProviderResult.objects.create(
        discovery_run=run,
        provider_key="openstreetmap",
        status=ProviderResultStatus.RETRYING,
        attempt_count=2,
        records_returned=3,
    )

    response = client.get(reverse("command_center:run-status-fragment"))

    assert response.status_code == 200
    assert b"openstreetmap" in response.content
    assert b"Retrying" in response.content
    assert b"2 attempts" in response.content


def test_cancel_run_marks_nonterminal_sources_canceled(client):
    user = UserFactory()
    client.force_login(user)
    client.post(
        reverse("command_center:create-hunt-profile"),
        {
            "name": "Cancelable",
            "minimum_score": 1,
            "use_openstreetmap": "on",
            "openstreetmap_max_records": 5,
            "geographies": "Toronto",
        },
    )
    profile = HuntProfile.objects.get(name="Cancelable")
    run = start_run(profile.current_version, trigger="manual", initiated_by=user)
    source = ProviderResult.objects.create(discovery_run=run, provider_key="openstreetmap")

    response = client.post(reverse("command_center:cancel-run", kwargs={"pk": run.pk}))

    run.refresh_from_db()
    source.refresh_from_db()
    assert response.status_code == 302
    assert run.status == DiscoveryRunStatus.CANCELED
    assert source.status == ProviderResultStatus.CANCELED


def test_create_hunt_profile_persists_independent_multi_source_policies(client):
    user = UserFactory()
    client.force_login(user)

    response = client.post(
        reverse("command_center:create-hunt-profile"),
        {
            "name": "Toronto professionals",
            "minimum_score": 1,
            "geographies": "Toronto, Ontario",
            "industries": "accountant, consultant",
            "use_openstreetmap": "on",
            "openstreetmap_max_records": 30,
            "openstreetmap_budget_cents": 0,
            "use_apollo": "on",
            "apollo_max_records": 5,
            "apollo_budget_cents": 25,
        },
    )

    assert response.status_code == 302
    version = HuntProfile.objects.get(name="Toronto professionals").current_version
    policies = {policy.source_key: policy for policy in version.source_policies.all()}
    assert policies["openstreetmap"].max_records == 30
    assert policies["openstreetmap"].budget_cents == 0
    assert policies["apollo"].max_records == 5
    assert policies["apollo"].budget_cents == 25
    assert version.search_scope.geographies == ["Toronto", "Ontario"]


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


def test_provider_catalog_explains_real_sources_and_uses_scoped_selectors(client):
    user = UserFactory()
    grant_provider_management(user)
    workspace = user.memberships.get().workspace
    provider = AIProvider.objects.create(
        workspace=workspace, name="Local AI", provider_key="local-ai", provider_type="mock"
    )
    credential = CredentialReference(workspace=workspace, name="Local secret")
    credential.set_secret("hidden")
    credential.save()
    client.force_login(user)

    response = client.get(reverse("command_center:provider-settings"))

    assert response.status_code == 200
    assert b"OpenStreetMap" in response.content
    assert b"no API key required" in response.content
    assert b"Open Database License" in response.content
    assert b"public Overpass fair-use limits" in response.content
    assert f'value="{provider.id}"'.encode() in response.content
    assert f'value="{credential.id}"'.encode() in response.content
    assert b"Use provider and credential UUIDs" not in response.content


def test_organization_detail_links_original_source_and_attribution(client):
    user = UserFactory()
    workspace = user.memberships.get().workspace
    organization = OrganizationFactory(workspace=workspace)
    profile = HuntProfile.objects.create(workspace=workspace, name="Provenance")
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
                    "weight": 1,
                }
            ],
        },
    )
    run = start_run(version, trigger="manual", initiated_by=user)
    SourceRecord.objects.create(
        discovery_run=run,
        source_key="openstreetmap",
        external_id="node-42",
        organization=organization,
        raw_payload={
            "source_url": "https://www.openstreetmap.org/node/42",
            "source_attribution": "© OpenStreetMap contributors (ODbL)",
        },
    )
    client.force_login(user)

    response = client.get(
        reverse("command_center:organization-detail", kwargs={"pk": organization.pk})
    )

    assert b"View original provider record" in response.content
    assert b"OpenStreetMap contributors" in response.content


@override_settings(SIGNALFORGE_CREDENTIAL_KEY="command-center-test-key-at-least-32-characters")
def test_apollo_configuration_is_workspace_scoped_and_rotates_secret(client):
    user = UserFactory()
    grant_provider_management(user)
    workspace = user.memberships.get().workspace
    client.force_login(user)

    for secret in ("first-apollo-key", "rotated-apollo-key"):
        response = client.post(
            reverse("command_center:configure-apollo"),
            {
                "name": "Apollo production",
                "api_key": secret,
                "timeout_seconds": 20,
                "estimated_cost_per_page_cents": 15,
                "enabled": "on",
            },
            follow=True,
        )
        assert secret not in response.content.decode()

    configuration = LeadSourceConfiguration.objects.get(workspace=workspace)
    assert LeadSourceConfiguration.objects.count() == 1
    assert configuration.credential.get_secret() == "rotated-apollo-key"
    assert "rotated-apollo-key" not in configuration.credential.encrypted_value


@patch("apps.command_center.views.get_lead_source_adapter")
def test_apollo_live_validation_reports_success(mock_get_adapter, client):
    user = UserFactory()
    grant_provider_management(user)
    client.force_login(user)
    adapter = mock_get_adapter.return_value
    adapter.is_configured.return_value = True
    adapter.search.return_value = [{"id": "sample"}]

    response = client.post(reverse("command_center:test-apollo"), follow=True)

    assert response.status_code == 200
    assert b"Apollo connection passed" in response.content
    adapter.search.assert_called_once_with({"limit": 1})


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
