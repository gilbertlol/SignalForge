from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.models import AlertRule, DeliveryChannel, NotificationPriority
from apps.notifications.services import emit_alert
from apps.organizations.models import Organization

from .models import (
    BillingFrequency,
    Commission,
    CommissionRule,
    CommissionStatus,
    CostAllocation,
    Expense,
    FinancialTransaction,
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentKind,
    PaymentStatus,
    RevenueForecast,
    Subscription,
    SubscriptionStatus,
    TransactionType,
)

ZERO = Decimal("0.0000")
HUNDRED = Decimal("100")


def money(value: Decimal | str | int) -> Decimal:
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def invoice_total(invoice: Invoice) -> Decimal:
    return money(invoice.subtotal + invoice.tax_amount - invoice.credit_amount)


def invoice_collected(invoice: Invoice) -> Decimal:
    payments = invoice.payment_set.filter(status=PaymentStatus.SUCCEEDED)
    paid = payments.filter(kind=PaymentKind.PAYMENT).aggregate(total=Sum("amount"))["total"] or ZERO
    returned = (
        payments.filter(kind__in=[PaymentKind.REFUND, PaymentKind.CHARGEBACK]).aggregate(
            total=Sum("amount")
        )["total"]
        or ZERO
    )
    return money(paid - returned)


def invoice_receivable(invoice: Invoice) -> Decimal:
    return max(ZERO, money(invoice_total(invoice) - invoice_collected(invoice)))


def record_transaction(
    *,
    workspace,
    organization: Organization | None,
    transaction_type: str,
    amount: Decimal,
    currency: str,
    source,
    description: str,
    actor: User | None = None,
    reverses: FinancialTransaction | None = None,
    metadata: dict | None = None,
) -> FinancialTransaction:
    return FinancialTransaction.objects.create(
        workspace=workspace,
        organization=organization,
        transaction_type=transaction_type,
        amount=money(amount),
        currency=currency,
        occurred_at=timezone.now(),
        description=description,
        source_type=source._meta.label,
        source_id=str(source.pk),
        created_by=actor,
        reverses=reverses,
        metadata=metadata or {},
    )


@transaction.atomic
def post_invoice(invoice: Invoice, *, actor: User | None = None) -> FinancialTransaction:
    if invoice.status not in [InvoiceStatus.DRAFT, InvoiceStatus.ISSUED]:
        raise ValidationError("Only draft or issued invoices can be posted.")
    invoice.status = InvoiceStatus.ISSUED
    invoice.issued_on = invoice.issued_on or timezone.localdate()
    invoice.save(update_fields=["status", "issued_on", "updated_at"])
    return record_transaction(
        workspace=invoice.workspace,
        organization=invoice.organization,
        transaction_type=TransactionType.INVOICE,
        amount=invoice_total(invoice),
        currency=invoice.currency,
        source=invoice,
        description=f"Invoice {invoice.number} issued",
        actor=actor,
    )


@transaction.atomic
def post_payment(payment: Payment, *, actor: User | None = None) -> FinancialTransaction:
    if payment.amount <= 0:
        raise ValidationError("Payment amounts must be positive.")
    if payment.invoice and payment.invoice.currency != payment.currency:
        raise ValidationError("Payment currency must match the invoice.")
    if payment.invoice and payment.invoice.organization_id != payment.organization_id:
        raise ValidationError("Payment and invoice must use the same organization.")
    payment.status = PaymentStatus.SUCCEEDED
    payment.paid_at = payment.paid_at or timezone.now()
    payment.save(update_fields=["status", "paid_at", "updated_at"])
    transaction_type = (
        TransactionType.PAYMENT if payment.kind == PaymentKind.PAYMENT else TransactionType.REFUND
    )
    entry = record_transaction(
        workspace=payment.workspace,
        organization=payment.organization,
        transaction_type=transaction_type,
        amount=payment.amount if payment.kind == PaymentKind.PAYMENT else -payment.amount,
        currency=payment.currency,
        source=payment,
        description=f"{payment.get_kind_display()} posted",
        actor=actor,
    )
    if payment.invoice:
        collected = invoice_collected(payment.invoice)
        total = invoice_total(payment.invoice)
        if collected >= total:
            status = InvoiceStatus.PAID
        elif collected > ZERO:
            status = InvoiceStatus.PARTIALLY_PAID
        else:
            status = InvoiceStatus.ISSUED
        payment.invoice.status = status
        payment.invoice.save(update_fields=["status", "updated_at"])
    return entry


def reverse_transaction(
    transaction_entry: FinancialTransaction,
    *,
    reason: str,
    actor: User | None = None,
) -> FinancialTransaction:
    persisted = FinancialTransaction.all_objects.get(pk=transaction_entry.pk)
    if persisted.reversed_by.exists():
        raise ValidationError("This transaction has already been reversed.")
    return record_transaction(
        workspace=persisted.workspace,
        organization=persisted.organization,
        transaction_type=TransactionType.REVERSAL,
        amount=-persisted.amount,
        currency=persisted.currency,
        source=persisted,
        description=reason,
        actor=actor,
        reverses=persisted,
    )


