from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model

from .models import Evidence


def record_evidence(subject: Model, **fields: Any) -> Evidence:
    """Create an Evidence row attached to `subject` (an Organization or Opportunity).

    Kept as a plain function (not a signal) so call sites are explicit
    about what evidence gets captured, mirroring `apps.audit.services.record`.
    """
    return Evidence.objects.create(
        workspace=subject.workspace,  # type: ignore[attr-defined]
        content_type=ContentType.objects.get_for_model(subject),
        object_id=subject.pk,
        **fields,
    )
