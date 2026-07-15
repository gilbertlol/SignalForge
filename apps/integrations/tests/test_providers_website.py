from email.message import Message
from unittest.mock import MagicMock, patch

import pytest

from apps.integrations.providers.website import PublicWebsiteAnalysisAdapter, WebsiteAnalysisError


@patch("apps.integrations.providers.website.socket.getaddrinfo")
def test_website_analysis_rejects_private_destinations(mock_dns):
    mock_dns.return_value = [(None, None, None, None, ("127.0.0.1", 0))]
    with pytest.raises(WebsiteAnalysisError, match="public IPs"):
        PublicWebsiteAnalysisAdapter().analyze("http://internal.example")


@patch("apps.integrations.providers.website.urlopen")
@patch("apps.integrations.providers.website.socket.getaddrinfo")
def test_website_analysis_returns_observed_metadata(mock_dns, mock_urlopen):
    mock_dns.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
    headers = Message(); headers["Content-Type"] = "text/html; charset=utf-8"; headers["Server"] = "nginx/1.25"
    response = MagicMock(); response.headers = headers; response.geturl.return_value = "https://example.com/"
    response.read.return_value = b'<html><head><title>Real Co</title><meta name="description" content="Observed description"><script src="https://www.googletagmanager.com/x.js"></script></head></html>'
    response.__enter__.return_value = response; mock_urlopen.return_value = response

    result = PublicWebsiteAnalysisAdapter().analyze("example.com")

    assert result["title"] == "Real Co"
    assert result["description"] == "Observed description"
    assert result["technologies"] == ["Google Analytics", "Server: nginx"]
