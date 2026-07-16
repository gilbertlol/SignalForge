from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from apps.communications.models import Message, MessageStatus
from apps.finance.models import Invoice, InvoiceStatus, Payment, PaymentStatus
from apps.finance.services import client_summary
from apps.notifications.models import AlertRule, DeliveryChannel, NotificationPriority
from apps.notifications.services import emit_alert
from apps.tasks.models import AssignmentStrategy, WorkItem

from .models import (
    AcceptancePolicy,
    ControlRecommendation,
    ControlType,
    FactType,
    ObservationSource,
    Override,
    RecommendationStatus,
    RiskCategory,
    RiskCategoryKey,
    RiskObservation,
    RiskProfile,
    RiskSnapshot,
)

ZERO = Decimal("0")
HUNDRED = Decimal("100")
CALCULATION_VERSION = "risk-v1"

CATEGORY_DESCRIPTIONS = {
    RiskCategoryKey.PAYMENT: "Ability and willingness to pay on agreed terms.",
    RiskCategoryKey.DELIVERY: (
        "Likelihood that scope, timeline, and support load remain deliverable."
    ),
    RiskCategoryKey.RELATIONSHIP: "Communication quality, alignment, and stakeholder behavior.",
    RiskCategoryKey.LEGAL_COMPLIANCE: "Contractual, regulatory, and compliance exposure.",
    RiskCategoryKey.PROFITABILITY: "Contribution margin and cost-growth exposure.",
    RiskCategoryKey.STRATEGIC: "Fit with positioning, capacity, and long-term direction.",
    RiskCategoryKey.SECURITY_PRIVACY: "Data access, automation, security, and privacy exposure.",
    RiskCategoryKey.FOUNDER_DEPENDENCY: "Dependence on unavailable senior or founder capacity.",
}

DEFAULT_CONTROLS = {
    RiskCategoryKey.PAYMENT: ControlType.PREPAYMENT,
    RiskCategoryKey.DELIVERY: ControlType.MILESTONE_BILLING,
    RiskCategoryKey.RELATIONSHIP: ControlType.SENIOR_REVIEW,
    RiskCategoryKey.LEGAL_COMPLIANCE: ControlType.PAID_DISCOVERY,
    RiskCategoryKey.PROFITABILITY: ControlType.SCOPE_LIMIT,
    RiskCategoryKey.STRATEGIC: ControlType.REJECTION,
    RiskCategoryKey.SECURITY_PRIVACY: ControlType.RESTRICTED_AUTOMATION,
    RiskCategoryKey.FOUNDER_DEPENDENCY: ControlType.SENIOR_REVIEW,
}


def decimal_score(value) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ensure_categories(workspace) -> dict[str, RiskCategory]:
    categories = {}
    for key, label in RiskCategoryKey.choices:
        categories[key] = RiskCategory.objects.get_or_create(
            workspace=workspace,
            key=key,
            defaults={"name": label, "description": CATEGORY_DESCRIPTIONS[key]},
        )[0]
    return categories


def observation_score(observation: RiskObservation, *, now=None) -> tuple[Decimal, bool]:
    now = now or timezone.now()
    stale = bool(observation.expires_at and observation.expires_at <= now)
    if stale:
        return ZERO, True
    base = (observation.severity + observation.probability + observation.impact) / Decimal(3)
    confidence = observation.confidence
    if observation.source == ObservationSource.AI_SUGGESTION and not observation.confirmed:
        confidence *= Decimal("0.5")
    return decimal_score(base * confidence), False


def _active_override(profile, category, now):
    return (
        Override.objects.filter(
            profile=profile,
            category=category,
            effective_at__lte=now,
        )
        .filter(expires_at__isnull=True)
        .order_by("-effective_at", "-created_at")
        .first()
        or Override.objects.filter(
            profile=profile,
            category=category,
            effective_at__lte=now,
            expires_at__gt=now,
        )
        .order_by("-effective_at", "-created_at")
        .first()
    )


def _category_result(profile, category, now):
    observations = list(
        profile.observations.filter(category=category).select_related("evidence", "factor")
    )
    components = []
    weighted_total = ZERO
    total_weight = ZERO
    polarities = set()
    for observation in observations:
        score, stale = observation_score(observation, now=now)
        weight = observation.factor.weight if observation.factor_id else Decimal(1)
        if not stale:
            weighted_total += score * weight
            total_weight += weight
            polarities.add("high" if score >= 60 else "low" if score <= 40 else "medium")
        components.append(
            {
                "observation_id": str(observation.pk),
                "source": observation.source,
                "fact_type": observation.fact_type,
                "evidence_id": str(observation.evidence_id) if observation.evidence_id else None,
                "source_record": (
                    {"type": observation.source_type, "id": observation.source_id}
                    if observation.source_type
                    else None
                ),
                "explanation": observation.explanation,
                "score": str(score),
                "confidence": str(observation.confidence),
                "stale": stale,
                "confirmed": observation.confirmed,
            }
        )
    score = decimal_score(weighted_total / total_weight) if total_weight else decimal_score(ZERO)
    override = _active_override(profile, category, now)
    if override:
        score = override.score
        components.append(
            {
                "override_id": str(override.pk),
                "fact_type": FactType.OVERRIDE,
                "evidence_id": str(override.evidence_id) if override.evidence_id else None,
                "explanation": override.reason,
                "score": str(override.score),
                "stale": False,
            }
        )
    return score, components, "high" in polarities and "low" in polarities


