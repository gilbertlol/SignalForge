from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model

from apps.core.models import Workspace
from apps.evidence.models import Evidence, Reliability, VerificationStatus

from .models import ScoreSnapshot, ScoreThreshold, ScoringRule

_RELIABILITY_RANK = {Reliability.LOW: 1, Reliability.MEDIUM: 2, Reliability.HIGH: 3}

_OPERATORS = ("eq", "neq", "in", "between", "gte", "lte")


def evaluate(subject: Model, family: str) -> ScoreSnapshot:
    """Deterministically score `subject` for `family` and persist an immutable snapshot.

    Every rule for the family is evaluated and recorded in the snapshot's
    `components`, whether it matched or not, so the explanation is complete.
    A matched hard-disqualifier forces `value` to 0 but doesn't stop other
    rules from being evaluated and recorded — the explanation shows what
    *would* have scored, not just the disqualifier.

    There is no AI call anywhere in this path: scoring is pure rule
    evaluation against `subject` and its `Evidence`, which is what keeps it
    reproducible and immune to non-deterministic AI suggestions overriding it.
    """
    workspace: Workspace = subject.workspace  # type: ignore[attr-defined]
    content_type = ContentType.objects.get_for_model(subject)
    evidence_context = _build_evidence_context(
        Evidence.objects.filter(content_type=content_type, object_id=subject.pk)
    )

    components: list[dict[str, Any]] = []
    total = 0
    hard_disqualified = False

    rules = ScoringRule.objects.filter(workspace=workspace, family=family).order_by("key")
    for rule in rules:
        matched, reason = _matches(rule.conditions, subject, evidence_context)
        components.append(
            {
                "rule_id": str(rule.id),
                "rule_key": rule.key,
                "rule_version": rule.version,
                "points": rule.points,
                "matched": matched,
                "is_hard_disqualifier": rule.is_hard_disqualifier,
                "reason": reason,
            }
        )
        if matched:
            if rule.is_hard_disqualifier:
                hard_disqualified = True
            else:
                total += rule.points

    value = 0 if hard_disqualified else total
    label = _resolve_label(workspace, family, value)

    return ScoreSnapshot.objects.create(
        workspace=workspace,
        content_type=content_type,
        object_id=subject.pk,
        family=family,
        value=value,
        is_hard_disqualified=hard_disqualified,
        label=label,
        components=components,
    )


def latest_snapshot(subject: Model, family: str) -> ScoreSnapshot | None:
    """The most recent snapshot for `subject`+`family`, or None if never scored."""
    content_type = ContentType.objects.get_for_model(subject)
    return (
        ScoreSnapshot.objects.filter(content_type=content_type, object_id=subject.pk, family=family)
        .order_by("-created_at")
        .first()
    )


def _resolve_label(workspace: Workspace, family: str, value: int) -> str:
    threshold = (
        ScoreThreshold.objects.filter(workspace=workspace, family=family, min_value__lte=value)
        .order_by("-min_value")
        .first()
    )
    return threshold.label if threshold else ""


def _build_evidence_context(evidence_qs: Any) -> dict[str, Any]:
    """Aggregate evidence into the flat keys condition specs can reference.

    Mainly used by `score_confidence` rules; nothing stops other families
    from referencing these keys too (e.g. requiring at least one piece of
    evidence before a prospect-quality rule can match).
    """
    evidence_list = list(evidence_qs)
    if not evidence_list:
        return {
            "evidence_count": 0,
            "min_age_days": None,
            "max_age_days": None,
            "high_reliability_count": 0,
            "verified_count": 0,
            "inferred_count": 0,
            "max_reliability_rank": 0,
        }
    ages = [e.age_days for e in evidence_list]
    return {
        "evidence_count": len(evidence_list),
        "min_age_days": min(ages),
        "max_age_days": max(ages),
        "high_reliability_count": sum(
            1 for e in evidence_list if e.reliability == Reliability.HIGH
        ),
        "verified_count": sum(
            1 for e in evidence_list if e.verification_status == VerificationStatus.VERIFIED
        ),
        "inferred_count": sum(1 for e in evidence_list if e.is_inferred),
        "max_reliability_rank": max(_RELIABILITY_RANK.get(e.reliability, 0) for e in evidence_list),
    }


def _matches(
    conditions: dict[str, Any], subject: Model, evidence_context: dict[str, Any]
) -> tuple[bool, str]:
    if not conditions:
        return True, "no conditions: always applies"

    field = conditions["field"]
    op = conditions["op"]
    expected = conditions.get("value")
    actual = _resolve_value(field, subject, evidence_context)
    matched = _apply_operator(op, actual, expected)
    return matched, f"{field} {op} {expected!r} (actual={actual!r})"


def _resolve_value(field: str, subject: Model, evidence_context: dict[str, Any]) -> Any:
    if field in evidence_context:
        return evidence_context[field]
    value: Any = subject
    for part in field.split("."):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def _apply_operator(op: str, actual: Any, expected: Any) -> bool:
    if actual is None:
        return False
    if op == "eq":
        return bool(actual == expected)
    if op == "neq":
        return bool(actual != expected)
    if op == "in":
        return bool(actual in expected)
    if op == "between":
        low, high = expected
        return bool(low <= actual <= high)
    if op == "gte":
        return bool(actual >= expected)
    if op == "lte":
        return bool(actual <= expected)
    raise ValueError(f"Unsupported operator {op!r}; expected one of {_OPERATORS}")
