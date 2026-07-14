from rest_framework import viewsets

from apps.core.services import get_default_workspace

from .models import Opportunity
from .serializers import OpportunitySerializer


class OpportunityViewSet(viewsets.ModelViewSet):
    serializer_class = OpportunitySerializer
    filterset_fields = ["status", "organization"]

    def get_queryset(self):
        return Opportunity.objects.filter(workspace=get_default_workspace())
