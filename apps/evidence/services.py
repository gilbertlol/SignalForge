from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model

from .models import Evidence, Reliability, VerificationStatus

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
