"""The owner API of fixed assets: scope, permissions, the module switch, and the flows."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.assets import services
from apps.assets.models import Asset
from apps.assets.tests.test_posting import buy

pytestmark = pytest.mark.django_db


def base(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/assets"


@pytest.fixture
def fridge(shop, owner, category, chilonzor):
    return services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich Pozis",
        cost=D(8_400_000),
        life_months=84,
        branch=chilonzor,
        in_service_on=date(2026, 9, 10),
    )


def test_create_from_a_purchase_and_see_its_page(
    shop, owner, owner_api, cash, equipment, chilonzor, category
):
    txn = buy(shop, owner, cash, equipment, chilonzor)
    client = owner_api(owner)
    reply = client.get(f"{base(shop)}/purchases/")
    assert reply.status_code == 200
    assert [row["id"] for row in reply.json()] == [txn.pk]
    assert reply.json()[0]["base_amount"] == "12000000.00"

    reply = client.post(
        f"{base(shop)}/items/",
        {
            "category": category.pk,
            "name": "Muzlatgich Pozis",
            "purchase_transaction": txn.pk,
            "in_service_on": "2026-05-25",
            "serial": "PZ-1",
        },
        format="json",
    )
    assert reply.status_code == 201, reply.json()
    page = reply.json()
    assert page["asset"]["number"] == "AV-0001"
    assert page["asset"]["cost"] == "12000000.00"
    assert page["values"]["accumulated"] == "714285.70"
    assert page["purchase"]["capitalized"] is True
    assert page["booked"] is True
    states = {row["state"] for row in page["schedule"]}
    assert states == {"booked", "planned"}
    assert client.get(f"{base(shop)}/purchases/").json() == []

    listed = client.get(f"{base(shop)}/items/").json()
    assert listed[0]["book_value"] == "11285714.30"
    summary = client.get(f"{base(shop)}/summary/").json()
    assert summary["count"] == 1 and summary["book"] == "11285714.30"


def test_actions_answer_with_the_page(shop, owner, owner_api, fridge, ali, cash):
    client = owner_api(owner)
    url = f"{base(shop)}/items/{fridge.pk}"
    reply = client.post(f"{url}/issue/", {"person": ali.pk, "on": "2026-11-07"}, format="json")
    assert reply.status_code == 200, reply.json()
    assert reply.json()["asset"]["custodian"]["id"] == ali.pk
    reply = client.post(f"{url}/return/", {"on": "2026-11-07", "condition": "good"}, format="json")
    assert reply.json()["asset"]["custodian"] is None
    reply = client.post(f"{url}/service/", {"on": "2026-11-06"}, format="json")
    assert reply.json()["next_service_on"] == "2027-05-06"
    reply = client.post(f"{url}/estimate/", {"on": "2026-11-07", "life_months": 96}, format="json")
    assert reply.status_code == 200, reply.json()
    assert reply.json()["life_months"] == 96
    reply = client.post(f"{url}/suspend/", {"on": "2026-11-07"}, format="json")
    assert reply.json()["asset"]["status"] == "suspended"
    reply = client.post(f"{url}/resume/", {"on": "2026-11-08"}, format="json")
    assert reply.status_code == 400  # the future
    reply = client.post(f"{url}/resume/", {"on": "2026-11-07"}, format="json")
    assert reply.json()["asset"]["status"] == "in_use"
    reply = client.post(
        f"{url}/dispose/",
        {"on": "2026-11-07", "kind": "sold", "amount": "7000000", "account": cash.pk},
        format="json",
    )
    assert reply.status_code == 200, reply.json()
    assert reply.json()["asset"]["status"] == "disposed"
    events = [event["kind"] for event in reply.json()["events"]]
    assert events[0] == "disposed" and "issued" in events


def test_reports(shop, owner, owner_api, fridge):
    client = owner_api(owner)
    report = client.get(f"{base(shop)}/depreciation/?year=2026&group=category").json()
    assert report["total"] == "300000.00"  # October, November, December: 3 x 100 000
    assert report["groups"][0]["name"] == "Pharmacy fridges"
    movement = client.get(f"{base(shop)}/movement/?from=2026-01-01&to=2026-10-31").json()
    assert movement["total"]["in_cost"] == "8400000.00"
    assert movement["total"]["depreciation"] == "100000.00"
    planning = client.get(f"{base(shop)}/planning/").json()
    assert planning["inflation"] == "10.00"
    assert client.get(f"{base(shop)}/custody/").json() == []


def test_counts(shop, owner, owner_api, fridge, chilonzor):
    client = owner_api(owner)
    reply = client.post(f"{base(shop)}/counts/", {"branch": chilonzor.pk}, format="json")
    assert reply.status_code == 201
    count = reply.json()
    line = count["lines"][0]
    reply = client.post(
        f"{base(shop)}/counts/{count['id']}/lines/{line['id']}/", {"result": "found"}, format="json"
    )
    assert reply.json()["totals"]["found"] == 1
    reply = client.post(f"{base(shop)}/counts/{count['id']}/close/")
    assert reply.json()["status"] == "closed"


def test_another_company_and_another_branch_answer_404(
    shop, other_company, member, owner_api, owner, keeper, fridge, category, yunusobod
):
    stranger = member(other_company, "Owner")
    other_company.features = ["assets"]
    other_company.save(update_fields=["features"])
    reply = owner_api(stranger).get(
        f"/api/v1/owner/companies/{other_company.pk}/assets/items/{fridge.pk}/"
    )
    assert reply.status_code == 404
    elsewhere = services.create_asset(
        shop, by=owner, category=category, name="Boshqa", cost=D(1_000_000), branch=yunusobod
    )
    client = owner_api(keeper)  # Chilonzor only
    assert client.get(f"{base(shop)}/items/{fridge.pk}/").status_code == 200
    assert client.get(f"{base(shop)}/items/{elsewhere.pk}/").status_code == 404
    assert [row["id"] for row in client.get(f"{base(shop)}/items/").json()] == [fridge.pk]
    reply = client.post(
        f"{base(shop)}/items/",
        {"category": category.pk, "name": "X", "cost": "100", "branch": yunusobod.pk},
        format="json",
    )
    assert reply.status_code == 400


def test_permissions_and_the_module_switch(shop, owner_api, member, accountant, fridge):
    pharmacist = member(shop, "Pharmacist")
    assert owner_api(pharmacist).get(f"{base(shop)}/items/").status_code == 403
    # finance.view reads, but can't change anything.
    client = owner_api(accountant)
    assert client.get(f"{base(shop)}/items/").status_code == 200
    reply = client.post(f"{base(shop)}/items/{fridge.pk}/service/", {"on": "2026-11-07"})
    assert reply.status_code == 403
    shop.features = ["finance"]
    shop.save(update_fields=["features"])
    assert client.get(f"{base(shop)}/items/").status_code == 403


def test_settings_lock_the_rule_once_posted(shop, owner_api, owner, fridge):
    client = owner_api(owner)
    reply = client.get(f"{base(shop)}/settings/").json()
    assert reply["locked_rule"] is False  # its months so far are opening ones
    assert {group["code"] for group in reply["tax_groups"]} >= {"III", "V"}
    reply = client.patch(f"{base(shop)}/settings/", {"tax_book": True}, format="json")
    assert reply.status_code == 200 and reply.json()["tax_book"] is True
    page = client.get(f"{base(shop)}/items/{fridge.pk}/").json()
    assert page["tax"]["rate"] == "20.00" and page["tax"]["monthly"] == "140000.00"
    Asset.objects.filter(pk=fridge.pk).update(created_at=fridge.created_at.replace(year=2025))
    fridge.entries.update(opening=False)
    reply = client.patch(f"{base(shop)}/settings/", {"start_rule": "daily"}, format="json")
    assert reply.status_code == 400
