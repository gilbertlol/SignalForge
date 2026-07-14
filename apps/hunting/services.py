"""Hunt profile lifecycle, criteria-tree construction, and the dry-run engine.

Everything that mutates a `HuntProfile`'s criteria goes through here —
`create_version` is the only way a criteria tree is ever written, and
nothing under a version is ever updated afterward (see model docstrings).
"""

from typing import Any, TypeVar

import jsonschema
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Model

from apps.core.conditions import evaluate_condition
from apps.core.models import Workspace
from apps.evidence.services import build_evidence_context
from apps.organizations.models import Organization
from apps.scoring.services import latest_snapshot

from .models import (
    CriterionGroup,
    CriterionOperator,
    ExclusionRule,
    HuntCriterion,
    HuntProfile,
    HuntProfileStatus,
    HuntProfileVersion,
    KeywordSet,
    ResultThreshold,
    SchedulePolicy,
    SearchScope,
    SourcePolicy,
    ValueSignal,
)

_M = TypeVar("_M", bound=Model)

# --- Criteria JSON schema -------------------------------------------------

_NODE_REF = {"$ref": "#/$defs/node"}

_CRITERION_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"const": "criterion"},
        "category": {"type": "string"},
        "field": {"type": "string", "minLength": 1},
        "op": {"type": "string", "enum": ["eq", "neq", "in", "between", "gte", "lte"]},
        "value": {},
        "weight": {"type": "integer"},
        "is_required": {"type": "boolean"},
        "is_hard_disqualifier": {"type": "boolean"},
        "keyword_set": {"type": "string"},
        "value_signal": {"type": "string"},
    },
    "required": ["type", "category", "field", "op"],
    "additionalProperties": False,
}

_GROUP_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"const": "group"},
        "operator": {"enum": [choice.value for choice in CriterionOperator]},
        "children": {"type": "array", "items": _NODE_REF, "minItems": 1},
    },
    "required": ["type", "operator", "children"],
    "additionalProperties": False,
}

CRITERIA_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$defs": {"node": {"oneOf": [_CRITERION_SCHEMA, _GROUP_SCHEMA]}},
    **_GROUP_SCHEMA,
}


