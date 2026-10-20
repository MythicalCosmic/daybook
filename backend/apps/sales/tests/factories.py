"""Test helpers for sales and cash.

Shifts, movements and receipts have no factories on purpose: make them through
`apps.sales.services`, which books the ledger in step (the helpers below do exactly that).
"""

from dataclasses import dataclass
from decimal import Decimal

from apps.companies.models import Branch, Company
from apps.companies.tests.factories import CompanyFactory
from apps.finance import defaults as finance_defaults
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import MembershipFactory
from apps.sales import defaults, rollup, services
from apps.sales.conf import get_settings
from apps.sales.models import CashShift, PaymentMethod, Register
from apps.sales.services import PaymentLine


@dataclass
class Shop:
    company: Company
    branch: Branch
    other_branch: Branch
    register: Register
    other_register: Register
    owner: Membership
    manager: Membership
    cashier: Membership
    colleague: Membership

    def method(self, code: str) -> PaymentMethod:
        return PaymentMethod.objects.get(company=self.company, system_code=code)


def make_member(company, role_name: str, *, branches=(), **kwargs) -> Membership:
    role = AccessRole.objects.get(company=company, name=role_name)
    membership = MembershipFactory(
        company=company,
        role=role,
        status=Membership.Status.APPROVED,
        home_branch=branches[0] if branches else None,
        **kwargs,
    )
    if branches:
        membership.branches.set(branches)
    return membership


def scoped_role(company, *perms) -> AccessRole:
    """A role without branches.all, so its holders see only their own branches."""
    return AccessRole.objects.create(
        company=company,
        name=f"Scoped {AccessRole.objects.filter(company=company).count()}",
        permissions=[Perm.DASHBOARD_ACCESS, *perms],
    )


def make_shop(**company_fields) -> Shop:
    company = CompanyFactory(features=["finance", "sales"], **company_fields)
    finance_defaults.ensure(company)
    first = company.branches.order_by("pk").first()
    first.name, first.code = "Chilonzor", "CHL"
    first.save()
    second = Branch.objects.create(company=company, name="Yunusobod", code="YNS", order=1)
    defaults.ensure(company)
    get_settings(company)  # the lazy row exists, so tests may update it directly
    register = Register.objects.get(branch=first)
    other_register = Register.objects.get(branch=second)
    return Shop(
        company=company,
        branch=first,
        other_branch=second,
        register=register,
        other_register=other_register,
        owner=make_member(company, "Owner", branches=(first, second), first_name="Dilnoza"),
        manager=make_member(company, "Manager", branches=(first, second), first_name="Bekzod"),
        cashier=make_member(company, "Cashier", branches=(first,), first_name="Madina"),
        colleague=make_member(company, "Cashier", branches=(second,), first_name="Jasur"),
    )


def open_and_close(
    shop: Shop,
    *,
    cashier=None,
    register=None,
    opening: str = "200000",
    cash_sales: str = "1000000",
    card_sales: str = "500000",
    counted: str | None = None,
    refunds: str = "0",
    receipts: int = 20,
) -> CashShift:
    """A whole shift through the services: open, then close with these totals (counted cash
    defaults to exactly what's expected)."""
    cashier = cashier or shop.cashier
    register = register or shop.register
    shift = services.open_shift(by=cashier, register=register, opening_float=opening)
    expected = Decimal(opening) + Decimal(cash_sales) - Decimal(refunds)
    lines = [PaymentLine(shop.method("cash"), Decimal(cash_sales), Decimal(refunds), 0)]
    if Decimal(card_sales):
        lines.append(PaymentLine(shop.method("uzcard"), Decimal(card_sales), Decimal(0), 0))
    closed = services.close_shift(
        shift,
        by=cashier,
        payments=lines,
        counted_cash=counted if counted is not None else str(expected),
        receipts=receipts,
        z_photo=jpeg(),
        terminal_photo=jpeg() if Decimal(card_sales) else None,
    )
    # What the close queues after commit (tests run inside one transaction).
    rollup.rebuild_day(closed.branch_id, closed.business_day)
    return closed


def jpeg(name: str = "photo.jpg"):
    """A tiny real JPEG upload."""
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 120, 60)).save(buffer, "JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")
