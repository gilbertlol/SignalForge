from datetime import UTC, datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.contacts.tests.factories import ContactFactory
from apps.core.tests.factories import WorkspaceFactory
from apps.opportunities.tests.factories import OpportunityFactory
from apps.organizations.tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


def test_contacted_property_reflects_first_contacted_at():
    opportunity = OpportunityFactory()
    assert opportunity.contacted is False

    opportunity.first_contacted_at = datetime.now(tz=UTC)
    opportunity.save()

    assert opportunity.contacted is True


def test_organization_deletion_is_protected_while_opportunities_exist():
    opportunity = OpportunityFactory()

    with pytest.raises(IntegrityError):
        opportunity.organization.delete(hard=True)


def test_organization_must_share_opportunitys_workspace():
    workspace = WorkspaceFactory()
    other_workspace_org = OrganizationFactory()

    with pytest.raises(ValidationError):
        OpportunityFactory(workspace=workspace, organization=other_workspace_org)


def test_primary_contact_must_belong_to_opportunitys_organization():
    opportunity = OpportunityFactory()
    unrelated_contact = ContactFactory(workspace=opportunity.workspace)

    opportunity.primary_contact = unrelated_contact

    with pytest.raises(ValidationError):
        opportunity.save()
