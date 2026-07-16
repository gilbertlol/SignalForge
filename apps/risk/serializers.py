from django.utils import timezone
from rest_framework import serializers

from apps.finance.models import Contract
from apps.opportunities.models import Opportunity

from .models import (
    AcceptancePolicy,
    ControlRecommendation,
    Mitigation,
    Override,
    Review,
    RiskCategory,
    RiskFactor,
    RiskObservation,
    RiskProfile,
    RiskSnapshot,
)


class WorkspaceSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        workspace = self.context["workspace"]
        for value in attrs.values():
            if hasattr(value, "workspace_id") and value.workspace_id != workspace.pk:
                raise serializers.ValidationError("Related records must use this workspace.")
        return attrs

    def create(self, validated_data):
        validated_data["workspace"] = self.context["workspace"]
        return super().create(validated_data)


class RiskProfileSerializer(WorkspaceSerializer):
    opportunity = serializers.PrimaryKeyRelatedField(
        queryset=Opportunity.objects.all(), required=False, allow_null=True
    )
    contract = serializers.PrimaryKeyRelatedField(
        queryset=Contract.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = RiskProfile
        fields = "__all__"
        read_only_fields = ["workspace"]
        extra_kwargs = {
            "opportunity": {"required": False, "allow_null": True},
            "contract": {"required": False, "allow_null": True},
        }
        validators = []

    def validate(self, attrs):
        attrs = super().validate(attrs)
        organization = attrs.get("organization", getattr(self.instance, "organization", None))
        opportunity = attrs.get("opportunity", getattr(self.instance, "opportunity", None))
        contract = attrs.get("contract", getattr(self.instance, "contract", None))
        if opportunity and opportunity.organization_id != organization.pk:
            raise serializers.ValidationError("Opportunity must belong to the organization.")
        if contract and contract.organization_id != organization.pk:
            raise serializers.ValidationError("Contract must belong to the organization.")
        duplicate = RiskProfile.objects.filter(
            workspace=self.context["workspace"],
            organization=organization,
            opportunity=opportunity,
            contract=contract,
        )
        if self.instance:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError("A risk profile already exists for this scope.")
        return attrs


class RiskCategorySerializer(WorkspaceSerializer):
    class Meta:
        model = RiskCategory
        fields = "__all__"
        read_only_fields = ["workspace"]


class RiskFactorSerializer(WorkspaceSerializer):
    class Meta:
        model = RiskFactor
        fields = "__all__"
        read_only_fields = ["workspace"]


class RiskObservationSerializer(WorkspaceSerializer):
    class Meta:
        model = RiskObservation
        fields = "__all__"
        read_only_fields = ["workspace", "created_by"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class RiskSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskSnapshot
        fields = "__all__"


class ControlRecommendationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlRecommendation
        fields = "__all__"
        read_only_fields = [
            "workspace",
            "profile",
            "snapshot",
            "category",
            "control_type",
            "rationale",
            "threshold",
            "requires_approval",
        ]


class MitigationSerializer(WorkspaceSerializer):
    class Meta:
        model = Mitigation
        fields = "__all__"
        read_only_fields = ["workspace"]


class OverrideSerializer(WorkspaceSerializer):
    class Meta:
        model = Override
        fields = "__all__"
        read_only_fields = ["workspace", "created_by", "effective_at"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        validated_data["effective_at"] = timezone.now()
        return super().create(validated_data)


class ReviewSerializer(WorkspaceSerializer):
    class Meta:
        model = Review
        fields = "__all__"
        read_only_fields = ["workspace", "reviewer", "reviewed_at"]

    def create(self, validated_data):
        validated_data["reviewer"] = self.context["request"].user
        validated_data["reviewed_at"] = timezone.now()
        return super().create(validated_data)


class AcceptancePolicySerializer(WorkspaceSerializer):
    class Meta:
        model = AcceptancePolicy
        fields = "__all__"
        read_only_fields = ["workspace"]
