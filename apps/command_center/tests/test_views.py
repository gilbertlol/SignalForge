import pytest
from django.urls import reverse

from apps.accounts.models import AccessPermission
from apps.accounts.tests.factories import UserFactory
from apps.core.models import Workspace
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
