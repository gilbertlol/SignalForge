import json
from unittest.mock import MagicMock, patch

import pytest

from apps.integrations.providers.openstreetmap import (
    OpenStreetMapError,
    OpenStreetMapLeadSourceAdapter,
)


def test_openstreetmap_requires_a_geography():
    with pytest.raises(OpenStreetMapError, match="geography"):
        OpenStreetMapLeadSourceAdapter().search({"industries": ["dentist"]})


@patch("apps.integrations.providers.openstreetmap.urlopen")
def test_openstreetmap_normalizes_business_and_preserves_attribution(mock_urlopen):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {
            "elements": [
                {
                    "type": "node",
                    "id": 42,
                    "lat": 45.5,
                    "lon": -73.5,
                    "tags": {
                        "name": "Bright Dental",
                        "amenity": "dentist",
                        "website": "https://bright.example",
                        "contact:phone": "+1 555 0100",
                    },
                }
            ]
        }
    ).encode()
    mock_urlopen.return_value = response

    results = OpenStreetMapLeadSourceAdapter().search(
        {"geographies": ["Montreal"], "industries": ["dentist"], "limit": 5}
    )

    assert results[0]["name"] == "Bright Dental"
    assert results[0]["domain"] == "https://bright.example"
    assert results[0]["source_attribution"] == "© OpenStreetMap contributors (ODbL)"


@patch("apps.integrations.providers.openstreetmap.urlopen")
def test_openstreetmap_supports_a_free_radius_search(mock_urlopen):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"elements": []}'
    mock_urlopen.return_value = response

    OpenStreetMapLeadSourceAdapter().search(
        {
            "center_latitude": 45.5017,
            "center_longitude": -73.5673,
            "radius_meters": 7500,
            "industries": ["manufacturer"],
        }
    )

    encoded_query = mock_urlopen.call_args.args[0].data.decode()
    assert "around%3A7500%2C45.5017%2C-73.5673" in encoded_query
