"""Provider adapter seams.

These abstract base classes document how future lead sources, messaging
providers, and AI models plug into SignalForge without any of them being
hard-coded into the core application. No concrete provider is implemented
in this ticket — that starts with the first real integration issue.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GroundedCompletion:
    text: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    search_cost_cents: float = 0


class ProviderAdapter(ABC):
    """Base contract every provider adapter implements."""

    provider_key: str

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether this adapter has the credentials/config it needs to run."""
        raise NotImplementedError


class LeadSourceAdapter(ProviderAdapter):
    capabilities: frozenset[str] = frozenset()
    """Searches an external source for prospect signals."""

    @abstractmethod
    def search(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError


class EnrichmentAdapter(ProviderAdapter):
    """Adds normalized fields to an already-discovered record."""

    @abstractmethod
    def enrich(self, record: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class EmailVerificationAdapter(ProviderAdapter):
    """Checks deliverability/risk for an email address."""

    @abstractmethod
    def verify(self, email: str) -> dict[str, Any]:
        raise NotImplementedError


class TechnologyDetectionAdapter(ProviderAdapter):
    """Detects technologies/tools a domain appears to use."""

    @abstractmethod
    def detect(self, domain: str) -> list[str]:
        raise NotImplementedError


class WebsiteAnalysisAdapter(ProviderAdapter):
    """Extracts signals (content, structure, indicators) from a website."""

    @abstractmethod
    def analyze(self, url: str) -> dict[str, Any]:
        raise NotImplementedError


class MessagingAdapter(ProviderAdapter):
    """Sends outbound communication (email, SMS, etc.) through a provider."""

    @abstractmethod
    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class AIModelAdapter(ProviderAdapter):
    """Connects to a local or cloud AI model for scoring/generation."""

    @abstractmethod
    def complete(self, prompt: str, **options: Any) -> str:
        raise NotImplementedError

    def grounded_complete(self, prompt: str, **options: Any) -> GroundedCompletion:
        """Run vendor-native web search. Unsupported adapters fail closed."""
        raise NotImplementedError("grounded web search is not supported")
