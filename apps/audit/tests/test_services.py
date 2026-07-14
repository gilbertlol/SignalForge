import pytest

from apps.accounts.tests.factories import UserFactory
from apps.audit.models import AuditLogEntry
from apps.audit.services import record

pytestmark = pytest.mark.django_db


def test_record_creates_an_entry_with_actor_and_metadata():
    user = UserFactory()

    entry = record(
        "organization.created",
        actor=user,
        object_type="organization",
        object_id="1234",
        metadata={"source": "manual"},
    )

    assert AuditLogEntry.objects.count() == 1
    assert entry.actor == user
    assert entry.action == "organization.created"
    assert entry.metadata == {"source": "manual"}


def test_record_allows_a_null_actor_for_system_actions():
    entry = record("system.startup")

    assert entry.actor is None
    assert entry.metadata == {}
