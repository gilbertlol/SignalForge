"""Vendor-native grounded web-search adapters.

Only this module knows vendor HTTP and citation shapes. Domain services consume
GroundedCompletion and retain the raw response for auditability.
"""

import json
import urllib.error
import urllib.request
from typing import Any

from apps.integrations.adapters import AIModelAdapter, GroundedCompletion


def _post(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: int,
    max_retries: int = 1,
) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    attempts = max(1, min(max_retries + 1, 3))
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == attempts - 1:
                raise
        except urllib.error.URLError:
            if attempt == attempts - 1:
                raise
    raise RuntimeError("grounded search request failed")


def _citation(url: str, title: str = "", **extra: Any) -> dict[str, Any]:
    return {"url": url, "title": title, **extra}


class GroundedAdapter(AIModelAdapter):
    capabilities = frozenset({"grounded_web_search", "citations"})

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt: str, **options: Any) -> str:
        result = self.grounded_complete(prompt, **options)
        options["_grounded_result"] = result
        return result.text


class OpenAIResponsesWebSearchAdapter(GroundedAdapter):
    provider_key = "openai"

    def grounded_complete(self, prompt: str, **options: Any) -> GroundedCompletion:
        body = _post(
            f"{options['base_url'].rstrip('/')}/responses",
            {
                "model": options["model"],
                "input": prompt,
                "tools": [{"type": "web_search"}],
                "store": False,
            },
            {"Authorization": f"Bearer {options['api_key']}"},
            options.get("timeout", 30),
            options.get("max_retries", 1),
        )
        texts, citations, queries = [], [], []
        for item in body.get("output", []):
            if item.get("type") == "web_search_call":
                action = item.get("action", {})
                queries.extend(action.get("queries", []))
                if action.get("query"):
                    queries.append(action["query"])
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    texts.append(content.get("text", ""))
                    for note in content.get("annotations", []):
                        if note.get("type") == "url_citation" and note.get("url"):
                            citations.append(
                                _citation(
                                    note["url"],
                                    note.get("title", ""),
                                    start_index=note.get("start_index"),
                                    end_index=note.get("end_index"),
                                )
                            )
        usage = body.get("usage", {})
        return GroundedCompletion(
            "\n".join(texts),
            citations,
            queries,
            body,
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
        )


class GeminiGoogleSearchAdapter(GroundedAdapter):
    provider_key = "gemini"

    def grounded_complete(self, prompt: str, **options: Any) -> GroundedCompletion:
        url = f"{options['base_url'].rstrip('/')}/models/{options['model']}:generateContent"
        body = _post(
            url,
            {"contents": [{"parts": [{"text": prompt}]}], "tools": [{"google_search": {}}]},
            {"x-goog-api-key": options["api_key"]},
            options.get("timeout", 30),
            options.get("max_retries", 1),
        )
        candidate = (body.get("candidates") or [{}])[0]
        text = "".join(
            part.get("text", "") for part in candidate.get("content", {}).get("parts", [])
        )
        grounding = candidate.get("groundingMetadata", {})
        citations = []
        for chunk in grounding.get("groundingChunks", []):
            web = chunk.get("web", {})
            if web.get("uri"):
                citations.append(_citation(web["uri"], web.get("title", "")))
        usage = body.get("usageMetadata", {})
        return GroundedCompletion(
            text,
            citations,
            grounding.get("webSearchQueries", []),
            body,
            usage.get("promptTokenCount", 0),
            usage.get("candidatesTokenCount", 0),
        )


class MistralWebSearchAdapter(GroundedAdapter):
    provider_key = "mistral"

    def grounded_complete(self, prompt: str, **options: Any) -> GroundedCompletion:
        body = _post(
            f"{options['base_url'].rstrip('/')}/conversations",
            {"model": options["model"], "inputs": prompt, "tools": [{"type": "web_search"}]},
            {"Authorization": f"Bearer {options['api_key']}"},
            options.get("timeout", 30),
            options.get("max_retries", 1),
        )
        outputs = body.get("outputs", body.get("output", []))
        texts, citations, queries = [], [], []
        for item in outputs:
            if item.get("type") in {"message.output", "text", "model_output"}:
                content = item.get("content", item.get("text", ""))
                if isinstance(content, str):
                    texts.append(content)
                else:
                    texts.extend(part.get("text", "") for part in content if part.get("text"))
            for ref in item.get("references", item.get("citations", [])):
                url = ref.get("url", ref.get("uri"))
                if url:
                    citations.append(_citation(url, ref.get("title", "")))
            if item.get("type") in {"web_search", "web_search_call"}:
                query = item.get("query")
                if query:
                    queries.append(query)
        usage = body.get("usage", {})
        return GroundedCompletion(
            "\n".join(texts),
            citations,
            queries,
            body,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )


class AnthropicWebSearchAdapter(GroundedAdapter):
    provider_key = "anthropic"

    def grounded_complete(self, prompt: str, **options: Any) -> GroundedCompletion:
        body = _post(
            f"{options['base_url'].rstrip('/')}/messages",
            {
                "model": options["model"],
                "max_tokens": options.get("max_tokens", 2048),
                "messages": [{"role": "user", "content": prompt}],
                "tools": [
                    {
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": options.get("max_searches", 5),
                    }
                ],
            },
            {"x-api-key": options["api_key"], "anthropic-version": "2023-06-01"},
            options.get("timeout", 30),
            options.get("max_retries", 1),
        )
        texts, citations, queries = [], [], []
        for block in body.get("content", []):
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
                for cite in block.get("citations", []):
                    url = cite.get("url")
                    if url:
                        citations.append(
                            _citation(
                                url, cite.get("title", ""), cited_text=cite.get("cited_text", "")
                            )
                        )
            if block.get("type") == "server_tool_use" and block.get("name") == "web_search":
                query = block.get("input", {}).get("query")
                if query:
                    queries.append(query)
        usage = body.get("usage", {})
        return GroundedCompletion(
            "\n".join(texts),
            citations,
            queries,
            body,
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
        )
