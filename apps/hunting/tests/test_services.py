import datetime

import pytest
from django.core.exceptions import ValidationError

from apps.evidence.models import Reliability, SourceType
from apps.evidence.services import record_evidence
from apps.hunting.models import HuntProfileStatus, ScheduleFrequency
from apps.hunting.services import (
    activate_version,
    archive,
    clone_profile,
    create_version,
    dry_run,
    ensure_schedule_policy,
    evaluate_candidate,
    pause,
    serialize_criteria_tree,
    validate_criteria_tree,
)
from apps.hunting.tests.factories import HuntProfileFactory, KeywordSetFactory
from apps.organizations.tests.factories import OrganizationFactory
from apps.scoring.models import ScoreFamily
from apps.scoring.services import evaluate
from apps.scoring.tests.factories import ScoringRuleFactory

pytestmark = pytest.mark.django_db


def _leaf(field, op, value, **extra):
    return {
        "type": "criterion",
        "category": "custom_attribute",
        "field": field,
        "op": op,
        "value": value,
        "weight": 1,
        "is_required": False,
        "is_hard_disqualifier": False,
        **extra,
    }


def _group(operator, children):
    return {"type": "group", "operator": operator, "children": children}


# --- schema validation -------------------------------------------------


def test_validate_rejects_group_missing_children():
    with pytest.raises(ValidationError):
        validate_criteria_tree({"type": "group", "operator": "AND", "children": []})


def test_validate_rejects_unknown_operator():
    with pytest.raises(ValidationError):
        validate_criteria_tree(
            {"type": "group", "operator": "XOR", "children": [_leaf("domain", "eq", "x")]}
        )


def test_validate_rejects_not_group_with_two_children():
    tree = _group("NOT", [_leaf("domain", "eq", "a"), _leaf("domain", "eq", "b")])
    with pytest.raises(ValidationError, match="NOT group"):
        validate_criteria_tree(tree)


def test_validate_accepts_well_formed_tree():
    tree = _group("AND", [_leaf("domain", "neq", "")])
    validate_criteria_tree(tree)  # does not raise


# --- create_version / versioning ----------------------------------------


def test_create_version_builds_expected_tree():
    profile = HuntProfileFactory()
    tree = _group(
        "AND",
        [_leaf("domain", "neq", "", weight=5, is_required=True, is_hard_disqualifier=False)],
    )

    version = create_version(profile, criteria=tree)

    assert version.version_number == 1
    assert version.root_group.operator == "AND"
    criterion = version.root_group.criteria.get()
    assert criterion.field == "domain"
    assert criterion.weight == 5
    assert criterion.is_required is True
    assert serialize_criteria_tree(version.root_group) == tree


def test_create_version_increments_and_leaves_prior_version_untouched():
    profile = HuntProfileFactory()
    v1 = create_version(profile, criteria=_group("AND", [_leaf("domain", "neq", "")]))
    v2 = create_version(profile, criteria=_group("OR", [_leaf("name", "eq", "Acme")]))

    assert v1.version_number == 1
    assert v2.version_number == 2
    v1.refresh_from_db()
    assert v1.root_group.operator == "AND"  # untouched by v2's creation


def test_create_version_resolves_keyword_set_reference():
    profile = HuntProfileFactory()
    keyword_set = KeywordSetFactory(workspace=profile.workspace, name="pain keywords")
    tree = _group("AND", [_leaf("domain", "in", ["a"], keyword_set="pain keywords")])

    version = create_version(profile, criteria=tree)

    criterion = version.root_group.criteria.get()
    assert criterion.keyword_set_id == keyword_set.id


def test_create_version_rejects_unknown_keyword_set_reference():
    profile = HuntProfileFactory()
    tree = _group("AND", [_leaf("domain", "in", ["a"], keyword_set="does-not-exist")])

    with pytest.raises(ValidationError, match="Unknown keyword_set"):
        create_version(profile, criteria=tree)


# --- lifecycle -----------------------------------------------------------


