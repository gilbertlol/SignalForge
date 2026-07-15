"""The discover -> normalize -> deduplicate -> enrich -> collect evidence -> score pipeline.

Celery fans enabled sources out into independent provider tasks and invokes
one durable fan-in after they reach terminal states. Provider payloads stay
in PostgreSQL; the broker carries IDs only. `execute_run` retains a synchronous
compatibility path for tests and direct callers using the same idempotent steps.
"""

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from typing import Any

from billiard.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.evidence.models import Reliability, SourceType, VerificationStatus
from apps.evidence.services import record_evidence, record_organization_claims
from apps.hunting.models import HuntProfileVersion
from apps.hunting.services import evaluate_candidate
from apps.integrations.registry import (
    get_lead_source_adapter,
    get_technology_detection_adapter,
    get_website_analysis_adapter,
)
from apps.integrations.services import lead_source_availability, record_lead_source_outcome
from apps.organizations.models import Organization
from apps.organizations.services import create_organization, normalize_domain
from apps.scoring.models import ScoreFamily
from apps.scoring.services import evaluate

from .models import (
    DiscoveryRun,
    DiscoveryRunStatus,
    EnrichmentRun,
    EnrichmentRunStatus,
    MatchMethod,
    ProviderResult,
    ProviderResultStatus,
    SourceRecord,
    SourceRecordStatus,
    SuppressionEntry,
)


@dataclass
class _EffectiveSourcePolicy:
    source_key: str
    max_records: int | None
    budget_cents: int | None
    reliability_weight: int = 50
    timeout_seconds: int = 30
    max_retries: int = 2
    priority: int = 100


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
    """Synchronous compatibility entry point; Celery uses parallel provider tasks."""
    if run.status in (DiscoveryRunStatus.SUCCEEDED, DiscoveryRunStatus.CANCELED):
        return run

    if run.started_at is None:
        run.started_at = timezone.now()
    run.status = DiscoveryRunStatus.RUNNING
    run.save(update_fields=["status", "started_at", "updated_at"])

    try:
        executions = prepare_provider_executions(run)
        for execution in executions:
            execute_provider_search(execution.id)
        run.refresh_from_db()
        if run.status == DiscoveryRunStatus.CANCELED:
            return run

        finalize_run(run.id)
    except Exception as exc:  # noqa: BLE001 - isolate unexpected failures, never leave "running" stuck
        run.status = DiscoveryRunStatus.FAILED
        run.error_summary = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_summary", "finished_at", "updated_at"])
        raise

    run.refresh_from_db()
    return run


# --- discover ----------------------------------------------------------------


def _get_effective_source_policies(version: HuntProfileVersion) -> list[_EffectiveSourcePolicy]:
    """Return enabled immutable policies; production never invents a source.

    Tests retain an isolated deterministic adapter to exercise orchestration.
    """
    all_policies = version.source_policies.all()
    if not all_policies.exists():
        return [_EffectiveSourcePolicy("demo", None, None)] if settings.TESTING else []
    return [
        _EffectiveSourcePolicy(
            p.source_key,
            p.max_records,
            p.budget_cents,
            p.reliability_weight,
            p.timeout_seconds,
            p.max_retries,
            p.priority,
        )
        for p in all_policies.filter(is_enabled=True).order_by("priority", "source_key")
    ]


def _search_query(run: DiscoveryRun) -> dict[str, Any]:
    version = run.hunt_profile_version
    search_scope = getattr(version, "search_scope", None)
    base_query: dict[str, Any] = {}
    if search_scope:
        base_query = {
            "industries": search_scope.industries,
            "geographies": search_scope.geographies,
            "company_size_min": search_scope.company_size_min,
            "company_size_max": search_scope.company_size_max,
            "keyword": search_scope.keyword,
            "included_type": search_scope.included_type,
            "center_latitude": float(search_scope.center_latitude)
            if search_scope.center_latitude is not None
            else None,
            "center_longitude": float(search_scope.center_longitude)
            if search_scope.center_longitude is not None
            else None,
            "radius_meters": search_scope.radius_meters,
        }

    return base_query


