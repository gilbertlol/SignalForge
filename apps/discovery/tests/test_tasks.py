import pytest

from apps.discovery.models import DiscoveryRun, DiscoveryRunStatus, DiscoveryRunTrigger
from apps.discovery.tasks import dispatch_scheduled_discoveries
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
