from rest_framework import serializers

from .models import (
    ClientBudget,
    Commission,
    CommissionRule,
    Contract,
    CostAllocation,
    Expense,
    FinancialTransaction,
    Invoice,
    Payment,
    Proposal,
    Quote,
    RevenueForecast,
    Subscription,
)


class WorkspaceSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        workspace = self.context["workspace"]
        for value in attrs.values():
            if hasattr(value, "workspace_id") and value.workspace_id != workspace.pk:
                raise serializers.ValidationError("Related records must use this workspace.")
        return attrs

    def validate_currency(self, value):
        value = value.upper()
        if len(value) != 3 or not value.isalpha():
            raise serializers.ValidationError("Use a three-letter ISO currency code.")
        return value

    def create(self, validated_data):
        validated_data["workspace"] = self.context["workspace"]
        return super().create(validated_data)


def serializer_for(model):
    meta = type(
        "Meta", (), {"model": model, "fields": "__all__", "read_only_fields": ["workspace"]}
    )
    return type(f"{model.__name__}Serializer", (WorkspaceSerializer,), {"Meta": meta})


QuoteSerializer = serializer_for(Quote)
ProposalSerializer = serializer_for(Proposal)
ContractSerializer = serializer_for(Contract)
InvoiceSerializer = serializer_for(Invoice)
PaymentSerializer = serializer_for(Payment)
ExpenseSerializer = serializer_for(Expense)
CommissionRuleSerializer = serializer_for(CommissionRule)
CommissionSerializer = serializer_for(Commission)
SubscriptionSerializer = serializer_for(Subscription)
ClientBudgetSerializer = serializer_for(ClientBudget)
CostAllocationSerializer = serializer_for(CostAllocation)
RevenueForecastSerializer = serializer_for(RevenueForecast)


class FinancialTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancialTransaction
        fields = "__all__"
