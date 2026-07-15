"""Recomputable source scorecards derived only from durable run facts."""

from collections import defaultdict
from decimal import Decimal

from apps.discovery.models import SourceRecordStatus


def build_source_scorecards(runs) -> dict:
    runs = list(
        runs.select_related("hunt_profile_version__profile").prefetch_related(
            "provider_results__records__organization__opportunities",
            "source_records__organization__field_resolutions__selected_claim",
            "source_records__organization__source_claims",
        )
    )
    executions = [execution for run in runs for execution in run.provider_results.all()]
    organization_sources: dict[str, set[str]] = defaultdict(set)
    first_source: dict[str, tuple[object, str]] = {}
    for execution in executions:
        for record in execution.records.all():
            if not record.organization_id:
                continue
            key = str(record.organization_id)
            organization_sources[key].add(execution.provider_key)
            candidate = (record.created_at, execution.provider_key)
            if key not in first_source or candidate < first_source[key]:
                first_source[key] = candidate

    cards = []
    for source_key in sorted({execution.provider_key for execution in executions}):
        source_executions = [item for item in executions if item.provider_key == source_key]
        records = [record for item in source_executions for record in item.records.all()]
        organization_ids = {
            str(record.organization_id) for record in records if record.organization_id
        }
        organizations = {
            str(record.organization_id): record.organization
            for record in records
            if record.organization_id
        }
        unique_count = len(organization_ids)
        qualified = sum(record.status == SourceRecordStatus.QUALIFIED for record in records)
        rejected = sum(record.status == SourceRecordStatus.REJECTED for record in records)
        cost = sum(item.cost_cents for item in source_executions)
        reported = [
            item.reported_cost_cents
            for item in source_executions
            if item.reported_cost_cents is not None
        ]
        overlaps = sum(len(organization_sources[org_id]) > 1 for org_id in organization_ids)
        first_touch = sum(first_source[org_id][1] == source_key for org_id in organization_ids)
        fractional = sum(
            Decimal(1) / len(organization_sources[org_id]) for org_id in organization_ids
        )
        opportunities = sum(org.opportunities.exists() for org in organizations.values())
        latency_values = [
            (item.finished_at - item.started_at).total_seconds()
            for item in source_executions
            if item.started_at and item.finished_at
        ]
        queue_values = [
            (item.started_at - item.created_at).total_seconds()
            for item in source_executions
            if item.started_at
        ]
        total_values = [
            (item.finished_at - item.created_at).total_seconds()
            for item in source_executions
            if item.finished_at
        ]
        claims = [
            claim
            for organization in organizations.values()
            for claim in organization.source_claims.all()
            if claim.source_key == source_key
        ]
        corroborated = sum(
            resolution.corroboration_count > 1
            for organization in organizations.values()
            for resolution in organization.field_resolutions.all()
            if resolution.selected_claim.source_key == source_key
        )
        conflicts = sum(
            resolution.has_conflict
            for organization in organizations.values()
            for resolution in organization.field_resolutions.all()
            if resolution.selected_claim.source_key == source_key
        )
        sample_size = len(records)
        cards.append(
            {
                "source_key": source_key,
                "runs": len(source_executions),
                "requested_records": sum(item.max_records or 0 for item in source_executions),
                "returned_records": sum(item.records_returned for item in source_executions),
                "pages_requested": sum(item.pages_requested for item in source_executions),
                "pages_returned": sum(item.pages_returned for item in source_executions),
                "unique_organizations": unique_count,
                "within_source_duplicates": max(0, len(records) - unique_count),
                "cross_source_overlaps": overlaps,
                "first_touch_organizations": first_touch,
                "multi_touch_organizations": overlaps,
                "fractional_organization_credit": float(round(fractional, 3)),
                "claims": len(claims),
                "corroborated_fields": corroborated,
                "conflicting_fields": conflicts,
                "qualified": qualified,
                "rejected": rejected,
                "qualification_rate": round(qualified / sample_size, 4) if sample_size else None,
                "opportunity_conversions": opportunities,
                "queue_seconds_average": round(sum(queue_values) / len(queue_values), 3)
                if queue_values
                else None,
                "latency_seconds_average": round(sum(latency_values) / len(latency_values), 3)
                if latency_values
                else None,
                "total_seconds_average": round(sum(total_values) / len(total_values), 3)
                if total_values
                else None,
                "retry_count": sum(max(0, item.attempt_count - 1) for item in source_executions),
                "rate_limit_count": sum(item.rate_limit_count for item in source_executions),
                "failure_count": sum(item.failure_count for item in source_executions),
                "timeout_count": sum(item.timeout_count for item in source_executions),
                "estimated_cost_cents": cost,
                "reported_cost_cents": float(sum(reported)) if reported else None,
                "cost_per_unique_lead_cents": round(cost / unique_count, 2)
                if unique_count
                else None,
                "cost_per_qualified_lead_cents": round(cost / qualified, 2) if qualified else None,
                "sample_size": sample_size,
                "sample_warning": "Directional only — fewer than 30 records."
                if sample_size < 30
                else "",
            }
        )
    eligible = [card for card in cards if card["sample_size"]]
    recommendation = None
    if eligible:
        winner = max(
            eligible,
            key=lambda card: (
                card["qualification_rate"] or 0,
                card["unique_organizations"],
                -card["estimated_cost_cents"],
            ),
        )
        recommendation = {
            "source_key": winner["source_key"],
            "objective": "qualification rate, then unique yield, then estimated cost",
            "explanation": (
                f"{winner['source_key']} currently leads on the selected ordering. "
                f"Based on {winner['sample_size']} records; this is directional, "
                "not statistical proof."
            ),
            "is_directional": winner["sample_size"] < 30,
        }
    niches = sorted(
        {
            industry
            for run in runs
            for industry in (
                getattr(run.hunt_profile_version, "search_scope", None).industries
                if hasattr(run.hunt_profile_version, "search_scope")
                else []
            )
        }
    )
    return {
        "scorecards": cards,
        "recommendation": recommendation,
        "run_count": len(runs),
        "niches": niches,
    }
