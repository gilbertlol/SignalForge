from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.tests.factories import UserFactory
from apps.finance.models import (
    BillingFrequency,
    CommissionRule,
    Expense,
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentKind,
    RevenueForecast,
    Subscription,
    TransactionType,
)
from apps.finance.services import (
    allocate_cost,
    calculate_commission,
    client_summary,
    evaluate_financial_alerts,
    invoice_receivable,
    money,
    monthly_recurring_revenue,
    post_invoice,
    post_payment,
    reverse_transaction,
    weighted_forecast,
)
from apps.organizations.tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


def invoice_for(organization, **overrides):
    values = {
        "workspace": organization.workspace,
        "organization": organization,
        "number": "INV-001",
        "subtotal": Decimal("100.00"),
        "tax_amount": Decimal("15.00"),
        "currency": "CAD",
    }
    values.update(overrides)
    return Invoice.objects.create(**values)


def test_money_rounding_is_decimal_and_deterministic():
    assert money(Decimal("10.55555")) == Decimal("10.5556")
    assert money(Decimal("10.55554")) == Decimal("10.5555")


def test_partial_payment_and_refund_update_receivable():
    organization = OrganizationFactory()
    invoice = invoice_for(organization)
    post_invoice(invoice)
    payment = Payment.objects.create(
        workspace=organization.workspace,
        organization=organization,
        invoice=invoice,
        amount=Decimal("60"),
        currency="CAD",
    )
    post_payment(payment)
    invoice.refresh_from_db()

    assert invoice.status == InvoiceStatus.PARTIALLY_PAID
    assert invoice_receivable(invoice) == Decimal("55.0000")

    refund = Payment.objects.create(
        workspace=organization.workspace,
        organization=organization,
        invoice=invoice,
        kind=PaymentKind.REFUND,
        amount=Decimal("10"),
        currency="CAD",
    )
    post_payment(refund)
    assert invoice_receivable(invoice) == Decimal("65.0000")


def test_financial_ledger_is_immutable_and_reversible():
    organization = OrganizationFactory()
    invoice = invoice_for(organization)
    entry = post_invoice(invoice)

    entry.amount = Decimal("1")
    with pytest.raises(ValidationError, match="immutable"):
        entry.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        entry.delete()

    reversal = reverse_transaction(entry, reason="Invoice voided")
    assert reversal.amount == -Decimal("115.0000")
    assert reversal.transaction_type == TransactionType.REVERSAL
    assert reversal.reverses == entry
    with pytest.raises(ValidationError, match="already been reversed"):
        reverse_transaction(entry, reason="Again")


def test_commission_is_reproducible_from_basis_and_decimal_rate():
    beneficiary = UserFactory()
    workspace = beneficiary.memberships.get().workspace
    organization = OrganizationFactory(workspace=workspace)
    rule = CommissionRule.objects.create(
        workspace=workspace,
        name="Closer 7.5%",
        basis="collected_revenue",
        rate_percent=Decimal("7.5"),
    )

    commission = calculate_commission(
        rule=rule,
        beneficiary=beneficiary,
        organization=organization,
        basis_amount=Decimal("1234.56"),
    )

    assert commission.amount == Decimal("92.5920")
    assert commission.basis_amount == Decimal("1234.5600")


def test_cost_allocations_cannot_exceed_actual_expense():
    organization = OrganizationFactory()
    expense = Expense.objects.create(
        workspace=organization.workspace,
        description="Shared infrastructure",
        category="infrastructure",
        estimated_amount=Decimal("100"),
        actual_amount=Decimal("80"),
        incurred_on=date.today(),
        currency="CAD",
    )

    allocation = allocate_cost(expense, organization, Decimal("50"))
    assert allocation.currency == "CAD"
    with pytest.raises(ValidationError, match="cannot exceed"):
        allocate_cost(expense, organization, Decimal("31"))


def test_mrr_normalizes_recurring_frequencies():
    organization = OrganizationFactory()
    for name, amount, frequency in [
        ("Monthly", "100", BillingFrequency.MONTHLY),
        ("Quarterly", "300", BillingFrequency.QUARTERLY),
        ("Annual", "1200", BillingFrequency.ANNUAL),
    ]:
        Subscription.objects.create(
            workspace=organization.workspace,
            organization=organization,
            name=name,
            amount=Decimal(amount),
            frequency=frequency,
            starts_on=date.today(),
            currency="CAD",
        )

    assert monthly_recurring_revenue(organization.workspace, currency="CAD") == Decimal("300.0000")


def test_weighted_forecast_is_explainable():
    organization = OrganizationFactory()
    RevenueForecast.objects.create(
        workspace=organization.workspace,
        organization=organization,
        name="Likely renewal",
        category="renewal",
        period_start=date.today(),
        period_end=date.today(),
        amount=Decimal("1000"),
        probability_percent=Decimal("75"),
        currency="CAD",
        assumptions={"reason": "verbal confirmation"},
    )

    assert weighted_forecast(
        organization.workspace, currency="CAD", organization=organization
    ) == Decimal("750.0000")


def test_client_summary_flags_negative_contribution_profit():
    organization = OrganizationFactory()
    invoice = invoice_for(organization, subtotal=Decimal("50"), tax_amount=Decimal("0"))
    post_invoice(invoice)
    payment = Payment.objects.create(
        workspace=organization.workspace,
        organization=organization,
        invoice=invoice,
        amount=Decimal("50"),
        currency="CAD",
    )
    post_payment(payment)
    Expense.objects.create(
        workspace=organization.workspace,
        organization=organization,
        description="Delivery labor",
        category="human_labor",
        actual_amount=Decimal("80"),
        incurred_on=date.today(),
        currency="CAD",
    )

    summary = client_summary(organization, currency="CAD")

    assert summary.collected == Decimal("50.0000")
    assert summary.contribution_profit == Decimal("-30.0000")
    assert summary.contribution_margin_percent == Decimal("-60.0000")

    user = UserFactory(workspace_membership=organization.workspace)
    assert (
        evaluate_financial_alerts(
            organization.workspace,
            recipient=user,
            currency="CAD",
            forecast_target=Decimal("1000"),
        )
        == 2
    )
    assert user.notifications.filter(priority="critical").exists()
