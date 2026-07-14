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