def _recommend_controls(profile, snapshot, category_scores):
    recommendations = []
    policies = list(
        AcceptancePolicy.objects.filter(workspace=profile.workspace, enabled=True).select_related(
            "category"
        )
    )
    if not policies:
        policies = [
            AcceptancePolicy(
                workspace=profile.workspace,
                name=f"Default {category.name}",
                category=category,
                threshold=profile.acceptance_threshold,
                control_type=DEFAULT_CONTROLS[category.key],
                requires_approval=True,
            )
            for category in RiskCategory.objects.filter(workspace=profile.workspace)
        ]
    for policy in policies:
        applicable = (
            [policy.category]
            if policy.category_id
            else list(RiskCategory.objects.filter(workspace=profile.workspace))
        )
        for category in applicable:
            score = Decimal(category_scores[category.key])
            if score < policy.threshold:
                continue
            recommendation = ControlRecommendation.objects.create(
                workspace=profile.workspace,
                profile=profile,
                snapshot=snapshot,
                category=category,
                control_type=policy.control_type,
                rationale=(
                    f"{category.name} risk is {score}, meeting the {policy.threshold} threshold."
                ),
                threshold=policy.threshold,
                status=RecommendationStatus.PROPOSED,
                requires_approval=policy.requires_approval,
            )
            recommendations.append(recommendation)
            if policy.requires_approval:
                WorkItem.objects.get_or_create(
                    workspace=profile.workspace,
                    context_type="risk_recommendation",
                    context_id=str(recommendation.pk),
                    defaults={
                        "title": f"Review {recommendation.get_control_type_display()} control",
                        "description": recommendation.rationale,
                        "priority": 1,
                        "assignment_strategy": AssignmentStrategy.FIRST_AVAILABLE,
                    },
                )
    return recommendations


@transaction.atomic
def calculate_risk(profile: RiskProfile, *, triggered_by: str, now=None) -> RiskSnapshot:
    now = now or timezone.now()
    categories = ensure_categories(profile.workspace)
    category_scores = {}
    components = {}
    for key, category in categories.items():
        score, category_components, contradictory = _category_result(profile, category, now)
        category_scores[key] = str(score)
        components[key] = {
            "score": str(score),
            "explanation": category.description,
            "contradictory_evidence": contradictory,
            "observations": category_components,
        }
    snapshot = RiskSnapshot.objects.create(
        workspace=profile.workspace,
        profile=profile,
        category_scores=category_scores,
        components=components,
        calculated_at=now,
        calculation_version=CALCULATION_VERSION,
        triggered_by=triggered_by,
    )
    recommendations = _recommend_controls(profile, snapshot, category_scores)
    if recommendations:
        rule = AlertRule.objects.get_or_create(
            workspace=profile.workspace,
            event_type="risk.control_required",
            defaults={
                "name": "Risk control required",
                "priority": NotificationPriority.HIGH,
                "channels": [DeliveryChannel.IN_APP],
            },
        )[0]
        recipient = profile.organization.workspace.memberships.filter(is_active=True).first()
        if recipient:
            emit_alert(
                rule=rule,
                recipient=recipient.user,
                payload={"profile": str(profile.pk)},
                title=f"Risk controls required for {profile.organization.name}",
                body=f"{len(recommendations)} control recommendations need review.",
                resource_type="risk_profile",
                resource_id=str(profile.pk),
                deduplication_key=f"risk-controls:{profile.pk}:{snapshot.pk}",
            )
    if profile.opportunity_id and recommendations:
        Message.objects.filter(
            conversation__opportunity=profile.opportunity,
            status__in=[MessageStatus.DRAFT, MessageStatus.APPROVED, MessageStatus.SCHEDULED],
        ).update(
            high_risk=True,
            status=MessageStatus.PENDING_APPROVAL,
            approval_reasons=["Risk controls require review"],
        )
    return snapshot


def sync_finance_observations(profile: RiskProfile, *, currency: str) -> int:
    categories = ensure_categories(profile.workspace)
    created = 0
    overdue_count = Invoice.objects.filter(
        workspace=profile.workspace,
        organization=profile.organization,
        currency=currency,
        status=InvoiceStatus.OVERDUE,
    ).count()
    failed_count = Payment.objects.filter(
        workspace=profile.workspace,
        organization=profile.organization,
        currency=currency,
        status=PaymentStatus.FAILED,
    ).count()
    summary = client_summary(profile.organization, currency=currency)
    signals = [
        (categories[RiskCategoryKey.PAYMENT], "overdue_invoices", overdue_count, 20),
        (categories[RiskCategoryKey.PAYMENT], "failed_payments", failed_count, 30),
        (
            categories[RiskCategoryKey.PROFITABILITY],
            "negative_margin",
            1 if summary.contribution_profit < 0 else 0,
            80,
        ),
    ]
    for category, key, count, severity in signals:
        if not count:
            continue
        _, was_created = RiskObservation.objects.update_or_create(
            workspace=profile.workspace,
            profile=profile,
            category=category,
            source=ObservationSource.DETERMINISTIC,
            source_type="finance_signal",
            source_id=f"{key}:{currency}",
            defaults={
                "fact_type": FactType.OBSERVED,
                "explanation": f"Finance signal {key} has value {count}.",
                "severity": min(Decimal(100), Decimal(severity * count)),
                "probability": Decimal(100),
                "impact": Decimal(severity),
                "confidence": Decimal(1),
                "observed_at": timezone.now(),
                "expires_at": timezone.now() + timedelta(days=1),
                "confirmed": True,
            },
        )
        created += was_created
    return created
