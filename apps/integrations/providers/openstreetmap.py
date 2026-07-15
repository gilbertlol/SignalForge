"""Credential-free OpenStreetMap business discovery through Overpass."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from apps.integrations.adapters import LeadSourceAdapter


class OpenStreetMapError(RuntimeError):
    pass


class OpenStreetMapLeadSourceAdapter(LeadSourceAdapter):
    provider_key = "openstreetmap"
    capabilities = frozenset({"geographies", "industries", "radius", "max_records"})
    endpoint = "https://overpass-api.de/api/interpreter"

    def is_configured(self) -> bool:
        return True

    def search(self, query):
        locations = [
            str(value).strip() for value in query.get("geographies", []) if str(value).strip()
        ]
        latitude = query.get("center_latitude")
        longitude = query.get("center_longitude")
        has_center = latitude is not None and longitude is not None
        if not locations and not has_center:
            raise OpenStreetMapError("OpenStreetMap searches require at least one geography.")
        limit = min(max(int(query.get("limit") or 25), 1), 100)
        keywords = [
            str(value).strip() for value in query.get("industries", []) if str(value).strip()
        ]
        value_filter = "|".join(re.escape(value) for value in keywords) or ".+"
        areas = ""
        if has_center:
            radius = min(max(int(query.get("radius_meters") or 5000), 1), 50000)
            search_targets = [f"around:{radius},{float(latitude)},{float(longitude)}"]
        else:
            areas = "".join(
                f'area["name"="{self._escape(location)}"]["boundary"="administrative"]->.a{i};'
                for i, location in enumerate(locations)
            )
            search_targets = [f"area.a{i}" for i in range(len(locations))]
        searches = "".join(
            f'nwr({target})["name"][~"^(shop|office|craft|amenity|description|brand)$"~"{self._escape(value_filter)}",i];'
            for target in search_targets
        )
        overpass_query = f"[out:json][timeout:25];{areas}({searches});out center tags {limit};"
        request = Request(
            self.endpoint,
            data=urlencode({"data": overpass_query}).encode(),
            headers={"User-Agent": "SignalForge/1.0 (lead discovery; OpenStreetMap attributed)"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise OpenStreetMapError("OpenStreetMap discovery is temporarily unavailable.") from exc
        return [self._normalize(element) for element in payload.get("elements", [])[:limit]]

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _normalize(element):
        tags = element.get("tags", {})
        center = element.get("center", element)
        website = tags.get("website") or tags.get("contact:website")
        return {
            "id": f'{element.get("type", "element")}/{element.get("id")}',
            "name": tags.get("name", "Unnamed business"),
            "website_url": website,
            "domain": website,
            "phone": tags.get("contact:phone") or tags.get("phone"),
            "email": tags.get("contact:email") or tags.get("email"),
            "industry": tags.get("office")
            or tags.get("shop")
            or tags.get("craft")
            or tags.get("amenity"),
            "location": tags.get("addr:city") or tags.get("addr:country"),
            "latitude": center.get("lat"),
            "longitude": center.get("lon"),
            "source_url": (
                "https://www.openstreetmap.org/"
                f'{element.get("type", "node")}/{element.get("id")}'
            ),
            "source_attribution": "© OpenStreetMap contributors (ODbL)",
        }
