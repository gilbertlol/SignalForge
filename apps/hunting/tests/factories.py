import factory

from apps.core.tests.factories import WorkspaceFactory

from ..models import HuntProfile, KeywordSet, ValueSignal


class HuntProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HuntProfile

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f"Hunt Profile {n}")


class KeywordSetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = KeywordSet

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f"Keywords {n}")
    keywords = factory.LazyFunction(lambda: ["crm", "automation"])


class ValueSignalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ValueSignal

    workspace = factory.SubFactory(WorkspaceFactory)
    key = factory.Sequence(lambda n: f"signal_{n}")
    weight = 5
