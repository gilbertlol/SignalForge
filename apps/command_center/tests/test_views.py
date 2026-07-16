from unittest.mock import patch

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import AccessPermission
from apps.accounts.tests.factories import UserFactory
from apps.command_center.forms import HuntProfileForm
from apps.core.models import Workspace
from apps.discovery.models import (
    DiscoveryRunStatus,
    ProviderResult,
    ProviderResultStatus,
    SourceRecord,
)
from apps.discovery.services import start_run
from apps.evidence.models import OrganizationClaim, OrganizationFieldResolution
from apps.evidence.services import create_manual_claim
from apps.hunting.models import HuntPreset, HuntProfile
from apps.hunting.services import create_version
from apps.integrations.models import (
    AIEndpoint,
    AIProvider,
    CredentialReference,
    LeadSourceConfiguration,
    LeadSourceHealthCheck,
    LeadSourceHealthStatus,
    ModelDefinition,
    ModelRoute,
    PrivacyClass,
    ProviderHealthCheck,
    ProviderType,
)
from apps.opportunities.tests.factories import OpportunityFactory
from apps.organizations.models import Organization
from apps.organizations.tests.factories import OrganizationFactory
from apps.tasks.models import Operator, OperatorType

pytestmark = pytest.mark.django_db


def validated_lead_source(workspace, source_key):
    credential = CredentialReference.objects.create(
        workspace=workspace, name=f"{source_key} key", encrypted_value="opaque-test-secret"
    )
    configuration = LeadSourceConfiguration.objects.create(
        workspace=workspace,
        source_key=source_key,
        name=source_key,
        credential=credential,
        enabled=True,
        config={"storage_permitted": True},
    )
    LeadSourceHealthCheck.objects.create(
        workspace=workspace,
        configuration=configuration,
        status=LeadSourceHealthStatus.READY,
        was_successful=True,
    )
    return configuration


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


def test_crew_page_requires_permission_and_lists_operators(client):
    user = UserFactory()
    workspace = user.memberships.get().workspace
    Operator.objects.create(
        workspace=workspace, name="Scout agent", operator_type=OperatorType.AI_AGENT
    )
    client.force_login(user)

    assert client.get(reverse("command_center:crew")).status_code == 403
    permission, _ = AccessPermission.objects.get_or_create(
        key="agents.manage", defaults={"name": "Manage agents"}
    )
    user.memberships.get().permission_grants.add(permission)

    response = client.get(reverse("command_center:crew"))
    assert response.status_code == 200
    assert b"Scout agent" in response.content
    assert b"Your expedition crew" in response.content


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


