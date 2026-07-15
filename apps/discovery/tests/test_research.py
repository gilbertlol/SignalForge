from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from apps.discovery.research import (
    ORGANIZATION_EXTRACTION,
    QUERY_PLANNING,
    extract_from_evidence,
    plan_search_queries,
)
from apps.hunting.services import create_version
from apps.hunting.tests.factories import HuntProfileFactory
from apps.integrations.models import ModelRoute
from apps.organizations.tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


def _version(profile):
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


def test_query_planning_has_a_deterministic_non_ai_fallback():
    profile = HuntProfileFactory()

    queries = plan_search_queries(
        _version(profile),
        {"industries": ["precision manufacturing"], "geographies": ["Montreal"]},
    )

    assert queries == ["precision manufacturing Montreal"]


@patch("apps.discovery.research.invoke")
def test_query_planning_bounds_and_rejects_model_generated_urls(mock_invoke):
    profile = HuntProfileFactory()
    ModelRoute.objects.create(
        workspace=profile.workspace,
        task_type=QUERY_PLANNING,
        name="Local planner",
        is_default=True,
    )
    mock_invoke.return_value = SimpleNamespace(
        parsed={
            "queries": [
                "manufacturers expanding in Quebec",
                "http://internal.example/private",
            ]
        }
    )

    queries = plan_search_queries(_version(profile), {"industries": ["manufacturing"]})

    assert queries == ["manufacturers expanding in Quebec"]


@patch("apps.discovery.research.invoke")
def test_extraction_rejects_citations_not_present_in_stored_evidence(mock_invoke):
    organization = OrganizationFactory()
    ModelRoute.objects.create(
        workspace=organization.workspace,
        task_type=ORGANIZATION_EXTRACTION,
        name="Local extractor",
        is_default=True,
    )
    evidence_id = uuid4()
    evidence = SimpleNamespace(
        id=evidence_id,
        source_url="https://example.com",
        excerpt="Observed public statement",
        observed_date=SimpleNamespace(isoformat=lambda: "2026-07-15"),
    )
    mock_invoke.return_value = SimpleNamespace(
        parsed={
            "company": {"name": "Acme", "domain": "", "industry": "", "location": ""},
            "claims": [{"statement": "Unsupported", "evidence_ids": [str(uuid4())]}],
            "buying_signals": [],
            "summary": "Review",
        },
        invocation=SimpleNamespace(id=uuid4()),
    )

    result = extract_from_evidence(
        workspace=organization.workspace,
        organization=organization,
        evidence_rows=[evidence],
    )

    assert result is None
