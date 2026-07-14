from django.db import models
from django.db.models import Q

from apps.core.models import WorkspaceScopedModel


class Organization(WorkspaceScopedModel):
    """A business entity that may become a prospect or client.

    `dedupe_key` is the merge-safe identity used by `services.find_or_create_by_domain`
    to avoid creating duplicate organizations for the same business. It's blank when
    no domain is known yet; the uniqueness constraint below only applies once it's set,
    same as `Contact.dedupe_key` — organizations without a known domain simply aren't
    deduplicated (matches, rather than duplicates, the Contact pattern).
    """

    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255, blank=True)
    dedupe_key = models.CharField(max_length=255, blank=True)
    external_ids = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "dedupe_key"],
                condition=~Q(dedupe_key=""),
                name="organization_unique_dedupe_key_per_workspace",
            ),
        ]

    def __str__(self) -> str:
        return self.name
