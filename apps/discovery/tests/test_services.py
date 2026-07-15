from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from apps.discovery.analytics import build_source_scorecards
from apps.discovery.models import (
    DiscoveryRunStatus,
    EnrichmentRun,
    MatchMethod,
    ProviderResultStatus,
    SourceRecord,
    SourceRecordStatus,
    WebPageObservation,
)
from apps.discovery.services import (
    _collect_evidence,
    _enrich,
    create_manual_source_record,
    execute_provider_search,
    execute_run,
    import_csv,
    prepare_provider_executions,
    start_run,
)
from apps.discovery.tests.factories import SuppressionEntryFactory
from apps.evidence.models import (
    Evidence,
    OrganizationClaim,
    OrganizationFieldResolution,
    SourceType,
)
from apps.hunting.services import create_version
from apps.hunting.tests.factories import HuntProfileFactory
from apps.organizations.models import Organization

pytestmark = pytest.mark.django_db


def _always_matches_domain():
    return {
        "type": "group",
        "operator": "AND",
        "children": [
            {
                "type": "criterion",
                "category": "custom_attribute",
                "field": "domain",
                "op": "neq",
                "value": "",
            }
        ],
    }


def test_unvalidated_paid_source_is_skipped_while_open_source_stays_queued():
    profile = HuntProfileFactory()
    version = create_version(
        profile,
        criteria=_always_matches_domain(),
        source_policies=[
            {"source_key": "openstreetmap", "max_records": 5},
            {"source_key": "apollo", "max_records": 5},
        ],
    )
    run = start_run(version, trigger="manual")

    executions = {item.provider_key: item for item in prepare_provider_executions(run)}

    assert executions["openstreetmap"].status == ProviderResultStatus.QUEUED
    assert executions["apollo"].status == ProviderResultStatus.SKIPPED
    assert "API key not configured" in executions["apollo"].error


def _version(profile, **kwargs):
    return create_version(profile, criteria=_always_matches_domain(), **kwargs)


@override_settings(TESTING=False)
@patch("apps.discovery.services.get_website_analysis_adapter")
def test_public_page_observation_is_reused_and_becomes_observed_evidence(mock_get_adapter):
    profile = HuntProfileFactory()
    version = _version(profile)
    run = start_run(version, trigger="manual")
    organization = Organization.objects.create(
        workspace=profile.workspace,
        name="Observed Co",
        domain="observed.example",
        dedupe_key="observed.example",
    )
    records = [
        SourceRecord.objects.create(
            discovery_run=run,
            source_key="searxng",
            external_id=f"result-{index}",
            raw_payload={"source_url": "https://observed.example/about"},
            normalized_data={"name": "Observed Co", "domain": "observed.example"},
            status=SourceRecordStatus.NORMALIZED,
            organization=organization,
        )
        for index in range(2)
    ]
    adapter = mock_get_adapter.return_value
    adapter.analyze.return_value = {
        "requested_url": "https://observed.example/about",
        "url": "https://observed.example/about",
        "canonical_url": "https://observed.example/company",
        "title": "Observed Co",
        "description": "Precision manufacturing observed on the company website.",
        "visible_text": "Observed Co builds precision components.",
        "contact_links": ["mailto:hello@observed.example"],
        "technologies": ["WordPress"],
        "observed_bytes": 1200,
        "content_sha256": "a" * 64,
    }

    _enrich(run)
    _collect_evidence(run)

    assert adapter.analyze.call_count == 1
    observation = WebPageObservation.objects.get(workspace=profile.workspace)
    assert observation.canonical_url == "https://observed.example/company"
    results = {
        item.source_record_id: item.result
        for item in EnrichmentRun.objects.filter(source_record__in=records)
    }
    assert sorted(result["reused"] for result in results.values()) == [False, True]
    evidence = Evidence.objects.filter(
        workspace=profile.workspace, source_type=SourceType.WEBSITE
    ).first()
    assert evidence is not None
    assert evidence.source_url == "https://observed.example/company"
    assert evidence.excerpt == "Precision manufacturing observed on the company website."


