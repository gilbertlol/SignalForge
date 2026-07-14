from rest_framework import viewsets

from apps.accounts.permissions import HasWorkspacePermission
from apps.core.services import get_request_workspace

from .models import Organization
from .serializers import OrganizationSerializer


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "prospects.access"
    filterset_fields = ["domain"]

    def get_queryset(self):
        return Organization.objects.filter(workspace=get_request_workspace(self.request))
