import pytest
from rest_framework.test import APIClient

from apps.accounts.models import AccessPermission
from apps.accounts.tests.factories import UserFactory

from ..models import ChannelAccount

pytestmark = pytest.mark.django_db


def test_channel_account_api_is_workspace_scoped():
    user = UserFactory()
    membership = user.memberships.get()
    permission, _ = AccessPermission.objects.get_or_create(
        key="settings.manage", defaults={"name": "Manage settings"}
    )
    membership.permission_grants.add(permission)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/v1/channel-accounts/",
        {
            "name": "Sales",
            "channel": "email",
            "provider_key": "mock_email",
            "address": "sales@example.com",
        },
    )

    assert response.status_code == 201
    assert ChannelAccount.objects.get().workspace == membership.workspace
