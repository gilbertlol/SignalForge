import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.contacts.tests.factories import ContactFactory
from apps.core.tests.factories import WorkspaceFactory
from apps.organizations.tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


def test_multiple_contacts_with_blank_email_are_allowed():
    workspace = WorkspaceFactory()

    ContactFactory(workspace=workspace, email="", dedupe_key="")
    ContactFactory(workspace=workspace, email="", dedupe_key="")

    assert workspace is not None  # no IntegrityError raised above


def test_dedupe_key_is_unique_per_workspace_when_set():
    contact = ContactFactory()

    with pytest.raises(IntegrityError), transaction.atomic():
        ContactFactory(workspace=contact.workspace, dedupe_key=contact.dedupe_key)


def test_organization_must_share_contacts_workspace():
    workspace = WorkspaceFactory()
    other_workspace_org = OrganizationFactory()

    with pytest.raises(ValidationError):
        ContactFactory(workspace=workspace, organization=other_workspace_org)
