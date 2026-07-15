import io
import json
from unittest.mock import patch
from urllib.error import HTTPError

import pytest
from django.test import override_settings

from apps.core.tests.factories import WorkspaceFactory
from apps.integrations.models import CredentialReference, LeadSourceConfiguration
from apps.integrations.providers.apollo import ApolloError, ApolloLeadSourceAdapter

pytestmark = pytest.mark.django_db


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@override_settings(SIGNALFORGE_CREDENTIAL_KEY="apollo-test-key-at-least-32-characters")
def test_apollo_search_maps_filters_and_keeps_secret_in_header():
    workspace = WorkspaceFactory()
    credential = CredentialReference(workspace=workspace, name="Apollo", encrypted_value="")
    credential.set_secret("secret-apollo-key")
    credential.save()
    configuration = LeadSourceConfiguration.objects.create(
        workspace=workspace, source_key="apollo", name="Apollo", credential=credential
    )
    response = Response(
        json.dumps(
            {"organizations": [{"id": "org-1", "name": "Acme", "primary_domain": "acme.test"}]}
        ).encode()
    )

    with patch("apps.integrations.providers.apollo.urlopen", return_value=response) as mocked:
        results = ApolloLeadSourceAdapter(configuration).search(
            {
                "industries": ["automation"],
                "geographies": ["toronto"],
                "company_size_min": 10,
                "company_size_max": 50,
                "limit": 250,
            }
        )

    request = mocked.call_args.args[0]
    assert results[0]["id"] == "org-1"
    assert request.headers["X-api-key"] == "secret-apollo-key"
    assert "secret-apollo-key" not in request.full_url
    assert "per_page=100" in request.full_url
    assert "organization_locations%5B%5D=toronto" in request.full_url
    assert "organization_num_employees_ranges%5B%5D=10%2C50" in request.full_url


@override_settings(SIGNALFORGE_CREDENTIAL_KEY="apollo-test-key-at-least-32-characters")
def test_apollo_errors_are_sanitized():
    workspace = WorkspaceFactory()
    credential = CredentialReference(workspace=workspace, name="Apollo", encrypted_value="")
    credential.set_secret("must-not-leak")
    credential.save()
    configuration = LeadSourceConfiguration.objects.create(
        workspace=workspace, source_key="apollo", name="Apollo", credential=credential
    )
    error = HTTPError(configuration.base_url, 401, "contains must-not-leak", {}, None)

    with patch("apps.integrations.providers.apollo.urlopen", side_effect=error):
        with pytest.raises(ApolloError, match="authentication failed") as exc:
            ApolloLeadSourceAdapter(configuration).search({})

    assert "must-not-leak" not in str(exc.value)
