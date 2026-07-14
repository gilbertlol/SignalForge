import pytest

from apps.discovery.models import (
    DiscoveryRunStatus,
    ProviderResultStatus,
    SourceRecordStatus,
)
from apps.discovery.services import (
    create_manual_source_record,
    execute_run,
    import_csv,
    start_run,
)
from apps.discovery.tests.factories import SuppressionEntryFactory
from apps.evidence.models import Evidence
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


def _version(profile, **kwargs):
    return create_version(profile, criteria=_always_matches_domain(), **kwargs)


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
