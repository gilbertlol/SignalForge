"""The discover -> normalize -> deduplicate -> enrich -> collect evidence -> score pipeline.

`execute_run` is one resumable orchestrator, not a multi-task Celery chain
(see apps/discovery/tasks.py) — idempotency comes from each phase only
touching `SourceRecord`s still at that phase's entry state, so calling it
again on an already-completed (or partially-completed) run just finds
nothing left to do in the phases that already finished.
"""

import csv
import io
from dataclasses import dataclass
from typing import Any

from django.utils import timezone

from apps.evidence.models import Reliability, SourceType, VerificationStatus
from apps.evidence.services import record_evidence
from apps.hunting.models import HuntProfileVersion
from apps.hunting.services import evaluate_candidate
from apps.integrations.registry import get_lead_source_adapter, get_technology_detection_adapter
from apps.organizations.services import create_organization, normalize_domain
from apps.scoring.models import ScoreFamily
from apps.scoring.services import evaluate

from .models import (
    DiscoveryRun,
    DiscoveryRunStatus,
    EnrichmentRun,
    EnrichmentRunStatus,
    ProviderResult,
    ProviderResultStatus,
    SourceRecord,
    SourceRecordStatus,
    SuppressionEntry,
)

_MOCK_COST_PER_RECORD_CENTS = 10


@dataclass
class _EffectiveSourcePolicy:
    source_key: str
    max_records: int | None
    budget_cents: int | None


def start_run(
    hunt_profile_version: HuntProfileVersion, *, trigger: str, initiated_by=None
) -> DiscoveryRun:
    return DiscoveryRun.objects.create(
        workspace=hunt_profile_version.profile.workspace,
        hunt_profile_version=hunt_profile_version,
        trigger=trigger,
        initiated_by=initiated_by,
    )


def execute_run(run: DiscoveryRun) -> DiscoveryRun:
    """Run every phase in order. Safe to call again on the same `run`."""
    if run.status in (DiscoveryRunStatus.SUCCEEDED, DiscoveryRunStatus.CANCELED):
        return run

    if run.started_at is None:
        run.started_at = timezone.now()
    run.status = DiscoveryRunStatus.RUNNING
    run.save(update_fields=["status", "started_at", "updated_at"])

    try:
        _discover(run)
        run.refresh_from_db()
        if run.status == DiscoveryRunStatus.CANCELED:
            return run

        _normalize(run)
        _deduplicate(run)
        run.refresh_from_db()
        if run.status == DiscoveryRunStatus.CANCELED:
            return run

        _enrich(run)
        _collect_evidence(run)
        _score(run)
    except Exception as exc:  # noqa: BLE001 - isolate unexpected failures, never leave "running" stuck
        run.status = DiscoveryRunStatus.FAILED
        run.error_summary = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_summary", "finished_at", "updated_at"])
        raise

    run.refresh_from_db()
    if run.status != DiscoveryRunStatus.CANCELED:
        has_failed = run.provider_results.filter(status=ProviderResultStatus.FAILED).exists()
        has_succeeded = run.provider_results.filter(status=ProviderResultStatus.SUCCEEDED).exists()
        if has_failed and has_succeeded:
            run.status = DiscoveryRunStatus.PARTIAL
        elif has_failed and not has_succeeded:
            run.status = DiscoveryRunStatus.FAILED
        else:
            run.status = DiscoveryRunStatus.SUCCEEDED
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at", "updated_at"])
    return run


# --- discover ----------------------------------------------------------------


def _get_effective_source_policies(version: HuntProfileVersion) -> list[_EffectiveSourcePolicy]:
    """Falls back to a single "demo" source only when the version has **no**
    `SourcePolicy` rows at all — not merely none enabled. That distinction
    matters: it's what lets a version explicitly configure `[{"source_key":
    "demo", "is_enabled": False}]` to disable automatic discovery entirely
    (manual entry / CSV import only) rather than silently falling back to
    the demo source anyway.
    """
    all_policies = version.source_policies.all()
    if not all_policies.exists():
        return [_EffectiveSourcePolicy("demo", None, None)]
    return [
        _EffectiveSourcePolicy(p.source_key, p.max_records, p.budget_cents)
        for p in all_policies.filter(is_enabled=True)
    ]