def test_full_pipeline_discovers_normalizes_dedupes_enriches_and_qualifies():
    profile = HuntProfileFactory()
    version = _version(profile, result_threshold={"min_total_score": 0})
    run = start_run(version, trigger="manual")

    execute_run(run)
    run.refresh_from_db()

    assert run.status == DiscoveryRunStatus.SUCCEEDED
    assert run.records_discovered == 5
    assert run.records_qualified == 5
    assert Organization.objects.filter(workspace=profile.workspace).count() == 5
    assert run.source_records.filter(status=SourceRecordStatus.QUALIFIED).count() == 5


def test_rerunning_the_same_run_is_idempotent():
    profile = HuntProfileFactory()
    version = _version(profile, result_threshold={"min_total_score": 0})
    run = start_run(version, trigger="manual")

    execute_run(run)
    org_count_after_first = Organization.objects.filter(workspace=profile.workspace).count()
    record_count_after_first = run.source_records.count()
    evidence_count_after_first = Evidence.objects.filter(workspace=profile.workspace).count()

    execute_run(run)

    assert Organization.objects.filter(workspace=profile.workspace).count() == org_count_after_first
    assert run.source_records.count() == record_count_after_first
    assert (
        Evidence.objects.filter(workspace=profile.workspace).count() == evidence_count_after_first
    )


def test_duplicate_provider_task_delivery_does_not_duplicate_records_or_cost():
    profile = HuntProfileFactory()
    version = _version(profile, result_threshold={"min_total_score": 0})
    run = start_run(version, trigger="manual")
    execution = prepare_provider_executions(run)[0]

    execute_provider_search(execution.id)
    execute_provider_search(execution.id)

    execution.refresh_from_db()
    assert execution.records.count() == 5
    assert execution.records_returned == 5
    assert execution.cost_cents == 50
    assert execution.attempt_count == 1
    assert execution.policy_snapshot["source_key"] == "demo"
    assert execution.policy_snapshot["timeout_seconds"] == 30


def test_rerunning_the_same_source_via_a_new_run_does_not_duplicate_organizations():
    profile = HuntProfileFactory()
    version = _version(profile, result_threshold={"min_total_score": 0})

    run1 = start_run(version, trigger="manual")
    execute_run(run1)
    assert Organization.objects.filter(workspace=profile.workspace).count() == 5

    run2 = start_run(version, trigger="manual")
    execute_run(run2)

    assert Organization.objects.filter(workspace=profile.workspace).count() == 5
    # "duplicate" is an intermediate marker the score phase overwrites with a
    # final qualified/rejected status; the durable dedup signal is the counter.
    run2.refresh_from_db()
    assert run2.records_deduplicated == 5
    assert run2.source_records.filter(status=SourceRecordStatus.QUALIFIED).count() == 5


def test_max_records_is_enforced():
    profile = HuntProfileFactory()
    version = _version(
        profile,
        source_policies=[{"source_key": "demo", "max_records": 2}],
        result_threshold={"min_total_score": 0},
    )
    run = start_run(version, trigger="manual")

    execute_run(run)
    run.refresh_from_db()

    assert run.records_discovered == 2
    assert run.source_records.count() == 2


def test_budget_cents_is_enforced():
    profile = HuntProfileFactory()
    # cost is 10 cents/record: a 25-cent budget affords exactly 2 records.
    version = _version(
        profile,
        source_policies=[{"source_key": "demo", "budget_cents": 25}],
        result_threshold={"min_total_score": 0},
    )
    run = start_run(version, trigger="manual")

    execute_run(run)
    run.refresh_from_db()

    assert run.records_discovered == 2
    assert run.cost_cents == 20


def test_all_providers_failing_marks_the_run_failed():
    profile = HuntProfileFactory()
    version = _version(
        profile,
        source_policies=[{"source_key": "does-not-exist"}],
        result_threshold={"min_total_score": 0},
    )
    run = start_run(version, trigger="manual")

    execute_run(run)
    run.refresh_from_db()

    assert run.status == DiscoveryRunStatus.FAILED
    assert run.provider_results.get().status == ProviderResultStatus.FAILED