def test_activate_version_swaps_current_version_and_status():
    profile = HuntProfileFactory()
    v1 = create_version(profile, criteria=_group("AND", [_leaf("domain", "neq", "")]))
    v2 = create_version(profile, criteria=_group("OR", [_leaf("name", "eq", "Acme")]))

    activate_version(profile, v1)
    assert profile.current_version_id == v1.id
    assert profile.status == HuntProfileStatus.ACTIVE

    activate_version(profile, v2)
    assert profile.current_version_id == v2.id


def test_pause_and_archive_transition_status():
    profile = HuntProfileFactory()
    create_version(profile, criteria=_group("AND", [_leaf("domain", "neq", "")]))

    pause(profile)
    assert profile.status == HuntProfileStatus.PAUSED

    archive(profile)
    assert profile.status == HuntProfileStatus.ARCHIVED


def test_clone_profile_copies_the_current_versions_tree():
    profile = HuntProfileFactory()
    tree = _group("AND", [_leaf("domain", "neq", "", weight=7)])
    version = create_version(profile, criteria=tree)
    activate_version(profile, version)

    clone = clone_profile(profile, name="Clone of profile")

    assert clone.id != profile.id
    assert clone.status == HuntProfileStatus.DRAFT
    assert clone.current_version.version_number == 1
    assert serialize_criteria_tree(clone.current_version.root_group) == tree


def test_clone_profile_requires_a_current_version():
    profile = HuntProfileFactory()
    with pytest.raises(ValidationError):
        clone_profile(profile, name="Clone")


def test_ensure_schedule_policy_creates_once_and_reuses():
    profile = HuntProfileFactory()

    policy = ensure_schedule_policy(profile, frequency=ScheduleFrequency.DAILY, is_enabled=True)
    assert policy.workspace_id == profile.workspace_id
    assert policy.frequency == ScheduleFrequency.DAILY

    same_policy = ensure_schedule_policy(profile, frequency=ScheduleFrequency.WEEKLY)
    assert same_policy.id == policy.id
    assert same_policy.frequency == ScheduleFrequency.DAILY  # get_or_create: unchanged on reuse


# --- dry-run ---------------------------------------------------------------


def test_evaluate_candidate_matches_dry_run_for_a_single_organization():
    profile = HuntProfileFactory()
    org = OrganizationFactory(workspace=profile.workspace, domain="acme.com", name="Acme")
    version = create_version(profile, criteria=_group("AND", [_leaf("domain", "neq", "")]))

    direct = evaluate_candidate(version, org)
    [via_dry_run] = dry_run(version, organizations=[org])

    assert direct == via_dry_run
    assert direct["matched"] is True


def test_dry_run_and_requires_all_children_to_match():
    profile = HuntProfileFactory()
    org = OrganizationFactory(workspace=profile.workspace, domain="acme.com", name="Acme")
    tree = _group("AND", [_leaf("domain", "neq", ""), _leaf("name", "eq", "Nonexistent")])
    version = create_version(profile, criteria=tree)

    [result] = dry_run(version, organizations=[org])

    assert result["matched"] is False


def test_dry_run_or_matches_if_any_child_matches():
    profile = HuntProfileFactory()
    org = OrganizationFactory(workspace=profile.workspace, domain="acme.com", name="Acme")
    tree = _group("OR", [_leaf("name", "eq", "Nonexistent"), _leaf("domain", "neq", "")])
    version = create_version(profile, criteria=tree)

    [result] = dry_run(version, organizations=[org])

    assert result["matched"] is True


def test_dry_run_not_negates_single_child():
    profile = HuntProfileFactory()
    org = OrganizationFactory(workspace=profile.workspace, domain="acme.com")
    tree = _group("NOT", [_leaf("domain", "eq", "other.com")])
    version = create_version(profile, criteria=tree)

    [result] = dry_run(version, organizations=[org])

    assert result["matched"] is True  # org's domain is NOT "other.com"


