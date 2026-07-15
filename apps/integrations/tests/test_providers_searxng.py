import json
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from apps.core.tests.factories import WorkspaceFactory
from apps.integrations.models import CredentialReference, LeadSourceConfiguration
from apps.integrations.providers.searxng import (
    SearXNGError,
    SearXNGLeadSourceAdapter,
)

pytestmark = pytest.mark.django_db


def configuration(**overrides):
    values = {
        "workspace": WorkspaceFactory(),
        "source_key": "searxng",
        "name": "SearXNG",
        "base_url": "https://search.example",
        "credential": None,
    }
    values.update(overrides)
    return LeadSourceConfiguration.objects.create(**values)


@patch("apps.integrations.providers.searxng.urlopen")
def test_searxng_builds_bounded_query_and_preserves_provenance(mock_urlopen):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {
            "results": [
                {
                    "title": "Northstar Manufacturing",
                    "url": "https://northstar.example/about",
                    "content": "Precision manufacturer in Montreal.",
                    "engines": ["brave", "duckduckgo"],
                    "publishedDate": "2026-07-01",
                }
            ]
        }
    ).encode()
    mock_urlopen.return_value = response
    source = configuration(
        base_url="https://search.example/",
        config={"language": "en"},
    )

    results = SearXNGLeadSourceAdapter(source).search(
        {
            "industries": ["precision manufacturing"],
            "geographies": ["Montreal"],
            "limit": 5,
        }
    )

    request = mock_urlopen.call_args.args[0]
    parameters = parse_qs(urlparse(request.full_url).query)
    assert urlparse(request.full_url).path == "/search"
    assert parameters["q"] == ["precision manufacturing Montreal"]
    assert parameters["format"] == ["json"]
    assert results[0]["domain"] == "northstar.example"
    assert results[0]["search_rank"] == 1
    assert results[0]["search_query"] == "precision manufacturing Montreal"
    assert results[0]["upstream_engines"] == ["brave", "duckduckgo"]
    assert results[0]["source_attribution"] == "SearXNG"


@patch("apps.integrations.providers.searxng.urlopen")
def test_searxng_uses_optional_private_instance_token(mock_urlopen):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"results": []}'
    mock_urlopen.return_value = response
    workspace = WorkspaceFactory()
    credential = CredentialReference(workspace=workspace, name="SearXNG token")
    credential.set_secret("private-token")
    credential.save()
    source = configuration(
        workspace=workspace, base_url="https://search.example", credential=credential
    )

    SearXNGLeadSourceAdapter(source).search({"keyword": "accountants"})

    request = mock_urlopen.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer private-token"


def test_searxng_rejects_endpoint_url_components_that_could_change_request_scope():
    source = configuration(
        base_url="https://search.example/?target=http://internal",
    )

    with pytest.raises(SearXNGError, match="unsupported URL components"):
        SearXNGLeadSourceAdapter(source).search({"keyword": "business"})