@patch("apps.discovery.services.get_lead_source_adapter")
def test_provider_rate_limit_is_explicitly_persisted(mock_get_adapter):
    adapter = mock_get_adapter.return_value
    adapter.search.side_effect = RuntimeError("Provider rate limit was reached.")
    adapter.estimated_search_cost_cents = 0
    profile = HuntProfileFactory()
    version = _version(profile, source_policies=[{"source_key": "limited"}])
    run = start_run(version, trigger="manual")
    execution = prepare_provider_executions(run)[0]

    execute_provider_search(execution.id)

    execution.refresh_from_db()
    assert execution.status == ProviderResultStatus.RATE_LIMITED


def test_partial_provider_failure_does_not_corrupt_the_run():
    profile = HuntProfileFactory()
    version = _version(
        profile,
        source_policies=[
            {"source_key": "demo"},
            {"source_key": "does-not-exist"},
        ],
        result_threshold={"min_total_score": 0},
    )
    run = start_run(version, trigger="manual")

    execute_run(run)
    run.refresh_from_db()

    assert run.status == DiscoveryRunStatus.PARTIAL
    assert run.provider_results.filter(status=ProviderResultStatus.SUCCEEDED).count() == 1
    assert run.provider_results.filter(status=ProviderResultStatus.FAILED).count() == 1
    # the working source's records were still fully processed
    assert run.source_records.filter(status=SourceRecordStatus.QUALIFIED).count() == 5


def test_multiple_sources_merge_with_claim_provenance_and_conflicts():
    class Adapter:
        def __init__(self, payload):
            self.payload = payload

        def search(self, _query):
            return [self.payload]

    profile = HuntProfileFactory()
    version = _version(
        profile,
        source_policies=[{"source_key": "source-a"}, {"source_key": "source-b"}],
        result_threshold={"min_total_score": 0},
    )
    run = start_run(version, trigger="manual")
    adapters = {
        "source-a": Adapter(
            {
                "id": "a-1",
                "name": "Acme Automation",
                "domain": "acme.test",
                "industry": "automation",
                "estimated_num_employees": 20,
            }
        ),
        "source-b": Adapter(
            {
                "id": "b-9",
                "name": "Acme Automation Inc.",
                "domain": "https://www.acme.test/",
                "industry": "industrial automation",
                "estimated_num_employees": 20,
            }
        ),
    }

    with patch(
        "apps.discovery.services.get_lead_source_adapter",
        side_effect=lambda key, **_kwargs: adapters[key],
    ):
        execute_run(run)

    organization = Organization.objects.get(workspace=profile.workspace, domain="acme.test")
    assert run.source_records.count() == 2
    assert OrganizationClaim.objects.filter(organization=organization).count() == 10
    assert organization.external_ids == {"source-a": "a-1", "source-b": "b-9"}
    records = list(run.source_records.order_by("created_at"))
    assert {record.match_method for record in records} == {
        MatchMethod.CREATED,
        MatchMethod.DOMAIN,
    }
    domain_match = next(record for record in records if record.match_method == MatchMethod.DOMAIN)
    assert domain_match.match_confidence == 1
    assert "normalized domain" in domain_match.match_explanation

    headcount = OrganizationFieldResolution.objects.get(
        organization=organization, field_name="employee_count"
    )
    industry = OrganizationFieldResolution.objects.get(
        organization=organization, field_name="industry"
    )
    assert headcount.corroboration_count == 2
    assert headcount.has_conflict is False
    assert industry.distinct_value_count == 2
    assert industry.has_conflict is True

    analytics = build_source_scorecards(type(run).objects.filter(pk=run.pk))
    cards = {card["source_key"]: card for card in analytics["scorecards"]}
    assert cards["source-a"]["cross_source_overlaps"] == 1
    assert cards["source-a"]["multi_touch_organizations"] == 1
    assert cards["source-b"]["fractional_organization_credit"] == 0.5
    assert cards["source-a"]["sample_warning"]
    assert analytics["recommendation"]["is_directional"] is True

    record = records[0]
    record.raw_payload = {"tampered": True}
    with pytest.raises(ValidationError, match="immutable"):
        record.save()

    claim = OrganizationClaim.objects.filter(organization=organization).first()
    claim.value = "tampered"
    with pytest.raises(ValidationError, match="immutable"):
        claim.save()


