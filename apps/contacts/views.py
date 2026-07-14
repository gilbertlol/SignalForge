from rest_framework import viewsets

from apps.accounts.permissions import HasWorkspacePermission
from apps.core.services import get_request_workspace

from .models import Contact
from .serializers import ContactSerializer


class ContactViewSet(viewsets.ModelViewSet):
    serializer_class = ContactSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "prospects.access"
    filterset_fields = ["organization"]

    def get_queryset(self):
        return Contact.objects.filter(workspace=get_request_workspace(self.request))
