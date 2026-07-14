"""Shared field/op/value condition evaluation.

Used by `apps.scoring` (flat rule list) and `apps.hunting` (recursive
AND/OR/NOT criteria tree) — both need the same primitive: resolve a dotted
field path (or a precomputed context key) off a subject, then compare it
against an expected value with one of a small fixed set of operators. This
is intentionally not a rules DSL: just enough to express "field op value".
"""

from typing import Any

from django.db.models import Model

OPERATORS = ("eq", "neq", "in", "between", "gte", "lte")


def resolve_value(field: str, subject: Model, context: dict[str, Any]) -> Any:
    """`context` keys (e.g. precomputed evidence aggregates) take priority
    over attribute lookup on `subject`, which supports dotted paths."""
    if field in context:
        return context[field]
    value: Any = subject
    for part in field.split("."):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def apply_operator(op: str, actual: Any, expected: Any) -> bool:
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
    raise ValueError(f"Unsupported operator {op!r}; expected one of {OPERATORS}")


def evaluate_condition(
    conditions: dict[str, Any], subject: Model, context: dict[str, Any]
) -> tuple[bool, str]:
    """Evaluate a single `{"field", "op", "value"}` spec. Empty conditions always match."""
    if not conditions:
        return True, "no conditions: always applies"

    field = conditions["field"]
    op = conditions["op"]
    expected = conditions.get("value")
    actual = resolve_value(field, subject, context)
    matched = apply_operator(op, actual, expected)
    return matched, f"{field} {op} {expected!r} (actual={actual!r})"
