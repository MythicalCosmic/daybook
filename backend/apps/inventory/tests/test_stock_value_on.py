"""`queries.stock_value_on`: the stock at cost at the end of a past day, for the finance
statements' balance sheet: today's value less what moved after that day."""

from datetime import timedelta

import pytest

from apps.inventory import queries
from apps.inventory.tests.conftest import DAY, D, local, opening

pytestmark = pytest.mark.django_db


def test_stock_value_on_a_past_day(shop, owner, chilonzor, yunusobod, product):
    # Day -3: 10 blisters at 10 340 a pack of 2 (5 170 each); today: 4 more at Yunusobod.
    opening(
        chilonzor,
        product,
        "S-1",
        expires_on=DAY + timedelta(days=400),
        quantity=10,
        by=owner,
        at=local(DAY - timedelta(days=3)),
    )
    opening(
        yunusobod,
        product,
        "S-2",
        expires_on=DAY + timedelta(days=400),
        quantity=4,
        by=owner,
        at=local(DAY, 9),
    )
    assert queries.stock_value_on(shop, DAY, branch_ids=None) == D("72380.00")
    assert queries.stock_value_on(shop, DAY - timedelta(days=1), branch_ids=None) == D("51700.00")
    assert queries.stock_value_on(shop, DAY - timedelta(days=5), branch_ids=None) == D("0.00")
    assert queries.stock_value_on(shop, DAY - timedelta(days=1), branch_ids=[yunusobod.pk]) == D(
        "0.00"
    )
    assert queries.stock_value_on(shop, DAY, branch_ids=[yunusobod.pk]) == D("20680.00")