def allocate_cost(
    expense: Expense, organization: Organization, amount: Decimal, *, rationale: str = ""
) -> CostAllocation:
    if organization.workspace_id != expense.workspace_id:
        raise ValidationError("Expense and organization must use the same workspace.")
    allocated = expense.allocations.aggregate(total=Sum("amount"))["total"] or ZERO
    amount = money(amount)
    if amount <= 0 or allocated + amount > expense.actual_amount:
        raise ValidationError("Allocations must be positive and cannot exceed actual cost.")
    return CostAllocation.objects.create(
        workspace=expense.workspace,
        expense=expense,
        organization=organization,
        amount=amount,
        currency=expense.currency,
        rationale=rationale,
    )


def calculate_commission(
    *,
    rule: CommissionRule,
    beneficiary: User,
    organization: Organization,
    basis_amount: Decimal,
    payment: Payment | None = None,
) -> Commission:
    if not rule.active:
        raise ValidationError("Commission rule is inactive.")
    if not beneficiary.memberships.filter(workspace=rule.workspace, is_active=True).exists():
        raise ValidationError("Beneficiary is not a workspace member.")
    basis_amount = money(basis_amount)
    amount = money(basis_amount * rule.rate_percent / HUNDRED)
    return Commission.objects.create(
        workspace=rule.workspace,
        rule=rule,
        beneficiary=beneficiary,
        organization=organization,
        payment=payment,
        basis_amount=basis_amount,
        amount=amount,
        currency=payment.currency if payment else "USD",
        status=CommissionStatus.EARNED,
    )


def monthly_recurring_revenue(workspace, *, currency: str) -> Decimal:
    total = ZERO
    divisors = {
        BillingFrequency.MONTHLY: Decimal(1),
        BillingFrequency.QUARTERLY: Decimal(3),
        BillingFrequency.ANNUAL: Decimal(12),
    }
    subscriptions = Subscription.objects.filter(
        workspace=workspace,
        currency=currency,
        status=SubscriptionStatus.ACTIVE,
        frequency__in=divisors,
    )
    for subscription in subscriptions:
        total += subscription.amount / divisors[subscription.frequency]
    return money(total)


def weighted_forecast(workspace, *, currency: str, organization=None) -> Decimal:
    forecasts = RevenueForecast.objects.filter(workspace=workspace, currency=currency)
    if organization is not None:
        forecasts = forecasts.filter(organization=organization)
    return money(
        sum(
            (item.amount * item.probability_percent / HUNDRED for item in forecasts),
            start=ZERO,
        )
    )


@dataclass(frozen=True)
class ClientFinancialSummary:
    currency: str
    invoiced: Decimal
    collected: Decimal
    receivables: Decimal
    actual_costs: Decimal
    contribution_profit: Decimal
    contribution_margin_percent: Decimal
    mrr: Decimal
    lifetime_value: Decimal
    acquisition_cost: Decimal


