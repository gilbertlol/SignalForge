import os

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.services import attach_owner, ensure_default_roles
from apps.core.services import get_default_workspace


class Command(BaseCommand):
    help = "Idempotently initialize workspace, roles, and owner access."

    def add_arguments(self, parser):
        parser.add_argument("--with-examples", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        workspace = get_default_workspace()
        roles = ensure_default_roles(workspace)
        if os.environ.get("SIGNALFORGE_OWNER_EMAIL") and os.environ.get(
            "SIGNALFORGE_OWNER_PASSWORD"
        ):
            call_command("bootstrap_owner")
        else:
            superusers = list(User.objects.filter(is_active=True, is_superuser=True))
            for user in superusers:
                attach_owner(user, workspace, roles["Owner"])
            if superusers:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Attached {len(superusers)} existing superuser(s) as workspace owners"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "No owner provisioned: set SIGNALFORGE_OWNER_EMAIL/PASSWORD "
                        "or create a superuser"
                    )
                )
        if options["with_examples"]:
            call_command("seed_hunt_profile_examples")
        self.stdout.write(self.style.SUCCESS(f"Operational bootstrap complete: {workspace.slug}"))
