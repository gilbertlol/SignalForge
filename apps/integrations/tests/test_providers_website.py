from email.message import Message
from unittest.mock import MagicMock, patch

import pytest

from apps.integrations.providers.website import (
    PublicWebsiteAnalysisAdapter,
    WebsiteAnalysisError,
    _SafeRedirectHandler,
)


def _response(body: bytes, *, url="https://example.com/about", content_type="text/html"):
    headers = Message()
    headers["Content-Type"] = f"{content_type}; charset=utf-8"
    headers["Server"] = "nginx/1.25"
    response = MagicMock()
    response.headers = headers
    response.geturl.return_value = url
    response.read.return_value = body
    response.__enter__.return_value = response
    return response


@patch("apps.integrations.providers.website.socket.getaddrinfo")
def test_website_analysis_rejects_private_destinations(mock_dns):
    mock_dns.return_value = [(None, None, None, None, ("127.0.0.1", 0))]
    with pytest.raises(WebsiteAnalysisError, match="public IPs"):
        PublicWebsiteAnalysisAdapter().analyze("http://internal.example")


@patch("apps.integrations.providers.website.socket.getaddrinfo")
def test_redirect_handler_rejects_private_destination_before_following(mock_dns):
    mock_dns.return_value = [(None, None, None, None, ("10.0.0.8", 0))]

    with pytest.raises(WebsiteAnalysisError, match="public IPs"):
        _SafeRedirectHandler().redirect_request(
            MagicMock(full_url="https://public.example"),
            MagicMock(),
            302,
            "Found",
            {},
            "http://internal.example/admin",
        )


@patch("apps.integrations.providers.website.build_opener")
@patch("apps.integrations.providers.website.socket.getaddrinfo")
def test_website_analysis_returns_observed_content_and_hash(mock_dns, mock_build_opener):
    mock_dns.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
    robots = _response(b"User-agent: *\nAllow: /", url="https://example.com/robots.txt")
    page = _response(
        b"""<html><head><title>Real Co</title>
        <meta name="description" content="Observed description">
        <link rel="canonical" href="/company">
        <script>secret ignored text</script></head>
        <body><h1>Precision manufacturing</h1>
        <a href="mailto:hello@example.com">Contact</a>
        <script src="https://www.googletagmanager.com/x.js"></script></body></html>"""
    )
    opener = mock_build_opener.return_value
    opener.open.side_effect = [robots, page]

    result = PublicWebsiteAnalysisAdapter().analyze("https://example.com/about")

    assert result["title"] == "Real Co"
    assert result["description"] == "Observed description"
    assert result["canonical_url"] == "https://example.com/company"
    assert result["contact_links"] == ["mailto:hello@example.com"]
    assert "Precision manufacturing" in result["visible_text"]
    assert "secret ignored text" not in result["visible_text"]
    assert result["technologies"] == ["Google Analytics", "Server: nginx"]
    assert len(result["content_sha256"]) == 64


@patch("apps.integrations.providers.website.build_opener")
@patch("apps.integrations.providers.website.socket.getaddrinfo")
def test_website_analysis_honors_robots_policy(mock_dns, mock_build_opener):
    mock_dns.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
    mock_build_opener.return_value.open.return_value = _response(
        b"User-agent: *\nDisallow: /private",
        url="https://example.com/robots.txt",
    )

    with pytest.raises(WebsiteAnalysisError, match="robots policy"):
        PublicWebsiteAnalysisAdapter().analyze("https://example.com/private")


@patch("apps.integrations.providers.website.build_opener")
@patch("apps.integrations.providers.website.socket.getaddrinfo")
def test_website_analysis_rejects_oversized_content(mock_dns, mock_build_opener):
    mock_dns.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
    robots = _response(b"User-agent: *\nAllow: /")
    page = _response(b"x" * (PublicWebsiteAnalysisAdapter.max_bytes + 1))
    mock_build_opener.return_value.open.side_effect = [robots, page]

    with pytest.raises(WebsiteAnalysisError, match="analysis limit"):
        PublicWebsiteAnalysisAdapter().analyze("https://example.com/")
