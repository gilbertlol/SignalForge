import pytest
from django.db import IntegrityError, transaction

from apps.discovery.models import DiscoveryRunStatus, DiscoveryRunTrigger
from apps.discovery.tests.factories import DiscoveryRunFactory, SuppressionEntryFactory
from apps.hunting.services import create_version
from apps.hunting.tests.factories import HuntProfileFactory

pytestmark = pytest.mark.django_db


def _simple_version(profile):
    return create_version(
        profile,
        criteria={
            "type": "group",
            "operator": "AND",
            "children": [
                {
                    "type": "criterion",
                    "category": "custom_attribute",
                    "field": "domain",
                    "op": "neq",
                    "value": "",
                }
            ],
        },
    )


def test_discovery_run_defaults_to_pending():
    profile = HuntProfileFactory()
    version = _simple_version(profile)

    run = DiscoveryRunFactory(workspace=profile.workspace, hunt_profile_version=version)

    assert run.status == DiscoveryRunStatus.PENDING
    assert run.trigger == DiscoveryRunTrigger.MANUAL
    assert run.records_discovered == 0


def test_suppression_entry_domain_unique_per_workspace():
    entry = SuppressionEntryFactory()

    with pytest.raises(IntegrityError), transaction.atomic():
        SuppressionEntryFactory(workspace=entry.workspace, domain=entry.domain)
