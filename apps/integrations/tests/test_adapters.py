import pytest

from apps.integrations.adapters import (
    AIModelAdapter,
    EmailVerificationAdapter,
    EnrichmentAdapter,
    LeadSourceAdapter,
    MessagingAdapter,
    ProviderAdapter,
    TechnologyDetectionAdapter,
    WebsiteAnalysisAdapter,
)


@pytest.mark.parametrize(
    "adapter_class",
    [
        ProviderAdapter,
        LeadSourceAdapter,
        MessagingAdapter,
        AIModelAdapter,
        EnrichmentAdapter,
        EmailVerificationAdapter,
        TechnologyDetectionAdapter,
        WebsiteAnalysisAdapter,
    ],
)
def test_adapter_base_classes_cannot_be_instantiated_directly(adapter_class):
    with pytest.raises(TypeError):
        adapter_class()
