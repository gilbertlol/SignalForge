from typing import Any

from rest_framework import serializers

from .models import Evidence
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
