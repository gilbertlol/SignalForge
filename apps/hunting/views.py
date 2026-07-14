from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import HasWorkspacePermission
from apps.core.services import get_request_workspace
from apps.organizations.models import Organization

from . import services
from .models import HuntProfile
from .serializers import (
    CloneSerializer,
    CreateVersionSerializer,
    DryRunRequestSerializer,
    HuntProfileSerializer,
    HuntProfileVersionSerializer,
)


class HuntProfileViewSet(viewsets.ModelViewSet):
    serializer_class = HuntProfileSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "prospects.access"
    filterset_fields = ["status"]

    def get_queryset(self):
        return HuntProfile.objects.filter(workspace=get_request_workspace(self.request))

    @action(detail=True, methods=["get", "post"])
    def versions(self, request: Request, pk=None) -> Response:
        profile = self.get_object()
        if request.method == "POST":
            payload = CreateVersionSerializer(data=request.data)
            payload.is_valid(raise_exception=True)
            version = services.create_version(profile, **payload.validated_data)
            return Response(HuntProfileVersionSerializer(version).data, status=201)
        serializer = HuntProfileVersionSerializer(profile.versions.all(), many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def activate(self, request: Request, pk=None) -> Response:
        profile = self.get_object()
        version_id = request.data.get("version_id")
        version = profile.versions.get(pk=version_id) if version_id else profile.current_version
        if version is None:
            return Response({"detail": "No version to activate."}, status=400)
        services.activate_version(profile, version)
        return Response(HuntProfileSerializer(profile).data)

    @action(detail=True, methods=["post"])
    def pause(self, request: Request, pk=None) -> Response:
        profile = services.pause(self.get_object())
        return Response(HuntProfileSerializer(profile).data)

    @action(detail=True, methods=["post"])
    def archive(self, request: Request, pk=None) -> Response:
        profile = services.archive(self.get_object())
        return Response(HuntProfileSerializer(profile).data)

    @action(detail=True, methods=["post"])
    def clone(self, request: Request, pk=None) -> Response:
        profile = self.get_object()
        payload = CloneSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        clone = services.clone_profile(profile, name=payload.validated_data["name"])
        return Response(HuntProfileSerializer(clone).data, status=201)

    @action(detail=True, methods=["post"], url_path="dry-run")
    def dry_run(self, request: Request, pk=None) -> Response:
        profile = self.get_object()
        if profile.current_version is None:
            return Response({"detail": "Profile has no version yet."}, status=400)
        payload = DryRunRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        organization_ids = payload.validated_data.get("organization_ids")
        organizations = None
        if organization_ids:
            organizations = list(
                Organization.objects.filter(workspace=profile.workspace, id__in=organization_ids)
            )
        results = services.dry_run(profile.current_version, organizations=organizations)
        return Response({"results": results})
