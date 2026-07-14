import pytest
from django.core.management import call_command

from apps.core.models import Workspace
from apps.core.services import DEFAULT_WORKSPACE_SLUG

pytestmark = pytest.mark.django_db


def test_ensure_default_workspace_is_idempotent():
    call_command("ensure_default_workspace")
    call_command("ensure_default_workspace")

    assert Workspace.objects.filter(slug=DEFAULT_WORKSPACE_SLUG).count() == 1
