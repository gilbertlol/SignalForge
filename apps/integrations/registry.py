"""Runtime provider registry; synthetic adapters exist only under TESTING."""

from django.conf import settings

from .adapters import (
    AIModelAdapter,
    LeadSourceAdapter,
    MessagingAdapter,
    TechnologyDetectionAdapter,
)
from .providers.ai import OpenAICompatibleAdapter
from .providers.apollo import ApolloLeadSourceAdapter
from .providers.openstreetmap import OpenStreetMapLeadSourceAdapter
from .providers.website import PublicWebsiteAnalysisAdapter

_LEAD_SOURCE_ADAPTERS: dict[str, type[LeadSourceAdapter]] = {"openstreetmap": OpenStreetMapLeadSourceAdapter}

_TECHNOLOGY_DETECTION_ADAPTERS: dict[str, type[TechnologyDetectionAdapter]] = {}

_AI_MODEL_ADAPTERS: dict[str, type[AIModelAdapter]] = {
    "local_openai": OpenAICompatibleAdapter,
    "cloud_openai": OpenAICompatibleAdapter,
}

_MESSAGING_ADAPTERS: dict[str, type[MessagingAdapter]] = {}

if settings.TESTING:
    from .providers.ai import MockAIModelAdapter
    from .providers.demo import DemoLeadSourceAdapter, DemoTechnologyDetectionAdapter
    from .providers.messaging import MockEmailAdapter, MockSMSAdapter

    _LEAD_SOURCE_ADAPTERS["demo"] = DemoLeadSourceAdapter
    _TECHNOLOGY_DETECTION_ADAPTERS["demo"] = DemoTechnologyDetectionAdapter
    _AI_MODEL_ADAPTERS["mock"] = MockAIModelAdapter
    _MESSAGING_ADAPTERS.update(mock_email=MockEmailAdapter, mock_sms=MockSMSAdapter)


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


def get_website_analysis_adapter(provider_key: str):
    return PublicWebsiteAnalysisAdapter() if provider_key == "public_website" else None


def get_ai_model_adapter(provider_type: str) -> AIModelAdapter | None:
    adapter_class = _AI_MODEL_ADAPTERS.get(provider_type)
    return adapter_class() if adapter_class else None


def get_messaging_adapter(provider_key: str) -> MessagingAdapter | None:
    adapter_class = _MESSAGING_ADAPTERS.get(provider_key)
    return adapter_class() if adapter_class else None
