import pytest

from apps.contacts.models import Contact
from apps.contacts.services import find_or_create_by_email
from apps.core.tests.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


def test_find_or_create_by_email_creates_once_and_reuses():
    workspace = WorkspaceFactory()

    contact, created = find_or_create_by_email(workspace, "  Person@Example.com ")
    assert created is True
    assert contact.dedupe_key == "person@example.com"

    same_contact, created_again = find_or_create_by_email(workspace, "person@example.com")
    assert created_again is False
    assert same_contact.id == contact.id
    assert Contact.objects.filter(workspace=workspace).count() == 1