def test_preset_prefills_editable_builder_and_explains_missing_sources(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(
        reverse("command_center:create-hunt-profile") + "?preset=local-businesses"
    )

    assert response.status_code == 200
    assert response.context["form"].initial["use_google_places"] is False
    assert response.context["form"].initial["use_openstreetmap"] is True
    assert response.context["form"].initial["google_places_budget_cents"] == 25
    assert response.context["form"].initial["google_places_reliability_weight"] == 80
    assert response.context["form"].fields["use_google_places"].disabled is True
    assert b"corporate_registry" in response.content
    assert b"setup needed" in response.content
    assert b"change everything afterward" in response.content
    assert b'class="preset-list"' in response.content
    assert response.content.count(b'class="preset-option') == 5
    assert response.content.count(b'class="preset-preview') == 1
    assert b'id="id_location_type"' in response.content
    assert b'id="radius-fields"' in response.content
    assert b'id="radius-map-dialog"' in response.content
    assert b'id="radius-map"' in response.content
    assert b'type="hidden" name="center_latitude"' in response.content


def test_openstreetmap_radius_requires_complete_coordinates():
    form = HuntProfileForm(
        {
            "name": "Radius hunt",
            "minimum_score": 10,
            "location_type": "radius",
            "use_openstreetmap": "on",
            "openstreetmap_max_records": 10,
            "radius_meters": 5000,
        }
    )

    assert form.is_valid() is False
    assert "center_latitude" in form.errors


def test_map_radius_values_validate_with_google_places():
    form = HuntProfileForm(
        {
            "name": "Mapped radius hunt",
            "minimum_score": 10,
            "location_type": "radius",
            "use_google_places": "on",
            "google_places_max_records": 20,
            "center_latitude": "45.501700",
            "center_longitude": "-73.567300",
            "radius_meters": 12000,
        }
    )

    assert form.is_valid(), form.errors


def test_applying_preset_copies_values_and_later_preset_changes_do_not_mutate_profile(client):
    user = UserFactory()
    client.force_login(user)
    preset = HuntPreset.objects.get(key="local-businesses", version=1)

    response = client.post(
        reverse("command_center:create-hunt-profile"),
        {
            "preset": preset.pk,
            "name": "Editable local hunt",
            "minimum_score": 17,
            "geographies": "Montreal",
            "industries": "dentist",
            "use_openstreetmap": "on",
            "openstreetmap_max_records": 12,
            "reliability_weight": 73,
            "activate_now": "on",
        },
    )

    assert response.status_code == 302
    profile = HuntProfile.objects.get(name="Editable local hunt")
    version = profile.current_version
    assert version.applied_preset_key == "local-businesses"
    assert version.applied_preset_version == 1
    assert version.search_scope.industries == ["dentist"]
    assert version.source_policies.get().max_records == 12
    preset.configuration = {"form_initial": {"openstreetmap_max_records": 99}}
    preset.save(update_fields=["configuration", "updated_at"])
    version.refresh_from_db()
    assert version.source_policies.get().max_records == 12
    assert version.result_threshold.min_total_score == 17


def test_funded_growth_preset_defaults_create_a_profile(client):
    user = UserFactory()
    validated_lead_source(user.memberships.get().workspace, "apollo")
    client.force_login(user)
    preset = HuntPreset.objects.get(key="funded-growing-companies", version=1)

    response = client.post(
        reverse("command_center:create-hunt-profile") + "?preset=funded-growing-companies",
        {
            "preset": preset.pk,
            "name": preset.name,
            "description": preset.description,
            "minimum_score": 15,
            "use_apollo": "on",
            "apollo_max_records": 40,
            "apollo_budget_cents": 100,
            "apollo_reliability_weight": 70,
            "reliability_weight": 70,
            "activate_now": "on",
        },
    )

    assert response.status_code == 302
    profile = HuntProfile.objects.get(name="Funded and growing companies")
    assert profile.current_version.applied_preset_key == "funded-growing-companies"
    policy = profile.current_version.source_policies.get()
    assert policy.source_key == "apollo"
    assert policy.max_records == 40
    assert policy.budget_cents == 100


def test_hunt_profile_validation_errors_are_summarized_at_top(client):
    user = UserFactory()
    client.force_login(user)

    response = client.post(reverse("command_center:create-hunt-profile"), {})

    assert response.status_code == 200
    assert b"Almost there" in response.content
    assert b"Name: This field is required" in response.content


def test_invalid_preset_submission_keeps_the_selected_preview(client):
    user = UserFactory()
    client.force_login(user)
    preset = HuntPreset.objects.get(key="funded-growing-companies", version=1)

    response = client.post(
        reverse("command_center:create-hunt-profile") + "?preset=funded-growing-companies",
        {
            "preset": preset.pk,
            "minimum_score": 15,
            "use_apollo": "on",
            "apollo_max_records": 40,
        },
    )

    assert response.status_code == 200
    assert response.context["selected_preset"] == preset
    assert response.context["display_preset"].pk == preset.pk
    assert b"Almost there" in response.content


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


def test_builder_disables_unvalidated_paid_source(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("command_center:create-hunt-profile"))

    assert response.status_code == 200
    assert response.context["form"].fields["use_apollo"].disabled is True
    assert b"Configure and validate Apollo" in response.content


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
    validated_lead_source(user.memberships.get().workspace, "apollo")
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


def test_manual_organization_correction_preserves_claim_history(client):
    user = UserFactory()
    client.force_login(user)
    response = client.post(
        reverse("command_center:create-organization"),
        {
            "name": "Hand Built Co",
            "domain": "handbuilt.test",
            "industry": "consulting",
            "location": "Montreal",
            "employee_count": 8,
            "website_url": "https://handbuilt.test",
            "phone": "555-0100",
            "notes": "Met at an event",
        },
    )
    organization = Organization.objects.get(name="Hand Built Co")
    assert response.status_code == 302
    assert organization.source_claims.count() == 8
    assert not organization.source_claims.exclude(source_key="manual").exists()

    client.post(
        reverse("command_center:add-manual-claim", kwargs={"pk": organization.pk}),
        {
            "field_name": "industry",
            "value": "automation consulting",
            "reliability": "high",
            "note": "Confirmed directly by the owner.",
        },
    )
    claims = OrganizationClaim.objects.filter(organization=organization, field_name="industry")
    assert claims.count() == 2
    correction = claims.get(value="automation consulting")

    client.post(
        reverse("command_center:prefer-claim", kwargs={"pk": correction.pk}),
        {"note": "Owner-confirmed value."},
    )
    resolution = OrganizationFieldResolution.objects.get(
        organization=organization, field_name="industry"
    )
    assert resolution.selected_claim == correction
    assert resolution.is_manually_selected is True
    assert resolution.has_conflict is True
    assert resolution.selection_note == "Owner-confirmed value."


def test_manual_claim_writes_cannot_cross_workspaces(client):
    user = UserFactory()
    foreign_workspace = Workspace.objects.create(name="Foreign claims", slug="foreign-claims")
    foreign_organization = OrganizationFactory(workspace=foreign_workspace)
    foreign_claim = create_manual_claim(
        foreign_organization,
        field_name="industry",
        value="private",
        reliability="high",
        note="Foreign workspace data.",
    )
    client.force_login(user)

    add_response = client.post(
        reverse("command_center:add-manual-claim", kwargs={"pk": foreign_organization.pk}),
        {"field_name": "industry", "value": "leak", "reliability": "high", "note": "x"},
    )
    prefer_response = client.post(
        reverse("command_center:prefer-claim", kwargs={"pk": foreign_claim.pk}),
        {"note": "Try to select foreign data."},
    )

    assert add_response.status_code == 404
    assert prefer_response.status_code == 404
    assert not OrganizationClaim.objects.filter(value="leak").exists()


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


def test_searxng_configuration_is_workspace_scoped_and_requires_live_validation(client):
    user = UserFactory()
    grant_provider_management(user)
    workspace = user.memberships.get().workspace
    client.force_login(user)

    response = client.post(
        reverse("command_center:configure-searxng"),
        {
            "base_url": "http://searxng:8080",
            "language": "en",
            "timeout_seconds": 15,
            "enabled": "on",
        },
        follow=True,
    )

    configuration = LeadSourceConfiguration.objects.get(workspace=workspace, source_key="searxng")
    assert response.status_code == 200
    assert configuration.base_url == "http://searxng:8080"
    assert configuration.credential is None
    assert configuration.config == {"language": "en"}
    builder = client.get(reverse("command_center:create-hunt-profile"))
    assert builder.context["form"].fields["use_searxng"].disabled is True
    assert b"Run live validation first" in builder.content


@patch("apps.integrations.services.get_lead_source_adapter")
def test_searxng_live_validation_enables_the_hunt_source(mock_get_adapter, client):
    user = UserFactory()
    grant_provider_management(user)
    workspace = user.memberships.get().workspace
    configuration = LeadSourceConfiguration.objects.create(
        workspace=workspace,
        source_key="searxng",
        name="SearXNG",
        base_url="http://searxng:8080",
        credential=None,
    )
    adapter = mock_get_adapter.return_value
    adapter.is_configured.return_value = True
    adapter.search.return_value = []
    client.force_login(user)

    response = client.post(reverse("command_center:test-searxng"), follow=True)

    assert response.status_code == 200
    assert configuration.health_checks.get().was_successful is True
    builder = client.get(reverse("command_center:create-hunt-profile"))
    assert builder.context["form"].fields["use_searxng"].disabled is False
    assert b"Instance validated" in builder.content


def test_provider_admin_can_configure_a_local_default_research_route(client):
    user = UserFactory()
    grant_provider_management(user)
    workspace = user.memberships.get().workspace
    provider = AIProvider.objects.create(
        workspace=workspace,
        name="Ollama",
        provider_key="ollama",
        provider_type=ProviderType.LOCAL_OPENAI,
    )
    endpoint = AIEndpoint.objects.create(
        workspace=workspace,
        provider=provider,
        name="Local Ollama",
        base_url="http://ollama:11434/v1",
        privacy_class=PrivacyClass.LOCAL_ONLY,
    )
    model = ModelDefinition.objects.create(
        workspace=workspace,
        endpoint=endpoint,
        model_name="qwen3:8b",
        display_name="Qwen 3 8B",
    )
    client.force_login(user)

    response = client.post(
        reverse("command_center:configure-research-route"),
        {
            "task_type": "research_query_planning",
            "model": model.id,
            "required_privacy_class": PrivacyClass.LOCAL_ONLY,
        },
        follow=True,
    )

    route = ModelRoute.objects.get(
        workspace=workspace, task_type="research_query_planning", is_default=True
    )
    assert response.status_code == 200
    assert route.entries.get().model == model
    assert b"research_query_planning" in response.content
    assert b"Qwen 3 8B" in response.content


@override_settings(SIGNALFORGE_CREDENTIAL_KEY="command-center-test-key-at-least-32-characters")
@patch("apps.integrations.services.get_lead_source_adapter")
def test_apollo_live_validation_reports_success(mock_get_adapter, client):
    user = UserFactory()
    grant_provider_management(user)
    workspace = user.memberships.get().workspace
    credential = CredentialReference(workspace=workspace, name="Apollo key")
    credential.set_secret("valid-apollo-key")
    credential.save()
    configuration = LeadSourceConfiguration.objects.create(
        workspace=workspace,
        source_key="apollo",
        name="Apollo",
        credential=credential,
    )
    client.force_login(user)
    adapter = mock_get_adapter.return_value
    adapter.is_configured.return_value = True
    adapter.search.return_value = [{"id": "sample"}]

    response = client.post(reverse("command_center:test-apollo"), follow=True)

    assert response.status_code == 200
    assert b"Apollo connection passed" in response.content
    adapter.search.assert_called_once_with({"limit": 1})
    assert configuration.health_checks.get().was_successful is True


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
