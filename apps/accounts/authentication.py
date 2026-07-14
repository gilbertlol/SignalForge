import hashlib
import secrets

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import APIKey


class APIKeyAuthentication(BaseAuthentication):
    keyword = "ApiKey"

    def authenticate(self, request):
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith(f"{self.keyword} "):
            return None
        raw_key = authorization.removeprefix(f"{self.keyword} ").strip()
        try:
            marker, prefix, secret = raw_key.split("_", 2)
        except ValueError as exc:
            raise AuthenticationFailed("Invalid API key") from exc
        if marker != "sf":
            raise AuthenticationFailed("Invalid API key")
        key = APIKey.objects.select_related("user", "workspace").filter(prefix=prefix).first()
        if (
            not key
            or not key.is_usable()
            or not secrets.compare_digest(
                key.secret_hash, hashlib.sha256(secret.encode()).hexdigest()
            )
        ):
            raise AuthenticationFailed("Invalid or revoked API key")
        if (
            not key.user.is_active
            or not key.user.memberships.filter(workspace=key.workspace, is_active=True).exists()
        ):
            raise AuthenticationFailed("API key user has no workspace access")
        key.last_used_at = timezone.now()
        key.save(update_fields=["last_used_at", "updated_at"])
        request.workspace = key.workspace
        request.api_key = key
        return key.user, key
