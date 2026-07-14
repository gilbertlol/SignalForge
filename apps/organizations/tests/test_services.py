import pytest

from apps.core.tests.factories import WorkspaceFactory
from apps.organizations.models import Organization
from apps.organizations.services import find_or_create_by_domain, normalize_domain

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.Acme.com/about", "acme.com"),
        ("http://acme.com", "acme.com"),
        ("acme.com", "acme.com"),
        ("ACME.COM/", "acme.com"),
        ("acme.com:8080", "acme.com"),
    ],
)
def test_normalize_domain(raw, expected):
    assert normalize_domain(raw) == expected


def test_find_or_create_by_domain_creates_once_and_reuses():
    workspace = WorkspaceFactory()

    org, created = find_or_create_by_domain(workspace, "https://www.Acme.com/")
    assert created is True
    assert org.dedupe_key == "acme.com"

    same_org, created_again = find_or_create_by_domain(workspace, "acme.com")
    assert created_again is False
    assert same_org.id == org.id
    assert Organization.objects.filter(workspace=workspace, dedupe_key="acme.com").count() == 1


def test_find_or_create_by_domain_respects_defaults():
    workspace = WorkspaceFactory()

    org, _ = find_or_create_by_domain(workspace, "acme.com", defaults={"name": "Acme Inc"})

    assert org.name == "Acme Inc"
