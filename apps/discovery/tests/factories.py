import factory

from apps.core.tests.factories import WorkspaceFactory

from ..models import DiscoveryRun, DiscoveryRunTrigger, SuppressionEntry


class DiscoveryRunFactory(factory.django.DjangoModelFactory):
    """`hunt_profile_version` has no sensible default — pass it explicitly,
    built via `apps.hunting.services.create_version`."""

    class Meta:
        model = DiscoveryRun

    workspace = factory.SubFactory(WorkspaceFactory)
    trigger = DiscoveryRunTrigger.MANUAL


class SuppressionEntryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SuppressionEntry

    workspace = factory.SubFactory(WorkspaceFactory)
    domain = factory.Sequence(lambda n: f"suppressed{n}.com")
    is_active = True
