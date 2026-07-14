from rest_framework.permissions import BasePermission

from apps.core.services import get_request_workspace


class HasWorkspacePermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        workspace = get_request_workspace(request)
        request.workspace = workspace
        required_permission = getattr(view, "required_workspace_permission", None)
        if request.user.is_superuser or required_permission is None:
            return True
        api_key = getattr(request, "api_key", None)
        if api_key is not None and required_permission not in api_key.scopes:
            return False
        membership = request.user.memberships.filter(workspace=workspace, is_active=True).first()
        return bool(membership and membership.has_permission(required_permission))
