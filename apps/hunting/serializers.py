from typing import Any

from rest_framework import serializers

from apps.core.services import get_default_workspace

from . import services
from .models import HuntProfile, HuntProfileVersion


class HuntProfileVersionSerializer(serializers.ModelSerializer):
    criteria = serializers.SerializerMethodField()
    search_scope = serializers.SerializerMethodField()
    source_policies = serializers.SerializerMethodField()
    exclusion_rules = serializers.SerializerMethodField()
    result_threshold = serializers.SerializerMethodField()

    class Meta:
        model = HuntProfileVersion
        fields = [
            "id",
            "version_number",
            "criteria",
            "search_scope",
            "source_policies",
            "exclusion_rules",
            "result_threshold",
            "created_at",
        ]
        read_only_fields = fields

    def get_criteria(self, obj: HuntProfileVersion) -> dict[str, Any]:
        return services.serialize_criteria_tree(obj.root_group)

    def get_search_scope(self, obj: HuntProfileVersion) -> dict[str, Any] | None:
        return services.serialize_search_scope(obj)

    def get_source_policies(self, obj: HuntProfileVersion) -> list[dict[str, Any]]:
        return services.serialize_source_policies(obj)

    def get_exclusion_rules(self, obj: HuntProfileVersion) -> list[dict[str, Any]]:
        return services.serialize_exclusion_rules(obj)

    def get_result_threshold(self, obj: HuntProfileVersion) -> dict[str, Any] | None:
        return services.serialize_result_threshold(obj)


class HuntProfileSerializer(serializers.ModelSerializer):
    current_version = HuntProfileVersionSerializer(read_only=True)

    # Write-only: the payload for the initial version, consumed by create().
    criteria = serializers.JSONField(write_only=True)
    search_scope = serializers.JSONField(write_only=True, required=False)
    source_policies = serializers.JSONField(write_only=True, required=False)
    exclusion_rules = serializers.JSONField(write_only=True, required=False)
    result_threshold = serializers.JSONField(write_only=True, required=False)

    class Meta:
        model = HuntProfile
        fields = [
            "id",
            "name",
            "description",
            "status",
            "current_version",
            "criteria",
            "search_scope",
            "source_policies",
            "exclusion_rules",
            "result_threshold",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "current_version", "created_at", "updated_at"]

    def create(self, validated_data: dict[str, Any]) -> HuntProfile:
        workspace = get_default_workspace()
        profile = HuntProfile.objects.create(
            workspace=workspace,
            name=validated_data["name"],
            description=validated_data.get("description", ""),
        )
        version = services.create_version(
            profile,
            criteria=validated_data["criteria"],
            search_scope=validated_data.get("search_scope"),
            source_policies=validated_data.get("source_policies"),
            exclusion_rules=validated_data.get("exclusion_rules"),
            result_threshold=validated_data.get("result_threshold"),
        )
        profile.current_version = version
        profile.save(update_fields=["current_version", "updated_at"])
        return profile


class CreateVersionSerializer(serializers.Serializer):
    """Input for POST .../versions/ — same shape as HuntProfileSerializer's write-only fields."""

    criteria = serializers.JSONField()
    search_scope = serializers.JSONField(required=False)
    source_policies = serializers.JSONField(required=False)
    exclusion_rules = serializers.JSONField(required=False)
    result_threshold = serializers.JSONField(required=False)


class CloneSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)


class DryRunRequestSerializer(serializers.Serializer):
    organization_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True
    )
