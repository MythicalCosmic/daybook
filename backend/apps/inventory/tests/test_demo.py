"""The stock demo on the root `demo_people` fixture (rule 22): two pharmacies like Demo
Dorixona, the §14.3 shape of the story."""

from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.companies.models import Branch
from apps.inventory import demo, queries
from apps.inventory.models import (
    ControlledPeriod,
    GoodsReceipt,
    MissingRequest,
    Product,
    RecallNotice,
    StockCount,
    StockTransfer,
    WriteOff,
)
from apps.inventory.tests.conftest import TZ

pytestmark = pytest.mark.django_db


@pytest.fixture
def pharmacy(company, demo_people, freeze):
    freeze(datetime(2026, 11, 7, 10, tzinfo=TZ))
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
    from apps.finance import defaults as finance_defaults

    finance_defaults.ensure(company)
    people = demo_people(company)
    return company, people


def test_the_story(pharmacy, django_capture_on_commit_callbacks):
    company, people = pharmacy
    now = timezone.now()
    with django_capture_on_commit_callbacks(execute=True):
        demo.seed(company, people, now)
    today = now.astimezone(TZ).date()

    products = Product.objects.for_company(company)
    assert products.count() == len(demo.CATALOGUE)
    assert products.filter(rx_required=True).count() >= 25
    assert products.filter(e_rx_group=True).count() == 8
    assert products.filter(mandatory_list=True).count() == 20
    assert products.filter(storage="cold").count() == 3

    board = queries.expiry_board(company, branch_ids=None, within=90, as_of=today)
    counts = {bucket["key"]: bucket["count"] for bucket in board["buckets"]}
    assert counts["expired"] == 3
    assert counts["d30"] == 8
    assert counts["d60"] + counts["d90"] == 12

    receipts = GoodsReceipt.objects.for_company(company)
    assert receipts.filter(status="posted").count() == 11
    assert receipts.filter(status="submitted").count() == 1
    warnings = {code for row in receipts for line in row.lines.all() for code in line.warnings}
    assert {"cost_jump", "short_shelf_life"} <= warnings
    assert StockTransfer.objects.filter(company=company, status="disputed").count() == 1
    assert StockTransfer.objects.filter(company=company).count() == 4
    states = sorted(WriteOff.objects.filter(company=company).values_list("status", flat=True))
    assert states == ["approved", "destroyed", "proposed"]
    destroyed = WriteOff.objects.get(company=company, status="destroyed")
    assert len(destroyed.commission) == 5 and destroyed.act_pdf
    waiting = WriteOff.objects.get(company=company, status="approved")
    assert (waiting.destroy_by - today).days == 12
    applied = StockCount.objects.filter(company=company, status="applied")
    assert applied.count() == 2
    shortage = min(row.value_difference for row in applied)
    assert -125000 < shortage <= -115000
    assert StockCount.objects.filter(company=company, status="open").count() == 1
    [recall] = RecallNotice.objects.filter(company=company)
    assert {row["branch"] for row in recall.found} == {"Chilonzor", "Yunusobod"}
    assert MissingRequest.objects.filter(company=company, source="counter").count() == 15
    period = ControlledPeriod.objects.filter(company=company)
    assert period.exists() and all(row.closed_at for row in period)
    missing = queries.mandatory_missing(company, branch_ids=None, day=today)
    assert [row["branch"] for row in missing] == ["Chilonzor"]

    # Once Finance has a bank account, the payables that fell due are paid but the latest.
    from apps.finance import services as finance
    from apps.finance.models import Debt

    bank = finance.create_account(company, by=people["owner"], kind="bank", name="Bank")
    finance.record_transaction(
        company,
        by=people["owner"],
        kind="opening",
        amount=Decimal(500_000_000),
        occurred_on=today - timedelta(days=90),
        account=bank,
    )
    with django_capture_on_commit_callbacks(execute=True):
        demo.finish(company, people, now)
    due = Debt.objects.filter(
        company=company, source_type="inventory.goodsreceipt", due_on__lt=today
    )
    assert due.count() > 2
    assert due.exclude(status="paid").count() == 1


def test_the_distributor(company, freeze):
    from apps.members.models import AccessRole, Membership
    from apps.members.tests.factories import MembershipFactory

    freeze(datetime.combine(datetime(2026, 11, 7).date(), time(10), tzinfo=TZ))
    company.features = ["stock"]
    company.save(update_fields=["features"])
    owner = MembershipFactory(
        company=company,
        role=AccessRole.objects.get(company=company, name="Owner"),
        status=Membership.Status.APPROVED,
        onboarded_at=timezone.now(),
    )
    people = {"owner": owner, "manager": owner, "worker": owner, "cashier": owner}
    demo.seed_small(company, people, timezone.now())
    assert Product.objects.for_company(company).count() == len(demo.CATALOGUE)
    assert queries.stock_value(company, branch_ids=None)["value"] > 0
