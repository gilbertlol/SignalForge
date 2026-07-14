import datetime

import pytest

from apps.evidence.models import Reliability, SourceType
from apps.evidence.services import record_evidence
from apps.organizations.tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


def test_record_evidence_derives_workspace_and_content_type_from_subject():
    org = OrganizationFactory()

    evidence = record_evidence(
        org,
        source_type=SourceType.NEWS,
        observed_date=datetime.date.today(),
        excerpt="Raised a Series A.",
        reliability=Reliability.HIGH,
    )

    assert evidence.subject == org
    assert evidence.workspace_id == org.workspace_id
