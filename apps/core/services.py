from django.http import Http404

from .models import Workspace

DEFAULT_WORKSPACE_SLUG = "default"


def get_default_workspace() -> Workspace:
    """The single workspace this v1 (pre-GOR-244) installation operates against.

    Idempotent: safe to call from a management command, a migration data
    step, or directly from API views that need "the" workspace before real
    multi-workspace selection exists.
    """
    workspace, _ = Workspace.objects.get_or_create(
        slug=DEFAULT_WORKSPACE_SLUG,
        defaults={"name": "Default Workspace"},
    )
    return workspace


def get_user_workspace(user, requested_slug: str | None = None) -> Workspace:
    """Resolve a workspace only through an active membership.

    Superusers may access an explicitly requested workspace. The default-workspace
    fallback is retained only for anonymous/internal pre-auth callers and legacy
    management commands; authenticated application requests never gain implicit access.
    """
    if not getattr(user, "is_authenticated", False):
        return get_default_workspace()
    if user.is_superuser and requested_slug:
        return Workspace.objects.get(slug=requested_slug)
    memberships = user.memberships.filter(is_active=True).select_related("workspace")
    if requested_slug:
        membership = memberships.filter(workspace__slug=requested_slug).first()
        if not membership:
            raise Http404("Workspace not found")
        return membership.workspace
    preference = getattr(user, "preferences", None)
    if preference and preference.active_workspace_id:
        membership = memberships.filter(workspace_id=preference.active_workspace_id).first()
        if membership:
            return membership.workspace
    membership = memberships.order_by("created_at").first()
    if membership:
        return membership.workspace
    raise Http404("Workspace not found")


def get_request_workspace(request) -> Workspace:
    cached = getattr(request, "workspace", None)
    if cached is not None:
        return cached
    slug = request.headers.get("X-Workspace") if request is not None else None
    return get_user_workspace(request.user, slug)
