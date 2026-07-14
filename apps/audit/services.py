from typing import Any

from apps.accounts.models import User

from .models import AuditLogEntry


def record(
    action: str,
    *,
    actor: User | None = None,
    object_type: str = "",
    object_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> AuditLogEntry:
    """Create an audit log entry for a meaningful action.

    Kept as a plain function (not a signal) so call sites are explicit
    about what gets audited, per the project's guidance to avoid signals
    for business-critical behavior.
    """
    return AuditLogEntry.objects.create(
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=object_id,
        metadata=metadata or {},
    )
