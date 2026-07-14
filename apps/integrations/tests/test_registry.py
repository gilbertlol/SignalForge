from apps.integrations.providers.demo import DemoLeadSourceAdapter, DemoTechnologyDetectionAdapter
from apps.integrations.registry import get_lead_source_adapter, get_technology_detection_adapter


def test_get_lead_source_adapter_resolves_demo():
    adapter = get_lead_source_adapter("demo")
    assert isinstance(adapter, DemoLeadSourceAdapter)


def test_get_lead_source_adapter_returns_none_for_unknown_key():
    assert get_lead_source_adapter("does-not-exist") is None


def test_get_technology_detection_adapter_resolves_demo():
    adapter = get_technology_detection_adapter("demo")
    assert isinstance(adapter, DemoTechnologyDetectionAdapter)
