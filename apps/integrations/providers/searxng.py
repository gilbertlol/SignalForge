"""Self-hosted SearXNG web discovery adapter."""

import json
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from apps.integrations.adapters import LeadSourceAdapter


class SearXNGError(RuntimeError):
    """A sanitized error safe to persist in discovery output."""


class SearXNGLeadSourceAdapter(LeadSourceAdapter):
    provider_key = "searxng"
    capabilities = frozenset({"geographies", "industries", "keyword", "max_records"})

    def __init__(self, configuration):
        self.configuration = configuration

    def is_configured(self) -> bool:
        return bool(self.configuration.enabled and self.configuration.base_url)

    def search(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.is_configured():
            raise SearXNGError("SearXNG is not enabled for this workspace.")
        limit = min(max(int(query.get("limit") or 10), 1), 50)
        search_query = self._build_query(query)
        endpoint = self._search_endpoint(self.configuration.base_url)
        params = urlencode(
            {
                "q": search_query,
                "format": "json",
                "language": self.configuration.config.get("language", "auto"),
                "safesearch": 1,
            }
        )
        headers = {
            "Accept": "application/json",
            "User-Agent": "SignalForge/1.0 (workspace web discovery)",
        }
        if self.configuration.credential_id:
            headers["Authorization"] = f"Bearer {self.configuration.credential.get_secret()}"
        request = Request(f"{endpoint}?{params}", headers=headers)
        try:
            with urlopen(request, timeout=self.configuration.timeout_seconds) as response:  # noqa: S310
                payload = json.load(response)
        except HTTPError as exc:
            messages = {
                401: "SearXNG authentication failed.",
                403: "SearXNG denied JSON search access.",
                429: "SearXNG rate limit was reached.",
            }
            raise SearXNGError(
                messages.get(exc.code, "SearXNG returned an upstream error.")
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SearXNGError("SearXNG could not be reached or returned invalid JSON.") from exc

        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            raise SearXNGError("SearXNG returned an invalid response.")
        retrieved_at = datetime.now(UTC).isoformat()
        results = [
            self._normalize(item, search_query, rank, retrieved_at)
            for rank, item in enumerate(raw_results[:limit], start=1)
            if isinstance(item, dict) and item.get("url")
        ]
        self.last_search_cost_cents = 0
        return results

    @staticmethod
    def _build_query(query: dict[str, Any]) -> str:
        keyword = str(query.get("keyword") or "").strip()
        industries = [str(value).strip() for value in query.get("industries", []) if value]
        geographies = [str(value).strip() for value in query.get("geographies", []) if value]
        terms = [keyword] if keyword else industries[:3]
        parts = [*(terms or ["business company"]), *geographies[:2]]
        return " ".join(parts)[:500]

    @staticmethod
    def _search_endpoint(base_url: str) -> str:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise SearXNGError("SearXNG endpoint must be an HTTP or HTTPS URL.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise SearXNGError("SearXNG endpoint contains unsupported URL components.")
        path = parsed.path.rstrip("/")
        if not path.endswith("/search"):
            path = f"{path}/search"
        return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))

    @staticmethod
    def _normalize(item: dict[str, Any], query: str, rank: int, retrieved_at: str):
        url = str(item["url"])
        parsed = urlparse(url)
        engines = item.get("engines") or ([item["engine"]] if item.get("engine") else [])
        return {
            "id": url,
            "name": item.get("title") or parsed.hostname or "Web result",
            "website_url": url,
            "domain": parsed.hostname,
            "description": item.get("content") or "",
            "source_url": url,
            "source_attribution": "SearXNG",
            "upstream_engines": engines,
            "search_query": query,
            "search_rank": rank,
            "retrieved_at": retrieved_at,
            "published_at": item.get("publishedDate"),
        }