def test_provider_identifier_merges_domainless_records_across_runs():
    class Adapter:
        def search(self, _query):
            return [{"id": "stable-42", "name": "Domainless Company"}]

    profile = HuntProfileFactory()
    version = _version(
        profile,
        source_policies=[{"source_key": "stable-source"}],
        result_threshold={"min_total_score": 0},
    )

    with patch("apps.discovery.services.get_lead_source_adapter", return_value=Adapter()):
        first_run = start_run(version, trigger="manual")
        execute_run(first_run)
        second_run = start_run(version, trigger="manual")
        execute_run(second_run)

    assert Organization.objects.filter(workspace=profile.workspace).count() == 1
    second_record = second_run.source_records.get()
    assert second_record.match_method == MatchMethod.PROVIDER_ID
    assert second_record.match_confidence == 1
    assert "provider identifier" in second_record.match_explanation


def test_suppressed_domain_blocks_organization_creation():
    profile = HuntProfileFactory()
    SuppressionEntryFactory(workspace=profile.workspace, domain="riversideautomation.com")
    version = _version(profile, result_threshold={"min_total_score": 0})
    run = start_run(version, trigger="manual")

    execute_run(run)

    assert not Organization.objects.filter(
        workspace=profile.workspace, domain="riversideautomation.com"
    ).exists()
    assert run.source_records.filter(status=SourceRecordStatus.SUPPRESSED).count() == 1
    assert run.source_records.filter(status=SourceRecordStatus.QUALIFIED).count() == 4


def test_qualified_records_have_evidence_linked_to_their_organization():
    profile = HuntProfileFactory()
    version = _version(profile, result_threshold={"min_total_score": 0})
    run = start_run(version, trigger="manual")

    execute_run(run)

    for record in run.source_records.filter(status=SourceRecordStatus.QUALIFIED):
        assert Evidence.objects.filter(
            content_type__model="organization", object_id=record.organization_id
        ).exists()


def test_execute_run_on_a_canceled_run_is_a_noop():
    profile = HuntProfileFactory()
    version = _version(profile)
    run = start_run(version, trigger="manual")
    run.status = DiscoveryRunStatus.CANCELED
    run.save(update_fields=["status"])

    execute_run(run)

    assert run.source_records.count() == 0


def test_create_manual_source_record_skips_straight_to_normalized():
    profile = HuntProfileFactory()
    version = _version(profile)
    run = start_run(version, trigger="manual")

    record = create_manual_source_record(run, name="Acme Manual Co", domain="acmemanual.com")

    assert record.status == SourceRecordStatus.NORMALIZED
    assert record.normalized_data["domain"] == "acmemanual.com"
    run.refresh_from_db()
    assert run.records_discovered == 1


def test_import_csv_creates_pending_records_for_normalize_to_process():
    import io

    profile = HuntProfileFactory()
    # Explicitly disabling the demo source (vs. configuring none at all)
    # isolates this test to the CSV-only path -- see
    # _get_effective_source_policies's docstring for why that distinction
    # exists.
    version = _version(
        profile,
        source_policies=[{"source_key": "demo", "is_enabled": False}],
        result_threshold={"min_total_score": 0},
    )
    run = start_run(version, trigger="manual")
    csv_content = "name,domain\nCsv Co,csvco.com\nAnother Co,anotherco.com\n"

    records = import_csv(run, io.BytesIO(csv_content.encode()))

    assert len(records) == 2
    assert all(r.status == SourceRecordStatus.PENDING for r in records)

    execute_run(run)
    run.refresh_from_db()
    assert run.records_qualified == 2
    assert Organization.objects.filter(workspace=profile.workspace, domain="csvco.com").exists()
