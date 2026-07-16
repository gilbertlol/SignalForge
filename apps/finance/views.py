from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasWorkspacePermission
from apps.core.services import get_request_workspace
from apps.organizations.models import Organization

from . import models, serializers
from .services import (
    client_summary,
    evaluate_financial_alerts,
    monthly_recurring_revenue,
    post_invoice,
    post_payment,
    reverse_transaction,
    weighted_forecast,
)


class FinanceViewSet(viewsets.ModelViewSet):
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "financials.access"

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["workspace"] = get_request_workspace(self.request)
        return context

    def get_queryset(self):
        return self.queryset.filter(workspace=get_request_workspace(self.request))


def viewset_for(model, serializer):
    return type(
        f"{model.__name__}ViewSet",
        (FinanceViewSet,),
        {"queryset": model.objects.all(), "serializer_class": serializer},
    )


QuoteViewSet = viewset_for(models.Quote, serializers.QuoteSerializer)
ProposalViewSet = viewset_for(models.Proposal, serializers.ProposalSerializer)
ContractViewSet = viewset_for(models.Contract, serializers.ContractSerializer)
ExpenseViewSet = viewset_for(models.Expense, serializers.ExpenseSerializer)
CommissionRuleViewSet = viewset_for(models.CommissionRule, serializers.CommissionRuleSerializer)
CommissionViewSet = viewset_for(models.Commission, serializers.CommissionSerializer)
SubscriptionViewSet = viewset_for(models.Subscription, serializers.SubscriptionSerializer)
ClientBudgetViewSet = viewset_for(models.ClientBudget, serializers.ClientBudgetSerializer)
CostAllocationViewSet = viewset_for(models.CostAllocation, serializers.CostAllocationSerializer)
RevenueForecastViewSet = viewset_for(models.RevenueForecast, serializers.RevenueForecastSerializer)


class InvoiceViewSet(FinanceViewSet):
    queryset = models.Invoice.objects.all()
    serializer_class = serializers.InvoiceSerializer

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        try:
            entry = post_invoice(self.get_object(), actor=request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializers.FinancialTransactionSerializer(entry).data)


class PaymentViewSet(FinanceViewSet):
    queryset = models.Payment.objects.all()
    serializer_class = serializers.PaymentSerializer

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        try:
            entry = post_payment(self.get_object(), actor=request.user)
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializers.FinancialTransactionSerializer(entry).data)


class FinancialTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = serializers.FinancialTransactionSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "financials.access"

    def get_queryset(self):
        return models.FinancialTransaction.objects.filter(
            workspace=get_request_workspace(self.request)
        )

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        if not request.data.get("reason"):
            return Response({"detail": "reason is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            entry = reverse_transaction(
                self.get_object(), reason=request.data["reason"], actor=request.user
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(entry).data, status=status.HTTP_201_CREATED)


class FinanceSummaryViewSet(viewsets.ViewSet):
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "financials.access"

    def list(self, request):
        workspace = get_request_workspace(request)
        currency = request.query_params.get("currency", "USD").upper()
        clients = []
        for organization in Organization.objects.filter(workspace=workspace):
            summary = client_summary(organization, currency=currency)
            clients.append(
                {"organization_id": organization.pk, "name": organization.name, **summary.__dict__}
            )
        return Response(
            {
                "currency": currency,
                "mrr": monthly_recurring_revenue(workspace, currency=currency),
                "weighted_forecast": weighted_forecast(workspace, currency=currency),
                "clients": clients,
            }
        )

    @action(detail=False, methods=["post"])
    def evaluate_alerts(self, request):
        try:
            target = (
                Decimal(str(request.data["forecast_target"]))
                if request.data.get("forecast_target") is not None
                else None
            )
        except InvalidOperation:
            return Response(
                {"detail": "Invalid forecast target"}, status=status.HTTP_400_BAD_REQUEST
            )
        count = evaluate_financial_alerts(
            get_request_workspace(request),
            recipient=request.user,
            currency=request.data.get("currency", "USD").upper(),
            forecast_target=target,
        )
        return Response({"alerts_emitted": count})
