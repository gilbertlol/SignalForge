from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import AccessPermission
from apps.accounts.tests.factories import UserFactory
from apps.finance.models import FinancialTransaction, Invoice
from apps.organizations.tests.factories import OrganizationFactory

pytestmark = pytest.mark.django_db


def grant(user):
    permission, _ = AccessPermission.objects.get_or_create(
        key="financials.access", defaults={"name": "Financial access"}
    )
    user.memberships.get().permission_grants.add(permission)


def test_finance_api_requires_permission_and_posts_invoice():
    user = UserFactory()
    workspace = user.memberships.get().workspace
    organization = OrganizationFactory(workspace=workspace)
    client = APIClient()
    client.force_authenticate(user=user)
    assert client.get("/api/v1/finance/invoices/").status_code == 403
    grant(user)

    response = client.post(
        "/api/v1/finance/invoices/",
        {
            "organization": str(organization.pk),
            "number": "INV-API",
            "subtotal": "100.00",
            "tax_amount": "15.00",
            "currency": "cad",
        },
        format="json",
    )
    assert response.status_code == 201
    invoice = Invoice.objects.get(pk=response.json()["id"])
    posted = client.post(f"/api/v1/finance/invoices/{invoice.pk}/post/")
    assert posted.status_code == 200
    assert FinancialTransaction.objects.get().amount == Decimal("115.0000")


def test_finance_api_rejects_cross_workspace_organization():
    user = UserFactory()
    grant(user)
    foreign = OrganizationFactory()
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/v1/finance/invoices/",
        {
            "organization": str(foreign.pk),
            "number": "FOREIGN",
            "subtotal": "10",
            "currency": "USD",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "workspace" in str(response.json()).lower()
