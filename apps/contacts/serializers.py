from typing import Any

from rest_framework import serializers

from apps.core.services import get_default_workspace

from .models import Contact
from .services import find_or_create_by_email


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = [
            "id",
            "organization",
            "first_name",
            "last_name",
            "email",
            "dedupe_key",
            "external_ids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "dedupe_key", "created_at", "updated_at"]

    def create(self, validated_data: dict[str, Any]) -> Contact:
        workspace = get_default_workspace()
        email = validated_data.pop("email", "")
        if email:
            contact, _ = find_or_create_by_email(workspace, email, defaults=validated_data)
            return contact
        return Contact.objects.create(
            workspace=workspace, email="", dedupe_key="", **validated_data
        )