@transaction.atomic
def prepare_provider_executions(run: DiscoveryRun) -> list[ProviderResult]:
    """Persist the fan-out before dispatch so re-dispatch is idempotent."""
    run = DiscoveryRun.objects.select_for_update().get(pk=run.pk)
    if run.status == DiscoveryRunStatus.CANCELED:
        return []
    if run.started_at is None:
        run.started_at = timezone.now()
    run.status = DiscoveryRunStatus.RUNNING
    run.save(update_fields=["status", "started_at", "updated_at"])

    base_query = _search_query(run)
    version = run.hunt_profile_version
    executions = []
    for policy in _get_effective_source_policies(version):
        execution, _ = ProviderResult.objects.get_or_create(
            discovery_run=run,
            provider_key=policy.source_key,
            defaults={
                "query_snapshot": {
                    **base_query,
                    "limit": policy.max_records,
                    "budget_cents": policy.budget_cents,
                },
                "policy_snapshot": {
                    "source_key": policy.source_key,
                    "max_records": policy.max_records,
                    "budget_cents": policy.budget_cents,
                    "reliability_weight": policy.reliability_weight,
                    "timeout_seconds": policy.timeout_seconds,
                    "max_retries": policy.max_retries,
                    "priority": policy.priority,
                },
                "max_records": policy.max_records,
                "budget_cents": policy.budget_cents,
            },
        )
        if execution.status == ProviderResultStatus.QUEUED and policy.source_key in {
            "searxng",
            "apollo",
            "google_places",
        }:
            availability = lead_source_availability(run.workspace, policy.source_key)
            if not availability.ready:
                execution.status = ProviderResultStatus.SKIPPED
                execution.error = f"Unavailable at dispatch: {availability.reason}."
                execution.finished_at = timezone.now()
                execution.save(update_fields=["status", "error", "finished_at", "updated_at"])
        executions.append(execution)
    return executions


def _payload_external_id(source_key: str, payload: dict[str, Any]) -> str:
    provider_id = payload.get("id") or payload.get("organization_id")
    if provider_id:
        value = str(provider_id)
        if len(value) <= 255:
            return value
        return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def execute_provider_search(provider_result_id) -> ProviderResult:
    """Execute exactly one source; safe to deliver more than once."""
    with transaction.atomic():
        execution = (
            ProviderResult.objects.select_for_update()
            .select_related("discovery_run__workspace")
            .get(pk=provider_result_id)
        )
        if execution.status in {
            ProviderResultStatus.SUCCEEDED,
            ProviderResultStatus.EMPTY,
            ProviderResultStatus.PARTIAL,
            ProviderResultStatus.BUDGET_BLOCKED,
            ProviderResultStatus.CANCELED,
            ProviderResultStatus.SKIPPED,
        }:
            return execution
        if execution.discovery_run.status == DiscoveryRunStatus.CANCELED:
            execution.status = ProviderResultStatus.CANCELED
            execution.finished_at = timezone.now()
            execution.save(update_fields=["status", "finished_at", "updated_at"])
            return execution
        execution.status = ProviderResultStatus.RUNNING
        execution.started_at = execution.started_at or timezone.now()
        execution.attempt_count += 1
        execution.error = ""
        execution.save(
            update_fields=["status", "started_at", "attempt_count", "error", "updated_at"]
        )

    run = execution.discovery_run
    policy = _EffectiveSourcePolicy(
        execution.provider_key, execution.max_records, execution.budget_cents
    )
    adapter = get_lead_source_adapter(policy.source_key, workspace=run.workspace)
    if adapter is None:
        return _finish_provider_failure(
            execution, f"No lead source adapter registered for {policy.source_key!r}."
        )

    estimated_search_cost = getattr(adapter, "estimated_search_cost_cents", 0)
    if policy.budget_cents is not None and estimated_search_cost > policy.budget_cents:
        execution.status = ProviderResultStatus.BUDGET_BLOCKED
        execution.error = "Configured provider page cost exceeds this source budget."
        execution.finished_at = timezone.now()
        execution.save(update_fields=["status", "error", "finished_at", "updated_at"])
        return execution

    try:
        results = adapter.search(execution.query_snapshot)
    except SoftTimeLimitExceeded:
        return _finish_provider_failure(
            execution,
            "Provider execution exceeded its configured deadline.",
            status=ProviderResultStatus.TIMED_OUT,
        )
    except Exception as exc:  # noqa: BLE001 - source failure is persisted and isolated
        error = str(exc)
        if policy.source_key in {"searxng", "apollo", "google_places"}:
            record_lead_source_outcome(run.workspace, policy.source_key, error)
        status = (
            ProviderResultStatus.RATE_LIMITED
            if "rate limit" in error.lower()
            else ProviderResultStatus.FAILED
        )
        return _finish_provider_failure(execution, error, status=status)

    if policy.source_key in {"searxng", "apollo", "google_places"}:
        record_lead_source_outcome(run.workspace, policy.source_key)

    execution.refresh_from_db(fields=["status"])
    run.refresh_from_db(fields=["status"])
    if (
        execution.status == ProviderResultStatus.CANCELED
        or run.status == DiscoveryRunStatus.CANCELED
    ):
        execution.status = ProviderResultStatus.CANCELED
        execution.finished_at = timezone.now()
        execution.save(update_fields=["status", "finished_at", "updated_at"])
        return execution

    cost = getattr(adapter, "last_search_cost_cents", estimated_search_cost) if results else 0
    record_cost = 10 if settings.TESTING and policy.source_key == "demo" else 0
    created = 0
    for payload in results:
        if policy.budget_cents is not None and cost + record_cost > policy.budget_cents:
            break
        _, was_created = SourceRecord.objects.get_or_create(
            discovery_run=run,
            source_key=policy.source_key,
            external_id=_payload_external_id(policy.source_key, payload),
            defaults={
                "provider_result": execution,
                "raw_payload": payload,
                "status": SourceRecordStatus.PENDING,
            },
        )
        if was_created:
            created += 1
            cost += record_cost

    execution.status = ProviderResultStatus.SUCCEEDED if created else ProviderResultStatus.EMPTY
    execution.records_returned = execution.records.count()
    execution.pages_requested = getattr(adapter, "last_pages_requested", 1)
    execution.pages_returned = getattr(adapter, "last_pages_returned", 1 if results else 0)
    execution.cost_cents = cost if execution.records_returned else 0
    execution.finished_at = timezone.now()
    execution.save(
        update_fields=[
            "status",
            "records_returned",
            "pages_requested",
            "pages_returned",
            "cost_cents",
            "finished_at",
            "updated_at",
        ]
    )
    return execution


