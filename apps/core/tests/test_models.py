import uuid

import pytest

from apps.core.models import Workspace
from apps.core.tests.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


def test_workspace_gets_uuid_pk_and_timestamps():
    workspace = WorkspaceFactory()

    assert isinstance(workspace.id, uuid.UUID)
    assert workspace.created_at is not None
    assert workspace.updated_at is not None
    assert workspace.deleted_at is None


def test_soft_delete_excludes_from_default_manager():
    workspace = WorkspaceFactory()

    workspace.delete()

    assert not Workspace.objects.filter(id=workspace.id).exists()
    assert Workspace.all_objects.filter(id=workspace.id).exists()

    reloaded = Workspace.all_objects.get(id=workspace.id)
    assert reloaded.deleted_at is not None


def test_hard_delete_removes_row():
    workspace = WorkspaceFactory()
    workspace_id = workspace.id

    workspace.delete(hard=True)

    assert not Workspace.all_objects.filter(id=workspace_id).exists()


def test_workspace_slug_must_be_unique():
    WorkspaceFactory(slug="acme")

    with pytest.raises(Exception):  # noqa: B017 - IntegrityError raised at the DB layer
        WorkspaceFactory(slug="acme")
