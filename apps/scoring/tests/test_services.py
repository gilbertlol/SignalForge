import datetime

import pytest

from apps.evidence.models import Reliability
from apps.evidence.tests.factories import EvidenceFactory
from apps.opportunities.tests.factories import OpportunityFactory
from apps.organizations.tests.factories import OrganizationFactory
from apps.scoring.exceptions import ImmutableRecordError
from apps.scoring.models import ScoreFamily, ScoreSnapshot
from apps.scoring.services import evaluate, latest_snapshot
from apps.scoring.tests.factories import ScoreThresholdFactory, ScoringRuleFactory

pytestmark = pytest.mark.django_db


def test_evaluate_is_reproducible_for_unchanged_inputs():
    org = OrganizationFactory(domain="acme.com")
    ScoringRuleFactory(
        workspace=org.workspace,
        family=ScoreFamily.PROSPECT_QUALITY,
        key="has_domain",
        points=15,
        conditions={"field": "domain", "op": "neq", "value": ""},
    )

    first = evaluate(org, ScoreFamily.PROSPECT_QUALITY)
    second = evaluate(org, ScoreFamily.PROSPECT_QUALITY)

    assert first.value == second.value == 15
    assert first.components == second.components


def test_hard_disqualifier_overrides_positive_scoring():
    org = OrganizationFactory(domain="acme.com")
    ScoringRuleFactory(
        workspace=org.workspace,
        family=ScoreFamily.PROSPECT_QUALITY,
        key="has_domain",
        points=50,
        conditions={"field": "domain", "op": "neq", "value": ""},
    )
    ScoringRuleFactory(
        workspace=org.workspace,
        family=ScoreFamily.PROSPECT_QUALITY,
        key="blocklisted_domain",
        points=0,
        is_hard_disqualifier=True,
        conditions={"field": "domain", "op": "eq", "value": "acme.com"},
    )

    snapshot = evaluate(org, ScoreFamily.PROSPECT_QUALITY)

    assert snapshot.value == 0
    assert snapshot.is_hard_disqualified is True
    matched_keys = {c["rule_key"] for c in snapshot.components if c["matched"]}
    assert matched_keys == {"has_domain", "blocklisted_domain"}


def test_stale_evidence_lowers_confidence_score():
    fresh_org = OrganizationFactory()
    EvidenceFactory(
        subject=fresh_org,
        observed_date=datetime.date.today(),
        reliability=Reliability.HIGH,
    )
    stale_org = OrganizationFactory(workspace=fresh_org.workspace)
    EvidenceFactory(
        subject=stale_org,
        observed_date=datetime.date.today() - datetime.timedelta(days=400),
        reliability=Reliability.HIGH,
    )
    ScoringRuleFactory(
        workspace=fresh_org.workspace,
        family=ScoreFamily.SCORE_CONFIDENCE,
        key="recent_evidence",
        points=20,
        conditions={"field": "max_age_days", "op": "lte", "value": 90},
    )

    fresh_snapshot = evaluate(fresh_org, ScoreFamily.SCORE_CONFIDENCE)
    stale_snapshot = evaluate(stale_org, ScoreFamily.SCORE_CONFIDENCE)

    assert fresh_snapshot.value == 20
    assert stale_snapshot.value == 0


def test_threshold_resolves_label():
    org = OrganizationFactory()
    ScoreThresholdFactory(
        workspace=org.workspace, family=ScoreFamily.PROSPECT_QUALITY, label="cold", min_value=0
    )
    ScoreThresholdFactory(
        workspace=org.workspace,
        family=ScoreFamily.PROSPECT_QUALITY,
        label="qualified",
        min_value=50,
    )
    ScoringRuleFactory(
        workspace=org.workspace,
        family=ScoreFamily.PROSPECT_QUALITY,
        key="always",
        points=60,
        conditions={},
    )

    snapshot = evaluate(org, ScoreFamily.PROSPECT_QUALITY)

    assert snapshot.label == "qualified"


def test_score_snapshot_is_immutable_after_creation():
    org = OrganizationFactory()
    snapshot = evaluate(org, ScoreFamily.PROSPECT_QUALITY)

    snapshot.value = 999
    with pytest.raises(ImmutableRecordError):
        snapshot.save()


def test_latest_snapshot_returns_most_recent():
    org = OrganizationFactory()
    ScoringRuleFactory(
        workspace=org.workspace,
        family=ScoreFamily.PROSPECT_QUALITY,
        key="always",
        points=10,
        conditions={},
    )

    evaluate(org, ScoreFamily.PROSPECT_QUALITY)
    second = evaluate(org, ScoreFamily.PROSPECT_QUALITY)

    latest = latest_snapshot(org, ScoreFamily.PROSPECT_QUALITY)
    assert latest is not None
    assert latest.id == second.id
    assert ScoreSnapshot.objects.count() == 2


def test_opportunity_can_be_scored_too():
    opportunity = OpportunityFactory()
    ScoringRuleFactory(
        workspace=opportunity.workspace,
        family=ScoreFamily.OPPORTUNITY_SCORE,
        key="contacted",
        points=25,
        conditions={"field": "contacted", "op": "eq", "value": True},
    )

    snapshot = evaluate(opportunity, ScoreFamily.OPPORTUNITY_SCORE)
    assert snapshot.value == 0

    opportunity.first_contacted_at = datetime.datetime.now(tz=datetime.UTC)
    opportunity.save()
    snapshot = evaluate(opportunity, ScoreFamily.OPPORTUNITY_SCORE)
    assert snapshot.value == 25
