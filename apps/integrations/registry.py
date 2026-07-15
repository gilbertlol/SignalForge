"""Provider lookup by `source_key`/`provider_key` string.

Keeps `apps.discovery` (and any future caller) from hard-coding provider
names — it asks the registry for "the lead source adapter for 'demo'"
instead of importing a concrete class directly.
"""

from .adapters import (
    AIModelAdapter,
    LeadSourceAdapter,
    MessagingAdapter,
    TechnologyDetectionAdapter,
)
from .providers.ai import MockAIModelAdapter, OpenAICompatibleAdapter
from .providers.apollo import ApolloLeadSourceAdapter
from .providers.demo import DemoLeadSourceAdapter, DemoTechnologyDetectionAdapter
from .providers.messaging import MockEmailAdapter, MockSMSAdapter

_LEAD_SOURCE_ADAPTERS: dict[str, type[LeadSourceAdapter]] = {
    "demo": DemoLeadSourceAdapter,
}

_TECHNOLOGY_DETECTION_ADAPTERS: dict[str, type[TechnologyDetectionAdapter]] = {
    "demo": DemoTechnologyDetectionAdapter,
}

_AI_MODEL_ADAPTERS: dict[str, type[AIModelAdapter]] = {
    "mock": MockAIModelAdapter,
    "local_openai": OpenAICompatibleAdapter,
    "cloud_openai": OpenAICompatibleAdapter,
}

_MESSAGING_ADAPTERS: dict[str, type[MessagingAdapter]] = {
    "mock_email": MockEmailAdapter,
    "mock_sms": MockSMSAdapter,
}


def get_lead_source_adapter(source_key: str, *, workspace=None) -> LeadSourceAdapter | None:
    if source_key == "apollo":
        if workspace is None:
            return None
        from .models import LeadSourceConfiguration

        configuration = (
            LeadSourceConfiguration.objects.filter(
                workspace=workspace, source_key=source_key, enabled=True
            )
            .select_related("credential")
            .first()
        )
        return ApolloLeadSourceAdapter(configuration) if configuration else None
    adapter_class = _LEAD_SOURCE_ADAPTERS.get(source_key)
    return adapter_class() if adapter_class else None


def get_technology_detection_adapter(source_key: str) -> TechnologyDetectionAdapter | None:
    adapter_class = _TECHNOLOGY_DETECTION_ADAPTERS.get(source_key)
    return adapter_class() if adapter_class else None


def get_ai_model_adapter(provider_type: str) -> AIModelAdapter | None:
    adapter_class = _AI_MODEL_ADAPTERS.get(provider_type)
    return adapter_class() if adapter_class else None


def get_messaging_adapter(provider_key: str) -> MessagingAdapter | None:
    adapter_class = _MESSAGING_ADAPTERS.get(provider_key)
    return adapter_class() if adapter_class else None
