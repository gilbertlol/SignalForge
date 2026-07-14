import pytest
from django.db import IntegrityError, transaction

from apps.organizations.tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


def test_dedupe_key_is_unique_per_workspace():
    org = OrganizationFactory()

    with pytest.raises(IntegrityError), transaction.atomic():
        OrganizationFactory(workspace=org.workspace, dedupe_key=org.dedupe_key)


def test_dedupe_key_can_repeat_across_workspaces():
    org = OrganizationFactory()

    other = OrganizationFactory(dedupe_key=org.dedupe_key)

    assert other.workspace_id != org.workspace_id
