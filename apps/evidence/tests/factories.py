import datetime

import factory

from apps.organizations.tests.factories import OrganizationFactory

from ..models import Evidence, Reliability, SourceType


class EvidenceFactory(factory.django.DjangoModelFactory):
    """`subject` (an Organization or Opportunity instance) sets content_type/object_id
    via Django's GenericForeignKey descriptor; `workspace` mirrors it automatically.
    """

    class Meta:
        model = Evidence

    subject = factory.SubFactory(OrganizationFactory)
    workspace = factory.SelfAttribute("subject.workspace")
    source_type = SourceType.WEBSITE
    observed_date = factory.LazyFunction(datetime.date.today)
    excerpt = factory.Sequence(lambda n: f"Evidence excerpt {n}")
    reliability = Reliability.MEDIUM
