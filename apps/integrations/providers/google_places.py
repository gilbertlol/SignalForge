"""Google Places API (New) Text Search adapter."""

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from apps.integrations.adapters import LeadSourceAdapter


class GooglePlacesError(RuntimeError):
    """Sanitized provider error safe for persisted run output."""


class GooglePlacesLeadSourceAdapter(LeadSourceAdapter):
    provider_key = "google_places"
    capabilities = frozenset(
        {"geographies", "industries", "keyword", "included_type", "radius", "max_records", "budget"}
    )
    field_mask = ",".join(
        (
            "places.id",
            "places.displayName",
            "places.websiteUri",
            "places.types",
            "places.primaryType",
            "places.formattedAddress",
            "places.location",
            "places.nationalPhoneNumber",
            "places.rating",
            "places.userRatingCount",
            "places.businessStatus",
            "places.googleMapsUri",
            "places.attributions",
            "nextPageToken",
        )
    )

    def __init__(self, configuration):
        self.configuration = configuration

    def is_configured(self) -> bool:
        return bool(
            self.configuration.enabled
            and self.configuration.credential_id
            and self.configuration.config.get("storage_permitted") is True
        )

    @property
    def estimated_search_cost_cents(self) -> int:
        return self.configuration.estimated_cost_per_page_cents

    def search(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.is_configured():
            raise GooglePlacesError(
                "Google Places requires an enabled key and storage agreement attestation."
            )
        limit = min(max(int(query.get("limit") or 20), 1), 60)
        page_cost = self.estimated_search_cost_cents
        budget = query.get("budget_cents")
        max_pages = 3
        if budget is not None and page_cost:
            max_pages = min(max_pages, int(budget) // page_cost)
            if max_pages < 1:
                raise GooglePlacesError("Configured Google Places budget cannot fund one page.")
        industries = [str(value) for value in query.get("industries", []) if value]
        geographies = [str(value) for value in query.get("geographies", []) if value]
        terms = (
            [str(query.get("keyword") or "").strip()] if query.get("keyword") else industries[:1]
        )
        text_query = " ".join([*(terms or ["businesses"]), "in", *(geographies[:1] or [])]).strip()
        body: dict[str, Any] = {"textQuery": text_query, "pageSize": min(limit, 20)}
        if query.get("included_type"):
            body.update(includedType=query["included_type"], strictTypeFiltering=True)
        if query.get("center_latitude") is not None and query.get("center_longitude") is not None:
            body["locationBias"] = {
                "circle": {
                    "center": {
                        "latitude": float(query["center_latitude"]),
                        "longitude": float(query["center_longitude"]),
                    },
                    "radius": float(query.get("radius_meters") or 5000),
                }
            }
        results: list[dict[str, Any]] = []
        pages = 0
        while len(results) < limit and pages < max_pages:
            payload = self._request(body)
            pages += 1
            results.extend(
                self._normalize(place)
                for place in payload.get("places", [])
                if isinstance(place, dict)
            )
            token = payload.get("nextPageToken")
            if not token or len(results) >= limit:
                break
            body["pageToken"] = token
            body["pageSize"] = min(20, limit - len(results))
        self.last_search_cost_cents = pages * page_cost
        return results[:limit]

    def _request(self, body):
        request = Request(
            self.configuration.base_url,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.configuration.credential.get_secret(),
                "X-Goog-FieldMask": self.field_mask,
            },
        )
        try:
            with urlopen(request, timeout=self.configuration.timeout_seconds) as response:  # noqa: S310
                return json.load(response)
        except HTTPError as exc:
            messages = {
                400: "Google Places rejected the search filters.",
                401: "Google Places authentication failed.",
                403: "Google Places access or billing is not enabled.",
                429: "Google Places rate limit was reached.",
            }
            raise GooglePlacesError(
                messages.get(exc.code, "Google Places returned an upstream error.")
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise GooglePlacesError(
                "Google Places could not be reached or returned an invalid response."
            ) from exc

    @staticmethod
    def _normalize(place):
        display_name = place.get("displayName") or {}
        website = place.get("websiteUri")
        location = place.get("location") or {}
        return {
            "id": place.get("id"),
            "name": display_name.get("text") or "Unnamed place",
            "website_url": website,
            "domain": website,
            "industry": place.get("primaryType"),
            "categories": place.get("types", []),
            "location": place.get("formattedAddress"),
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "phone": place.get("nationalPhoneNumber"),
            "rating": place.get("rating"),
            "rating_count": place.get("userRatingCount"),
            "business_status": place.get("businessStatus"),
            "source_url": place.get("googleMapsUri"),
            "source_attribution": "Google Maps",
            "provider_attributions": place.get("attributions", []),
        }
