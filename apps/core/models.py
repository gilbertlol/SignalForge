import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base adding a UUID primary key and creation/update timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self) -> "SoftDeleteQuerySet":
        return self.filter(deleted_at__isnull=True)

    def dead(self) -> "SoftDeleteQuerySet":
        return self.filter(deleted_at__isnull=False)


class SoftDeleteManager(models.Manager):
    """Default manager: excludes soft-deleted rows. Use `all_objects` to see everything."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self.model, using=self._db).alive()


class SoftDeleteModel(models.Model):
    """Abstract base providing soft-delete behavior.

    `delete()` soft-deletes by default (sets `deleted_at`); pass `hard=True`
    to actually remove the row. The plain `all_objects` manager bypasses the
    soft-delete filter, e.g. for admin tooling or audits.
    """

    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False, hard=False):
        if hard:
            return super().delete(using=using, keep_parents=keep_parents)
        from django.utils import timezone

        self.deleted_at = timezone.now()
        self.save(using=using, update_fields=["deleted_at"])
        return (1, {self._meta.label: 1})


class BaseModel(TimeStampedModel, SoftDeleteModel):
    """The base every domain model should inherit from."""

    class Meta:
        abstract = True


class Workspace(BaseModel):
    """Foundation for future multi-tenancy (full tenancy lands in GOR-244).

    Business models will scope to a Workspace via `WorkspaceScopedModel`
    once they exist, so no future migration has to retrofit isolation
    onto globally shared data.
    """

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class WorkspaceScopedModel(BaseModel):
    """Abstract base for future business models that belong to a Workspace."""

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        abstract = True
