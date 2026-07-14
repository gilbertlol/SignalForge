from rest_framework import viewsets

from apps.core.services import get_default_workspace

from .models import Organization
from .serializers import OrganizationSerializer


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer
    filterset_fields = ["domain"]

    def get_queryset(self):
        return Organization.objects.filter(workspace=get_default_workspace())
