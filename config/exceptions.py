"""DRF exception handling for exceptions raised below the API layer.

Model `clean()`/`save()` methods raise Django's `ValidationError` (not
DRF's) to enforce integrity regardless of caller (ORM, shell, API) — see
apps.contacts/opportunities/evidence models. DRF's default handler only
understands its own `rest_framework.exceptions.ValidationError`, so
without this, those integrity errors would surface as 500s instead of 400s.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}
        return Response(detail, status=status.HTTP_400_BAD_REQUEST)
    return drf_exception_handler(exc, context)
