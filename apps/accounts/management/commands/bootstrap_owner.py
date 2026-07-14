import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import AccessPermission, Membership, PersonalPreference, Role, User
from apps.core.services import get_default_workspace

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
    "Outreach Specialist": {"prospects.access", "communications.access", "communications.send"},
    "Account Manager": {"prospects.access", "communications.access", "risk.access"},
    "Developer": {"prospects.access", "agents.manage", "providers.manage", "settings.manage"},
    "Finance": {"prospects.access", "financials.access", "exports.create"},
    "Read Only": {"prospects.access", "communications.access", "risk.access"},
}


class Command(BaseCommand):
    help = "Create or update the local owner from SIGNALFORGE_OWNER_EMAIL/PASSWORD."

    @transaction.atomic
    def handle(self, *args, **options):
        email = os.environ.get("SIGNALFORGE_OWNER_EMAIL", "").strip().lower()
        password = os.environ.get("SIGNALFORGE_OWNER_PASSWORD", "")
        if not email or not password:
            raise CommandError(
                "SIGNALFORGE_OWNER_EMAIL and SIGNALFORGE_OWNER_PASSWORD are required"
            )
        if len(password) < 12:
            raise CommandError("Owner password must contain at least 12 characters")
        workspace = get_default_workspace()
        user, _ = User.objects.get_or_create(email=email)
        user.set_password(password)
        user.is_active = True
        user.is_staff = True
        user.save()
        permissions = [
            AccessPermission.objects.update_or_create(key=key, defaults={"name": name})[0]
            for key, name in PERMISSIONS.items()
        ]
        permissions_by_key = {permission.key: permission for permission in permissions}
        roles = {}
        for role_name, permission_keys in ROLE_PERMISSIONS.items():
            role, _ = Role.objects.get_or_create(
                workspace=workspace, name=role_name, defaults={"is_system": True}
            )
            if not role.is_system:
                role.is_system = True
                role.save(update_fields=["is_system", "updated_at"])
            role.permissions.set([permissions_by_key[key] for key in permission_keys])
            roles[role_name] = role
        membership, _ = Membership.objects.get_or_create(workspace=workspace, user=user)
        membership.roles.add(roles["Owner"])
        PersonalPreference.objects.update_or_create(
            user=user, defaults={"active_workspace": workspace}
        )
        self.stdout.write(self.style.SUCCESS(f"Owner {email} is ready in {workspace.slug}"))
