from collections.abc import Callable
from functools import wraps
from typing import cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.communications.models import Conversation, Message, MessageStatus
from apps.communications.services import SendBlocked, approve_message, send_message
from apps.contacts.models import Contact
from apps.core.services import get_request_workspace
from apps.discovery.models import DiscoveryRun, DiscoveryRunStatus, SourceRecord, SourceRecordStatus
from apps.organizations.models import Organization


def workspace_permission(key: str):
    def decorator(view: Callable[..., HttpResponse]):
        @login_required
        @wraps(view)
        def wrapped(request: HttpRequest, *args, **kwargs):
            workspace = get_request_workspace(request)
            user = cast(User, request.user)
            membership = user.memberships.filter(workspace=workspace, is_active=True).first()
            if not user.is_superuser and not (membership and membership.has_permission(key)):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def _navigation(request: HttpRequest) -> dict[str, bool]:
    workspace = get_request_workspace(request)
    user = cast(User, request.user)
    membership = user.memberships.filter(workspace=workspace, is_active=True).first()

    def allowed(key: str) -> bool:
        return user.is_superuser or bool(membership and membership.has_permission(key))

    return {
        "prospects": allowed("prospects.access"),
        "communications": allowed("communications.access"),
        "providers": allowed("providers.manage"),
        "users": allowed("users.manage"),
    }


def _render(request: HttpRequest, template: str, context: dict) -> HttpResponse:
    return render(
        request,
        template,
        {**context, "workspace": get_request_workspace(request), "nav": _navigation(request)},
    )


@workspace_permission("prospects.access")
def dashboard(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    recent_runs = DiscoveryRun.objects.filter(workspace=workspace)[:6]
    return _render(
        request,
        "command_center/dashboard.html",
        {
            "organization_count": Organization.objects.filter(workspace=workspace).count(),
            "review_count": SourceRecord.objects.filter(
                discovery_run__workspace=workspace, status=SourceRecordStatus.QUALIFIED
            ).count(),
            "pending_approval_count": Message.objects.filter(
                workspace=workspace, status=MessageStatus.PENDING_APPROVAL
            ).count(),
            "active_run_count": DiscoveryRun.objects.filter(
                workspace=workspace,
                status__in=[DiscoveryRunStatus.PENDING, DiscoveryRunStatus.RUNNING],
            ).count(),
            "recent_runs": recent_runs,
        },
    )


@workspace_permission("prospects.access")
def review_queue(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    records = SourceRecord.objects.filter(
        discovery_run__workspace=workspace, status=SourceRecordStatus.QUALIFIED
    ).select_related("organization", "discovery_run__hunt_profile_version__hunt_profile")[:100]
    return _render(request, "command_center/review_queue.html", {"records": records})


@workspace_permission("prospects.access")
def run_monitor(request: HttpRequest) -> HttpResponse:
    runs = DiscoveryRun.objects.filter(workspace=get_request_workspace(request)).select_related(
        "hunt_profile_version__hunt_profile", "initiated_by"
    )[:100]
    return _render(request, "command_center/runs.html", {"runs": runs})


@workspace_permission("prospects.access")
def organizations(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    queryset = Organization.objects.filter(workspace=get_request_workspace(request))
    if query:
        queryset = queryset.filter(Q(name__icontains=query) | Q(domain__icontains=query))
    return _render(
        request,
        "command_center/organizations.html",
        {"organizations": queryset[:100], "query": query},
    )


@workspace_permission("prospects.access")
def organization_detail(request: HttpRequest, pk) -> HttpResponse:
    workspace = get_request_workspace(request)
    organization = get_object_or_404(Organization, workspace=workspace, pk=pk)
    opportunities = organization.opportunities.all()
    conversations = Conversation.objects.filter(
        workspace=workspace, opportunity__organization=organization
    )[:20]
    return _render(
        request,
        "command_center/organization_detail.html",
        {
            "organization": organization,
            "contacts": organization.contacts.all(),
            "opportunities": opportunities,
            "conversations": conversations,
        },
    )


@workspace_permission("communications.access")
def inbox(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    conversations = Conversation.objects.filter(workspace=workspace).prefetch_related(
        "messages", "participants"
    )[:100]
    pending = Message.objects.filter(
        workspace=workspace, status=MessageStatus.PENDING_APPROVAL
    ).select_related("conversation")
    return _render(
        request,
        "command_center/inbox.html",
        {"conversations": conversations, "pending_messages": pending},
    )


@require_POST
@workspace_permission("communications.send")
def approve_outbound(request: HttpRequest, pk) -> HttpResponse:
    message = get_object_or_404(Message, workspace=get_request_workspace(request), pk=pk)
    approve_message(message, cast(User, request.user))
    messages.success(request, "Message approved.")
    return redirect("command_center:inbox")


@require_POST
@workspace_permission("communications.send")
def send_outbound(request: HttpRequest, pk) -> HttpResponse:
    message = get_object_or_404(Message, workspace=get_request_workspace(request), pk=pk)
    try:
        send_message(message, actor=cast(User, request.user))
    except SendBlocked as exc:
        messages.error(request, f"Send blocked: {exc}")
    else:
        messages.success(request, "Message sent.")
    return redirect("command_center:inbox")


@workspace_permission("prospects.access")
def global_search(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return _render(request, "command_center/search.html", {"query": query, "results": []})
    workspace = get_request_workspace(request)
    organizations_found = Organization.objects.filter(workspace=workspace).filter(
        Q(name__icontains=query) | Q(domain__icontains=query)
    )[:20]
    contacts_found = Contact.objects.filter(workspace=workspace).filter(
        Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(email__icontains=query)
    )[:20]
    results: list[tuple[str, object, str | None]] = [
        (
            "Organization",
            item,
            reverse("command_center:organization-detail", kwargs={"pk": item.pk}),
        )
        for item in organizations_found
    ]
    results.extend(("Contact", item, None) for item in contacts_found)
    return _render(
        request,
        "command_center/search.html",
        {"query": query, "results": results},
    )
