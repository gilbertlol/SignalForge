import factory

from apps.core.tests.factories import WorkspaceFactory
from apps.organizations.tests.factories import OrganizationFactory

from ..models import Opportunity


class OpportunityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Opportunity

    workspace = factory.SubFactory(WorkspaceFactory)
    organization = factory.SubFactory(
        OrganizationFactory, workspace=factory.SelfAttribute("..workspace")
    )
    title = factory.Sequence(lambda n: f"Opportunity {n}")
