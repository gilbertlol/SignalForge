import os

import redis
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.accounts.models import Membership
from apps.core.models import Workspace
from apps.hunting.models import HuntProfile


class Command(BaseCommand):
    help = "Report actionable local operational readiness without exposing secrets."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Treat warnings as failures")

    def handle(self, *args, **options):
        failures: list[str] = []
        warnings: list[str] = []

        def report(label: str, state: str, detail: str = ""):
            suffix = f" — {detail}" if detail else ""
            self.stdout.write(f"[{state}] {label}{suffix}")

        try:
            connection.ensure_connection()
            report("database", "PASS")
        except Exception:  # pragma: no cover - exercised against external failure only
            failures.append("database")
            report("database", "FAIL", "unavailable")

        try:
            redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2).ping()
            report("redis", "PASS")
        except redis.RedisError:
            failures.append("redis")
            report("redis", "FAIL", "unavailable")

        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if pending:
            failures.append("migrations")
            report("migrations", "FAIL", f"{len(pending)} unapplied")
        else:
            report("migrations", "PASS")

        workspace = Workspace.objects.filter(slug="default").first()
        if workspace is None:
            failures.append("workspace")
            report("default workspace", "FAIL", "missing")
        else:
            report("default workspace", "PASS")
            owners = Membership.objects.filter(
                workspace=workspace,
                is_active=True,
                user__is_active=True,
                roles__name="Owner",
            ).count()
            if owners:
                report("workspace owner", "PASS", f"{owners} active")
            else:
                failures.append("owner")
                report("workspace owner", "FAIL", "none active")

            if HuntProfile.objects.filter(workspace=workspace).exists():
                report("hunt profiles", "PASS")
            else:
                warnings.append("hunt_profiles")
                report("hunt profiles", "WARN", "none configured")

        if os.environ.get("SIGNALFORGE_CREDENTIAL_KEY"):
            report("credential encryption key", "PASS", "explicitly configured")
        else:
            warnings.append("credential_key")
            report("credential encryption key", "WARN", "falling back to Django secret key")

        if failures or (options["strict"] and warnings):
            parts = [f"{len(failures)} failure(s)"]
            if warnings:
                parts.append(f"{len(warnings)} warning(s)")
            raise CommandError("Operational readiness failed: " + ", ".join(parts))
        self.stdout.write(
            self.style.SUCCESS(f"Operational readiness passed with {len(warnings)} warning(s)")
        )
