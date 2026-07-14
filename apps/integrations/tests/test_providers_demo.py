from apps.integrations.providers.demo import DemoLeadSourceAdapter, DemoTechnologyDetectionAdapter


def test_demo_lead_source_adapter_returns_fixed_results():
    adapter = DemoLeadSourceAdapter()

    results = adapter.search({})

    assert len(results) == 5
    assert all("company_name" in r and "website" in r for r in results)


def test_demo_lead_source_adapter_respects_limit():
    adapter = DemoLeadSourceAdapter()

    results = adapter.search({"limit": 2})

    assert len(results) == 2


def test_demo_technology_detection_adapter_returns_a_list():
    adapter = DemoTechnologyDetectionAdapter()

    result = adapter.detect("example.com")

    assert result == ["Google Analytics", "WordPress"]
