from typing import Any

from apps.core.models import Workspace

from .models import Contact


def normalize_email(email: str) -> str:
    return email.strip().lower()


def find_or_create_by_email(
    workspace: Workspace,
    email: str,
    defaults: dict[str, Any] | None = None,
) -> tuple[Contact, bool]:
    """Merge-safe contact lookup: exact match on normalized email.

    Contacts without a known email are never deduplicated this way (the
    unique constraint on `dedupe_key` only applies to non-blank keys).
    """
    normalized = normalize_email(email)
    defaults = dict(defaults or {})
    defaults.setdefault("email", normalized)
    return Contact.objects.get_or_create(
        workspace=workspace,
        dedupe_key=normalized,
        defaults=defaults,
    )
