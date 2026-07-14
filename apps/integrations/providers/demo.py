"""Fixed, deterministic demo providers.

Prove the provider-registry seam end-to-end (discovery + one enrichment
kind) without needing real credentials or network access. Field names in
`DemoLeadSourceAdapter`'s results deliberately differ from the project's
normalized schema (`company_name`/`website` vs `name`/`domain`) so the
discovery pipeline's normalize step does real mapping work, not passthrough.
"""

from typing import Any

from apps.integrations.adapters import LeadSourceAdapter, TechnologyDetectionAdapter

_DEMO_COMPANIES: list[dict[str, Any]] = [
    {"company_name": "Riverside Automation Co", "website": "riversideautomation.com"},
    {"company_name": "BrightPath Consulting", "website": "brightpathconsulting.com"},
    {"company_name": "NorthStar SaaS Labs", "website": "northstarsaas.com"},
    {"company_name": "Bluepeak Professional Services", "website": "bluepeakservices.com"},
    {"company_name": "Ridgeline CRM Solutions", "website": "ridgelinecrm.com"},
]


class DemoLeadSourceAdapter(LeadSourceAdapter):
    provider_key = "demo"

    def is_configured(self) -> bool:
        return True

    def search(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        limit = query.get("limit")
        results = _DEMO_COMPANIES
        return results[:limit] if limit is not None else list(results)


class DemoTechnologyDetectionAdapter(TechnologyDetectionAdapter):
    provider_key = "demo"

    def is_configured(self) -> bool:
        return True

    def detect(self, domain: str) -> list[str]:
        return ["Google Analytics", "WordPress"]
