from typing import Any

from rest_framework import serializers

from apps.core.services import get_request_workspace
from apps.evidence.serializers import OrganizationFieldResolutionSerializer

from .models import Organization
from .services import create_organization, normalize_domain


class OrganizationSerializer(serializers.ModelSerializer):
    sources = serializers.SerializerMethodField()
    first_discovered_source = serializers.SerializerMethodField()
    conflict_fields = serializers.SerializerMethodField()
    field_resolutions = OrganizationFieldResolutionSerializer(many=True, read_only=True)

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "domain",
            "dedupe_key",
            "external_ids",
            "sources",
            "first_discovered_source",
            "conflict_fields",
            "field_resolutions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "dedupe_key", "created_at", "updated_at"]

    def get_sources(self, obj: Organization) -> list[str]:
        return list(
            obj.source_claims.order_by("source_key").values_list("source_key", flat=True).distinct()
        )

    def get_first_discovered_source(self, obj: Organization) -> str | None:
        claim = obj.source_claims.order_by("observed_at", "created_at").first()
        return claim.source_key if claim else None

    def get_conflict_fields(self, obj: Organization) -> list[str]:
        return list(
            obj.field_resolutions.filter(has_conflict=True).values_list("field_name", flat=True)
        )

    def create(self, validated_data: dict[str, Any]) -> Organization:
        workspace = get_request_workspace(self.context["request"])
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
