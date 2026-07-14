from typing import Any

from rest_framework import serializers

from apps.core.services import get_request_workspace

from .models import Opportunity


class OpportunitySerializer(serializers.ModelSerializer):
    contacted = serializers.ReadOnlyField()

    class Meta:
        model = Opportunity
        fields = [
            "id",
            "organization",
            "primary_contact",
            "title",
            "status",
            "first_contacted_at",
            "contacted",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "contacted", "created_at", "updated_at"]

    def create(self, validated_data: dict[str, Any]) -> Opportunity:
        validated_data["workspace"] = get_request_workspace(self.context["request"])
        return Opportunity.objects.create(**validated_data)
