"""The mini app's "My equipment": only my items, no values, confirmed once."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.assets import services

pytestmark = pytest.mark.django_db


def url(company, rest: str = "") -> str:
    return f"/api/v1/companies/{company.pk}/assets/mine/{rest}"


def test_i_see_what_i_hold_and_confirm_it(shop, owner, ali, api_as, category):
    laptop = services.create_asset(
        shop, by=owner, category=category, name="Noutbuk", cost=D(9_000_000), serial="LN-1"
    )
    services.create_asset(shop, by=owner, category=category, name="Boshqasi", cost=D(1))
    assignment = services.issue(laptop, by=owner, membership=ali, on=date(2026, 11, 7))
    client = api_as(ali)
    rows = client.get(url(shop)).json()
    assert [row["id"] for row in rows] == [assignment.pk]
    row = rows[0]
    assert row["name"] == "Noutbuk" and row["serial"] == "LN-1"
    assert row["acknowledged_at"] is None
    assert "cost" not in row and "book_value" not in row  # never a value
    reply = client.post(url(shop, f"{assignment.pk}/acknowledge/"))
    assert reply.status_code == 200
    assert reply.json()["acknowledged_at"] is not None


def test_someone_elses_hand_out_is_not_found(shop, owner, ali, member, api_as, category):
    laptop = services.create_asset(shop, by=owner, category=category, name="Noutbuk", cost=D(1))
    assignment = services.issue(laptop, by=owner, membership=ali, on=date(2026, 11, 7))
    other = member(shop, "Pharmacist")
    assert api_as(other).get(url(shop)).json() == []
    assert api_as(other).post(url(shop, f"{assignment.pk}/acknowledge/")).status_code == 404


def test_off_while_the_module_is_off(shop, ali, api_as):
    shop.features = ["finance"]
    shop.save(update_fields=["features"])
    assert api_as(ali).get(url(shop)).status_code == 403