def test_dry_run_required_criterion_gates_across_or_branch():
    profile = HuntProfileFactory()
    org = OrganizationFactory(workspace=profile.workspace, domain="acme.com", name="Acme")
    tree = _group(
        "OR",
        [
            _leaf("domain", "eq", "never-matches.com", is_required=True),
            _leaf("name", "eq", "Acme"),
        ],
    )
    version = create_version(profile, criteria=tree)

    [result] = dry_run(version, organizations=[org])

    # OR matches (name matches) but the required criterion didn't, so overall no match
    assert result["matched"] is False


def test_dry_run_hard_disqualifier_excludes_regardless_of_match():
    profile = HuntProfileFactory()
    org = OrganizationFactory(workspace=profile.workspace, domain="acme.com")
    tree = _group(
        "OR",
        [
            _leaf("domain", "neq", "", is_hard_disqualifier=True),
            _leaf("domain", "eq", "irrelevant"),
        ],
    )
    version = create_version(profile, criteria=tree)

    [result] = dry_run(version, organizations=[org])

    assert result["excluded"] is True
    assert result["recommended_next_action"] == "excluded"


def test_dry_run_weight_summation_against_threshold():
    profile = HuntProfileFactory()
    org = OrganizationFactory(workspace=profile.workspace, domain="acme.com", name="Acme")
    tree = _group(
        "AND", [_leaf("domain", "neq", "", weight=10), _leaf("name", "eq", "Acme", weight=5)]
    )
    version = create_version(profile, criteria=tree, result_threshold={"min_total_score": 20})

    [result] = dry_run(version, organizations=[org])
    assert result["total_weight"] == 15
    assert result["recommended_next_action"] == "below_threshold"

    version2 = create_version(profile, criteria=tree, result_threshold={"min_total_score": 10})
    [result2] = dry_run(version2, organizations=[org])
    assert result2["recommended_next_action"] == "review_queue"


def test_dry_run_exclusion_rule_excludes_candidate():
    profile = HuntProfileFactory()
    org = OrganizationFactory(workspace=profile.workspace, domain="acme.com")
    tree = _group("AND", [_leaf("domain", "neq", "")])
    version = create_version(
        profile,
        criteria=tree,
        exclusion_rules=[{"field": "domain", "op": "eq", "value": "acme.com", "reason": "blocked"}],
    )

    [result] = dry_run(version, organizations=[org])

    assert result["excluded"] is True
    assert result["exclusion_reason"] == "blocked"
    assert result["recommended_next_action"] == "excluded"


def test_dry_run_criterion_can_reference_evidence_context():
    profile = HuntProfileFactory()
    org = OrganizationFactory(workspace=profile.workspace, domain="acme.com")
    record_evidence(
        org,
        source_type=SourceType.NEWS,
        observed_date=datetime.date(2020, 1, 1),
        excerpt="test",
        reliability=Reliability.HIGH,
    )
    tree = _group("AND", [_leaf("evidence_count", "gte", 1)])
    version = create_version(profile, criteria=tree)

    [result] = dry_run(version, organizations=[org])

    assert result["matched"] is True
    assert result["evidence_count"] == 1


def test_dry_run_respects_minimum_evidence_confidence():
    profile = HuntProfileFactory()
    org = OrganizationFactory(workspace=profile.workspace, domain="acme.com")
    ScoringRuleFactory(
        workspace=profile.workspace,
        family=ScoreFamily.SCORE_CONFIDENCE,
        key="base",
        points=30,
        conditions={},
    )
    evaluate(org, ScoreFamily.SCORE_CONFIDENCE)

    tree = _group("AND", [_leaf("domain", "neq", "")])
    version = create_version(
        profile,
        criteria=tree,
        result_threshold={"min_total_score": 0, "min_evidence_confidence": 50},
    )

    [result] = dry_run(version, organizations=[org])

    assert result["score_confidence"] == 30
    assert result["recommended_next_action"] == "below_threshold"


def test_dry_run_is_reproducible():
    profile = HuntProfileFactory()
    org = OrganizationFactory(workspace=profile.workspace, domain="acme.com", name="Acme")
    tree = _group("AND", [_leaf("domain", "neq", "", weight=3)])
    version = create_version(profile, criteria=tree)

    first = dry_run(version, organizations=[org])
    second = dry_run(version, organizations=[org])

    assert first == second
