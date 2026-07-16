import json
from unittest.mock import MagicMock, patch

import pytest

from apps.core.models import Workspace
from apps.integrations.adapters import GroundedCompletion
from apps.integrations.models import (
    AIEndpoint,
    AIProvider,
    GroundedSearchTrace,
    ModelDefinition,
    ModelRoute,
    ModelRouteEntry,
    PrivacyClass,
    ProviderHealthCheck,
    ProviderType,
)
from apps.integrations.providers.grounded import (
    AnthropicWebSearchAdapter,
    GeminiGoogleSearchAdapter,
    MistralWebSearchAdapter,
    OpenAIResponsesWebSearchAdapter,
)
from apps.integrations.services import invoke, route_models

pytestmark = pytest.mark.django_db


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(self.body).encode()


@pytest.mark.parametrize(
    ("adapter", "body", "expected_url", "expected_query"),
    [
        (
            OpenAIResponsesWebSearchAdapter(),
            {
                "output": [
                    {"type": "web_search_call", "action": {"query": "signalforge"}},
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Answer",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://openai.example",
                                        "title": "OpenAI source",
                                    }
                                ],
                            }
                        ],
                    },
                ],
                "usage": {"input_tokens": 4, "output_tokens": 2},
            },
            "https://openai.example",
            "signalforge",
        ),
        (
            GeminiGoogleSearchAdapter(),
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Answer"}]},
                        "groundingMetadata": {
                            "webSearchQueries": ["signalforge"],
                            "groundingChunks": [
                                {"web": {"uri": "https://gemini.example", "title": "Gemini source"}}
                            ],
                        },
                    }
                ]
            },
            "https://gemini.example",
            "signalforge",
        ),
        (
            MistralWebSearchAdapter(),
            {
                "outputs": [
                    {
                        "type": "web_search_call",
                        "query": "signalforge",
                        "references": [{"url": "https://mistral.example"}],
                    },
                    {"type": "message.output", "content": "Answer"},
                ]
            },
            "https://mistral.example",
            "signalforge",
        ),
        (
            AnthropicWebSearchAdapter(),
            {
                "content": [
                    {
                        "type": "server_tool_use",
                        "name": "web_search",
                        "input": {"query": "signalforge"},
                    },
                    {
                        "type": "text",
                        "text": "Answer",
                        "citations": [
                            {"url": "https://anthropic.example", "title": "Anthropic source"}
                        ],
                    },
                ]
            },
            "https://anthropic.example",
            "signalforge",
        ),
    ],
)
@patch("apps.integrations.providers.grounded.urllib.request.urlopen")
def test_grounded_adapters_normalize_vendor_citations(
    urlopen, adapter, body, expected_url, expected_query
):
    urlopen.return_value = Response(body)

    result = adapter.grounded_complete(
        "Research", model="model-1", base_url="https://api.example/v1", api_key="secret"
    )

    assert result.text == "Answer"
    assert result.citations[0]["url"] == expected_url
    assert expected_query in result.search_queries
    request = urlopen.call_args.args[0]
    assert b"secret" not in request.data


def _grounded_route(workspace):
    provider = AIProvider.objects.create(
        workspace=workspace,
        name="OpenAI BYOK",
        provider_key="openai",
        provider_type=ProviderType.NATIVE,
    )
    endpoint = AIEndpoint.objects.create(
        workspace=workspace,
        provider=provider,
        name="Responses",
        base_url="https://api.openai.com/v1",
        privacy_class=PrivacyClass.PUBLIC_CLOUD,
    )
    model = ModelDefinition.objects.create(
        workspace=workspace, endpoint=endpoint, model_name="gpt-test", display_name="GPT test"
    )
    route = ModelRoute.objects.create(
        workspace=workspace,
        task_type="research_query_planning",
        name="Grounded",
        required_privacy_class=PrivacyClass.PUBLIC_CLOUD,
    )
    ModelRouteEntry.objects.create(route=route, model=model, position=1)
    return route, provider


def test_grounded_model_is_not_selectable_until_live_validation():
    workspace = Workspace.objects.create(name="Health", slug="health")
    route, provider = _grounded_route(workspace)

    assert route_models(route) == []

    ProviderHealthCheck.objects.create(
        workspace=workspace,
        provider=provider,
        endpoint=provider.endpoints.get(),
        was_successful=True,
        capabilities=["grounded_web_search", "citations"],
    )
    assert route_models(route) == [route.entries.get().model]


@patch("apps.integrations.services.get_ai_model_adapter")
def test_gateway_persists_grounded_trace_and_vendor_usage(get_adapter):
    workspace = Workspace.objects.create(name="Trace", slug="trace")
    route, provider = _grounded_route(workspace)
    ProviderHealthCheck.objects.create(
        workspace=workspace,
        provider=provider,
        endpoint=provider.endpoints.get(),
        was_successful=True,
        capabilities=["grounded_web_search"],
    )
    adapter = MagicMock()
    adapter.is_configured.return_value = True
    adapter.capabilities = {"grounded_web_search", "citations"}
    adapter.grounded_complete.return_value = GroundedCompletion(
        text="Grounded answer",
        citations=[{"url": "https://source.example", "title": "Source"}],
        search_queries=["query used"],
        raw_metadata={"response_id": "vendor-1"},
        input_tokens=11,
        output_tokens=7,
    )
    get_adapter.return_value = adapter

    result = invoke(route=route, prompt="Find a company")

    trace = GroundedSearchTrace.objects.get(invocation=result.invocation)
    assert trace.provider_key == "openai"
    assert trace.citations[0]["url"] == "https://source.example"
    assert trace.raw_metadata == {"response_id": "vendor-1"}
    assert result.invocation.input_tokens == 11
    assert result.invocation.output_tokens == 7
