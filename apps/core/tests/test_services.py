import pytest

from apps.core.models import Workspace
from apps.core.services import DEFAULT_WORKSPACE_SLUG, get_default_workspace

pytestmark = pytest.mark.django_db


def test_get_default_workspace_creates_once_and_reuses():
    workspace = get_default_workspace()
    assert workspace.slug == DEFAULT_WORKSPACE_SLUG

    same_workspace = get_default_workspace()
    assert same_workspace.id == workspace.id
    assert Workspace.objects.filter(slug=DEFAULT_WORKSPACE_SLUG).count() == 1
