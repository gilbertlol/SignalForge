"""Apollo Organization Search lead-source adapter."""

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from apps.integrations.adapters import LeadSourceAdapter


class ApolloError(RuntimeError):
    """A sanitized error safe to persist in a provider result."""


class ApolloLeadSourceAdapter(LeadSourceAdapter):
    provider_key = "apollo"
    capabilities = frozenset({"geographies", "industries", "company_size", "max_records", "budget"})

    def __init__(self, configuration):
        self.configuration = configuration

    def is_configured(self) -> bool:
        return bool(self.configuration.enabled and self.configuration.credential_id)

    @property
    def estimated_search_cost_cents(self) -> int:
        return self.configuration.estimated_cost_per_page_cents

    def search(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.is_configured():
            raise ApolloError("Apollo is not enabled for this workspace.")

        limit = min(max(int(query.get("limit") or 25), 1), 100)
        params: list[tuple[str, str | int]] = [("page", 1), ("per_page", limit)]
        params.extend(("organization_locations[]", value) for value in query.get("geographies", []))
        params.extend(
            ("q_organization_keyword_tags[]", value) for value in query.get("industries", [])
        )
        minimum = query.get("company_size_min")
        maximum = query.get("company_size_max")
        if minimum is not None or maximum is not None:
            params.append(
                ("organization_num_employees_ranges[]", f"{minimum or 1},{maximum or 1000000}")
            )

        request = Request(
            f"{self.configuration.base_url}?{urlencode(params)}",
            data=b"",
            method="POST",
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "x-api-key": self.configuration.credential.get_secret(),
            },
        )
        try:
            with urlopen(request, timeout=self.configuration.timeout_seconds) as response:  # noqa: S310
                payload = json.load(response)
        except HTTPError as exc:
            messages = {
                401: "Apollo authentication failed.",
                403: "Apollo access is not permitted for this API key or plan.",
                422: "Apollo rejected the search filters.",
                429: "Apollo rate limit was reached.",
            }
            raise ApolloError(messages.get(exc.code, "Apollo returned an upstream error.")) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ApolloError(
                "Apollo could not be reached or returned an invalid response."
            ) from exc

        organizations = payload.get("organizations", [])
        if not isinstance(organizations, list):
            raise ApolloError("Apollo returned an invalid response.")
        return [
            organization for organization in organizations[:limit] if isinstance(organization, dict)
        ]
