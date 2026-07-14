from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import WorkspaceScopedModel
from apps.organizations.models import Organization


class Contact(WorkspaceScopedModel):
    """A person, optionally linked to an Organization.

    A contact can exist before it's linked to an organization (e.g. found
    via a personal profile before the employer is known), hence the
    nullable FK.
    """

    organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contacts",
    )
    first_name = models.CharField(max_length=255, blank=True)
    last_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    dedupe_key = models.CharField(max_length=255, blank=True)
    external_ids = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "dedupe_key"],
                condition=~Q(dedupe_key=""),
                name="contact_unique_dedupe_key_per_workspace",
            ),
        ]

    def __str__(self) -> str:
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or self.email or str(self.id)

    def clean(self) -> None:
        super().clean()
        if self.organization is not None and self.organization.workspace_id != self.workspace_id:
            raise ValidationError(
                {"organization": "Organization must belong to the same workspace as the contact."}
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
