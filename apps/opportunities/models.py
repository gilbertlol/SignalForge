from django.core.exceptions import ValidationError
from django.db import models

from apps.contacts.models import Contact
from apps.core.models import WorkspaceScopedModel
from apps.organizations.models import Organization


class OpportunityStatus(models.TextChoices):
    IDENTIFIED = "identified", "Identified"
    QUALIFIED = "qualified", "Qualified"
    DISQUALIFIED = "disqualified", "Disqualified"
    WON = "won", "Won"
    LOST = "lost", "Lost"


class Opportunity(WorkspaceScopedModel):
    """A specific pursuit against an Organization.

    Deliberately minimal: full pipeline/stage management is a later
    ticket. `first_contacted_at` exists because the "post-contact
    opportunity score" family (GOR-234) needs to know whether outreach
    has started; it is not a communications log — see GOR-236 for that.
    """

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="opportunities",
    )
    primary_contact = models.ForeignKey(
        Contact,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    title = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=OpportunityStatus.choices,
        default=OpportunityStatus.IDENTIFIED,
    )
    first_contacted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title

    @property
    def contacted(self) -> bool:
        return self.first_contacted_at is not None

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.organization is not None and self.organization.workspace_id != self.workspace_id:
            errors["organization"] = "Organization must belong to the same workspace."
        if (
            self.primary_contact is not None
            and self.primary_contact.workspace_id != self.workspace_id
        ):
            errors["primary_contact"] = "Primary contact must belong to the same workspace."
        if (
            self.primary_contact is not None
            and self.primary_contact.organization_id is not None
            and self.primary_contact.organization_id != self.organization_id
        ):
            errors["primary_contact"] = "Primary contact must belong to the same organization."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