def _finish_provider_failure(
    execution: ProviderResult,
    error: str,
    *,
    status: str = ProviderResultStatus.FAILED,
) -> ProviderResult:
    execution.status = status
    execution.error = error
    execution.failure_count += 1
    if status == ProviderResultStatus.RATE_LIMITED:
        execution.rate_limit_count += 1
    if status == ProviderResultStatus.TIMED_OUT:
        execution.timeout_count += 1
    execution.finished_at = timezone.now()
    execution.save(
        update_fields=[
            "status",
            "error",
            "failure_count",
            "rate_limit_count",
            "timeout_count",
            "finished_at",
            "updated_at",
        ]
    )
    return execution


def finalize_run(discovery_run_id) -> DiscoveryRun:
    """Idempotent fan-in. Returns early until every provider is terminal."""
    run = DiscoveryRun.objects.get(pk=discovery_run_id)
    if run.status == DiscoveryRunStatus.CANCELED:
        return run
    active = run.provider_results.filter(
        status__in=[
            ProviderResultStatus.QUEUED,
            ProviderResultStatus.RUNNING,
            ProviderResultStatus.RETRYING,
            ProviderResultStatus.RATE_LIMITED,
        ]
    ).exists()
    if active:
        return run

    totals = run.provider_results.aggregate(records=Sum("records_returned"), cost=Sum("cost_cents"))
    run.records_discovered = totals["records"] or 0
    run.cost_cents = totals["cost"] or 0
    run.save(update_fields=["records_discovered", "cost_cents", "updated_at"])

    _normalize(run)
    _deduplicate(run)
    run.refresh_from_db()
    if run.status == DiscoveryRunStatus.CANCELED:
        return run
    _enrich(run)
    _collect_evidence(run)
    _score(run)

    successful = run.provider_results.filter(
        status__in=[ProviderResultStatus.SUCCEEDED, ProviderResultStatus.EMPTY]
    ).exists()
    failed = run.provider_results.exclude(
        status__in=[ProviderResultStatus.SUCCEEDED, ProviderResultStatus.EMPTY]
    ).exists()
    run.status = (
        DiscoveryRunStatus.PARTIAL
        if successful and failed
        else DiscoveryRunStatus.FAILED
        if failed and not successful
        else DiscoveryRunStatus.SUCCEEDED
    )
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "finished_at", "updated_at"])
    return run


