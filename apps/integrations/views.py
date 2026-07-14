from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasWorkspacePermission
from apps.core.services import get_request_workspace

from .models import (
    AIEndpoint,
    AIProvider,
    CredentialReference,
    ModelDefinition,
    ModelInvocation,
    ModelRoute,
)
from .serializers import (
    AIEndpointSerializer,
    AIProviderSerializer,
    CredentialReferenceSerializer,
    ModelDefinitionSerializer,
    ModelInvocationSerializer,
    ModelRouteSerializer,
    ProviderHealthCheckSerializer,
)
from .services import check_provider


class WorkspaceViewSet(viewsets.ModelViewSet):
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "providers.manage"

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["workspace"] = get_request_workspace(self.request)
        return context


class AIProviderViewSet(WorkspaceViewSet):
    serializer_class = AIProviderSerializer

    def get_queryset(self):
        return AIProvider.objects.filter(workspace=get_request_workspace(self.request)).order_by(
            "name"
        )

    @action(detail=True, methods=["post"], url_path="test-connection")
    def test_connection(self, request, pk=None):
        result = check_provider(self.get_object())
        return Response(ProviderHealthCheckSerializer(result).data)


class CredentialReferenceViewSet(WorkspaceViewSet):
    serializer_class = CredentialReferenceSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return CredentialReference.objects.filter(
            workspace=get_request_workspace(self.request)
        ).order_by("name")


class AIEndpointViewSet(WorkspaceViewSet):
    serializer_class = AIEndpointSerializer

    def get_queryset(self):
        return AIEndpoint.objects.filter(workspace=get_request_workspace(self.request)).order_by(
            "name"
        )


class ModelDefinitionViewSet(WorkspaceViewSet):
    serializer_class = ModelDefinitionSerializer

    def get_queryset(self):
        return ModelDefinition.objects.filter(
            workspace=get_request_workspace(self.request)
        ).order_by("display_name")


class ModelRouteViewSet(WorkspaceViewSet):
    serializer_class = ModelRouteSerializer

    def get_queryset(self):
        return ModelRoute.objects.filter(workspace=get_request_workspace(self.request)).order_by(
            "name"
        )


class ModelInvocationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ModelInvocationSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "providers.manage"

    def get_queryset(self):
        return ModelInvocation.objects.filter(
            workspace=get_request_workspace(self.request)
        ).order_by("-created_at")
