"""Provider lookup by `source_key`/`provider_key` string.

Keeps `apps.discovery` (and any future caller) from hard-coding provider
names — it asks the registry for "the lead source adapter for 'demo'"
instead of importing a concrete class directly.
"""

from .adapters import LeadSourceAdapter, TechnologyDetectionAdapter
from .providers.demo import DemoLeadSourceAdapter, DemoTechnologyDetectionAdapter

_LEAD_SOURCE_ADAPTERS: dict[str, type[LeadSourceAdapter]] = {
    "demo": DemoLeadSourceAdapter,
}

_TECHNOLOGY_DETECTION_ADAPTERS: dict[str, type[TechnologyDetectionAdapter]] = {
    "demo": DemoTechnologyDetectionAdapter,
}


def get_lead_source_adapter(source_key: str) -> LeadSourceAdapter | None:
    adapter_class = _LEAD_SOURCE_ADAPTERS.get(source_key)
    return adapter_class() if adapter_class else None


def get_technology_detection_adapter(source_key: str) -> TechnologyDetectionAdapter | None:
    adapter_class = _TECHNOLOGY_DETECTION_ADAPTERS.get(source_key)
    return adapter_class() if adapter_class else None