def _discover(run: DiscoveryRun) -> None:
    """Deprecated synchronous discovery phase retained for internal compatibility."""
    for execution in prepare_provider_executions(run):
        execute_provider_search(execution.id)


# --- normalize -----------------------------------------------------------------


def _normalize_payload(raw_payload: dict[str, Any]) -> dict[str, Any]:
    """Maps provider-specific field names onto the project's normalized schema.

    A real (non-demo) provider would register its own mapper here instead
    of relying on this generic fallback chain.
    """
    name = raw_payload.get("company_name") or raw_payload.get("name") or ""
    domain_raw = (
        raw_payload.get("website")
        or raw_payload.get("domain")
        or raw_payload.get("primary_domain")
        or raw_payload.get("website_url")
        or ""
    )
    domain = normalize_domain(domain_raw) if domain_raw else ""
    return {
        "name": name,
        "domain": domain,
        "external_id": raw_payload.get("id") or raw_payload.get("organization_id") or "",
        "industry": raw_payload.get("industry") or "",
        "employee_count": raw_payload.get("estimated_num_employees"),
        "linkedin_url": raw_payload.get("linkedin_url") or "",
    }


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

        external_id = record.normalized_data.get("external_id", "")
        external_ids = {record.source_key: external_id} if external_id else {}
        org = None
        method = ""
        confidence = None
        explanation = ""
        if external_ids:
            org = Organization.objects.filter(
                workspace=workspace, external_ids__contains=external_ids
            ).first()
            if org:
                method = MatchMethod.PROVIDER_ID
                confidence = 1
                explanation = f"Exact {record.source_key} provider identifier match."
        if org is None and domain:
            org = Organization.objects.filter(
                workspace=workspace, dedupe_key=normalize_domain(domain)
            ).first()
            if org:
                method = MatchMethod.DOMAIN
                confidence = 1
                explanation = "Exact normalized domain match."
        if org is None and not domain and name:
            name_matches = Organization.objects.filter(workspace=workspace, name__iexact=name)[:2]
            matches = list(name_matches)
            if len(matches) == 1:
                org = matches[0]
                method = MatchMethod.EXACT_NAME
                confidence = 0.65
                explanation = "Single exact case-insensitive name match; no domain was available."
        created = org is None
        if created:
            org, _ = create_organization(
                workspace, name=name, domain=domain, external_ids=external_ids
            )
            method = MatchMethod.CREATED
            confidence = 1
            explanation = "No existing deterministic or unique exact-name match was found."
        record.organization = org
        record.match_method = method
        record.match_confidence = confidence
        record.match_explanation = explanation
        if not created:
            record.status = SourceRecordStatus.DUPLICATE
            deduplicated_count += 1
        record.save(
            update_fields=[
                "organization",
                "status",
                "match_method",
                "match_confidence",
                "match_explanation",
                "updated_at",
            ]
        )
        if external_ids:
            merged_external_ids = {**org.external_ids, **external_ids}
            if merged_external_ids != org.external_ids:
                org.external_ids = merged_external_ids
                org.save(update_fields=["external_ids", "updated_at"])
        record_organization_claims(record)

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
        provider_key = "demo" if settings.TESTING else "public_website"
        if EnrichmentRun.objects.filter(source_record=record, provider_key=provider_key).exists():
            continue
        domain = record.normalized_data.get("domain", "")
        adapter = (
            get_technology_detection_adapter("demo")
            if settings.TESTING
            else get_website_analysis_adapter("public_website")
        )
        if adapter is None or not domain:
            continue
        try:
            analysis = (
                {"technologies": adapter.detect(domain)}
                if settings.TESTING
                else adapter.analyze(domain)
            )
        except Exception as exc:  # noqa: BLE001 - enrichment is best-effort, never fails the record
            EnrichmentRun.objects.create(
                source_record=record,
                provider_key=provider_key,
                status=EnrichmentRunStatus.FAILED,
                error=str(exc),
            )
            continue
        EnrichmentRun.objects.create(
            source_record=record,
            provider_key=provider_key,
            status=EnrichmentRunStatus.SUCCEEDED,
            result=analysis,
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
        source_type = SourceType.OTHER
        record_evidence(
            org,
            source_url=record.raw_payload.get("source_url")
            or (f"https://{domain}" if domain else ""),
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
