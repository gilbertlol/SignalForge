from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class AuditLogEntry(TimeStampedModel):
    """Minimal, append-only record of a meaningful action.

    This is deliberately small: no middleware, no automatic signal capture.
    Call sites use `apps.audit.services.record()` explicitly when an action
    is worth auditing. The full audit system (retention, querying UI,
    automatic capture for more workflows) is future work.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_log_entries",
        help_text="The user who performed the action, if any (system actions leave this null).",
    )
    action = models.CharField(max_length=255)
    object_type = models.CharField(max_length=255, blank=True)
    object_id = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "audit log entries"

    def __str__(self) -> str:
        return f"{self.action} @ {self.created_at:%Y-%m-%d %H:%M:%S}"
