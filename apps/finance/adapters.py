from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from .models import Invoice, Payment


@dataclass(frozen=True)
class ExternalResult:
    external_id: str
    status: str
    amount: Decimal
    currency: str


class AccountingAdapter(Protocol):
    def export_invoice(self, invoice: Invoice) -> ExternalResult: ...

    def void_invoice(self, invoice: Invoice) -> ExternalResult: ...


class PaymentAdapter(Protocol):
    def collect(self, payment: Payment) -> ExternalResult: ...

    def refund(self, payment: Payment) -> ExternalResult: ...


class ManualAccountingAdapter:
    """Local adapter: records that a human is responsible for external bookkeeping."""

    def export_invoice(self, invoice: Invoice) -> ExternalResult:
        return ExternalResult(
            external_id=f"manual:{invoice.pk}",
            status="recorded",
            amount=invoice.subtotal + invoice.tax_amount - invoice.credit_amount,
            currency=invoice.currency,
        )

    def void_invoice(self, invoice: Invoice) -> ExternalResult:
        return ExternalResult(
            external_id=f"manual:void:{invoice.pk}",
            status="void_requested",
            amount=Decimal("0"),
            currency=invoice.currency,
        )


class ManualPaymentAdapter:
    def collect(self, payment: Payment) -> ExternalResult:
        return ExternalResult(
            external_id=f"manual:{payment.pk}",
            status="recorded",
            amount=payment.amount,
            currency=payment.currency,
        )

    def refund(self, payment: Payment) -> ExternalResult:
        return ExternalResult(
            external_id=f"manual:refund:{payment.pk}",
            status="recorded",
            amount=payment.amount,
            currency=payment.currency,
        )
