"""Aggregates ViewSets from each app into one router.

This is the one place allowed to import from multiple domain apps at once —
apps themselves don't import each other's viewsets, keeping the modular
monolith's dependency graph one-directional (domain apps -> nothing;
this router -> domain apps).
"""

from rest_framework.routers import DefaultRouter

from apps.accounts.views import APIKeyViewSet, MembershipViewSet, SessionViewSet
from apps.communications.views import ChannelAccountViewSet, ConversationViewSet, MessageViewSet
from apps.contacts.views import ContactViewSet
from apps.discovery.views import DiscoveryRunViewSet
from apps.finance.views import (
    ClientBudgetViewSet,
    CommissionRuleViewSet,
    CommissionViewSet,
    ContractViewSet,
    CostAllocationViewSet,
    ExpenseViewSet,
    FinanceSummaryViewSet,
    FinancialTransactionViewSet,
    InvoiceViewSet,
    PaymentViewSet,
    ProposalViewSet,
    QuoteViewSet,
    RevenueForecastViewSet,
    SubscriptionViewSet,
)
from apps.hunting.views import HuntProfileViewSet
from apps.integrations.views import (
    AIEndpointViewSet,
    AIProviderViewSet,
    CredentialReferenceViewSet,
    ModelDefinitionViewSet,
    ModelInvocationViewSet,
    ModelRouteViewSet,
)
from apps.notifications.views import (
    AlertEventViewSet,
    AlertRuleViewSet,
    DashboardViewSet,
    DashboardWidgetViewSet,
    DeliveryAttemptViewSet,
    NotificationEscalationPolicyViewSet,
    NotificationViewSet,
    QuietHoursViewSet,
    SavedFilterViewSet,
    UserPreferenceViewSet,
)
from apps.opportunities.views import OpportunityViewSet
from apps.organizations.views import OrganizationViewSet
from apps.scoring.views import ScoreSnapshotViewSet
from apps.tasks.views import (
    AgentExecutionViewSet,
    AgentProfileViewSet,
    AgentVersionViewSet,
    ApprovalRequestViewSet,
    AssignmentPoolViewSet,
    BudgetPolicyViewSet,
    DataScopeViewSet,
    OperatorViewSet,
    PerformanceMetricViewSet,
    TeamViewSet,
    ToolPermissionViewSet,
    WorkItemViewSet,
)

router = DefaultRouter()
router.register("memberships", MembershipViewSet, basename="membership")
router.register("channel-accounts", ChannelAccountViewSet, basename="channel-account")
router.register("conversations", ConversationViewSet, basename="conversation")
router.register("messages", MessageViewSet, basename="message")
router.register("api-keys", APIKeyViewSet, basename="api-key")
router.register("sessions", SessionViewSet, basename="session")
router.register("ai/providers", AIProviderViewSet, basename="ai-provider")
router.register("ai/credentials", CredentialReferenceViewSet, basename="ai-credential")
router.register("ai/endpoints", AIEndpointViewSet, basename="ai-endpoint")
router.register("ai/models", ModelDefinitionViewSet, basename="ai-model")
router.register("ai/routes", ModelRouteViewSet, basename="ai-route")
router.register("ai/invocations", ModelInvocationViewSet, basename="ai-invocation")
router.register("organizations", OrganizationViewSet, basename="organization")
router.register("contacts", ContactViewSet, basename="contact")
router.register("opportunities", OpportunityViewSet, basename="opportunity")
router.register("scores", ScoreSnapshotViewSet, basename="scoresnapshot")
router.register("hunt-profiles", HuntProfileViewSet, basename="huntprofile")
router.register("discovery-runs", DiscoveryRunViewSet, basename="discoveryrun")
router.register("finance/quotes", QuoteViewSet, basename="finance-quote")
router.register("finance/proposals", ProposalViewSet, basename="finance-proposal")
router.register("finance/contracts", ContractViewSet, basename="finance-contract")
router.register("finance/invoices", InvoiceViewSet, basename="finance-invoice")
router.register("finance/payments", PaymentViewSet, basename="finance-payment")
router.register("finance/expenses", ExpenseViewSet, basename="finance-expense")
router.register(
    "finance/commission-rules", CommissionRuleViewSet, basename="finance-commission-rule"
)
router.register("finance/commissions", CommissionViewSet, basename="finance-commission")
router.register("finance/subscriptions", SubscriptionViewSet, basename="finance-subscription")
router.register("finance/budgets", ClientBudgetViewSet, basename="finance-budget")
router.register(
    "finance/cost-allocations", CostAllocationViewSet, basename="finance-cost-allocation"
)
router.register("finance/forecasts", RevenueForecastViewSet, basename="finance-forecast")
router.register("finance/transactions", FinancialTransactionViewSet, basename="finance-transaction")
router.register("finance/summary", FinanceSummaryViewSet, basename="finance-summary")
router.register("dashboards", DashboardViewSet, basename="dashboard")
router.register("dashboard-widgets", DashboardWidgetViewSet, basename="dashboard-widget")
router.register("saved-filters", SavedFilterViewSet, basename="saved-filter")
router.register("alert-rules", AlertRuleViewSet, basename="alert-rule")
router.register("alert-events", AlertEventViewSet, basename="alert-event")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("notification-deliveries", DeliveryAttemptViewSet, basename="notification-delivery")
router.register(
    "notification-preferences", UserPreferenceViewSet, basename="notification-preference"
)
router.register("quiet-hours", QuietHoursViewSet, basename="quiet-hours")
router.register(
    "notification-escalations",
    NotificationEscalationPolicyViewSet,
    basename="notification-escalation",
)
router.register("operators", OperatorViewSet, basename="operator")
router.register("operator-teams", TeamViewSet, basename="operator-team")
router.register("assignment-pools", AssignmentPoolViewSet, basename="assignment-pool")
router.register("work-items", WorkItemViewSet, basename="work-item")
router.register("agent-profiles", AgentProfileViewSet, basename="agent-profile")
router.register("agent-versions", AgentVersionViewSet, basename="agent-version")
router.register("agent-tool-permissions", ToolPermissionViewSet, basename="agent-tool-permission")
router.register("agent-data-scopes", DataScopeViewSet, basename="agent-data-scope")
router.register("agent-budgets", BudgetPolicyViewSet, basename="agent-budget")
router.register("agent-executions", AgentExecutionViewSet, basename="agent-execution")
router.register("agent-approvals", ApprovalRequestViewSet, basename="agent-approval")
router.register("operator-metrics", PerformanceMetricViewSet, basename="operator-metric")

urlpatterns = router.urls
