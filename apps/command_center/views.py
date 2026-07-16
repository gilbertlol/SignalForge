from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
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
from apps.discovery.analytics import build_source_scorecards
from apps.discovery.models import (
    DiscoveryRun,
    DiscoveryRunStatus,
    DiscoveryRunTrigger,
    EnrichmentRun,
    ProviderResult,
    ProviderResultStatus,
    SourceRecord,
    SourceRecordStatus,
)
from apps.discovery.research import TASK_TYPES
from apps.discovery.services import start_run
from apps.discovery.tasks import run_discovery_task
from apps.evidence.models import OrganizationClaim
from apps.evidence.services import create_manual_claim, select_organization_claim
from apps.finance.models import FinancialTransaction, Invoice, InvoiceStatus
from apps.finance.services import client_summary, monthly_recurring_revenue, weighted_forecast
from apps.hunting.models import HuntPreset, HuntProfile, HuntProfileStatus
from apps.hunting.services import activate_version, archive, create_version, pause
from apps.integrations.models import (
    AIEndpoint,
    AIProvider,
    CredentialReference,
    FallbackPolicy,
    LeadSourceConfiguration,
    ModelDefinition,
    ModelRoute,
    ModelRouteEntry,
)
from apps.integrations.registry import get_lead_source_adapter
from apps.integrations.services import (
    check_lead_source,
    check_provider,
    lead_source_availability,
)
from apps.notifications.models import Notification
from apps.notifications.services import NotificationPolicyError, acknowledge
from apps.opportunities.models import Opportunity, OpportunityStatus
from apps.organizations.models import Organization
from apps.organizations.services import create_organization
from apps.risk.models import (
    ControlRecommendation,
    FactType,
    ObservationSource,
    Override,
    RecommendationStatus,
    RiskCategory,
    RiskObservation,
    RiskProfile,
)
from apps.risk.services import calculate_risk, sync_finance_observations
from apps.tasks.models import AgentExecution, ApprovalRequest, ApprovalStatus, Operator, WorkItem

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
    ResearchRouteForm,
    SearXNGConfigurationForm,
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
        "agents": allowed("agents.manage"),
        "financials": allowed("financials.access"),
        "risk": allowed("risk.access"),
    }


