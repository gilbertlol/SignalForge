from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import generics

from apps.accounts.permissions import HasWorkspacePermission
from apps.core.services import get_request_workspace
from apps.opportunities.models import Opportunity
from apps.organizations.models import Organization

from .models import Evidence
from .serializers import EvidenceSerializer


class _EvidenceForSubjectView(generics.ListCreateAPIView):
    """Base for `.../<subject>/<id>/evidence/` — subclasses set `subject_model`."""

    serializer_class = EvidenceSerializer
    subject_model: type
    subject_url_kwarg = "subject_id"
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "prospects.access"

    def get_subject(self):
        return get_object_or_404(
            self.subject_model,
            pk=self.kwargs[self.subject_url_kwarg],
            workspace=get_request_workspace(self.request),
        )

    def get_queryset(self):
        subject = self.get_subject()
        content_type = ContentType.objects.get_for_model(subject)
        return Evidence.objects.filter(
            workspace=get_request_workspace(self.request),
            content_type=content_type,
            object_id=subject.pk,
        )

    def perform_create(self, serializer):
        serializer.save(subject=self.get_subject())


class OrganizationEvidenceListCreateView(_EvidenceForSubjectView):
    subject_model = Organization
    subject_url_kwarg = "organization_id"


class OpportunityEvidenceListCreateView(_EvidenceForSubjectView):
    subject_model = Opportunity
    subject_url_kwarg = "opportunity_id"
