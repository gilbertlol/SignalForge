import factory

from apps.core.tests.factories import WorkspaceFactory
from apps.organizations.tests.factories import OrganizationFactory

from ..models import Contact


class ContactFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Contact

    workspace = factory.SubFactory(WorkspaceFactory)
    organization = factory.SubFactory(
        OrganizationFactory, workspace=factory.SelfAttribute("..workspace")
    )
    first_name = factory.Sequence(lambda n: f"Jamie{n}")
    last_name = "Rivera"
    email = factory.LazyAttribute(lambda o: f"{o.first_name.lower()}@example.com")
    dedupe_key = factory.LazyAttribute(lambda o: o.email)
