import datetime

import pytest
from django.core.exceptions import ValidationError

from apps.contacts.tests.factories import ContactFactory
from apps.core.tests.factories import WorkspaceFactory
from apps.evidence.tests.factories import EvidenceFactory
from apps.opportunities.tests.factories import OpportunityFactory
from apps.organizations.tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


def test_evidence_attaches_to_an_organization():
    org = OrganizationFactory()
    evidence = EvidenceFactory(subject=org)

    assert evidence.subject == org
    assert evidence.workspace_id == org.workspace_id


def test_evidence_attaches_to_an_opportunity():
    opportunity = OpportunityFactory()
    evidence = EvidenceFactory(subject=opportunity, workspace=opportunity.workspace)

    assert evidence.subject == opportunity


def test_evidence_rejects_unsupported_subject_types():
    workspace = WorkspaceFactory()
    contact = ContactFactory(workspace=workspace)

    with pytest.raises(ValidationError):
        EvidenceFactory(subject=contact, workspace=workspace)


def test_evidence_workspace_must_match_subjects_workspace():
    org = OrganizationFactory()
    other_workspace = WorkspaceFactory()

    with pytest.raises(ValidationError):
        EvidenceFactory(subject=org, workspace=other_workspace)


def test_age_days_computed_from_observed_date():
    evidence = EvidenceFactory(observed_date=datetime.date.today() - datetime.timedelta(days=10))

    assert evidence.age_days == 10
