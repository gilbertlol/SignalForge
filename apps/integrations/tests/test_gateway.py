from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import AccessPermission
from apps.accounts.tests.factories import UserFactory
from apps.core.models import Workspace
from apps.integrations.models import (
    AIEndpoint,
    AIProvider,
    CredentialReference,
    FallbackPolicy,
    ModelDefinition,
    ModelInvocation,
    ModelRoute,
    ModelRouteEntry,
    PrivacyClass,
    ProviderType,
    UsagePolicy,
)
from apps.integrations.services import GatewayError, invoke

pytestmark = pytest.mark.django_db


def gateway_fixture(workspace, *, privacy=PrivacyClass.LOCAL_ONLY, response_provider=True):
    provider = AIProvider.objects.create(
        workspace=workspace,
        name="Mock",
        provider_key="mock",
        provider_type="mock" if response_provider else ProviderType.NATIVE,
    )
    endpoint = AIEndpoint.objects.create(
        workspace=workspace,
        provider=provider,
        name="Mock endpoint",
        privacy_class=privacy,
    )
    model = ModelDefinition.objects.create(
        workspace=workspace,
        endpoint=endpoint,
        model_name="mock-1",
        display_name="Mock 1",
    )
    fallback = FallbackPolicy.objects.create(workspace=workspace, name="Ordered")
    route = ModelRoute.objects.create(
        workspace=workspace,
        task_type="classification",
        name="Classifier",
        fallback_policy=fallback,
        required_privacy_class=PrivacyClass.LOCAL_ONLY,
    )
    ModelRouteEntry.objects.create(route=route, model=model, position=1)
    return route


@override_settings(SIGNALFORGE_CREDENTIAL_KEY="a-secure-test-key-that-is-at-least-32-characters")
def test_credentials_are_encrypted_and_round_trip():
    workspace = Workspace.objects.create(name="Credential", slug="credential")
    credential = CredentialReference(workspace=workspace, name="Cloud token")
    credential.set_secret("super-secret-value")
    credential.save()

    assert "super-secret-value" not in credential.encrypted_value
    assert credential.get_secret() == "super-secret-value"


def test_mock_gateway_validates_structured_output():
    workspace = Workspace.objects.create(name="Gateway", slug="gateway")
    route = gateway_fixture(workspace)

    result = invoke(
        route=route,
        prompt="classify",
        output_schema={"type": "object", "required": ["score"]},
        options={"mock_response": {"score": 8}},
    )

    assert result.parsed == {"score": 8}
    assert result.invocation.status == "succeeded"


@patch("apps.integrations.services.get_ai_model_adapter")
def test_gateway_repairs_invalid_structured_output_once(mock_get_adapter):
    workspace = Workspace.objects.create(name="Repair", slug="repair")
    route = gateway_fixture(workspace)
    adapter = MagicMock()
    adapter.is_configured.return_value = True
    adapter.complete.side_effect = ['{"wrong": true}', '{"score": 8}']
    mock_get_adapter.return_value = adapter

    result = invoke(
        route=route,
        prompt="classify",
        output_schema={
            "type": "object",
            "required": ["score"],
            "properties": {"score": {"type": "integer"}},
        },
    )

    assert result.parsed == {"score": 8}
    assert adapter.complete.call_count == 2
    assert "failed the required JSON Schema" in adapter.complete.call_args.args[0]


def test_gateway_blocks_cloud_model_for_local_only_route():
    workspace = Workspace.objects.create(name="Private", slug="private")
    route = gateway_fixture(workspace, privacy=PrivacyClass.PUBLIC_CLOUD)

    with pytest.raises(GatewayError, match="No model"):
        invoke(route=route, prompt="sensitive")

    assert not ModelInvocation.objects.exists()


def test_gateway_records_sanitized_failure():
    workspace = Workspace.objects.create(name="Failure", slug="failure")
    route = gateway_fixture(workspace, response_provider=False)

    with pytest.raises(GatewayError):
        invoke(route=route, prompt="fail")

    invocation = ModelInvocation.objects.get()
    assert invocation.failure_reason == "GatewayError"


def test_gateway_falls_back_in_configured_order():
    workspace = Workspace.objects.create(name="Fallback", slug="fallback")
    route = gateway_fixture(workspace)
    first = route.entries.get().model
    second = ModelDefinition.objects.create(
        workspace=workspace,
        endpoint=first.endpoint,
        model_name="mock-2",
        display_name="Mock 2",
    )
    ModelRouteEntry.objects.create(route=route, model=second, position=2)

    result = invoke(
        route=route,
        prompt="fallback",
        options={"fail_models": ["mock-1"], "mock_response": {"ok": True}},
    )

    assert result.invocation.model == second
    assert result.invocation.retry_count == 1
    assert list(ModelInvocation.objects.values_list("status", flat=True)) == [
        "failed",
        "succeeded",
    ]


def test_gateway_enforces_provider_daily_budget():
    workspace = Workspace.objects.create(name="Budget", slug="budget")
    route = gateway_fixture(workspace)
    model = route.entries.get().model
    UsagePolicy.objects.create(
        workspace=workspace,
        name="Provider daily cap",
        provider=model.endpoint.provider,
        daily_budget_cents=1,
    )
    ModelInvocation.objects.create(
        workspace=workspace,
        route=route,
        model=model,
        task_type=route.task_type,
        status="succeeded",
        estimated_cost_cents=1,
    )

    with pytest.raises(GatewayError, match="budget exhausted"):
        invoke(route=route, prompt="over budget")


@override_settings(SIGNALFORGE_CREDENTIAL_KEY="a-secure-test-key-that-is-at-least-32-characters")
def test_credential_api_never_returns_secret():
    user = UserFactory()
    membership = user.memberships.get()
    permission, _ = AccessPermission.objects.get_or_create(
        key="providers.manage", defaults={"name": "Manage providers"}
    )
    membership.permission_grants.add(permission)
    client = APIClient()
    client.force_authenticate(user=user)

    created = client.post(
        "/api/v1/ai/credentials/", {"name": "API token", "secret": "never-return-this"}
    )
    listed = client.get("/api/v1/ai/credentials/")

    assert created.status_code == 201
    assert "secret" not in created.json()
    assert "never-return-this" not in str(listed.json())


def test_api_rejects_cross_workspace_provider_reference():
    user = UserFactory()
    membership = user.memberships.get()
    permission, _ = AccessPermission.objects.get_or_create(
        key="providers.manage", defaults={"name": "Manage providers"}
    )
    membership.permission_grants.add(permission)
    other = Workspace.objects.create(name="Other", slug="other-ai")
    provider = AIProvider.objects.create(
        workspace=other, name="Foreign", provider_key="foreign", provider_type="mock"
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/v1/ai/endpoints/", {"provider": str(provider.id), "name": "Bad reference"}
    )

    assert response.status_code == 400
    assert not AIEndpoint.objects.filter(workspace=membership.workspace).exists()
