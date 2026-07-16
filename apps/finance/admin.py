from django.contrib import admin

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

admin.site.register(
    [
        Quote,
        Proposal,
        Contract,
        Invoice,
        Payment,
        Expense,
        CommissionRule,
        Commission,
        Subscription,
        ClientBudget,
        CostAllocation,
        RevenueForecast,
        FinancialTransaction,
    ]
)
