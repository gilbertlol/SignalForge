import hashlib

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import AccessPermission, APIKey, Invitation, Membership, Role, User
from apps.accounts.tests.factories import UserFactory
from apps.core.models import Workspace
from apps.organizations.tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_workspace_header_cannot_cross_membership_boundary():
    allowed = Workspace.objects.create(name="Allowed", slug="allowed")
    forbidden = Workspace.objects.create(name="Forbidden", slug="forbidden")
    user = UserFactory(workspace_membership=allowed)
    OrganizationFactory(workspace=forbidden, name="Secret")

    response = authenticated_client(user).get(
        "/api/v1/organizations/", HTTP_X_WORKSPACE="forbidden"
    )

    assert response.status_code == 404


def test_id_guessing_cannot_fetch_cross_workspace_record():
    allowed = Workspace.objects.create(name="Allowed", slug="allowed-id")
    forbidden = Workspace.objects.create(name="Forbidden", slug="forbidden-id")
    user = UserFactory(workspace_membership=allowed)
    secret = OrganizationFactory(workspace=forbidden)

    response = authenticated_client(user).get(f"/api/v1/organizations/{secret.id}/")

    assert response.status_code == 404


def test_api_key_authentication_and_revocation():
    user = UserFactory()
    membership = user.memberships.get()
    key, raw_key = APIKey.issue(
        workspace=membership.workspace, user=user, name="CLI", scopes=["prospects.access"]
    )
    client = APIClient()

    assert (
        client.get("/api/v1/organizations/", HTTP_AUTHORIZATION=f"ApiKey {raw_key}").status_code
        == 200
    )
    key.revoked_at = timezone.now()
    key.save()
    assert (
        client.get("/api/v1/organizations/", HTTP_AUTHORIZATION=f"ApiKey {raw_key}").status_code
        == 403
    )


def test_api_key_scope_cannot_exceed_user_permissions():
    user = UserFactory()
    membership = user.memberships.get()
    _, raw_key = APIKey.issue(
        workspace=membership.workspace, user=user, name="Read only", scopes=["prospects.access"]
    )

    response = APIClient().get("/api/v1/api-keys/", HTTP_AUTHORIZATION=f"ApiKey {raw_key}")

    assert response.status_code == 403


def test_invitation_is_single_use():
    owner = UserFactory()
    workspace = owner.memberships.get().workspace
    role = Role.objects.create(workspace=workspace, name="Researcher")
    invitation, token = Invitation.issue(
        workspace=workspace,
        email="invitee@example.com",
        invited_by=owner,
        expires_at=timezone.now() + timezone.timedelta(hours=1),
    )
    invitation.roles.add(role)
    payload = {"token": token, "password": "long-secure-password", "display_name": "Invitee"}

    first = APIClient().post("/api/v1/auth/invitations/accept/", payload)
    second = APIClient().post("/api/v1/auth/invitations/accept/", payload)

    assert first.status_code == 201
    assert second.status_code == 400
    user = User.objects.get(email="invitee@example.com")
    assert Membership.objects.get(user=user, workspace=workspace).roles.filter(id=role.id).exists()
    assert invitation.token_hash == hashlib.sha256(token.encode()).hexdigest()


def test_invitation_rejects_role_from_another_workspace():
    owner = UserFactory()
    membership = owner.memberships.get()
    users_manage, _ = AccessPermission.objects.get_or_create(
        key="users.manage", defaults={"name": "Manage users"}
    )
    membership.permission_grants.add(users_manage)
    workspace = membership.workspace
    other_workspace = Workspace.objects.create(name="Other", slug="other-invite")
    foreign_role = Role.objects.create(workspace=other_workspace, name="Foreign")

    response = authenticated_client(owner).post(
        "/api/v1/memberships/invite/",
        {"email": "invitee@example.com", "role_ids": [str(foreign_role.id)]},
    )

    assert response.status_code == 400
    assert not Invitation.objects.filter(workspace=workspace).exists()


def test_raw_api_key_is_never_stored():
    user = UserFactory()
    workspace = user.memberships.get().workspace
    key, raw_key = APIKey.issue(workspace=workspace, user=user, name="Automation")

    assert raw_key not in key.secret_hash
    assert key.secret_hash == hashlib.sha256(raw_key.split("_", 2)[2].encode()).hexdigest()


def test_explicit_permission_denial_overrides_grant():
    user = UserFactory()
    membership = user.memberships.get()
    permission = AccessPermission.objects.get(key="prospects.access")
    membership.permission_denials.add(permission)

    response = authenticated_client(user).get("/api/v1/organizations/")

    assert response.status_code == 403