@workspace_permission("agents.manage")
def crew(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    operators = Operator.objects.filter(workspace=workspace).order_by("name")
    active_statuses = ["assigned", "in_progress", "blocked"]
    operator_rows = [
        {
            "operator": operator,
            "workload": operator.assigned_work.filter(status__in=active_statuses).count(),
        }
        for operator in operators
    ]
    return _render(
        request,
        "command_center/crew.html",
        {
            "operator_rows": operator_rows,
            "work_items": WorkItem.objects.filter(workspace=workspace)
            .select_related("assignee")
            .order_by("status", "priority", "created_at")[:30],
            "approvals": ApprovalRequest.objects.filter(
                workspace=workspace, status=ApprovalStatus.PENDING
            )
            .select_related("execution__operator")
            .order_by("created_at")[:20],
            "executions": AgentExecution.objects.filter(workspace=workspace)
            .select_related("operator")
            .order_by("-created_at")[:12],
        },
    )


@login_required
def notification_center(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    notification_queryset = (
        Notification.objects.filter(
            Q(recipient=request.user) | Q(escalation_history__escalated_to=request.user),
            workspace=workspace,
        )
        .select_related("event__rule")
        .distinct()
    )
    return _render(
        request,
        "command_center/notifications.html",
        {
            "notifications": notification_queryset[:100],
            "unread_count": notification_queryset.filter(read_at__isnull=True).count(),
            "critical_count": notification_queryset.filter(
                priority="critical", acknowledged_at__isnull=True
            ).count(),
        },
    )


@workspace_permission("financials.access")
def finance_dashboard(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    currency = request.GET.get("currency", "USD").upper()
    summaries = [
        {"organization": organization, "summary": client_summary(organization, currency=currency)}
        for organization in Organization.objects.filter(workspace=workspace)
    ]
    return _render(
        request,
        "command_center/finance.html",
        {
            "currency": currency,
            "summaries": summaries,
            "mrr": monthly_recurring_revenue(workspace, currency=currency),
            "forecast": weighted_forecast(workspace, currency=currency),
            "overdue_count": Invoice.objects.filter(
                workspace=workspace, currency=currency, status=InvoiceStatus.OVERDUE
            ).count(),
            "transactions": FinancialTransaction.objects.filter(
                workspace=workspace, currency=currency
            ).select_related("organization")[:20],
        },
    )


@workspace_permission("risk.access")
def risk_portfolio(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    rows = []
    for profile in RiskProfile.objects.filter(workspace=workspace).select_related(
        "organization", "opportunity", "contract"
    ):
        snapshot = profile.snapshots.first()
        scores = [Decimal(value) for value in snapshot.category_scores.values()] if snapshot else []
        rows.append(
            {
                "profile": profile,
                "snapshot": snapshot,
                "peak_score": max(scores) if scores else None,
                "pending_controls": profile.recommendations.filter(
                    status=RecommendationStatus.PROPOSED
                ).count(),
            }
        )
    return _render(request, "command_center/risk_portfolio.html", {"rows": rows})


@require_POST
@workspace_permission("risk.access")
def create_risk_profile(request: HttpRequest, organization_pk) -> HttpResponse:
    workspace = get_request_workspace(request)
    organization = get_object_or_404(Organization, workspace=workspace, pk=organization_pk)
    profile, created = RiskProfile.objects.get_or_create(
        workspace=workspace,
        organization=organization,
        opportunity=None,
        contract=None,
    )
    if created:
        messages.success(request, "Organization risk profile created.")
    return redirect("command_center:risk-profile", pk=profile.pk)


@workspace_permission("risk.access")
def risk_profile_detail(request: HttpRequest, pk) -> HttpResponse:
    profile = get_object_or_404(
        RiskProfile.objects.select_related("organization", "opportunity", "contract"),
        workspace=get_request_workspace(request),
        pk=pk,
    )
    snapshot = profile.snapshots.first()
    component_rows = []
    if snapshot:
        component_rows = [
            {"key": key, "score": Decimal(component["score"]), "component": component}
            for key, component in snapshot.components.items()
        ]
    return _render(
        request,
        "command_center/risk_detail.html",
        {
            "profile": profile,
            "snapshot": snapshot,
            "component_rows": component_rows,
            "categories": RiskCategory.objects.filter(workspace=profile.workspace),
            "observations": profile.observations.select_related("category", "evidence")[:100],
            "recommendations": profile.recommendations.select_related("category", "snapshot"),
            "overrides": profile.overrides.select_related("category", "created_by")[:30],
        },
    )


@require_POST
@workspace_permission("risk.access")
def calculate_risk_view(request: HttpRequest, pk) -> HttpResponse:
    profile = get_object_or_404(RiskProfile, workspace=get_request_workspace(request), pk=pk)
    calculate_risk(profile, triggered_by="manual_ui")
    messages.success(request, "Risk recalculated from the current evidence.")
    return redirect("command_center:risk-profile", pk=pk)


@require_POST
@workspace_permission("risk.access")
def sync_risk_finance(request: HttpRequest, pk) -> HttpResponse:
    profile = get_object_or_404(RiskProfile, workspace=get_request_workspace(request), pk=pk)
    currency = request.POST.get("currency", "USD").upper()
    if len(currency) != 3 or not currency.isalpha():
        messages.error(request, "Use a three-letter currency code.")
    else:
        count = sync_finance_observations(profile, currency=currency)
        messages.success(request, f"Finance signals synchronized ({count} new).")
    return redirect("command_center:risk-profile", pk=pk)


@require_POST
@workspace_permission("risk.access")
def add_risk_observation(request: HttpRequest, pk) -> HttpResponse:
    workspace = get_request_workspace(request)
    profile = get_object_or_404(RiskProfile, workspace=workspace, pk=pk)
    category = get_object_or_404(RiskCategory, workspace=workspace, pk=request.POST.get("category"))
    try:
        severity = Decimal(request.POST.get("severity", "0"))
        probability = Decimal(request.POST.get("probability", "0"))
        impact = Decimal(request.POST.get("impact", "0"))
        confidence = Decimal(request.POST.get("confidence", "1"))
        RiskObservation.objects.create(
            workspace=workspace,
            profile=profile,
            category=category,
            source=ObservationSource.HUMAN,
            fact_type=FactType.OBSERVED,
            source_type="manual_risk_review",
            source_id=f"user:{request.user.pk}:{timezone.now().isoformat()}",
            explanation=request.POST.get("explanation", "").strip(),
            severity=severity,
            probability=probability,
            impact=impact,
            confidence=confidence,
            observed_at=timezone.now(),
            confirmed=True,
            created_by=request.user,
        )
    except (InvalidOperation, ValueError, ValidationError):
        messages.error(request, "The observation values are invalid.")
    else:
        messages.success(request, "Human observation added with traceable provenance.")
    return redirect("command_center:risk-profile", pk=pk)


@require_POST
@workspace_permission("risk.access")
def add_risk_override(request: HttpRequest, pk) -> HttpResponse:
    workspace = get_request_workspace(request)
    profile = get_object_or_404(RiskProfile, workspace=workspace, pk=pk)
    category = get_object_or_404(RiskCategory, workspace=workspace, pk=request.POST.get("category"))
    try:
        score = Decimal(request.POST.get("score", "0"))
        if score < 0 or score > 100:
            raise ValueError
    except (InvalidOperation, ValueError):
        messages.error(request, "Override score must be from 0 to 100.")
    else:
        Override.objects.create(
            workspace=workspace,
            profile=profile,
            category=category,
            score=score,
            reason=request.POST.get("reason", "").strip(),
            created_by=request.user,
            effective_at=timezone.now(),
        )
        messages.success(request, "Override appended; historical snapshots remain unchanged.")
    return redirect("command_center:risk-profile", pk=pk)


@require_POST
@workspace_permission("approvals.manage")
def decide_risk_control(request: HttpRequest, pk) -> HttpResponse:
    recommendation = get_object_or_404(
        ControlRecommendation,
        workspace=get_request_workspace(request),
        pk=pk,
    )
    decision = request.POST.get("decision")
    if decision not in [RecommendationStatus.ACCEPTED, RecommendationStatus.REJECTED]:
        messages.error(request, "Choose accept or reject.")
    else:
        recommendation.status = decision
        recommendation.save(update_fields=["status", "updated_at"])
        messages.success(request, f"Control {decision}.")
    return redirect("command_center:risk-profile", pk=recommendation.profile_id)


@require_POST
@login_required
def acknowledge_notification(request: HttpRequest, pk) -> HttpResponse:
    workspace = get_request_workspace(request)
    notification = get_object_or_404(
        Notification.objects.filter(
            Q(recipient=request.user) | Q(escalation_history__escalated_to=request.user)
        ).distinct(),
        workspace=workspace,
        pk=pk,
    )
    try:
        acknowledge(notification, user=cast(User, request.user))
    except NotificationPolicyError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Alert acknowledged.")
    return redirect("command_center:notification-center")


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
    workspace = get_request_workspace(request)
    source_availability = {
        key: lead_source_availability(workspace, key)
        for key in ("openstreetmap", "searxng", "apollo", "google_places")
    }
    presets = list(HuntPreset.objects.filter(is_active=True).order_by("name", "-version"))
    selected_preset = None
    initial = None
    if request.method == "GET" and request.GET.get("preset"):
        selected_preset = (
            HuntPreset.objects.filter(is_active=True, key=request.GET["preset"])
            .order_by("-version")
            .first()
        )
        if selected_preset:
            initial = {
                **selected_preset.configuration.get("form_initial", {}),
                "preset": str(selected_preset.pk),
                "name": selected_preset.name,
                "description": selected_preset.description,
            }
            for key in ("searxng", "apollo", "google_places"):
                if not source_availability[key].ready:
                    initial[f"use_{key}"] = False
            if not any(
                initial.get(f"use_{key}")
                for key in ("openstreetmap", "searxng", "apollo", "google_places")
            ):
                initial["manual_only"] = True
    form = HuntProfileForm(
        request.POST if request.method == "POST" else None,
        initial=initial,
        source_availability=source_availability,
    )
    form_valid = form.is_valid() if request.method == "POST" else False
    if request.method == "POST" and form.cleaned_data.get("preset"):
        selected_preset = HuntPreset.objects.filter(pk=form.cleaned_data["preset"]).first()
    for preset in presets:
        preset.source_statuses = []
        for guidance in preset.source_guidance:
            availability = lead_source_availability(workspace, guidance["source_key"])
            preset.source_statuses.append(
                {
                    **guidance,
                    "available": availability.ready,
                    "availability_reason": availability.reason,
                }
            )
    display_preset = next(
        (preset for preset in presets if selected_preset and preset.pk == selected_preset.pk),
        presets[0] if presets else None,
    )
    if request.method == "POST" and form_valid:
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
            applied_preset=selected_preset,
        )
        profile.current_version = version
        profile.save(update_fields=["current_version", "updated_at"])
        if form.cleaned_data["activate_now"]:
            activate_version(profile, version)
        messages.success(request, f"Hunt Profile “{profile.name}” created.")
        return redirect("command_center:hunt-profiles")
    return _render(
        request,
        "command_center/hunt_profile_form.html",
        {
            "form": form,
            "presets": presets,
            "selected_preset": selected_preset,
            "display_preset": display_preset,
            "searxng_availability": source_availability["searxng"],
            "apollo_availability": source_availability["apollo"],
            "google_places_availability": source_availability["google_places"],
        },
    )


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
    usable = [
        policy
        for policy in policies
        if policy.source_key not in {"searxng", "apollo", "google_places"}
        or lead_source_availability(profile.workspace, policy.source_key).ready
    ]
    if not usable:
        messages.error(
            request,
            "Discovery was not started because none of this profile’s sources are currently "
            "available. Enable an open source or validate a customer API key.",
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
    providers = list(
        AIProvider.objects.filter(workspace=workspace).prefetch_related(
            "endpoints__models", "health_checks"
        )
    )
    for provider in providers:
        provider.latest_health_ui = max(  # type: ignore[attr-defined]
            provider.health_checks.all(), key=lambda item: item.created_at, default=None
        )
        provider.is_live_validated_ui = bool(  # type: ignore[attr-defined]
            provider.latest_health_ui
            and provider.latest_health_ui.was_successful
            and provider.latest_health_ui.created_at >= timezone.now() - timedelta(hours=24)
        )
    lead_sources = list(LeadSourceConfiguration.objects.filter(workspace=workspace))
    apollo = next((source for source in lead_sources if source.source_key == "apollo"), None)
    google = next((source for source in lead_sources if source.source_key == "google_places"), None)
    searxng = next((source for source in lead_sources if source.source_key == "searxng"), None)
    apollo_availability = lead_source_availability(workspace, "apollo")
    google_availability = lead_source_availability(workspace, "google_places")
    searxng_availability = lead_source_availability(workspace, "searxng")
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
            "name": "SearXNG Web Search",
            "source_key": "searxng",
            "state": searxng_availability.reason,
            "cost": "Free self-hosted metasearch · upstream engines may impose limits",
            "limits": "Up to 50 results per hunt · bounded query and safe-search enabled",
            "capabilities": "Public web discovery with query, rank, URL and engine provenance",
            "attribution": "SearXNG and the upstream engine returned with each result",
            "attribution_url": "https://docs.searxng.org/",
            "ready": searxng_availability.ready,
            "configuration": searxng,
        },
        {
            "name": "Apollo Organization Search",
            "source_key": "apollo",
            "state": apollo_availability.reason,
            "cost": f"Estimated {apollo.estimated_cost_per_page_cents}¢ per returned page"
            if apollo
            else "Plan-dependent credit usage",
            "limits": (
                "Up to 100 records per hunt · availability depends on Apollo plan entitlements"
            ),
            "capabilities": "Organization filters, domains, industries and company metadata",
            "attribution": "Commercial provider data · subject to your Apollo plan and terms",
            "ready": apollo_availability.ready,
            "configuration": apollo,
        },
        {
            "name": "Google Places",
            "source_key": "google_places",
            "state": google_availability.reason,
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
            "ready": google_availability.ready,
            "configuration": google,
        },
    ]
    research_routes = {
        route.task_type: route
        for route in ModelRoute.objects.filter(
            workspace=workspace, task_type__in=TASK_TYPES, is_default=True, enabled=True
        ).prefetch_related("entries__model__endpoint__provider")
    }
    return _render(
        request,
        "command_center/provider_settings.html",
        {
            "providers": providers,
            "source_catalog": source_catalog,
            "apollo_form": ApolloConfigurationForm(),
            "google_places_form": GooglePlacesConfigurationForm(),
            "searxng_form": SearXNGConfigurationForm(
                initial={
                    "base_url": searxng.base_url if searxng else "http://searxng:8080",
                    "language": searxng.config.get("language", "auto") if searxng else "auto",
                    "timeout_seconds": searxng.timeout_seconds if searxng else 20,
                    "enabled": searxng.enabled if searxng else True,
                }
            ),
            "credentials": CredentialReference.objects.filter(workspace=workspace),
            "provider_form": AIProviderForm(),
            "credential_form": CredentialForm(),
            "endpoint_form": AIEndpointForm(workspace=workspace),
            "model_form": AIModelForm(workspace=workspace),
            "research_route_form": ResearchRouteForm(workspace=workspace),
            "research_task_routes": [
                {"task_type": task_type, "route": research_routes.get(task_type)}
                for task_type in TASK_TYPES
            ],
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
        configuration.health_checks.all().delete()
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
        if old_credential:
            old_credential.delete()
        configuration.health_checks.all().delete()
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
def configure_searxng(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    form = SearXNGConfigurationForm(request.POST)
    if not form.is_valid():
        messages.error(request, "SearXNG configuration is invalid.")
        return redirect("command_center:provider-settings")
    configuration, _ = LeadSourceConfiguration.objects.get_or_create(
        workspace=workspace,
        source_key="searxng",
        defaults={"name": "SearXNG Web Search"},
    )
    access_token = form.cleaned_data["access_token"]
    if access_token:
        credential = configuration.credential or CredentialReference(
            workspace=workspace, name="SearXNG access token"
        )
        credential.set_secret(access_token)
        credential.save()
        configuration.credential = credential
    configuration.base_url = form.cleaned_data["base_url"]
    configuration.timeout_seconds = form.cleaned_data["timeout_seconds"]
    configuration.estimated_cost_per_page_cents = 0
    configuration.enabled = form.cleaned_data["enabled"]
    configuration.config = {"language": form.cleaned_data["language"]}
    configuration.save()
    configuration.health_checks.all().delete()
    messages.success(request, "SearXNG configuration saved. Run live validation to enable it.")
    return redirect("command_center:provider-settings")


@require_POST
@workspace_permission("providers.manage")
def test_lead_source_connection(request: HttpRequest, source_key: str) -> HttpResponse:
    workspace = get_request_workspace(request)
    configuration = LeadSourceConfiguration.objects.filter(
        workspace=workspace, source_key=source_key, enabled=True
    ).first()
    display_names = {
        "apollo": "Apollo",
        "google_places": "Google Places",
        "searxng": "SearXNG",
    }
    display_name = display_names.get(source_key, source_key)
    if configuration is None:
        messages.error(request, f"{display_name} is not configured and enabled.")
        return redirect("command_center:provider-settings")
    result = check_lead_source(configuration)
    if result.was_successful:
        messages.success(request, f"{display_name} connection passed and is selectable.")
    else:
        messages.error(
            request,
            f"{display_name} validation failed: {result.get_status_display()}.",
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
def configure_research_route(request: HttpRequest) -> HttpResponse:
    workspace = get_request_workspace(request)
    form = ResearchRouteForm(request.POST, workspace=workspace)
    if not form.is_valid():
        messages.error(request, "Research route configuration is invalid.")
        return redirect("command_center:provider-settings")
    task_type = form.cleaned_data["task_type"]
    ModelRoute.objects.filter(workspace=workspace, task_type=task_type, is_default=True).update(
        is_default=False
    )
    fallback, _ = FallbackPolicy.objects.get_or_create(
        workspace=workspace,
        name="Local-first research",
        defaults={"strategy": "ordered", "max_attempts": 3},
    )
    route, _ = ModelRoute.objects.update_or_create(
        workspace=workspace,
        task_type=task_type,
        name=f"Default {task_type.replace('_', ' ')}",
        defaults={
            "fallback_policy": fallback,
            "required_privacy_class": form.cleaned_data["required_privacy_class"],
            "is_default": True,
            "enabled": True,
        },
    )
    route.entries.all().delete()
    ModelRouteEntry.objects.create(route=route, model=form.cleaned_data["model"], position=1)
    messages.success(request, f"Default {task_type.replace('_', ' ')} route saved.")
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
        ProviderResultStatus.SKIPPED,
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
        run.source_analytics = build_source_scorecards(DiscoveryRun.objects.filter(pk=run.pk))
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
            "ai_suggestions": EnrichmentRun.objects.filter(
                source_record__organization=organization,
                provider_key="ai_research",
                status="succeeded",
            ).select_related("source_record"),
            "manual_claim_form": ManualClaimForm(),
            "risk_profiles": organization.risk_profiles.filter(active=True),
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
