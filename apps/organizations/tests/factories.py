import factory

from apps.core.tests.factories import WorkspaceFactory

from ..models import Organization


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organization

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f"Acme {n}")
    domain = factory.Sequence(lambda n: f"acme{n}.example.com")
    dedupe_key = factory.LazyAttribute(lambda o: o.domain)
