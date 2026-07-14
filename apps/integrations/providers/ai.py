import json
import urllib.request
from typing import Any

from apps.integrations.adapters import AIModelAdapter


class MockAIModelAdapter(AIModelAdapter):
    provider_key = "mock"

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt: str, **options: Any) -> str:
        if options.get("fail") or options.get("model") in options.get("fail_models", []):
            raise RuntimeError("Mock provider failure")
        response = options.get("mock_response")
        if response is not None:
            return response if isinstance(response, str) else json.dumps(response)
        return json.dumps({"text": prompt})


class OpenAICompatibleAdapter(AIModelAdapter):
    provider_key = "openai_compatible"

    def is_configured(self) -> bool:
        return True

    def complete(self, prompt: str, **options: Any) -> str:
        base_url = options["base_url"].rstrip("/")
        payload = json.dumps(
            {
                "model": options["model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": options.get("temperature", 0),
            }
        ).encode()
        headers = {"Content-Type": "application/json"}
        if options.get("api_key"):
            headers["Authorization"] = f"Bearer {options['api_key']}"
        request = urllib.request.Request(
            f"{base_url}/chat/completions", data=payload, headers=headers, method="POST"
        )
        with urllib.request.urlopen(request, timeout=options.get("timeout", 30)) as response:
            body = json.loads(response.read())
        return body["choices"][0]["message"]["content"]
