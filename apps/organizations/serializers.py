from typing import Any

from rest_framework import serializers

from apps.core.services import get_default_workspace

from .models import Organization
from .services import create_organization, normalize_domain


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "domain",
            "dedupe_key",
            "external_ids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "dedupe_key", "created_at", "updated_at"]

    def create(self, validated_data: dict[str, Any]) -> Organization:
        workspace = get_default_workspace()
        organization, _ = create_organization(
            workspace,
            name=validated_data.get("name", ""),
            domain=validated_data.get("domain", ""),
            external_ids=validated_data.get("external_ids"),
        )
        return organization

    def update(self, instance: Organization, validated_data: dict[str, Any]) -> Organization:
        if "domain" in validated_data:
            domain = validated_data["domain"]
            instance.dedupe_key = normalize_domain(domain) if domain else ""
        return super().update(instance, validated_data)
