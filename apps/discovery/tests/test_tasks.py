from unittest.mock import patch

import pytest

from apps.discovery.models import (
    DiscoveryRun,
    DiscoveryRunStatus,
    DiscoveryRunTrigger,
    ProviderResultStatus,
)
from apps.discovery.services import finalize_run, prepare_provider_executions, start_run
from apps.discovery.tasks import dispatch_scheduled_discoveries, run_discovery_task
from apps.hunting.models import HuntProfileStatus, ScheduleFrequency
from apps.hunting.services import activate_version, create_version, ensure_schedule_policy
from apps.hunting.tests.factories import HuntProfileFactory

pytestmark = pytest.mark.django_db


def _active_profile_with_daily_schedule():
    profile = HuntProfileFactory()
    version = create_version(
        profile,
        criteria={
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
        },
        result_threshold={"min_total_score": 0},
    )
    activate_version(profile, version)
    assert profile.status == HuntProfileStatus.ACTIVE
    ensure_schedule_policy(profile, frequency=ScheduleFrequency.DAILY, is_enabled=True)
    return profile


def test_dispatch_scheduled_discoveries_starts_a_run_for_an_active_daily_profile():
    profile = _active_profile_with_daily_schedule()

    dispatched = dispatch_scheduled_discoveries()

    assert dispatched == 1
    run = DiscoveryRun.objects.get(hunt_profile_version__profile=profile)
    assert run.trigger == DiscoveryRunTrigger.SCHEDULED
    assert run.status == DiscoveryRunStatus.SUCCEEDED  # eager Celery in test settings


def test_dispatch_scheduled_discoveries_does_not_double_dispatch_same_day():
    _active_profile_with_daily_schedule()

    first = dispatch_scheduled_discoveries()
    second = dispatch_scheduled_discoveries()

    assert first == 1
    assert second == 0
    assert DiscoveryRun.objects.filter(trigger=DiscoveryRunTrigger.SCHEDULED).count() == 1


def test_dispatch_scheduled_discoveries_skips_inactive_profiles():
    profile = HuntProfileFactory()
    create_version(
        profile,
        criteria={
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
        },
    )
    ensure_schedule_policy(profile, frequency=ScheduleFrequency.DAILY, is_enabled=True)
    # profile stays in draft status (never activated) -- version exists but profile isn't active

    dispatched = dispatch_scheduled_discoveries()

    assert dispatched == 0


def test_prepare_provider_executions_is_idempotent():
    profile = _active_profile_with_daily_schedule()
    run = start_run(profile.current_version, trigger=DiscoveryRunTrigger.MANUAL)

    first = prepare_provider_executions(run)
    second = prepare_provider_executions(run)

    assert [item.id for item in first] == [item.id for item in second]
    assert run.provider_results.count() == 1


def test_finalize_waits_until_every_source_is_terminal():
    profile = _active_profile_with_daily_schedule()
    run = start_run(profile.current_version, trigger=DiscoveryRunTrigger.MANUAL)
    execution = prepare_provider_executions(run)[0]

    finalize_run(run.id)

    run.refresh_from_db()
    assert execution.status == ProviderResultStatus.QUEUED
    assert run.status == DiscoveryRunStatus.RUNNING


@patch("apps.discovery.tasks.chord")
def test_run_discovery_fans_out_one_signature_per_source(mock_chord):
    profile = _active_profile_with_daily_schedule()
    version = profile.current_version
    version.source_policies.create(source_key="demo")
    version.source_policies.create(source_key="unknown-second-source")
    run = start_run(version, trigger=DiscoveryRunTrigger.MANUAL)

    run_discovery_task(str(run.id))

    header = mock_chord.call_args.args[0]
    assert len(header) == 2
    assert {signature.task for signature in header} == {"discovery.run_provider"}
    assert run.provider_results.count() == 2
