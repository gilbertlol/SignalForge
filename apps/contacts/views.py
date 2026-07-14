from rest_framework import viewsets

from apps.core.services import get_default_workspace

from .models import Contact
from .serializers import ContactSerializer


class ContactViewSet(viewsets.ModelViewSet):
    serializer_class = ContactSerializer
    filterset_fields = ["organization"]

    def get_queryset(self):
        return Contact.objects.filter(workspace=get_default_workspace())
