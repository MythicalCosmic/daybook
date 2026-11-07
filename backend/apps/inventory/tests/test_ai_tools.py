"""The stock AI tools through `call_tool` (what the runtime sends): branch scope, costs only
with finance.view and the share-finance switch, analogs as catalogue facts, no phones."""

from datetime import timedelta

import pytest

from apps.ai.tools.testing import call_tool
from apps.inventory import services
from apps.inventory.tests.conftest import DAY, line, opening, receive
from apps.inventory.tests.factories import ProductFactory
from apps.members.models import AccessRole
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db


@pytest.fixture
def stocked(shop, owner, chilonzor, yunusobod, supplier, product):
    receive(shop, owner, chilonzor, supplier, [line(product, "C1", packs=5)], invoice="C-1")
    receive(shop, owner, yunusobod, supplier, [line(product, "Y1", packs=3)], invoice="Y-1")
    return product


@pytest.fixture
def chilonzor_manager(shop, member, chilonzor):
    role = AccessRole.objects.create(
        company=shop, name="Chilonzor head", permissions=[Perm.SALES_VIEW, Perm.STOCK_MANAGE]
    )
    person = member.registered(shop, "Employee")
    person.role = role
    person.save(update_fields=["role"])
    person.branches.set([chilonzor])
    return person


def test_find_item_answers_stock_per_pharmacy(shop, owner, chilonzor_manager, stocked):
    answer = call_tool("inventory_find_item", owner, q="Paratsetamol")
    [row] = answer["rows"]
    assert row["parts_on_hand"] == "16" and row["price_per_pack"] == "13000.00"
    assert {item["pharmacy"] for item in row["by_pharmacy"]} == {"Chilonzor", "Yunusobod"}
    scoped = call_tool("inventory_find_item", chilonzor_manager, q="Paratsetamol")
    assert scoped["rows"][0]["parts_on_hand"] == "10"
    assert [item["pharmacy"] for item in scoped["rows"][0]["by_pharmacy"]] == ["Chilonzor"]


def test_analogs_are_catalogue_facts(shop, owner, stocked):
    other = ProductFactory(
        company=shop, name="Paratsetamol-Farm 500 mg tabletka №10", inn="paracetamol"
    )
    ProductFactory(company=shop, name="Paratsetamol sirop", inn="paracetamol", dosage_form="syrup")
    answer = call_tool("inventory_analogs", owner, product_id=stocked.pk)
    assert [row["id"] for row in answer["rows"]] == [other.pk]
    assert "not advice" in answer["data"]["note"]
    assert call_tool("inventory_analogs", owner, product_id=999999) == {"error": "not_found"}


def test_expiring_values_at_cost_need_finance(shop, owner, chilonzor_manager, chilonzor, product):
    opening(chilonzor, product, "S", expires_on=DAY + timedelta(days=10), quantity=4)
    answer = call_tool("inventory_expiring", owner, days=30)
    [row] = answer["rows"]
    assert row["value_retail"] == "26000.00" and row["value_cost"] == "20680.00"
    no_switch = call_tool("inventory_expiring", owner, days=30, _switches=frozenset())
    assert "value_cost" not in no_switch["rows"][0]
    manager = call_tool("inventory_expiring", chilonzor_manager, days=30)
    assert "value_cost" not in manager["rows"][0] and "value_cost" not in manager["data"]


def test_branch_scope_is_kept(shop, chilonzor_manager, yunusobod, stocked):
    assert call_tool("inventory_expiring", chilonzor_manager, days=365, branch_id=yunusobod.pk) == {
        "error": "not_found"
    }
    levels = call_tool("inventory_stock_levels", chilonzor_manager)
    assert {row["pharmacy"] for row in levels["rows"]} == {"Chilonzor"}


def test_receipts_and_defektura(shop, owner, chilonzor, stocked):
    receipts = call_tool("inventory_receipts", owner, days=30)
    assert {row["invoice"] for row in receipts["rows"]} == {"C-1", "Y-1"}
    assert receipts["rows"][0]["amount"]
    services.add_request(
        chilonzor, by=owner, name="Insulin glargin", customer_phone="+998901112233"
    )
    answer = call_tool("inventory_defektura", owner)
    [row] = answer["rows"]
    assert row["item"] == "Insulin glargin" and "998" not in str(answer)


def test_the_tools_need_the_module(shop, owner, stocked):
    shop.features = ["finance"]
    shop.save(update_fields=["features"])
    owner.company.refresh_from_db()
    assert call_tool("inventory_find_item", owner, q="Paratsetamol") == {"error": "not_allowed"}
