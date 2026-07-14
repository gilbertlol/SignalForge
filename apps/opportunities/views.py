from rest_framework import viewsets

from apps.accounts.permissions import HasWorkspacePermission
from apps.core.services import get_request_workspace

from .models import Opportunity
from .serializers import OpportunitySerializer


class OpportunityViewSet(viewsets.ModelViewSet):
    serializer_class = OpportunitySerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "prospects.access"
    filterset_fields = ["status", "organization"]

    def get_queryset(self):
        return Opportunity.objects.filter(workspace=get_request_workspace(self.request))
