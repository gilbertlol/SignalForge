from typing import Any

from rest_framework import serializers

from .models import Evidence, OrganizationClaim, OrganizationFieldResolution
from .services import record_evidence


class EvidenceSerializer(serializers.ModelSerializer):
    age_days = serializers.ReadOnlyField()

    class Meta:
        model = Evidence
        fields = [
            "id",
            "source_url",
            "source_type",
            "observed_date",
            "excerpt",
            "reliability",
            "verification_status",
            "is_inferred",
            "age_days",
            "created_at",
        ]
        read_only_fields = ["id", "age_days", "created_at"]

    def create(self, validated_data: dict[str, Any]) -> Evidence:
        subject = validated_data.pop("subject")
        return record_evidence(subject, **validated_data)


class OrganizationClaimSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationClaim
        fields = [
            "id",
            "source_record",
            "source_key",
            "field_name",
            "value",
            "reliability",
            "observed_at",
            "created_at",
        ]
        read_only_fields = fields


class OrganizationFieldResolutionSerializer(serializers.ModelSerializer):
    selected_claim = OrganizationClaimSerializer(read_only=True)

    class Meta:
        model = OrganizationFieldResolution
        fields = [
            "field_name",
            "selected_claim",
            "corroboration_count",
            "distinct_value_count",
            "has_conflict",
            "explanation",
            "resolved_at",
        ]
        read_only_fields = fields
