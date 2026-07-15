from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import Membership, User
from apps.core.models import Workspace
from apps.core.services import DEFAULT_WORKSPACE_SLUG
from apps.hunting.models import HuntProfile

pytestmark = pytest.mark.django_db


def test_ensure_default_workspace_is_idempotent():
    call_command("ensure_default_workspace")
    call_command("ensure_default_workspace")

    assert Workspace.objects.filter(slug=DEFAULT_WORKSPACE_SLUG).count() == 1


def test_operational_bootstrap_is_idempotent_and_attaches_existing_superuser():
    owner = User.objects.create_superuser(
        email="existing-owner@example.com", password="safe-password"
    )

    call_command("operational_bootstrap")
    call_command("operational_bootstrap")

    workspace = Workspace.objects.get(slug=DEFAULT_WORKSPACE_SLUG)
    membership = Membership.objects.get(workspace=workspace, user=owner)
    assert membership.roles.filter(name="Owner").exists()
    assert HuntProfile.objects.filter(workspace=workspace).count() == 0


@patch("apps.core.management.commands.operational_check.redis.Redis.from_url")
def test_operational_check_passes_after_bootstrap(mock_redis, capsys):
    mock_redis.return_value.ping.return_value = True
    User.objects.create_superuser(email="owner@example.com", password="safe-password")
    call_command("operational_bootstrap")

    call_command("operational_check")

    output = capsys.readouterr().out
    assert "[PASS] database" in output
    assert "[PASS] workspace owner" in output
    assert "Operational readiness passed" in output


@patch("apps.core.management.commands.operational_check.redis.Redis.from_url")
def test_operational_check_fails_without_owner(mock_redis):
    mock_redis.return_value.ping.return_value = True
    call_command("ensure_default_workspace")

    with pytest.raises(CommandError, match="Operational readiness failed"):
        call_command("operational_check")
