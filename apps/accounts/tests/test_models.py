import uuid

import pytest

from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_create_user_normalizes_email_and_sets_usable_password():
    user = User.objects.create_user(email="Person@Example.com", password="s3cret-pass")

    assert isinstance(user.id, uuid.UUID)
    assert user.email == "Person@example.com"
    assert user.check_password("s3cret-pass")
    assert user.is_active is True
    assert user.is_staff is False
    assert user.is_superuser is False


def test_create_user_requires_email():
    with pytest.raises(ValueError, match="email"):
        User.objects.create_user(email="", password="whatever")


def test_create_superuser_sets_staff_and_superuser_flags():
    admin = User.objects.create_superuser(email="owner@example.com", password="s3cret-pass")

    assert admin.is_staff is True
    assert admin.is_superuser is True


def test_create_superuser_rejects_explicit_non_staff():
    with pytest.raises(ValueError, match="is_staff"):
        User.objects.create_superuser(
            email="owner@example.com", password="s3cret-pass", is_staff=False
        )


def test_user_factory_produces_usable_password():
    user = UserFactory()

    assert user.check_password("temporary-pass-123")
