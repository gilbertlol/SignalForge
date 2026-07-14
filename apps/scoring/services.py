from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model

from apps.core.conditions import evaluate_condition
from apps.core.models import Workspace
from apps.evidence.services import build_evidence_context

from .models import ScoreSnapshot, ScoreThreshold, ScoringRule


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
    evidence_context = build_evidence_context(subject)

    components: list[dict[str, Any]] = []
    total = 0
    hard_disqualified = False

    rules = ScoringRule.objects.filter(workspace=workspace, family=family).order_by("key")
    for rule in rules:
        matched, reason = evaluate_condition(rule.conditions, subject, evidence_context)
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
