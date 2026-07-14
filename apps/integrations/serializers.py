from rest_framework import serializers

from .models import (
    AIEndpoint,
    AIProvider,
    CredentialReference,
    ModelDefinition,
    ModelInvocation,
    ModelRoute,
    ProviderHealthCheck,
)


class WorkspaceModelSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        workspace = self.context["workspace"]
        for value in attrs.values():
            related = value if isinstance(value, list | tuple) else [value]
            for instance in related:
                if hasattr(instance, "workspace_id") and instance.workspace_id != workspace.id:
                    raise serializers.ValidationError(
                        "Related records must use the active workspace."
                    )
        return attrs

    def create(self, validated_data):
        validated_data["workspace"] = self.context["workspace"]
        return super().create(validated_data)


class AIProviderSerializer(WorkspaceModelSerializer):
    class Meta:
        model = AIProvider
        fields = ["id", "name", "provider_key", "provider_type", "enabled", "config"]


class CredentialReferenceSerializer(WorkspaceModelSerializer):
    secret = serializers.CharField(write_only=True, min_length=1)

    class Meta:
        model = CredentialReference
        fields = ["id", "name", "secret", "key_version", "last_rotated_at"]
        read_only_fields = ["key_version", "last_rotated_at"]

    def create(self, validated_data):
        secret = validated_data.pop("secret")
        instance = CredentialReference(**validated_data, workspace=self.context["workspace"])
        instance.set_secret(secret)
        instance.save()
        return instance


class AIEndpointSerializer(WorkspaceModelSerializer):
    class Meta:
        model = AIEndpoint
        fields = [
            "id",
            "provider",
            "name",
            "base_url",
            "credential",
            "timeout_seconds",
            "requests_per_minute",
            "privacy_class",
            "enabled",
        ]


class ModelDefinitionSerializer(WorkspaceModelSerializer):
    class Meta:
        model = ModelDefinition
        fields = [
            "id",
            "endpoint",
            "model_name",
            "display_name",
            "context_limit",
            "input_cost_per_million",
            "output_cost_per_million",
            "capabilities",
            "enabled",
        ]


class ModelRouteSerializer(WorkspaceModelSerializer):
    class Meta:
        model = ModelRoute
        fields = [
            "id",
            "task_type",
            "name",
            "fallback_policy",
            "required_privacy_class",
            "is_default",
            "enabled",
        ]


class ModelInvocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModelInvocation
        fields = "__all__"
        read_only_fields = fields


class ProviderHealthCheckSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderHealthCheck
        fields = "__all__"
        read_only_fields = fields