def _discover(run: DiscoveryRun) -> None:
    version = run.hunt_profile_version
    search_scope = getattr(version, "search_scope", None)
    base_query: dict[str, Any] = {}
    if search_scope:
        base_query = {
            "industries": search_scope.industries,
            "geographies": search_scope.geographies,
            "company_size_min": search_scope.company_size_min,
            "company_size_max": search_scope.company_size_max,
        }

    discovered_count = 0
    cost_total = 0
    for policy in _get_effective_source_policies(version):
        already_ran = run.provider_results.filter(
            provider_key=policy.source_key,
            status__in=[ProviderResultStatus.SUCCEEDED, ProviderResultStatus.PARTIAL],
        ).exists()
        if already_ran:
            continue

        started_at = timezone.now()
        adapter = get_lead_source_adapter(policy.source_key)
        if adapter is None:
            ProviderResult.objects.create(
                discovery_run=run,
                provider_key=policy.source_key,
                status=ProviderResultStatus.FAILED,
                error=f"No lead source adapter registered for {policy.source_key!r}.",
                started_at=started_at,
                finished_at=timezone.now(),
            )
            continue

        try:
            results = adapter.search({**base_query, "limit": policy.max_records})
        except Exception as exc:  # noqa: BLE001 - one provider's failure must not sink the run
            ProviderResult.objects.create(
                discovery_run=run,
                provider_key=policy.source_key,
                status=ProviderResultStatus.FAILED,
                error=str(exc),
                started_at=started_at,
                finished_at=timezone.now(),
            )
            continue

        created = 0
        cost = 0
        for payload in results:
            if (
                policy.budget_cents is not None
                and cost + _MOCK_COST_PER_RECORD_CENTS > policy.budget_cents
            ):
                break
            SourceRecord.objects.create(
                discovery_run=run,
                source_key=policy.source_key,
                raw_payload=payload,
                status=SourceRecordStatus.PENDING,
            )
            created += 1
            cost += _MOCK_COST_PER_RECORD_CENTS

        ProviderResult.objects.create(
            discovery_run=run,
            provider_key=policy.source_key,
            status=ProviderResultStatus.SUCCEEDED,
            records_returned=created,
            cost_cents=cost,
            started_at=started_at,
            finished_at=timezone.now(),
        )
        discovered_count += created
        cost_total += cost

    if discovered_count or cost_total:
        run.records_discovered += discovered_count
        run.cost_cents += cost_total
        run.save(update_fields=["records_discovered", "cost_cents", "updated_at"])


# --- normalize -----------------------------------------------------------------


def _normalize_payload(raw_payload: dict[str, Any]) -> dict[str, Any]:
    """Maps provider-specific field names onto the project's normalized schema.

    A real (non-demo) provider would register its own mapper here instead
    of relying on this generic fallback chain.
    """
    name = raw_payload.get("company_name") or raw_payload.get("name") or ""
    domain_raw = raw_payload.get("website") or raw_payload.get("domain") or ""
    domain = normalize_domain(domain_raw) if domain_raw else ""
    return {"name": name, "domain": domain}


def _normalize(run: DiscoveryRun) -> None:
    failed_count = 0
    for record in run.source_records.filter(status=SourceRecordStatus.PENDING):
        normalized = _normalize_payload(record.raw_payload)
        if not normalized["domain"] and not normalized["name"]:
            record.status = SourceRecordStatus.FAILED
            record.failure_reason = "Unable to extract a name or domain from the raw payload."
            failed_count += 1
        else:
            record.normalized_data = normalized
            record.status = SourceRecordStatus.NORMALIZED
        record.save(update_fields=["normalized_data", "status", "failure_reason", "updated_at"])
    if failed_count:
        run.records_failed += failed_count
        run.save(update_fields=["records_failed", "updated_at"])


# --- deduplicate -----------------------------------------------------------------


def _is_suppressed(workspace: Any, domain: str) -> bool:
    return SuppressionEntry.objects.filter(
        workspace=workspace, domain=domain, is_active=True
    ).exists()


def _deduplicate(run: DiscoveryRun) -> None:
    workspace = run.workspace
    deduplicated_count = 0
    records = run.source_records.filter(
        status=SourceRecordStatus.NORMALIZED, organization__isnull=True
    )
    for record in records:
        domain = record.normalized_data.get("domain", "")
        name = record.normalized_data.get("name", "") or domain

        if domain and _is_suppressed(workspace, domain):
            record.status = SourceRecordStatus.SUPPRESSED
            record.save(update_fields=["status", "updated_at"])
            continue

        org, created = create_organization(workspace, name=name, domain=domain)
        record.organization = org
        if not created:
            record.status = SourceRecordStatus.DUPLICATE
            deduplicated_count += 1
        record.save(update_fields=["organization", "status", "updated_at"])

    if deduplicated_count:
        run.records_deduplicated += deduplicated_count
        run.save(update_fields=["records_deduplicated", "updated_at"])


