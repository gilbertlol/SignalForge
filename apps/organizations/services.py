from typing import Any
from urllib.parse import urlparse

from apps.core.models import Workspace

from .models import Organization


def normalize_domain(url_or_domain: str) -> str:
    """Reduce a URL or bare domain to a comparable dedupe key.

    Strips scheme, "www.", path/query/fragment, port, and trailing dots,
    then lowercases what's left. Used both when storing `Organization.domain`
    and as the basis for `Organization.dedupe_key`.
    """
    value = url_or_domain.strip().lower()
    if "//" not in value:
        value = f"//{value}"
    parsed = urlparse(value)
    host = parsed.netloc or parsed.path
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[len("www.") :]
    return host.strip(".").rstrip("/")


def find_or_create_by_domain(
    workspace: Workspace,
    domain: str,
    defaults: dict[str, Any] | None = None,
) -> tuple[Organization, bool]:
    """Merge-safe organization lookup: exact match on normalized domain.

    Fuzzy/near-duplicate resolution (name similarity, alternate domains,
    etc.) is future work; this only prevents exact-domain duplicates.
    """
    normalized = normalize_domain(domain)
    defaults = dict(defaults or {})
    defaults.setdefault("name", normalized)
    defaults.setdefault("domain", normalized)
    return Organization.objects.get_or_create(
        workspace=workspace,
        dedupe_key=normalized,
        defaults=defaults,
    )


def create_organization(
    workspace: Workspace,
    *,
    name: str,
    domain: str = "",
    external_ids: dict[str, Any] | None = None,
) -> tuple[Organization, bool]:
    """API-facing entry point: dedup by domain when one is given, otherwise
    just create (an org with no domain has nothing to merge-safely match on).
    """
    if domain:
        return find_or_create_by_domain(
            workspace,
            domain,
            defaults={"name": name, "external_ids": external_ids or {}},
        )
    organization = Organization.objects.create(
        workspace=workspace,
        name=name,
        domain="",
        dedupe_key="",
        external_ids=external_ids or {},
    )
    return organization, True
