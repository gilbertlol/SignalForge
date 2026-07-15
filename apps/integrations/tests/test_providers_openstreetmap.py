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