def _records_ready_for(run: DiscoveryRun) -> Any:
    """Records that survived dedupe (have an organization) and aren't final yet."""
    return run.source_records.filter(
        organization__isnull=False,
        status__in=[SourceRecordStatus.NORMALIZED, SourceRecordStatus.DUPLICATE],
    )


# --- enrich ----------------------------------------------------------------------


def _enrich(run: DiscoveryRun) -> None:
    enriched_count = 0
    for record in _records_ready_for(run):
        if EnrichmentRun.objects.filter(source_record=record, provider_key="demo").exists():
            continue
        domain = record.normalized_data.get("domain", "")
        adapter = get_technology_detection_adapter("demo")
        if adapter is None or not domain:
            continue
        try:
            technologies = adapter.detect(domain)
        except Exception as exc:  # noqa: BLE001 - enrichment is best-effort, never fails the record
            EnrichmentRun.objects.create(
                source_record=record,
                provider_key="demo",
                status=EnrichmentRunStatus.FAILED,
                error=str(exc),
            )
            continue
        EnrichmentRun.objects.create(
            source_record=record,
            provider_key="demo",
            status=EnrichmentRunStatus.SUCCEEDED,
            result={"technologies": technologies},
        )
        enriched_count += 1

    if enriched_count:
        run.records_enriched += enriched_count
        run.save(update_fields=["records_enriched", "updated_at"])


# --- collect evidence --------------------------------------------------------------


def _collect_evidence(run: DiscoveryRun) -> None:
    for record in _records_ready_for(run):
        org = record.organization
        domain = record.normalized_data.get("domain", "")
        name = record.normalized_data.get("name", "")
        source_type = SourceType.MANUAL if record.source_key != "demo" else SourceType.WEBSITE
        record_evidence(
            org,
            source_url=f"https://{domain}" if domain else "",
            source_type=source_type,
            observed_date=timezone.now().date(),
            excerpt=f"Discovered via {record.source_key} ({name})",
            reliability=Reliability.MEDIUM,
            verification_status=VerificationStatus.UNVERIFIED,
            is_inferred=False,
        )


# --- score -----------------------------------------------------------------------


def _score(run: DiscoveryRun) -> None:
    version = run.hunt_profile_version
    qualified_count = 0
    for record in _records_ready_for(run):
        org = record.organization
        evaluate(org, ScoreFamily.PROSPECT_QUALITY)
        evaluate(org, ScoreFamily.SCORE_CONFIDENCE)
        result = evaluate_candidate(version, org)

        if result["recommended_next_action"] == "review_queue":
            record.status = SourceRecordStatus.QUALIFIED
            qualified_count += 1
        else:
            record.status = SourceRecordStatus.REJECTED
        record.save(update_fields=["status", "updated_at"])

    if qualified_count:
        run.records_qualified += qualified_count
        run.save(update_fields=["records_qualified", "updated_at"])


# --- manual entry / CSV import ------------------------------------------------------


def create_manual_source_record(
    discovery_run: DiscoveryRun, *, name: str, domain: str = "", **extra: Any
) -> SourceRecord:
    """Enters a candidate directly, already normalized — skips discover/normalize."""
    record = SourceRecord.objects.create(
        discovery_run=discovery_run,
        source_key="manual",
        raw_payload={"name": name, "domain": domain, **extra},
        normalized_data={"name": name, "domain": normalize_domain(domain) if domain else ""},
        status=SourceRecordStatus.NORMALIZED,
    )
    discovery_run.records_discovered += 1
    discovery_run.save(update_fields=["records_discovered", "updated_at"])
    return record


def import_csv(discovery_run: DiscoveryRun, file: Any) -> list[SourceRecord]:
    """Parses an uploaded CSV into `pending` SourceRecords (still goes through normalize)."""
    content = file.read()
    if isinstance(content, bytes):
        content = content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))

    records = [
        SourceRecord.objects.create(
            discovery_run=discovery_run,
            source_key="csv_import",
            raw_payload=dict(row),
            status=SourceRecordStatus.PENDING,
        )
        for row in reader
    ]
    if records:
        discovery_run.records_discovered += len(records)
        discovery_run.save(update_fields=["records_discovered", "updated_at"])
    return records
