"""Fixtures of the stock tests: a pharmacy with Stock and Finance on, two branches (Chilonzor,
and Yunusobod, licensed for controlled substances), a distributor on 30 days, and its people:

- owner: every permission;
- head: the head of Chilonzor (stock.manage at Chilonzor only, no branches.all, no finance.view);
- accountant: the Accountant role (sales.view and finance.view, no stock.manage);
- ali: a pharmacist at Chilonzor (stock.operate);
- nigora: a pharmacist at Yunusobod with stock.controlled.

The reference day is Saturday 7 November 2026, Asia/Tashkent; `freeze` moves the clock.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from apps.companies.models import Branch
from apps.finance import defaults as finance_defaults
from apps.finance.models import Counterparty
from apps.inventory import services
from apps.inventory.tests.factories import ProductFactory
from apps.members.models import AccessRole
from apps.members.permissions import Perm

TZ = ZoneInfo("Asia/Tashkent")
DAY = date(2026, 11, 7)


def local(day: date, hour: int = 12) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=TZ)


def D(value) -> Decimal:
    return Decimal(str(value))


@pytest.fixture
def freeze(monkeypatch):
    def set_now(moment: datetime) -> datetime:
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
        return moment

    return set_now


@pytest.fixture
def shop(company, freeze):
    freeze(local(DAY, 10))
    company.features = ["finance", "stock"]
    company.save(update_fields=["features"])
    first = company.branches.order_by("order", "pk").first()
    first.name, first.code = "Chilonzor", "CHL"
    first.save()
    Branch.objects.create(
        company=company,
        name="Yunusobod",
        code="YNS",
        order=1,
        open_24h=True,
        controlled_licence=True,
        e_prescription_area=True,
    )
    finance_defaults.ensure(company)
    return company


@pytest.fixture
def chilonzor(shop):
    return shop.branches.get(name="Chilonzor")


@pytest.fixture
def yunusobod(shop):
    return shop.branches.get(name="Yunusobod")


@pytest.fixture
def owner(shop, member, chilonzor, yunusobod):
    person = member.registered(shop, "Owner", home_branch=chilonzor)
    person.branches.set([chilonzor, yunusobod])
    return person


@pytest.fixture
def head(shop, member, chilonzor):
    role = AccessRole.objects.create(
        company=shop,
        name="Head of Chilonzor",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.STOCK_MANAGE, Perm.SALES_VIEW],
    )
    person = member.registered(shop, "Employee", home_branch=chilonzor)
    person.role = role
    person.save(update_fields=["role"])
    person.branches.set([chilonzor])
    chilonzor.manager = person
    chilonzor.save(update_fields=["manager"])
    return person


@pytest.fixture
def accountant(shop, member):
    return member.registered(shop, "Accountant")


@pytest.fixture
def ali(shop, member, chilonzor):
    person = member.registered(shop, "Pharmacist", first_name="Ali", home_branch=chilonzor)
    person.branches.set([chilonzor])
    return person


@pytest.fixture
def nigora(shop, member, yunusobod):
    role = AccessRole.objects.create(
        company=shop,
        name="Night pharmacist",
        permissions=[Perm.SALES_OPERATE, Perm.STOCK_OPERATE, Perm.STOCK_CONTROLLED],
    )
    person = member.registered(shop, "Employee", first_name="Nigora", home_branch=yunusobod)
    person.role = role
    person.save(update_fields=["role"])
    person.branches.set([yunusobod])
    return person


@pytest.fixture
def supplier(shop, owner):
    party = Counterparty.objects.create(
        company=shop, name="Ko‘kterak Farm Distribyutor", kind=Counterparty.Kind.SUPPLIER
    )
    services.save_supplier(party, by=owner, payment_terms_days=30, official_dealer=True)
    return party


@pytest.fixture
def product(shop):
    """An OTC tablet sold by the blister: 2 blisters a pack."""
    return ProductFactory(
        company=shop,
        name="Paratsetamol 500 mg tabletka №20",
        inn="paracetamol",
        units_per_pack=2,
        part_label="blister",
    )


@pytest.fixture
def rx(shop):
    """A prescription antibiotic, 2 blisters a pack."""
    return ProductFactory(
        company=shop,
        name="Amoksitsillin 500 mg kapsula №16",
        inn="amoxicillin",
        dosage_form="capsule",
        rx_required=True,
        units_per_pack=2,
        part_label="blister",
    )


def opening(branch, product, series, *, expires_on, quantity, cost="10340", by=None, at=None):
    """Opening stock of `quantity` parts."""
    return services.add_opening_stock(
        branch,
        by=by,
        product=product,
        series=series,
        expires_on=expires_on,
        quantity=D(quantity),
        unit_cost=D(cost),
        at=at,
    )


def receive(
    shop,
    by,
    branch,
    supplier,
    lines,
    *,
    invoice="N-1",
    invoice_date=date(2026, 11, 5),
    post=True,
):
    """A goods receipt with `lines` (dicts of add_line's fields), posted unless told not to."""
    receipt = services.create_receipt(
        shop,
        by=by,
        branch=branch,
        supplier=supplier,
        supplier_invoice_number=invoice,
        supplier_invoice_date=invoice_date,
        lines=lines,
    )
    return services.post_receipt(receipt, by=by) if post else receipt


def line(product, series="S-1", *, packs=10, cost="10340", expires_on=None, **extra):
    return {
        "product": product,
        "series": series,
        "expires_on": expires_on or DAY + timedelta(days=540),
        "packs": D(packs),
        "unit_cost": D(cost),
        **extra,
    }
