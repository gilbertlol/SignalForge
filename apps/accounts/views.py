from typing import cast

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.sessions.models import Session
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from apps.core.services import get_request_workspace

from .models import APIKey, LoginAttempt, Membership, SecurityAuditEvent, User, UserSession
from .permissions import HasWorkspacePermission
from .serializers import (
    APIKeySerializer,
    InvitationAcceptSerializer,
    InvitationCreateSerializer,
    MembershipSerializer,
    UserSerializer,
    UserSessionSerializer,
)


def client_ip(request):
    return request.META.get("REMOTE_ADDR")


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def login_view(request):
    email = request.data.get("email", "").lower()
    user = authenticate(request, email=email, password=request.data.get("password", ""))
    LoginAttempt.objects.create(
        email=email,
        ip_address=client_ip(request),
        was_successful=user is not None,
        failure_reason="" if user else "invalid_credentials",
    )
    if user is None:
        return Response({"detail": "Invalid credentials."}, status=status.HTTP_400_BAD_REQUEST)
    login(request, user)
    if not request.session.session_key:
        request.session.save()
    workspace = get_request_workspace(request)
    UserSession.objects.update_or_create(
        session_key=request.session.session_key,
        defaults={
            "user": user,
            "workspace": workspace,
            "ip_address": client_ip(request),
            "user_agent": request.headers.get("User-Agent", ""),
            "last_seen_at": timezone.now(),
        },
    )
    SecurityAuditEvent.objects.create(
        workspace=workspace,
        actor=cast(User, user),
        event="login",
        ip_address=client_ip(request),
    )
    return Response(UserSerializer(user).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    workspace = get_request_workspace(request)
    if request.session.session_key:
        UserSession.objects.filter(session_key=request.session.session_key).update(
            revoked_at=timezone.now()
        )
    SecurityAuditEvent.objects.create(
        workspace=workspace, actor=request.user, event="logout", ip_address=client_ip(request)
    )
    logout(request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@permission_classes([AllowAny])
def accept_invitation(request):
    serializer = InvitationAcceptSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    SecurityAuditEvent.objects.create(actor=user, event="invitation.accepted")
    return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def profile(request):
    user = cast(User, request.user)
    if request.method == "PATCH":
        serializer = UserSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
    return Response(UserSerializer(user).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def password_change(request):
    user = cast(User, request.user)
    if not user.check_password(request.data.get("current_password", "")):
        return Response({"current_password": ["Incorrect password."]}, status=400)
    new_password = request.data.get("new_password", "")
    if len(new_password) < 12:
        return Response({"new_password": ["Must contain at least 12 characters."]}, status=400)
    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    update_session_auth_hash(request, user)
    SecurityAuditEvent.objects.create(
        workspace=get_request_workspace(request), actor=user, event="password.changed"
    )
    return Response(status=status.HTTP_204_NO_CONTENT)


class MembershipViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MembershipSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "users.manage"

    def get_queryset(self):
        return (
            Membership.objects.filter(workspace=get_request_workspace(self.request))
            .select_related("user")
            .prefetch_related("roles")
        )

    @action(detail=False, methods=["post"])
    def invite(self, request):
        workspace = get_request_workspace(request)
        serializer = InvitationCreateSerializer(
            data=request.data, context={"request": request, "workspace": workspace}
        )
        serializer.is_valid(raise_exception=True)
        invitation = serializer.save()
        SecurityAuditEvent.objects.create(
            workspace=workspace,
            actor=request.user,
            event="invitation.created",
            target_id=str(invitation.id),
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class APIKeyViewSet(viewsets.ModelViewSet):
    serializer_class = APIKeySerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "settings.manage"
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return APIKey.objects.filter(
            user=cast(User, self.request.user), workspace=get_request_workspace(self.request)
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key, raw_key = APIKey.issue(
            workspace=get_request_workspace(request),
            user=cast(User, request.user),
            **serializer.validated_data,
        )
        data = APIKeySerializer(key).data
        data["key"] = raw_key
        SecurityAuditEvent.objects.create(
            workspace=key.workspace,
            actor=request.user,
            event="api_key.created",
            target_id=str(key.id),
        )
        return Response(data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        instance.revoked_at = timezone.now()
        instance.save(update_fields=["revoked_at", "updated_at"])


class SessionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = UserSessionSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "settings.manage"

    def get_queryset(self):
        return UserSession.objects.filter(
            user=cast(User, self.request.user), workspace=get_request_workspace(self.request)
        )

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        tracked = self.get_object()
        tracked.revoked_at = timezone.now()
        tracked.save(update_fields=["revoked_at", "updated_at"])
        Session.objects.filter(session_key=tracked.session_key).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
