import io
import json
from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.core.tests.factories import WorkspaceFactory
from apps.integrations.models import CredentialReference, LeadSourceConfiguration
from apps.integrations.providers.google_places import GooglePlacesLeadSourceAdapter

pytestmark = pytest.mark.django_db


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@override_settings(SIGNALFORGE_CREDENTIAL_KEY="google-test-key-at-least-32-characters")
def test_google_places_uses_field_mask_paginates_and_normalizes():
    workspace = WorkspaceFactory()
    credential = CredentialReference(workspace=workspace, name="Google", encrypted_value="")
    credential.set_secret("secret-google-key")
    credential.save()
    configuration = LeadSourceConfiguration.objects.create(
        workspace=workspace,
        source_key="google_places",
        name="Google Places",
        credential=credential,
        base_url="https://places.googleapis.com/v1/places:searchText",
        config={"storage_permitted": True},
    )
    responses = [
        Response(
            json.dumps(
                {
                    "places": [{"id": "p1", "displayName": {"text": "Gold Co"}}],
                    "nextPageToken": "next",
                }
            ).encode()
        ),
        Response(
            json.dumps({"places": [{"id": "p2", "displayName": {"text": "Hope Co"}}]}).encode()
        ),
    ]

    with patch(
        "apps.integrations.providers.google_places.urlopen", side_effect=responses
    ) as mocked:
        results = GooglePlacesLeadSourceAdapter(configuration).search(
            {
                "keyword": "cosmetic dentist",
                "industries": ["dentist"],
                "geographies": ["Toronto"],
                "included_type": "dentist",
                "center_latitude": 43.65,
                "center_longitude": -79.38,
                "radius_meters": 2500,
                "limit": 2,
            }
        )

    first_request = mocked.call_args_list[0].args[0]
    second_body = json.loads(mocked.call_args_list[1].args[0].data)
    assert first_request.headers["X-goog-api-key"] == "secret-google-key"
    assert "places.id" in first_request.headers["X-goog-fieldmask"]
    first_body = json.loads(first_request.data)
    assert first_body["textQuery"] == "cosmetic dentist in Toronto"
    assert first_body["includedType"] == "dentist"
    assert first_body["locationBias"]["circle"]["radius"] == 2500
    assert second_body["pageToken"] == "next"
    assert [result["id"] for result in results] == ["p1", "p2"]
    assert results[0]["source_attribution"] == "Google Maps"