def validate_criteria_tree(criteria: dict[str, Any]) -> None:
    """Raise `ValidationError` if `criteria` isn't a well-formed root group node."""
    try:
        jsonschema.validate(criteria, CRITERIA_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValidationError(f"Invalid criteria tree: {exc.message}") from exc
    _validate_not_arity(criteria)


def _validate_not_arity(node: dict[str, Any]) -> None:
    if node["type"] == "group":
        if node["operator"] == CriterionOperator.NOT and len(node["children"]) != 1:
            raise ValidationError("A NOT group must have exactly one child.")
        for child in node["children"]:
            _validate_not_arity(child)


# --- Version construction --------------------------------------------------


@transaction.atomic
def create_version(
    profile: HuntProfile,
    *,
    criteria: dict[str, Any],
    search_scope: dict[str, Any] | None = None,
    source_policies: list[dict[str, Any]] | None = None,
    exclusion_rules: list[dict[str, Any]] | None = None,
    result_threshold: dict[str, Any] | None = None,
) -> HuntProfileVersion:
    """Build an entirely new, immutable `HuntProfileVersion` in one transaction.

    `criteria` is the JSON representation validated by `validate_criteria_tree`.
    """
    validate_criteria_tree(criteria)

    root_group = _build_group(profile.workspace, criteria, parent=None)

    next_version_number = (
        HuntProfileVersion.objects.filter(profile=profile).aggregate(Max("version_number"))[
            "version_number__max"
        ]
        or 0
    ) + 1
    version = HuntProfileVersion.objects.create(
        profile=profile, version_number=next_version_number, root_group=root_group
    )

    if search_scope:
        SearchScope.objects.create(version=version, **search_scope)
    for policy in source_policies or []:
        SourcePolicy.objects.create(version=version, **policy)
    for rule in exclusion_rules or []:
        ExclusionRule.objects.create(version=version, **rule)
    ResultThreshold.objects.create(version=version, **(result_threshold or {}))

    return version


def _build_group(
    workspace: Workspace, node: dict[str, Any], parent: CriterionGroup | None
) -> CriterionGroup:
    group = CriterionGroup.objects.create(
        operator=node["operator"], parent=parent, position=node.get("_position", 0)
    )
    for index, child in enumerate(node["children"]):
        if child["type"] == "criterion":
            HuntCriterion.objects.create(
                group=group,
                category=child["category"],
                field=child["field"],
                op=child["op"],
                value=child.get("value"),
                weight=child.get("weight", 1),
                is_required=child.get("is_required", False),
                is_hard_disqualifier=child.get("is_hard_disqualifier", False),
                keyword_set=_resolve_named(
                    KeywordSet, workspace, child.get("keyword_set"), "keyword_set"
                ),
                value_signal=_resolve_named(
                    ValueSignal,
                    workspace,
                    child.get("value_signal"),
                    "value_signal",
                    key_field="key",
                ),
                position=index,
            )
        else:
            _build_group(workspace, {**child, "_position": index}, parent=group)
    return group


def _resolve_named(
    model: type[_M],
    workspace: Workspace,
    name: str | None,
    label: str,
    *,
    key_field: str = "name",
) -> _M | None:
    if not name:
        return None
    instance = model._default_manager.filter(workspace=workspace, **{key_field: name}).first()
    if instance is None:
        raise ValidationError(f"Unknown {label} {name!r} in workspace.")
    return instance


# --- Lifecycle ---------------------------------------------------------------


def activate_version(profile: HuntProfile, version: HuntProfileVersion) -> HuntProfile:
    if version.profile_id != profile.id:
        raise ValidationError("Version does not belong to this profile.")
    profile.current_version = version
    profile.status = HuntProfileStatus.ACTIVE
    profile.save(update_fields=["current_version", "status", "updated_at"])
    return profile


def pause(profile: HuntProfile) -> HuntProfile:
    profile.status = HuntProfileStatus.PAUSED
    profile.save(update_fields=["status", "updated_at"])
    return profile


def archive(profile: HuntProfile) -> HuntProfile:
    profile.status = HuntProfileStatus.ARCHIVED
    profile.save(update_fields=["status", "updated_at"])
    return profile


@transaction.atomic
def clone_profile(profile: HuntProfile, *, name: str) -> HuntProfile:
    if profile.current_version is None:
        raise ValidationError("Cannot clone a profile with no active version.")

    new_profile = HuntProfile.objects.create(
        workspace=profile.workspace, name=name, description=profile.description
    )
    version = profile.current_version
    tree = serialize_criteria_tree(version.root_group)
    new_version = create_version(
        new_profile,
        criteria=tree,
        search_scope=serialize_search_scope(version),
        source_policies=serialize_source_policies(version),
        exclusion_rules=serialize_exclusion_rules(version),
        result_threshold=serialize_result_threshold(version),
    )
    new_profile.current_version = new_version
    new_profile.save(update_fields=["current_version", "updated_at"])
    return new_profile


def serialize_criteria_tree(group: CriterionGroup) -> dict[str, Any]:
    children: list[dict[str, Any]] = []
    for criterion in group.criteria.order_by("position"):
        children.append(
            {
                "type": "criterion",
                "category": criterion.category,
                "field": criterion.field,
                "op": criterion.op,
                "value": criterion.value,
                "weight": criterion.weight,
                "is_required": criterion.is_required,
                "is_hard_disqualifier": criterion.is_hard_disqualifier,
                **({"keyword_set": criterion.keyword_set.name} if criterion.keyword_set else {}),
                **({"value_signal": criterion.value_signal.key} if criterion.value_signal else {}),
            }
        )
    for child_group in group.children.order_by("position"):
        children.append(serialize_criteria_tree(child_group))
    return {"type": "group", "operator": group.operator, "children": children}


def serialize_search_scope(version: HuntProfileVersion) -> dict[str, Any] | None:
    scope = getattr(version, "search_scope", None)
    if scope is None:
        return None
    return {
        "industries": scope.industries,
        "geographies": scope.geographies,
        "company_size_min": scope.company_size_min,
        "company_size_max": scope.company_size_max,
    }


def serialize_source_policies(version: HuntProfileVersion) -> list[dict[str, Any]]:
    return [
        {
            "source_key": policy.source_key,
            "is_enabled": policy.is_enabled,
            "max_records": policy.max_records,
            "budget_cents": policy.budget_cents,
        }
        for policy in version.source_policies.order_by("source_key")
    ]


def serialize_exclusion_rules(version: HuntProfileVersion) -> list[dict[str, Any]]:
    return [
        {"field": rule.field, "op": rule.op, "value": rule.value, "reason": rule.reason}
        for rule in version.exclusion_rules.order_by("id")
    ]


def serialize_result_threshold(version: HuntProfileVersion) -> dict[str, Any] | None:
    threshold = getattr(version, "result_threshold", None)
    if threshold is None:
        return None
    return {
        "min_total_score": threshold.min_total_score,
        "min_evidence_confidence": threshold.min_evidence_confidence,
    }


def ensure_schedule_policy(profile: HuntProfile, **fields: Any) -> SchedulePolicy:
    policy, _ = SchedulePolicy.objects.get_or_create(
        profile=profile, defaults={"workspace": profile.workspace, **fields}
    )
    return policy


# --- Dry-run engine ----------------------------------------------------------


def dry_run(
    version: HuntProfileVersion, organizations: list[Organization] | None = None
) -> list[dict[str, Any]]:
    """Evaluate `version`'s criteria tree against real local data.

    Defaults to every Organization in the version's workspace — this is
    what makes dry-run meaningful today without GOR-235's discovery
    providers: it runs the exact same evaluation logic a live discovery
    run would, just against organizations already known locally.
    """
    candidates = (
        organizations
        if organizations is not None
        else list(Organization.objects.filter(workspace=version.profile.workspace))
    )
    return [evaluate_candidate(version, org) for org in candidates]


def evaluate_candidate(version: HuntProfileVersion, organization: Model) -> dict[str, Any]:
    """Evaluate a single subject (an Organization, typically) against `version`.

    Shared by `dry_run` (loops this over local Organizations) and
    `apps.discovery`'s score phase (calls this once per newly discovered
    candidate) — the same evaluation logic either way.
    """
    threshold = getattr(version, "result_threshold", None)
    exclusion_rules = list(version.exclusion_rules.all())

    evidence_context = build_evidence_context(organization)
    matched, components, required_ok, disqualified_by_tree = _evaluate_group(
        version.root_group, organization, evidence_context
    )
    excluded, exclusion_reason = _check_exclusions(exclusion_rules, organization, evidence_context)
    total_weight = sum(
        c["weight"] for c in components if c["matched"] and not c["is_hard_disqualifier"]
    )
    hard_disqualified = disqualified_by_tree or excluded

    confidence_snapshot = latest_snapshot(organization, "score_confidence")
    confidence_value = confidence_snapshot.value if confidence_snapshot else None
    meets_confidence = (
        threshold is None
        or threshold.min_evidence_confidence is None
        or (confidence_value is not None and confidence_value >= threshold.min_evidence_confidence)
    )

    is_match = matched and required_ok and not hard_disqualified
    meets_score = threshold is None or total_weight >= threshold.min_total_score

    if hard_disqualified:
        recommended_next_action = "excluded"
    elif is_match and meets_score and meets_confidence:
        recommended_next_action = "review_queue"
    else:
        recommended_next_action = "below_threshold"

    return {
        "organization_id": str(organization.id),  # type: ignore[attr-defined]
        "organization_name": organization.name,  # type: ignore[attr-defined]
        "matched": is_match,
        "excluded": hard_disqualified,
        "exclusion_reason": exclusion_reason,
        "total_weight": total_weight,
        "components": components,
        "evidence_count": evidence_context["evidence_count"],
        "score_confidence": confidence_value,
        "recommended_next_action": recommended_next_action,
    }


def _check_exclusions(
    exclusion_rules: list[ExclusionRule], subject: Model, evidence_context: dict[str, Any]
) -> tuple[bool, str | None]:
    for rule in exclusion_rules:
        matched, reason = evaluate_condition(
            {"field": rule.field, "op": rule.op, "value": rule.value}, subject, evidence_context
        )
        if matched:
            return True, rule.reason or reason
    return False, None


def _evaluate_group(
    group: CriterionGroup, subject: Model, evidence_context: dict[str, Any]
) -> tuple[bool, list[dict[str, Any]], bool, bool]:
    """Returns (matched, components, required_criteria_ok, hard_disqualified)."""
    components: list[dict[str, Any]] = []
    required_ok = True
    hard_disqualified = False
    child_results: list[bool] = []

    for criterion in group.criteria.order_by("position"):
        matched, reason = evaluate_condition(
            {"field": criterion.field, "op": criterion.op, "value": criterion.value},
            subject,
            evidence_context,
        )
        components.append(
            {
                "type": "criterion",
                "category": criterion.category,
                "field": criterion.field,
                "matched": matched,
                "weight": criterion.weight,
                "is_required": criterion.is_required,
                "is_hard_disqualifier": criterion.is_hard_disqualifier,
                "reason": reason,
            }
        )
        if criterion.is_hard_disqualifier and matched:
            hard_disqualified = True
        if criterion.is_required and not matched:
            required_ok = False
        child_results.append(matched)

    for child_group in group.children.order_by("position"):
        child_matched, child_components, child_required_ok, child_disqualified = _evaluate_group(
            child_group, subject, evidence_context
        )
        components.extend(child_components)
        required_ok = required_ok and child_required_ok
        hard_disqualified = hard_disqualified or child_disqualified
        child_results.append(child_matched)

    if group.operator == CriterionOperator.AND:
        matched = all(child_results) if child_results else True
    elif group.operator == CriterionOperator.OR:
        matched = any(child_results)
    else:  # NOT — schema guarantees exactly one child
        matched = not child_results[0]

    return matched, components, required_ok, hard_disqualified