def client_summary(organization: Organization, *, currency: str) -> ClientFinancialSummary:
    invoices = Invoice.objects.filter(organization=organization, currency=currency).exclude(
        status__in=[InvoiceStatus.DRAFT, InvoiceStatus.VOID]
    )
    invoiced = money(sum((invoice_total(item) for item in invoices), start=ZERO))
    collected = money(sum((invoice_collected(item) for item in invoices), start=ZERO))
    costs = (
        Expense.objects.filter(
            workspace=organization.workspace, organization=organization, currency=currency
        ).aggregate(total=Sum("actual_amount"))["total"]
        or ZERO
    )
    allocations = (
        CostAllocation.objects.filter(
            workspace=organization.workspace, organization=organization, currency=currency
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    actual_costs = money(costs + allocations)
    profit = money(collected - actual_costs)
    margin = money(profit / collected * HUNDRED) if collected else ZERO
    acquisition_cost = (
        Expense.objects.filter(
            workspace=organization.workspace,
            organization=organization,
            currency=currency,
            category__in=["human_labor", "contractor", "enrichment", "messaging"],
        ).aggregate(total=Sum("actual_amount"))["total"]
        or ZERO
    )
    return ClientFinancialSummary(
        currency=currency,
        invoiced=invoiced,
        collected=collected,
        receivables=money(invoiced - collected),
        actual_costs=actual_costs,
        contribution_profit=profit,
        contribution_margin_percent=margin,
        mrr=monthly_recurring_revenue(organization.workspace, currency=currency),
        lifetime_value=collected,
        acquisition_cost=money(acquisition_cost),
    )


FINANCE_ALERTS = {
    "finance.invoice_overdue": ("Overdue invoice", NotificationPriority.HIGH),
    "finance.payment_failed": ("Failed payment", NotificationPriority.HIGH),
    "finance.margin_negative": ("Negative client margin", NotificationPriority.CRITICAL),
    "finance.cost_growth": ("Abnormal cost growth", NotificationPriority.HIGH),
    "finance.forecast_shortfall": ("Forecast shortfall", NotificationPriority.MEDIUM),
}


def _finance_rule(workspace, event_type: str) -> AlertRule:
    name, priority = FINANCE_ALERTS[event_type]
    return AlertRule.objects.get_or_create(
        workspace=workspace,
        event_type=event_type,
        defaults={
            "name": name,
            "priority": priority,
            "channels": [DeliveryChannel.IN_APP],
            "deduplication_window_minutes": 24 * 60,
        },
    )[0]


def evaluate_financial_alerts(
    workspace,
    *,
    recipient: User,
    currency: str,
    forecast_target: Decimal | None = None,
) -> int:
    emitted = 0
    today = timezone.localdate()
    overdue = Invoice.objects.filter(
        workspace=workspace,
        currency=currency,
        due_on__lt=today,
        status__in=[InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID],
    ).select_related("organization")
    for invoice in overdue:
        invoice.status = InvoiceStatus.OVERDUE
        invoice.save(update_fields=["status", "updated_at"])
        notification = emit_alert(
            rule=_finance_rule(workspace, "finance.invoice_overdue"),
            recipient=recipient,
            payload={"invoice": invoice.number},
            title=f"Invoice {invoice.number} is overdue",
            body=f"{invoice.organization.name} owes {invoice_receivable(invoice)} {currency}.",
            resource_type="invoice",
            resource_id=str(invoice.pk),
            deduplication_key=f"overdue:{invoice.pk}",
        )
        emitted += notification is not None

    failed = Payment.objects.filter(
        workspace=workspace, currency=currency, status=PaymentStatus.FAILED
    ).select_related("organization")
    for payment in failed:
        notification = emit_alert(
            rule=_finance_rule(workspace, "finance.payment_failed"),
            recipient=recipient,
            payload={"payment": str(payment.pk)},
            title=f"Payment failed for {payment.organization.name}",
            body=payment.failure_reason or "The payment provider did not provide a reason.",
            resource_type="payment",
            resource_id=str(payment.pk),
            deduplication_key=f"failed-payment:{payment.pk}",
        )
        emitted += notification is not None

    current_costs = (
        Expense.objects.filter(
            workspace=workspace,
            currency=currency,
            incurred_on__gte=today - timedelta(days=30),
        ).aggregate(total=Sum("actual_amount"))["total"]
        or ZERO
    )
    previous_costs = (
        Expense.objects.filter(
            workspace=workspace,
            currency=currency,
            incurred_on__gte=today - timedelta(days=60),
            incurred_on__lt=today - timedelta(days=30),
        ).aggregate(total=Sum("actual_amount"))["total"]
        or ZERO
    )
    if previous_costs > ZERO and current_costs > previous_costs * Decimal("1.5"):
        notification = emit_alert(
            rule=_finance_rule(workspace, "finance.cost_growth"),
            recipient=recipient,
            payload={"current": str(current_costs), "previous": str(previous_costs)},
            title="Costs grew by more than 50%",
            body=(
                f"Recent costs are {money(current_costs)} {currency}, "
                f"up from {money(previous_costs)}."
            ),
            deduplication_key=f"cost-growth:{today}:{currency}",
        )
        emitted += notification is not None

    for organization in Organization.objects.filter(workspace=workspace):
        summary = client_summary(organization, currency=currency)
        if summary.collected and summary.contribution_profit < ZERO:
            notification = emit_alert(
                rule=_finance_rule(workspace, "finance.margin_negative"),
                recipient=recipient,
                payload={"margin": str(summary.contribution_margin_percent)},
                title=f"{organization.name} is contribution-profit negative",
                body=(
                    f"Contribution profit is {summary.contribution_profit} {currency} "
                    f"({summary.contribution_margin_percent}%)."
                ),
                resource_type="organization",
                resource_id=str(organization.pk),
                deduplication_key=f"negative-margin:{organization.pk}",
            )
            emitted += notification is not None

    if forecast_target is not None:
        forecast = weighted_forecast(workspace, currency=currency)
        if forecast < forecast_target:
            notification = emit_alert(
                rule=_finance_rule(workspace, "finance.forecast_shortfall"),
                recipient=recipient,
                payload={"forecast": str(forecast), "target": str(forecast_target)},
                title="Weighted forecast is below target",
                body=(
                    f"Forecast: {forecast} {currency}; "
                    f"target: {money(forecast_target)} {currency}."
                ),
                deduplication_key=f"forecast-shortfall:{today}:{currency}",
            )
            emitted += notification is not None
    return emitted
