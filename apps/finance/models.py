from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import WorkspaceScopedModel

MONEY_MAX_DIGITS = 18
MONEY_DECIMAL_PLACES = 4


class MoneyMixin(models.Model):
    currency = models.CharField(max_length=3, default="USD")

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        self.currency = self.currency.upper()
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValidationError({"currency": "Use a three-letter ISO currency code."})


class DocumentStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SENT = "sent", "Sent"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    CANCELED = "canceled", "Canceled"


class Quote(WorkspaceScopedModel, MoneyMixin):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    opportunity = models.ForeignKey(
        "opportunities.Opportunity", null=True, blank=True, on_delete=models.SET_NULL
    )
    number = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=DocumentStatus.choices, default="draft")
    subtotal = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4)
    tax_amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4, default=0)
    discount_amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4, default=0)
    valid_until = models.DateField(null=True, blank=True)
    terms = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "number"], name="uniq_quote_number")
        ]

    def __str__(self):
        return self.number


class Proposal(WorkspaceScopedModel, MoneyMixin):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    quote = models.ForeignKey(Quote, null=True, blank=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=DocumentStatus.choices, default="draft")
    amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4)
    content = models.TextField(blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.title


class BillingFrequency(models.TextChoices):
    ONE_TIME = "one_time", "One time"
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    ANNUAL = "annual", "Annual"
    MILESTONE = "milestone", "Milestone"


class Contract(WorkspaceScopedModel, MoneyMixin):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    proposal = models.ForeignKey(Proposal, null=True, blank=True, on_delete=models.SET_NULL)
    number = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=DocumentStatus.choices, default="draft")
    total_value = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4)
    billing_frequency = models.CharField(
        max_length=20, choices=BillingFrequency.choices, default="one_time"
    )
    deposit_amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4, default=0)
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "number"], name="uniq_contract_number")
        ]

    def __str__(self):
        return self.number


class InvoiceStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ISSUED = "issued", "Issued"
    PARTIALLY_PAID = "partially_paid", "Partially paid"
    PAID = "paid", "Paid"
    OVERDUE = "overdue", "Overdue"
    VOID = "void", "Void"


class Invoice(WorkspaceScopedModel, MoneyMixin):
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="invoices"
    )
    contract = models.ForeignKey(Contract, null=True, blank=True, on_delete=models.SET_NULL)
    number = models.CharField(max_length=100)
    status = models.CharField(max_length=30, choices=InvoiceStatus.choices, default="draft")
    subtotal = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4)
    tax_amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4, default=0)
    credit_amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4, default=0)
    issued_on = models.DateField(null=True, blank=True)
    due_on = models.DateField(null=True, blank=True)
    milestone = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "number"], name="uniq_invoice_number")
        ]

    def __str__(self):
        return self.number


class PaymentKind(models.TextChoices):
    PAYMENT = "payment", "Payment"
    REFUND = "refund", "Refund"
    CHARGEBACK = "chargeback", "Chargeback"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    REVERSED = "reversed", "Reversed"


class Payment(WorkspaceScopedModel, MoneyMixin):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    invoice = models.ForeignKey(Invoice, null=True, blank=True, on_delete=models.PROTECT)
    kind = models.CharField(max_length=20, choices=PaymentKind.choices, default="payment")
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default="pending")
    amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4)
    paid_at = models.DateTimeField(null=True, blank=True)
    external_reference = models.CharField(max_length=255, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.kind} {self.amount} {self.currency}"


class CostCategory(models.TextChoices):
    HUMAN_LABOR = "human_labor", "Human labor"
    CONTRACTOR = "contractor", "Contractor"
    AI = "ai", "AI"
    MESSAGING = "messaging", "Messaging"
    ENRICHMENT = "enrichment", "Enrichment"
    INFRASTRUCTURE = "infrastructure", "Infrastructure"
    SUPPORT = "support", "Support"
    REWORK = "rework", "Rework"
    OTHER = "other", "Other"


class Expense(WorkspaceScopedModel, MoneyMixin):
    organization = models.ForeignKey(
        "organizations.Organization", null=True, blank=True, on_delete=models.PROTECT
    )
    category = models.CharField(max_length=30, choices=CostCategory.choices)
    description = models.CharField(max_length=255)
    estimated_amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4, default=0)
    actual_amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4, default=0)
    incurred_on = models.DateField()
    vendor = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.description


