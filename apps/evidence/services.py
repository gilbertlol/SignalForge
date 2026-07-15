import json
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Model
from django.utils import timezone

from .models import (
    Evidence,
    OrganizationClaim,
    OrganizationFieldResolution,
    Reliability,
    VerificationStatus,
)

_RELIABILITY_RANK: dict[str, int] = {Reliability.LOW: 1, Reliability.MEDIUM: 2, Reliability.HIGH: 3}


def record_evidence(subject: Model, **fields: Any) -> Evidence:
    """Create an Evidence row attached to `subject` (an Organization or Opportunity).

    Kept as a plain function (not a signal) so call sites are explicit
    about what evidence gets captured, mirroring `apps.audit.services.record`.
    """
    return Evidence.objects.create(
        workspace=subject.workspace,  # type: ignore[attr-defined]
        content_type=ContentType.objects.get_for_model(subject),
        object_id=subject.pk,
        **fields,
    )


def build_evidence_context(subject: Model) -> dict[str, Any]:
    """Aggregate a subject's evidence into the flat keys condition specs can
    reference (e.g. `evidence_count`, `max_age_days`). Shared by
    `apps.scoring` (flat rule list) and `apps.hunting` (criteria tree) so
    both evaluate conditions against evidence the same way.
    """
    content_type = ContentType.objects.get_for_model(subject)
    evidence_list = list(Evidence.objects.filter(content_type=content_type, object_id=subject.pk))
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


def _canonical_claim_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().casefold()
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


@transaction.atomic
def record_organization_claims(source_record) -> list[OrganizationClaim]:
    """Persist normalized claims once and refresh explainable resolutions."""
    organization = source_record.organization
    if organization is None:
        return []
    observed_at = (
        source_record.provider_result.finished_at
        if source_record.provider_result_id and source_record.provider_result.finished_at
        else source_record.created_at
    )
    claims = []
    for field_name, value in source_record.normalized_data.items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        claim, _ = OrganizationClaim.objects.get_or_create(
            source_record=source_record,
            field_name=field_name,
            defaults={
                "workspace": organization.workspace,
                "organization": organization,
                "source_key": source_record.source_key,
                "value": value,
                "normalized_value": _canonical_claim_value(value),
                "reliability": Reliability.MEDIUM,
                "observed_at": observed_at,
            },
        )
        claims.append(claim)
    resolve_organization_claims(organization)
    return claims


def resolve_organization_claims(organization) -> list[OrganizationFieldResolution]:
    """Select the most reliable, freshest claim and retain all alternatives."""
    resolutions = []
    field_names = organization.source_claims.values_list("field_name", flat=True).distinct()
    for field_name in field_names:
        claims = list(organization.source_claims.filter(field_name=field_name))
        selected = max(
            claims,
            key=lambda claim: (
                _RELIABILITY_RANK.get(claim.reliability, 0),
                claim.observed_at,
                claim.created_at,
            ),
        )
        distinct_values = {claim.normalized_value for claim in claims}
        corroboration_count = sum(
            claim.normalized_value == selected.normalized_value for claim in claims
        )
        has_conflict = len(distinct_values) > 1
        explanation = (
            f"Selected {selected.source_key} using reliability then freshness; "
            f"corroborated by {corroboration_count} claim(s)"
            + (f" with {len(distinct_values) - 1} conflicting value(s)." if has_conflict else ".")
        )
        resolution, _ = OrganizationFieldResolution.objects.update_or_create(
            organization=organization,
            field_name=field_name,
            defaults={
                "workspace": organization.workspace,
                "selected_claim": selected,
                "corroboration_count": corroboration_count,
                "distinct_value_count": len(distinct_values),
                "has_conflict": has_conflict,
                "explanation": explanation,
                "resolved_at": timezone.now(),
            },
        )
        resolutions.append(resolution)
    return resolutions
