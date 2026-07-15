from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasWorkspacePermission
from apps.core.services import get_request_workspace
from apps.evidence.serializers import (
    OrganizationClaimSerializer,
    OrganizationFieldResolutionSerializer,
)

from .models import Organization
from .serializers import OrganizationSerializer


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "prospects.access"
    filterset_fields = ["domain"]

    def get_queryset(self):
        return Organization.objects.filter(
            workspace=get_request_workspace(self.request)
        ).prefetch_related("source_claims", "field_resolutions__selected_claim")

    @action(detail=True, methods=["get"])
    def provenance(self, request, pk=None):
        organization = self.get_object()
        return Response(
            {
                "organization": str(organization.id),
                "claims": OrganizationClaimSerializer(
                    organization.source_claims.all(), many=True
                ).data,
                "resolutions": OrganizationFieldResolutionSerializer(
                    organization.field_resolutions.select_related("selected_claim"), many=True
                ).data,
            }
        )