class CommissionBasis(models.TextChoices):
    COLLECTED_REVENUE = "collected_revenue", "Collected revenue"
    CONTRACT_VALUE = "contract_value", "Contract value"
    CONTRIBUTION_PROFIT = "contribution_profit", "Contribution profit"


class CommissionRule(WorkspaceScopedModel):
    name = models.CharField(max_length=255)
    basis = models.CharField(max_length=30, choices=CommissionBasis.choices)
    rate_percent = models.DecimalField(max_digits=7, decimal_places=4)
    active = models.BooleanField(default=True)


class CommissionStatus(models.TextChoices):
    EARNED = "earned", "Earned"
    APPROVED = "approved", "Approved"
    PAYABLE = "payable", "Payable"
    PAID = "paid", "Paid"
    VOID = "void", "Void"


class Commission(WorkspaceScopedModel, MoneyMixin):
    rule = models.ForeignKey(CommissionRule, on_delete=models.PROTECT)
    beneficiary = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    payment = models.ForeignKey(Payment, null=True, blank=True, on_delete=models.PROTECT)
    basis_amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4)
    amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4)
    status = models.CharField(max_length=20, choices=CommissionStatus.choices, default="earned")

    def __str__(self):
        return f"{self.beneficiary}: {self.amount} {self.currency}"


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    CANCELED = "canceled", "Canceled"


class Subscription(WorkspaceScopedModel, MoneyMixin):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    contract = models.ForeignKey(Contract, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4)
    frequency = models.CharField(max_length=20, choices=BillingFrequency.choices, default="monthly")
    status = models.CharField(max_length=20, choices=SubscriptionStatus.choices, default="active")
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.name


class ClientBudget(WorkspaceScopedModel, MoneyMixin):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4)
    starts_on = models.DateField()
    ends_on = models.DateField()
    warning_percent = models.DecimalField(max_digits=6, decimal_places=2, default=80)

    def __str__(self):
        return self.name


class CostAllocation(WorkspaceScopedModel, MoneyMixin):
    expense = models.ForeignKey(Expense, on_delete=models.PROTECT, related_name="allocations")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4)
    rationale = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.organization}: {self.amount} {self.currency}"


class ForecastCategory(models.TextChoices):
    PIPELINE = "pipeline", "Pipeline"
    CONTRACTED = "contracted", "Contracted"
    RECURRING = "recurring", "Recurring"
    RENEWAL = "renewal", "Renewal"


class RevenueForecast(WorkspaceScopedModel, MoneyMixin):
    organization = models.ForeignKey(
        "organizations.Organization", null=True, blank=True, on_delete=models.PROTECT
    )
    opportunity = models.ForeignKey(
        "opportunities.Opportunity", null=True, blank=True, on_delete=models.SET_NULL
    )
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=ForecastCategory.choices)
    period_start = models.DateField()
    period_end = models.DateField()
    amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4)
    probability_percent = models.DecimalField(max_digits=6, decimal_places=2)
    assumptions = models.JSONField(default=dict)

    def __str__(self):
        return self.name


class TransactionType(models.TextChoices):
    INVOICE = "invoice", "Invoice"
    PAYMENT = "payment", "Payment"
    REFUND = "refund", "Refund"
    CREDIT = "credit", "Credit"
    EXPENSE = "expense", "Expense"
    COMMISSION = "commission", "Commission"
    ADJUSTMENT = "adjustment", "Adjustment"
    REVERSAL = "reversal", "Reversal"


class FinancialTransaction(WorkspaceScopedModel, MoneyMixin):
    organization = models.ForeignKey(
        "organizations.Organization", null=True, blank=True, on_delete=models.PROTECT
    )
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=4)
    occurred_at = models.DateTimeField()
    description = models.CharField(max_length=255)
    source_type = models.CharField(max_length=100)
    source_id = models.CharField(max_length=255)
    reverses = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_by"
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )

    class Meta:
        ordering = ["occurred_at", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "source_type", "source_id", "transaction_type"],
                condition=~Q(transaction_type__in=["adjustment", "reversal"]),
                name="uniq_financial_source_event",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and FinancialTransaction.all_objects.filter(pk=self.pk).exists():
            raise ValidationError("Financial transactions are immutable; create an adjustment.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Financial transactions cannot be deleted; create a reversal.")

    def __str__(self):
        return f"{self.transaction_type}: {self.amount} {self.currency}"
