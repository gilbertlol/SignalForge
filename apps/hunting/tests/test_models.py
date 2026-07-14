import pytest
from django.db import IntegrityError, transaction

from apps.hunting.models import CriterionGroup, CriterionOperator
from apps.hunting.tests.factories import HuntProfileFactory, KeywordSetFactory, ValueSignalFactory

pytestmark = pytest.mark.django_db


def test_criterion_group_can_nest():
    root = CriterionGroup.objects.create(operator=CriterionOperator.AND)
    child = CriterionGroup.objects.create(operator=CriterionOperator.OR, parent=root)

    assert child in root.children.all()
    assert child.parent_id == root.id


def test_keyword_set_name_unique_per_workspace():
    keyword_set = KeywordSetFactory()

    with pytest.raises(IntegrityError), transaction.atomic():
        KeywordSetFactory(workspace=keyword_set.workspace, name=keyword_set.name)


def test_value_signal_key_unique_per_workspace():
    signal = ValueSignalFactory()

    with pytest.raises(IntegrityError), transaction.atomic():
        ValueSignalFactory(workspace=signal.workspace, key=signal.key)


def test_hunt_profile_defaults_to_draft_with_no_current_version():
    profile = HuntProfileFactory()

    assert profile.status == "draft"
    assert profile.current_version is None
