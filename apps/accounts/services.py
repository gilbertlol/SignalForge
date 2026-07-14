from apps.core.models import Workspace

from .models import AccessPermission, Membership, PersonalPreference, Role, User

PERMISSIONS = {
    "prospects.access": "Access prospects",
    "communications.access": "Access communications",
    "communications.send": "Send communications",
    "approvals.manage": "Manage approvals",
    "agents.manage": "Manage agents",
    "providers.manage": "Manage provider configuration",
    "financials.access": "Access financial data",
    "risk.access": "Access risk data",
    "exports.create": "Create exports",
    "settings.manage": "Manage settings",
    "users.manage": "Manage users",
}

ROLE_PERMISSIONS = {
    "Owner": set(PERMISSIONS),
    "Administrator": set(PERMISSIONS),
    "Sales Manager": {
        "prospects.access",
        "communications.access",
        "communications.send",
        "approvals.manage",
        "exports.create",
    },
    "Closer": {
        "prospects.access",
        "communications.access",
        "communications.send",
        "approvals.manage",
    },
    "Researcher": {"prospects.access", "exports.create"},
    "Outreach Specialist": {
        "prospects.access",
        "communications.access",
        "communications.send",
    },
    "Account Manager": {"prospects.access", "communications.access", "risk.access"},
    "Developer": {"prospects.access", "agents.manage", "providers.manage", "settings.manage"},
    "Finance": {"prospects.access", "financials.access", "exports.create"},
    "Read Only": {"prospects.access", "communications.access", "risk.access"},
}


def ensure_default_roles(workspace: Workspace) -> dict[str, Role]:
    permissions = {
        key: AccessPermission.objects.update_or_create(key=key, defaults={"name": name})[0]
        for key, name in PERMISSIONS.items()
    }
    roles: dict[str, Role] = {}
    for role_name, permission_keys in ROLE_PERMISSIONS.items():
        role, _ = Role.objects.get_or_create(
            workspace=workspace, name=role_name, defaults={"is_system": True}
        )
        if not role.is_system:
            role.is_system = True
            role.save(update_fields=["is_system", "updated_at"])
        role.permissions.set([permissions[key] for key in permission_keys])
        roles[role_name] = role
    return roles


def attach_owner(user: User, workspace: Workspace, owner_role: Role) -> Membership:
    membership, _ = Membership.objects.get_or_create(workspace=workspace, user=user)
    if not membership.is_active:
        membership.is_active = True
        membership.save(update_fields=["is_active", "updated_at"])
    membership.roles.add(owner_role)
    PersonalPreference.objects.update_or_create(user=user, defaults={"active_workspace": workspace})
    return membership
