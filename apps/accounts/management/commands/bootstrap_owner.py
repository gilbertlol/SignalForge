import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.services import attach_owner, ensure_default_roles
from apps.core.services import get_default_workspace


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
        roles = ensure_default_roles(workspace)
        attach_owner(user, workspace, roles["Owner"])
        self.stdout.write(self.style.SUCCESS(f"Owner {email} is ready in {workspace.slug}"))
