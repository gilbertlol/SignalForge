from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.organizations.tests.factories import OrganizationFactory
from apps.risk.models import (
    AcceptancePolicy,
    ControlRecommendation,
    ControlType,
    FactType,
    ObservationSource,
    Override,
    RiskObservation,
    RiskProfile,
)
from apps.risk.services import calculate_risk, ensure_categories
from apps.tasks.models import WorkItem

pytestmark = pytest.mark.django_db


def profile_and_categories():
    organization = OrganizationFactory()
    profile = RiskProfile.objects.create(
        workspace=organization.workspace, organization=organization
    )
    return profile, ensure_categories(organization.workspace)


def observation(profile, category, *, severity=60, explanation="Observed signal", **overrides):
    values = {
        "workspace": profile.workspace,
        "profile": profile,
        "category": category,
        "source": ObservationSource.HUMAN,
        "fact_type": FactType.OBSERVED,
        "source_type": "manual_review",
        "source_id": explanation,
        "explanation": explanation,
        "severity": Decimal(severity),
        "probability": Decimal(severity),
        "impact": Decimal(severity),
        "confidence": Decimal("1"),
        "observed_at": timezone.now(),
        "confirmed": True,
    }
    values.update(overrides)
    return RiskObservation.objects.create(**values)


def test_rule_is_reproducible_and_categories_remain_independent():
    profile, categories = profile_and_categories()
    observation(profile, categories["payment"], severity=75)
    observation(profile, categories["delivery"], severity=30)

    first = calculate_risk(profile, triggered_by="test")
    second = calculate_risk(profile, triggered_by="test")

    assert first.category_scores == second.category_scores
    assert first.category_scores["payment"] == "75.00"
    assert first.category_scores["delivery"] == "30.00"
    assert len(first.category_scores) == 8


def test_stale_observations_are_visible_but_do_not_affect_score():
    profile, categories = profile_and_categories()
    stale = observation(
        profile,
        categories["payment"],
        severity=100,
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    snapshot = calculate_risk(profile, triggered_by="staleness")

    assert snapshot.category_scores["payment"] == "0.00"
    component = snapshot.components["payment"]["observations"][0]
    assert component["observation_id"] == str(stale.pk)
    assert component["stale"] is True


def test_contradictory_evidence_remains_explicit():
    profile, categories = profile_and_categories()
    observation(profile, categories["relationship"], severity=90, explanation="Hostile reply")
    observation(profile, categories["relationship"], severity=10, explanation="Positive meeting")

    snapshot = calculate_risk(profile, triggered_by="contradiction")

    assert snapshot.category_scores["relationship"] == "50.00"
    assert snapshot.components["relationship"]["contradictory_evidence"] is True
    assert len(snapshot.components["relationship"]["observations"]) == 2


def test_ai_suggestion_requires_evidence_and_is_not_silently_confirmed():
    profile, categories = profile_and_categories()
    with pytest.raises(ValidationError, match="AI suggestions require evidence"):
        observation(
            profile,
            categories["strategic"],
            source=ObservationSource.AI_SUGGESTION,
            confirmed=False,
        )


def test_human_override_is_append_only_and_preserves_components():
    profile, categories = profile_and_categories()
    user = UserFactory(workspace_membership=profile.workspace)
    observation(profile, categories["payment"], severity=80)
    override = Override.objects.create(
        workspace=profile.workspace,
        profile=profile,
        category=categories["payment"],
        score=Decimal("25"),
        reason="Verified prepaid contract",
        created_by=user,
        effective_at=timezone.now(),
    )

    snapshot = calculate_risk(profile, triggered_by="override")

    assert snapshot.category_scores["payment"] == "25.00"
    assert snapshot.components["payment"]["observations"][-1]["fact_type"] == "override"
    override.reason = "Changed silently"
    with pytest.raises(ValidationError, match="append-only"):
        override.save()


def test_high_risk_threshold_recommends_control_and_approval_work():
    profile, categories = profile_and_categories()
    observation(profile, categories["payment"], severity=90)
    AcceptancePolicy.objects.create(
        workspace=profile.workspace,
        name="Prepay risky clients",
        category=categories["payment"],
        threshold=Decimal("70"),
        control_type=ControlType.PREPAYMENT,
        requires_approval=True,
    )

    snapshot = calculate_risk(profile, triggered_by="policy")

    recommendation = ControlRecommendation.objects.get(snapshot=snapshot)
    assert recommendation.control_type == ControlType.PREPAYMENT
    assert recommendation.requires_approval is True
    assert WorkItem.objects.filter(
        workspace=profile.workspace,
        context_type="risk_recommendation",
        context_id=str(recommendation.pk),
    ).exists()
    assert profile.workspace_id == recommendation.workspace_id


def test_snapshots_are_immutable():
    profile, _ = profile_and_categories()
    snapshot = calculate_risk(profile, triggered_by="history")
    snapshot.triggered_by = "rewrite"
    with pytest.raises(ValidationError, match="immutable"):
        snapshot.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        snapshot.delete()
