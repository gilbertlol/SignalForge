"""Bounded, SSRF-resistant analysis of a discovered public website."""
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from apps.integrations.adapters import WebsiteAnalysisAdapter

class WebsiteAnalysisError(RuntimeError): pass

class _Parser(HTMLParser):
    def __init__(self): super().__init__(); self.title=""; self.description=""; self._title=False
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs); self._title = self._title or tag == "title"
        if tag == "meta" and attrs.get("name", "").lower() == "description": self.description=attrs.get("content", "")[:500]
    def handle_endtag(self, tag):
        if tag == "title": self._title=False
    def handle_data(self, data):
        if self._title and not self.title: self.title=data.strip()[:300]

class PublicWebsiteAnalysisAdapter(WebsiteAnalysisAdapter):
    provider_key="public_website"; max_bytes=512_000
    def is_configured(self): return True
    def analyze(self, url):
        target=url if "://" in url else f"https://{url}"; parsed=urlparse(target)
        if parsed.scheme not in {"http","https"} or not parsed.hostname: raise WebsiteAnalysisError("Website URL is invalid.")
        self._public(parsed.hostname)
        try:
            with urlopen(Request(target, headers={"User-Agent":"SignalForge/1.0 (+website validation)"}), timeout=10) as response:  # noqa: S310
                if response.headers.get_content_type() != "text/html": raise WebsiteAnalysisError("Website did not return HTML.")
                body=response.read(self.max_bytes+1)
                if len(body)>self.max_bytes: raise WebsiteAnalysisError("Website response exceeded the analysis limit.")
                final_url=response.geturl(); final_host=urlparse(final_url).hostname
                if not final_host: raise WebsiteAnalysisError("Website redirect was invalid.")
                self._public(final_host)
                html=body.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
                technologies=self._technologies(html, response.headers)
        except WebsiteAnalysisError: raise
        except (HTTPError, URLError, TimeoutError, OSError) as exc: raise WebsiteAnalysisError("Website could not be reached safely.") from exc
        parser=_Parser(); parser.feed(html)
        return {"url":final_url,"title":parser.title,"description":parser.description,"technologies":technologies,"observed_bytes":len(body)}
    @staticmethod
    def _public(hostname):
        try: addresses={item[4][0] for item in socket.getaddrinfo(hostname,None)}
        except socket.gaierror as exc: raise WebsiteAnalysisError("Website hostname could not be resolved.") from exc
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses): raise WebsiteAnalysisError("Website hostname does not resolve exclusively to public IPs.")
    @staticmethod
    def _technologies(html, headers):
        signatures={"WordPress":r"wp-content|wp-includes","Shopify":r"cdn\.shopify|shopify\.theme","Wix":r"wixstatic\.com","Squarespace":r"squarespace\.com","Google Analytics":r"googletagmanager\.com|google-analytics\.com","React":r"data-reactroot|__next_data__","Cloudflare":r"cloudflare"}; found=set()
        for name,pattern in signatures.items():
            if re.search(pattern,html.lower()): found.add(name)
        if headers.get("Server"): found.add(f"Server: {headers['Server'].split('/')[0]}")
        return sorted(found)
