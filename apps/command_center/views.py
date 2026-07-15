from collections.abc import Callable
from datetime import timedelta
from functools import wraps
from typing import cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.communications.models import Conversation, Message, MessageStatus
from apps.communications.services import SendBlocked, approve_message, send_message
from apps.contacts.models import Contact
from apps.core.services import get_request_workspace
from apps.discovery.models import (
    DiscoveryRun,
    DiscoveryRunStatus,
    DiscoveryRunTrigger,
    ProviderResult,
    ProviderResultStatus,
    SourceRecord,
    SourceRecordStatus,
)
from apps.discovery.services import start_run
from apps.discovery.tasks import run_discovery_task
from apps.evidence.models import OrganizationClaim
from apps.evidence.services import create_manual_claim, select_organization_claim
from apps.hunting.models import HuntProfile, HuntProfileStatus
from apps.hunting.services import activate_version, archive, create_version, pause
from apps.integrations.models import (
    AIEndpoint,
    AIProvider,
    CredentialReference,
    LeadSourceConfiguration,
    ModelDefinition,
)
from apps.integrations.registry import get_lead_source_adapter
from apps.integrations.services import check_provider
from apps.opportunities.models import Opportunity, OpportunityStatus
from apps.organizations.models import Organization
from apps.organizations.services import create_organization

from .forms import (
    AIEndpointForm,
    AIModelForm,
    AIProviderForm,
    ApolloConfigurationForm,
    CredentialForm,
    GooglePlacesConfigurationForm,
    HuntProfileForm,
    ManualClaimForm,
    OpportunityStatusForm,
    OrganizationCreateForm,
    ProfileActionForm,
)


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
    recent_runs = DiscoveryRun.objects.filter(workspace=workspace).select_related(
        "hunt_profile_version__profile"
    )[:6]
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
    ).select_related("organization", "discovery_run__hunt_profile_version__profile")[:100]
    return _render(request, "command_center/review_queue.html", {"records": records})


