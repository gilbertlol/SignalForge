from django.core.management.base import BaseCommand

from apps.core.services import get_default_workspace


class Command(BaseCommand):
    help = "Idempotently ensure the single default Workspace exists (pre-GOR-244 setup step)."

    def handle(self, *args, **options):
        workspace = get_default_workspace()
        self.stdout.write(self.style.SUCCESS(f"Default workspace ready: {workspace.slug}"))
