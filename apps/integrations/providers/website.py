"""Bounded, redirect-aware analysis of a discovered public webpage."""

import hashlib
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

from apps.integrations.adapters import WebsiteAnalysisAdapter


class WebsiteAnalysisError(RuntimeError):
    """A sanitized retrieval error safe to persist."""


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WebsiteAnalysisError("Website URL is invalid.")
    if parsed.username or parsed.password:
        raise WebsiteAnalysisError("Website URLs containing credentials are not allowed.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror as exc:
        raise WebsiteAnalysisError("Website hostname could not be resolved.") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise WebsiteAnalysisError("Website hostname does not resolve exclusively to public IPs.")


class _SafeRedirectHandler(HTTPRedirectHandler):
    max_redirects = 3

    def __init__(self):
        super().__init__()
        self.redirect_count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.redirect_count += 1
        if self.redirect_count > self.max_redirects:
            raise WebsiteAnalysisError("Website exceeded the redirect limit.")
        target = urljoin(req.full_url, newurl)
        _validate_public_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


class _PageParser(HTMLParser):
    max_text_chars = 20_000

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.canonical_url = ""
        self.contact_links: set[str] = set()
        self._in_title = False
        self._ignored_depth = 0
        self._text: list[str] = []
        self._text_chars = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta" and attributes.get("name", "").lower() == "description":
            self.description = attributes.get("content", "").strip()[:500]
        if tag == "link" and "canonical" in attributes.get("rel", "").lower().split():
            self.canonical_url = attributes.get("href", "").strip()
        if tag == "a":
            href = attributes.get("href", "").strip()
            if href.startswith(("mailto:", "tel:")):
                self.contact_links.add(href[:500])

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        value = " ".join(data.split())
        if not value:
            return
        if self._in_title and not self.title:
            self.title = value[:300]
        if self._ignored_depth or self._text_chars >= self.max_text_chars:
            return
        value = value[: self.max_text_chars - self._text_chars]
        self._text.append(value)
        self._text_chars += len(value) + 1

    @property
    def visible_text(self) -> str:
        return " ".join(self._text)[: self.max_text_chars]


class PublicWebsiteAnalysisAdapter(WebsiteAnalysisAdapter):
    provider_key = "public_website"
    max_bytes = 512_000
    timeout_seconds = 10
    user_agent = "SignalForge/1.0 (+public evidence retrieval)"

    def is_configured(self):
        return True

    def analyze(self, url):
        target = url if "://" in url else f"https://{url}"
        _validate_public_url(target)
        redirect_handler = _SafeRedirectHandler()
        opener = build_opener(redirect_handler)
        self._check_robots(opener, target)
        try:
            request = Request(target, headers={"User-Agent": self.user_agent})
            with opener.open(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                final_url = response.geturl()
                _validate_public_url(final_url)
                if response.headers.get_content_type() != "text/html":
                    raise WebsiteAnalysisError("Website did not return HTML.")
                declared_length = response.headers.get("Content-Length")
                if declared_length and int(declared_length) > self.max_bytes:
                    raise WebsiteAnalysisError("Website response exceeded the analysis limit.")
                body = response.read(self.max_bytes + 1)
                if len(body) > self.max_bytes:
                    raise WebsiteAnalysisError("Website response exceeded the analysis limit.")
                charset = response.headers.get_content_charset() or "utf-8"
                html = body.decode(charset, errors="replace")
                technologies = self._technologies(html, response.headers)
        except WebsiteAnalysisError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise WebsiteAnalysisError("Website could not be reached safely.") from exc

        parser = _PageParser()
        try:
            parser.feed(html)
        except Exception as exc:  # noqa: BLE001 - malformed HTML is untrusted input
            raise WebsiteAnalysisError("Website returned malformed HTML.") from exc
        canonical_url = (
            urljoin(final_url, parser.canonical_url) if parser.canonical_url else final_url
        )
        _validate_public_url(canonical_url)
        return {
            "requested_url": target,
            "url": final_url,
            "canonical_url": canonical_url,
            "title": parser.title,
            "description": parser.description,
            "visible_text": parser.visible_text,
            "contact_links": sorted(parser.contact_links),
            "technologies": technologies,
            "observed_bytes": len(body),
            "content_sha256": hashlib.sha256(body).hexdigest(),
        }

    def _check_robots(self, opener, target: str) -> None:
        parsed = urlparse(target)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        _validate_public_url(robots_url)
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            request = Request(robots_url, headers={"User-Agent": self.user_agent})
            with opener.open(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                rules = response.read(64_000).decode("utf-8", errors="replace").splitlines()
            parser.parse(rules)
        except (HTTPError, URLError, TimeoutError, OSError):
            return
        if not parser.can_fetch(self.user_agent, target):
            raise WebsiteAnalysisError("Website robots policy disallows retrieval.")

    @staticmethod
    def _technologies(html, headers):
        signatures = {
            "WordPress": r"wp-content|wp-includes",
            "Shopify": r"cdn\.shopify|shopify\.theme",
            "Wix": r"wixstatic\.com",
            "Squarespace": r"squarespace\.com",
            "Google Analytics": r"googletagmanager\.com|google-analytics\.com",
            "React": r"data-reactroot|__next_data__",
            "Cloudflare": r"cloudflare",
        }
        found = {name for name, pattern in signatures.items() if re.search(pattern, html.lower())}
        if headers.get("Server"):
            found.add(f"Server: {headers['Server'].split('/')[0]}")
        return sorted(found)
