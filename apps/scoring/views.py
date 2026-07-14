from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasWorkspacePermission
from apps.core.services import get_request_workspace
from apps.opportunities.models import Opportunity
from apps.organizations.models import Organization

from .models import ScoreFamily, ScoreSnapshot
from .serializers import ScoreSnapshotSerializer
from .services import evaluate, latest_snapshot

_VALID_FAMILIES = {choice.value for choice in ScoreFamily}


class ScoreSnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ScoreSnapshotSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "prospects.access"
    filterset_fields = ["family"]

    def get_queryset(self):
        return ScoreSnapshot.objects.filter(workspace=get_request_workspace(self.request))


class _ScoreForSubjectView(APIView):
    """Base for `.../<subject>/<id>/scores/<family>/{explain,recompute}/`."""

    subject_model: type
    subject_url_kwarg = "subject_id"
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "prospects.access"

    def get_subject_or_400(self, family: str, **kwargs):
        """Returns the subject instance, or a Response if `family` is invalid."""
        if family not in _VALID_FAMILIES:
            return Response({"detail": f"Unknown score family {family!r}."}, status=400)
        return get_object_or_404(
            self.subject_model,
            pk=kwargs[self.subject_url_kwarg],
            workspace=get_request_workspace(self.request),
        )


class _ScoreExplainView(_ScoreForSubjectView):
    def get(self, request: Request, family: str, **kwargs) -> Response:
        subject = self.get_subject_or_400(family, **kwargs)
        if isinstance(subject, Response):
            return subject
        snapshot = latest_snapshot(subject, family)
        if snapshot is None:
            return Response({"detail": "No score has been computed yet."}, status=404)
        return Response(ScoreSnapshotSerializer(snapshot).data)


class _ScoreRecomputeView(_ScoreForSubjectView):
    def post(self, request: Request, family: str, **kwargs) -> Response:
        subject = self.get_subject_or_400(family, **kwargs)
        if isinstance(subject, Response):
            return subject
        snapshot = evaluate(subject, family)
        return Response(ScoreSnapshotSerializer(snapshot).data, status=status.HTTP_201_CREATED)


class OrganizationScoreExplainView(_ScoreExplainView):
    subject_model = Organization
    subject_url_kwarg = "organization_id"


class OrganizationScoreRecomputeView(_ScoreRecomputeView):
    subject_model = Organization
    subject_url_kwarg = "organization_id"


class OpportunityScoreExplainView(_ScoreExplainView):
    subject_model = Opportunity
    subject_url_kwarg = "opportunity_id"


class OpportunityScoreRecomputeView(_ScoreRecomputeView):
    subject_model = Opportunity
    subject_url_kwarg = "opportunity_id"