@workspace_permission("prospects.access")
def hunt_profiles(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    profiles = (
        HuntProfile.objects.filter(workspace=workspace)
        .select_related("current_version")
        .prefetch_related("current_version__source_policies")
    )
    for profile in profiles:
        profile.source_preflight = []
        if profile.current_version:
            scope = getattr(profile.current_version, "search_scope", None)
            all_policies = profile.current_version.source_policies.all()
            enabled_policies = list(all_policies.filter(is_enabled=True).order_by("priority"))
            for policy in enabled_policies:
                adapter = get_lead_source_adapter(policy.source_key, workspace=workspace)
                requested = {"max_records"}
                if policy.budget_cents is not None:
                    requested.add("budget")
                if scope:
                    if scope.geographies:
                        requested.add("geographies")
                    if scope.industries:
                        requested.add("industries")
                    if scope.company_size_min is not None or scope.company_size_max is not None:
                        requested.add("company_size")
                unsupported = sorted(requested - getattr(adapter, "capabilities", frozenset()))
                profile.source_preflight.append(
                    {
                        "key": (
                            f"{policy.source_key} (ignores: {', '.join(unsupported)})"
                            if unsupported
                            else policy.source_key
                        ),
                        "ready": bool(adapter and adapter.is_configured()),
                        "records": policy.max_records,
                        "budget": policy.budget_cents,
                        "timeout": policy.timeout_seconds,
                        "retries": policy.max_retries,
                        "reliability": policy.reliability_weight,
                        "unsupported": unsupported,
                    }
                )
    return _render(
        request,
        "command_center/hunt_profiles.html",
        {"profiles": profiles, "action_form": ProfileActionForm()},
    )


@workspace_permission("prospects.access")
def create_hunt_profile(request: HttpRequest) -> HttpResponse:
    form = HuntProfileForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        workspace = get_request_workspace(request)
        profile = HuntProfile.objects.create(
            workspace=workspace,
            name=form.cleaned_data["name"],
            description=form.cleaned_data["description"],
        )
        criterion = {
            "type": "criterion",
            "category": "custom_attribute",
            "field": "domain",
            "op": "neq",
            "value": "",
            "weight": form.cleaned_data["minimum_score"],
            "is_required": form.cleaned_data["require_domain"],
        }
        version = create_version(
            profile,
            criteria={"type": "group", "operator": "AND", "children": [criterion]},
            search_scope={
                "geographies": [
                    value.strip()
                    for value in form.cleaned_data["geographies"].split(",")
                    if value.strip()
                ],
                "industries": [
                    value.strip()
                    for value in form.cleaned_data["industries"].split(",")
                    if value.strip()
                ],
                "keyword": form.cleaned_data["keyword"],
                "included_type": form.cleaned_data["included_type"],
                "center_latitude": form.cleaned_data["center_latitude"],
                "center_longitude": form.cleaned_data["center_longitude"],
                "radius_meters": form.cleaned_data["radius_meters"],
            },
            source_policies=[
                *form.source_policies(),
            ],
            result_threshold={"min_total_score": form.cleaned_data["minimum_score"]},
        )
        profile.current_version = version
        profile.save(update_fields=["current_version", "updated_at"])
        if form.cleaned_data["activate_now"]:
            activate_version(profile, version)
        messages.success(request, f"Hunt Profile “{profile.name}” created.")
        return redirect("command_center:hunt-profiles")
    return _render(request, "command_center/hunt_profile_form.html", {"form": form})


@require_POST
@workspace_permission("prospects.access")
def profile_action(request: HttpRequest, pk) -> HttpResponse:
    profile = get_object_or_404(HuntProfile, workspace=get_request_workspace(request), pk=pk)
    form = ProfileActionForm(request.POST)
    if form.is_valid():
        action = form.cleaned_data["action"]
        if action == HuntProfileStatus.ACTIVE and profile.current_version:
            activate_version(profile, profile.current_version)
        elif action == HuntProfileStatus.PAUSED:
            pause(profile)
        elif action == HuntProfileStatus.ARCHIVED:
            archive(profile)
        messages.success(request, f"{profile.name} is now {action}.")
    return redirect("command_center:hunt-profiles")


@require_POST
@workspace_permission("prospects.access")
def start_discovery(request: HttpRequest, pk) -> HttpResponse:
    profile = get_object_or_404(HuntProfile, workspace=get_request_workspace(request), pk=pk)
    if profile.current_version is None:
        messages.error(request, "This Hunt Profile has no version to run.")
        return redirect("command_center:hunt-profiles")
    all_policies = profile.current_version.source_policies.all()
    policies = all_policies.filter(is_enabled=True)
    if not policies.exists():
        messages.info(
            request, "This is a manual/CSV-only profile; it has no automatic source to run."
        )
        return redirect("command_center:hunt-profiles")
    for policy in policies:
        adapter = get_lead_source_adapter(policy.source_key, workspace=profile.workspace)
        if adapter is None or not adapter.is_configured():
            messages.error(
                request,
                f"Discovery was not started: lead source “{policy.source_key}” is not configured. "
                "Ask a workspace provider administrator to enable it.",
            )
            return redirect("command_center:hunt-profiles")
    run = start_run(
        profile.current_version,
        trigger=DiscoveryRunTrigger.MANUAL,
        initiated_by=cast(User, request.user),
    )
    run_discovery_task.delay(str(run.id))
    messages.success(request, f"Discovery started for {profile.name}.")
    return redirect("command_center:runs")


@workspace_permission("prospects.access")
def opportunity_pipeline(request: HttpRequest) -> HttpResponse:
    selected_status = request.GET.get("status", "")
    opportunities = Opportunity.objects.filter(
        workspace=get_request_workspace(request)
    ).select_related("organization", "primary_contact")
    if selected_status in OpportunityStatus.values:
        opportunities = opportunities.filter(status=selected_status)
    columns = [
        (value, label, opportunities.filter(status=value))
        for value, label in OpportunityStatus.choices
    ]
    return _render(
        request,
        "command_center/pipeline.html",
        {"columns": columns, "selected_status": selected_status},
    )


@require_POST
@workspace_permission("prospects.access")
def opportunity_status(request: HttpRequest, pk) -> HttpResponse:
    opportunity = get_object_or_404(Opportunity, workspace=get_request_workspace(request), pk=pk)
    form = OpportunityStatusForm(request.POST)
    if form.is_valid():
        opportunity.status = form.cleaned_data["status"]
        opportunity.save(update_fields=["status", "updated_at"])
        messages.success(
            request, f"{opportunity.title} moved to {opportunity.get_status_display()}."
        )
    return redirect("command_center:pipeline")


@workspace_permission("providers.manage")
def provider_settings(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    providers = AIProvider.objects.filter(workspace=workspace).prefetch_related("endpoints__models")
    lead_sources = list(LeadSourceConfiguration.objects.filter(workspace=workspace))
    apollo = next((source for source in lead_sources if source.source_key == "apollo"), None)
    google = next((source for source in lead_sources if source.source_key == "google_places"), None)
    source_catalog = [
        {
            "name": "OpenStreetMap",
            "source_key": "openstreetmap",
            "state": "Ready — no API key required",
            "cost": "Free public data · no per-result fee",
            "limits": (
                "Geography required · up to 100 records per hunt · "
                "public Overpass fair-use limits"
            ),
            "capabilities": (
                "Local businesses, places, categories, addresses, websites and phone numbers "
                "when mapped"
            ),
            "attribution": "© OpenStreetMap contributors · Open Database License (ODbL)",
            "attribution_url": "https://www.openstreetmap.org/copyright",
            "ready": True,
        },
        {
            "name": "Apollo Organization Search",
            "source_key": "apollo",
            "state": "Ready for live searches"
            if apollo and apollo.enabled and apollo.credential_id
            else (
                "Disabled"
                if apollo and not apollo.enabled
                else "API key and compatible Apollo plan required"
            ),
            "cost": f"Estimated {apollo.estimated_cost_per_page_cents}¢ per returned page"
            if apollo
            else "Plan-dependent credit usage",
            "limits": (
                "Up to 100 records per hunt · availability depends on Apollo plan entitlements"
            ),
            "capabilities": "Organization filters, domains, industries and company metadata",
            "attribution": "Commercial provider data · subject to your Apollo plan and terms",
            "ready": bool(apollo and apollo.enabled and apollo.credential_id),
            "configuration": apollo,
        },
        {
            "name": "Google Places",
            "source_key": "google_places",
            "state": "Ready for live searches"
            if google and google.enabled and google.config.get("storage_permitted")
            else "Key and storage agreement attestation required",
            "cost": f"Estimated {google.estimated_cost_per_page_cents}¢ per page"
            if google
            else "Field-mask dependent billing",
            "limits": "Up to 20 results/page and 60/query · Google Maps attribution required",
            "capabilities": (
                "Geographic local-business search, categories, addresses, websites, "
                "phones and ratings"
            ),
            "attribution": "Google Maps content · storage restricted by Google Maps Platform terms",
            "attribution_url": "https://developers.google.com/maps/documentation/places/web-service/policies",
            "ready": bool(google and google.enabled and google.config.get("storage_permitted")),
        },
    ]
    return _render(
        request,
        "command_center/provider_settings.html",
        {
            "providers": providers,
            "source_catalog": source_catalog,
            "apollo_form": ApolloConfigurationForm(),
            "google_places_form": GooglePlacesConfigurationForm(),
            "credentials": CredentialReference.objects.filter(workspace=workspace),
            "provider_form": AIProviderForm(),
            "credential_form": CredentialForm(),
            "endpoint_form": AIEndpointForm(workspace=workspace),
            "model_form": AIModelForm(workspace=workspace),
        },
    )


@require_POST
@workspace_permission("providers.manage")
def create_provider(request: HttpRequest) -> HttpResponse:
    form = AIProviderForm(request.POST)
    if form.is_valid():
        AIProvider.objects.create(workspace=get_request_workspace(request), **form.cleaned_data)
        messages.success(request, "AI provider created.")
    else:
        messages.error(request, "Provider configuration is invalid.")
    return redirect("command_center:provider-settings")


@require_POST
@workspace_permission("providers.manage")
def create_credential(request: HttpRequest) -> HttpResponse:
    form = CredentialForm(request.POST)
    if form.is_valid():
        credential = CredentialReference(
            workspace=get_request_workspace(request), name=form.cleaned_data["name"]
        )
        credential.set_secret(form.cleaned_data["secret"])
        credential.save()
        messages.success(request, "Credential encrypted and stored.")
    else:
        messages.error(request, "Credential configuration is invalid.")
    return redirect("command_center:provider-settings")


@require_POST
@workspace_permission("providers.manage")
def configure_apollo(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    form = ApolloConfigurationForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Apollo configuration is invalid.")
        return redirect("command_center:provider-settings")

    configuration = (
        LeadSourceConfiguration.objects.filter(workspace=workspace, source_key="apollo")
        .select_related("credential")
        .first()
    )
    if configuration:
        credential = configuration.credential
        credential.name = "Apollo API key"
        credential.set_secret(form.cleaned_data["api_key"])
        credential.save()
        configuration.name = form.cleaned_data["name"]
        configuration.timeout_seconds = form.cleaned_data["timeout_seconds"]
        configuration.estimated_cost_per_page_cents = form.cleaned_data[
            "estimated_cost_per_page_cents"
        ]
        configuration.enabled = form.cleaned_data["enabled"]
        configuration.save()
    else:
        credential = CredentialReference(workspace=workspace, name="Apollo API key")
        credential.set_secret(form.cleaned_data["api_key"])
        credential.save()
        LeadSourceConfiguration.objects.create(
            workspace=workspace,
            source_key="apollo",
            name=form.cleaned_data["name"],
            credential=credential,
            timeout_seconds=form.cleaned_data["timeout_seconds"],
            estimated_cost_per_page_cents=form.cleaned_data["estimated_cost_per_page_cents"],
            enabled=form.cleaned_data["enabled"],
        )
    messages.success(request, "Apollo configuration saved and API key encrypted.")
    return redirect("command_center:provider-settings")


@require_POST
@workspace_permission("providers.manage")
def configure_google_places(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    form = GooglePlacesConfigurationForm(request.POST)
    if not form.is_valid():
        messages.error(
            request, "Google Places configuration is invalid or lacks storage permission."
        )
        return redirect("command_center:provider-settings")
    credential = CredentialReference(workspace=workspace, name="Google Places API key")
    credential.set_secret(form.cleaned_data["api_key"])
    credential.save()
    configuration, created = LeadSourceConfiguration.objects.get_or_create(
        workspace=workspace,
        source_key="google_places",
        defaults={"name": "Google Places Text Search", "credential": credential},
    )
    if not created:
        old_credential = configuration.credential
        configuration.credential = credential
        old_credential.delete()
    configuration.base_url = "https://places.googleapis.com/v1/places:searchText"
    configuration.timeout_seconds = form.cleaned_data["timeout_seconds"]
    configuration.estimated_cost_per_page_cents = form.cleaned_data["estimated_cost_per_page_cents"]
    configuration.enabled = form.cleaned_data["enabled"]
    configuration.config = {"storage_permitted": form.cleaned_data["storage_permitted"]}
    configuration.save()
    messages.success(request, "Google Places configuration saved; API key encrypted.")
    return redirect("command_center:provider-settings")


@require_POST
@workspace_permission("providers.manage")
def test_apollo_connection(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    adapter = get_lead_source_adapter("apollo", workspace=workspace)
    if adapter is None or not adapter.is_configured():
        messages.error(request, "Apollo is not configured and enabled for this workspace.")
        return redirect("command_center:provider-settings")

    try:
        results = adapter.search({"limit": 1})
    except Exception as exc:  # noqa: BLE001 - adapters expose sanitized provider errors
        messages.error(request, f"Apollo connection failed: {exc}")
    else:
        messages.success(
            request,
            f"Apollo connection passed ({len(results)} validation result(s) returned).",
        )
    return redirect("command_center:provider-settings")


@require_POST
@workspace_permission("providers.manage")
def create_endpoint(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    # Preserve an explicit 404 for identifiers outside the active workspace,
    # while the form provides friendly validation for ordinary bad input.
    if (
        request.POST.get("provider")
        and AIProvider.objects.filter(pk=request.POST["provider"]).exists()
    ):
        get_object_or_404(AIProvider, workspace=workspace, pk=request.POST["provider"])
    form = AIEndpointForm(request.POST, workspace=workspace)
    if form.is_valid():
        provider = form.cleaned_data["provider"]
        credential = form.cleaned_data["credential"]
        AIEndpoint.objects.create(
            workspace=workspace,
            provider=provider,
            credential=credential,
            name=form.cleaned_data["name"],
            base_url=form.cleaned_data["base_url"],
            timeout_seconds=form.cleaned_data["timeout_seconds"],
            privacy_class=form.cleaned_data["privacy_class"],
        )
        messages.success(request, "AI endpoint created.")
    else:
        messages.error(request, "Endpoint configuration is invalid.")
    return redirect("command_center:provider-settings")


@require_POST
@workspace_permission("providers.manage")
def create_model(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    form = AIModelForm(request.POST, workspace=workspace)
    if form.is_valid():
        endpoint = form.cleaned_data["endpoint"]
        ModelDefinition.objects.create(
            workspace=workspace,
            endpoint=endpoint,
            model_name=form.cleaned_data["model_name"],
            display_name=form.cleaned_data["display_name"],
            context_limit=form.cleaned_data["context_limit"],
            input_cost_per_million=form.cleaned_data["input_cost_per_million"],
            output_cost_per_million=form.cleaned_data["output_cost_per_million"],
        )
        messages.success(request, "Model definition created.")
    else:
        messages.error(request, "Model configuration is invalid.")
    return redirect("command_center:provider-settings")


@require_POST
@workspace_permission("providers.manage")
def test_provider_connection(request: HttpRequest, pk) -> HttpResponse:
    provider = get_object_or_404(AIProvider, workspace=get_request_workspace(request), pk=pk)
    result = check_provider(provider)
    if result.was_successful:
        messages.success(request, f"{provider.name} connection passed ({result.latency_ms} ms).")
    else:
        messages.error(
            request,
            f"{provider.name} connection failed: {result.sanitized_error or 'unavailable'}.",
        )
    return redirect("command_center:provider-settings")


@workspace_permission("prospects.access")
def run_monitor(request: HttpRequest) -> HttpResponse:
    return _render(request, "command_center/runs.html", _run_monitor_context(request))


def _run_monitor_context(request: HttpRequest) -> dict:
    runs = list(
        DiscoveryRun.objects.filter(workspace=get_request_workspace(request))
        .select_related("hunt_profile_version__profile", "initiated_by")
        .prefetch_related("provider_results__records", "hunt_profile_version__source_policies")[
            :100
        ]
    )
    now = timezone.now()
    provider_terminal = {
        ProviderResultStatus.SUCCEEDED,
        ProviderResultStatus.EMPTY,
        ProviderResultStatus.FAILED,
        ProviderResultStatus.PARTIAL,
        ProviderResultStatus.TIMED_OUT,
        ProviderResultStatus.CANCELED,
        ProviderResultStatus.BUDGET_BLOCKED,
    }
    run_terminal = {
        DiscoveryRunStatus.SUCCEEDED,
        DiscoveryRunStatus.FAILED,
        DiscoveryRunStatus.PARTIAL,
        DiscoveryRunStatus.CANCELED,
    }
    for run in runs:
        policies = {p.source_key: p for p in run.hunt_profile_version.source_policies.all()}
        providers = list(run.provider_results.all())
        run.providers_live = providers
        run.is_terminal_ui = run.status in run_terminal
        run.elapsed_seconds_ui = int(
            ((run.finished_at or now) - (run.started_at or run.created_at)).total_seconds()
        )
        run.phase_ui = (
            "complete"
            if run.is_terminal_ui
            else (
                "downstream processing"
                if providers and all(p.status in provider_terminal for p in providers)
                else "provider search"
            )
        )
        for provider in providers:
            policy = policies.get(provider.provider_key)
            provider.elapsed_seconds_ui = int(
                (
                    (provider.finished_at or now) - (provider.started_at or provider.created_at)
                ).total_seconds()
            )
            provider.deadline_ui = (
                provider.started_at + timedelta(seconds=policy.timeout_seconds)
                if provider.started_at and policy
                else None
            )
            provider.can_cancel_ui = provider.status in {
                ProviderResultStatus.QUEUED,
                ProviderResultStatus.RETRYING,
                ProviderResultStatus.RATE_LIMITED,
            }
    return {"runs": runs, "has_active_runs": any(not run.is_terminal_ui for run in runs)}


@workspace_permission("prospects.access")
def run_status_fragment(request: HttpRequest) -> HttpResponse:
    return _render(request, "command_center/_run_status.html", _run_monitor_context(request))


@require_POST
@workspace_permission("prospects.access")
def cancel_run(request: HttpRequest, pk) -> HttpResponse:
    run = get_object_or_404(DiscoveryRun, workspace=get_request_workspace(request), pk=pk)
    if run.status not in {
        DiscoveryRunStatus.SUCCEEDED,
        DiscoveryRunStatus.FAILED,
        DiscoveryRunStatus.PARTIAL,
        DiscoveryRunStatus.CANCELED,
    }:
        run.status = DiscoveryRunStatus.CANCELED
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at", "updated_at"])
        for provider in run.provider_results.exclude(
            status__in=[
                ProviderResultStatus.SUCCEEDED,
                ProviderResultStatus.EMPTY,
                ProviderResultStatus.FAILED,
                ProviderResultStatus.CANCELED,
            ]
        ):
            provider.status = ProviderResultStatus.CANCELED
            provider.finished_at = timezone.now()
            provider.save(update_fields=["status", "finished_at", "updated_at"])
        messages.success(request, "Discovery run canceled.")
    return redirect("command_center:runs")


@require_POST
@workspace_permission("prospects.access")
def cancel_source(request: HttpRequest, pk) -> HttpResponse:
    provider = get_object_or_404(
        ProviderResult, discovery_run__workspace=get_request_workspace(request), pk=pk
    )
    if provider.status in {
        ProviderResultStatus.QUEUED,
        ProviderResultStatus.RETRYING,
        ProviderResultStatus.RATE_LIMITED,
    }:
        provider.status = ProviderResultStatus.CANCELED
        provider.finished_at = timezone.now()
        provider.save(update_fields=["status", "finished_at", "updated_at"])
        messages.success(request, f"{provider.provider_key} execution canceled.")
    else:
        messages.info(request, "This source can only be canceled safely before active execution.")
    return redirect("command_center:runs")


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
def create_organization_manual(request: HttpRequest) -> HttpResponse:
    form = OrganizationCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        workspace = get_request_workspace(request)
        organization, created = create_organization(
            workspace,
            name=form.cleaned_data["name"],
            domain=form.cleaned_data["domain"],
        )
        if not created:
            messages.error(request, "An organization with that domain already exists.")
            return redirect("command_center:organization-detail", pk=organization.pk)
        for field_name, value in form.cleaned_data.items():
            if value not in (None, ""):
                create_manual_claim(
                    organization,
                    field_name=field_name,
                    value=value,
                    reliability="high",
                    note="Entered during manual organization creation.",
                    actor=request.user,
                )
        messages.success(request, f"{organization.name} created manually.")
        return redirect("command_center:organization-detail", pk=organization.pk)
    return _render(request, "command_center/organization_form.html", {"form": form})


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
            "claims": organization.source_claims.select_related("source_record").all(),
            "resolutions": organization.field_resolutions.select_related("selected_claim").all(),
            "source_records": SourceRecord.objects.filter(organization=organization).select_related(
                "provider_result"
            ),
            "manual_claim_form": ManualClaimForm(),
        },
    )


@require_POST
@workspace_permission("prospects.access")
def add_manual_claim(request: HttpRequest, pk) -> HttpResponse:
    organization = get_object_or_404(Organization, workspace=get_request_workspace(request), pk=pk)
    form = ManualClaimForm(request.POST)
    if form.is_valid():
        claim = create_manual_claim(organization, actor=request.user, **form.cleaned_data)
        messages.success(request, f"Manual {claim.field_name} claim added; original data retained.")
    else:
        messages.error(request, "The manual correction is invalid.")
    return redirect("command_center:organization-detail", pk=pk)


@require_POST
@workspace_permission("prospects.access")
def prefer_claim(request: HttpRequest, pk) -> HttpResponse:
    claim = get_object_or_404(
        OrganizationClaim,
        organization__workspace=get_request_workspace(request),
        pk=pk,
    )
    note = request.POST.get("note", "Selected manually by an operator.").strip()
    select_organization_claim(claim, actor=request.user, note=note)
    messages.success(request, f"Preferred {claim.field_name} value updated; alternatives retained.")
    return redirect("command_center:organization-detail", pk=claim.organization_id)


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
