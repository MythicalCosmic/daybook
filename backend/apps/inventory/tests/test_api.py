"""The stock API: another company (404), a missing permission (403), cost fields absent without
finance.view, branch isolation, the module switch, and blind counts in both APIs."""

from datetime import date, timedelta

import pytest

from apps.inventory import services
from apps.inventory.models import GoodsReceipt, StockTransfer
from apps.inventory.tests.conftest import DAY, D, line, opening, receive

pytestmark = pytest.mark.django_db


def base(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/stock"


def app(company) -> str:
    return f"/api/v1/companies/{company.pk}/stock"


@pytest.fixture
def stocked(shop, owner, chilonzor, yunusobod, supplier, product):
    receive(shop, owner, chilonzor, supplier, [line(product, "C1", packs=5)], invoice="C-1")
    receive(shop, owner, yunusobod, supplier, [line(product, "Y1", packs=3)], invoice="Y-1")
    return product


def test_another_company_answers_404(shop, other_company, owner, owner_api, member):
    stranger = member(other_company, "Owner")
    client = owner_api(stranger)
    assert client.get(f"{base(shop)}/levels/").status_code == 404
    assert owner_api(owner).get(f"{base(other_company)}/levels/").status_code == 404


def test_reading_and_writing_need_their_permissions(
    shop, accountant, head, owner_api, stocked, chilonzor
):
    client = owner_api(accountant)  # sales.view and finance.view, no stock.manage
    assert client.get(f"{base(shop)}/levels/").status_code == 200
    receipt = GoodsReceipt.objects.filter(branch=chilonzor).first()
    assert (
        client.post(f"{base(shop)}/receipts/{receipt.pk}/void/", {"reason": "x"}).status_code == 403
    )
    assert (
        client.patch(f"{base(shop)}/settings/", {"fefo_strict": False}, format="json").status_code
        == 403
    )
    assert (
        client.get(
            f"{base(shop)}/journals/controlled/?branch={chilonzor.pk}&month=2026-10"
        ).status_code
        == 403
    )
    assert (
        owner_api(head)
        .patch(f"{base(shop)}/settings/", {"fefo_strict": False}, format="json")
        .status_code
        == 200
    )


def test_cost_fields_need_finance_view(shop, owner, head, owner_api, stocked, chilonzor):
    receipt = GoodsReceipt.objects.get(branch=chilonzor)
    seen = owner_api(owner).get(f"{base(shop)}/receipts/{receipt.pk}/").json()
    assert seen["receipt"]["total"] == "51700.00" and seen["lines"][0]["unit_cost"] == "10340.00"
    hidden = owner_api(head).get(f"{base(shop)}/receipts/{receipt.pk}/").json()
    assert "total" not in hidden["receipt"] and "debt_id" not in hidden["receipt"]
    assert "unit_cost" not in hidden["lines"][0] and "total" not in hidden["lines"][0]
    assert hidden["lines"][0]["retail_price"] == "13000.00"

    batches = owner_api(head).get(f"{base(shop)}/batches/").json()
    assert batches and all("unit_cost" not in row and "value" not in row for row in batches)
    product = owner_api(head).get(f"{base(shop)}/products/{stocked.pk}/").json()["product"]
    assert "cost_price" not in product
    summary = owner_api(head).get(f"{base(shop)}/summary/").json()
    assert "stock_value" not in summary and summary["stock_retail_value"]
    board = owner_api(head).get(f"{base(shop)}/expiry/?within=900").json()
    assert all("value" not in bucket for bucket in board["buckets"])


def test_branch_scope(shop, head, owner_api, stocked, chilonzor, yunusobod):
    client = owner_api(head)  # Chilonzor only
    levels = client.get(f"{base(shop)}/levels/").json()
    assert {row["branch"]["id"] for row in levels} == {chilonzor.pk}
    elsewhere = GoodsReceipt.objects.get(branch=yunusobod)
    assert client.get(f"{base(shop)}/receipts/{elsewhere.pk}/").status_code == 404
    assert client.get(f"{base(shop)}/levels/?branch={yunusobod.pk}").status_code == 404
    receipts = client.get(f"{base(shop)}/receipts/").json()
    assert [row["branch"]["id"] for row in receipts] == [chilonzor.pk]


def test_while_the_module_is_off(shop, owner, owner_api, api_as, ali):
    shop.features = ["finance"]
    shop.save(update_fields=["features"])
    assert owner_api(owner).get(f"{base(shop)}/levels/").status_code == 403
    assert owner_api(owner).get(f"{base(shop)}/settings/").status_code == 200
    assert api_as(ali).get(f"{app(shop)}/lookup/?q=para").status_code == 403


def test_a_receipt_from_draft_to_posted(
    shop, owner, ali, owner_api, api_as, supplier, product, chilonzor
):
    client = api_as(ali)
    reply = client.post(
        f"{app(shop)}/receipts/",
        {
            "supplier": supplier.pk,
            "supplier_invoice_number": "INV-77",
            "supplier_invoice_date": "2026-11-06",
        },
        format="json",
    )
    assert reply.status_code == 201, reply.json()
    receipt_id = reply.json()["id"]
    reply = client.post(
        f"{app(shop)}/receipts/{receipt_id}/lines/",
        {
            "product": product.pk,
            "series": "Z9",
            "expires_on": "2028-01-31",
            "packs": "4",
            "unit_cost": "9000",
        },
        format="json",
    )
    assert reply.status_code == 201, reply.json()
    assert "unit_cost" not in reply.json()["lines"][0]
    assert client.post(f"{app(shop)}/receipts/{receipt_id}/submit/").status_code == 200
    # The pharmacist can't post; the owner does.
    assert (
        owner_api(owner)
        .post(f"{base(shop)}/receipts/{receipt_id}/post/")
        .json()["receipt"]["status"]
        == "posted"
    )


def test_counts_are_blind(shop, owner, ali, head, owner_api, api_as, stocked, chilonzor):
    count = services.start_count(chilonzor, by=owner)
    [row] = count.lines.all()
    counter = api_as(ali).get(f"{app(shop)}/counts/{count.pk}/lines/").json()
    assert counter["lines"][0]["series"] == "C1"
    assert all("expected" not in line for line in counter["lines"])
    reply = api_as(ali).patch(
        f"{app(shop)}/counts/{count.pk}/lines/",
        {"lines": [{"line": row.pk, "counted": "9"}]},
        format="json",
    )
    assert reply.status_code == 200 and "expected" not in reply.json()["lines"][0]
    owner_view = owner_api(head).get(f"{base(shop)}/counts/{count.pk}/").json()
    assert all("expected" not in line for line in owner_view["lines"])  # open: blind for all
    owner_api(head).post(f"{base(shop)}/counts/{count.pk}/submit/")
    reviewed = owner_api(head).get(f"{base(shop)}/counts/{count.pk}/").json()
    assert reviewed["lines"][0]["expected"] == "10.000"
    assert reviewed["lines"][0]["difference"] == "-1.000"
    # Still blind for the counter after it was counted.
    after = api_as(ali).get(f"{app(shop)}/counts/{count.pk}/lines/").json()
    assert "expected" not in after["lines"][0]


def test_the_app_lookup_shows_my_pharmacy_first(shop, ali, api_as, stocked, yunusobod):
    rows = api_as(ali).get(f"{app(shop)}/lookup/?q=Parats").json()
    [row] = rows
    assert row["quantity"] == "10.000"
    assert row["elsewhere"] == [
        {"branch_id": yunusobod.pk, "branch": "Yunusobod", "quantity": "6.000"}
    ]
    detail = api_as(ali).get(f"{app(shop)}/products/{stocked.pk}/").json()
    assert [batch["series"] for batch in detail["batches"]] == ["C1"]
    assert "unit_cost" not in detail["batches"][0]


def test_receiving_a_transfer_in_the_app(
    shop, owner, nigora, api_as, stocked, chilonzor, yunusobod
):
    batch = stocked.batches.get(series="C1")
    transfer = services.create_transfer(
        shop,
        by=owner,
        from_branch=chilonzor,
        to_branch=yunusobod,
        lines=[{"product": stocked, "batch": batch, "quantity": D(2)}],
    )
    services.send_transfer(transfer, by=owner)
    incoming = api_as(nigora).get(f"{app(shop)}/transfers/incoming/").json()
    assert [row["transfer"]["id"] for row in incoming] == [transfer.pk]
    reply = api_as(nigora).post(f"{app(shop)}/transfers/{transfer.pk}/receive/", {}, format="json")
    assert reply.json()["transfer"]["status"] == StockTransfer.Status.RECEIVED


def test_expiry_action_proposes_a_write_off(shop, ali, api_as, chilonzor, product):
    old = opening(chilonzor, product, "OLD", expires_on=DAY - timedelta(days=2), quantity=2)
    stock = old.stocks.get(branch=chilonzor)
    rows = api_as(ali).get(f"{app(shop)}/expiry/").json()
    assert [row["series"] for row in rows] == ["OLD"] and rows[0]["expired"] is True
    reply = api_as(ali).post(
        f"{app(shop)}/batches/{stock.pk}/expiry-action/",
        {"action": "propose_writeoff"},
        format="json",
    )
    assert reply.status_code == 200 and reply.json()["writeoff_id"]


def test_the_act_and_the_journal_links(shop, owner, owner_api, chilonzor, yunusobod, product):
    old = opening(chilonzor, product, "E", expires_on=date(2026, 10, 1), quantity=2)
    writeoff = services.propose_writeoff(
        shop, by=owner, branch=chilonzor, reason="expired", lines=[{"batch": old, "quantity": 2}]
    )
    services.approve_writeoff(writeoff, by=owner)
    client = owner_api(owner)
    link = client.get(f"{base(shop)}/write-offs/{writeoff.pk}/act/?language=ru").json()
    assert link["url"].startswith("/api/v1/files/") and link["name"].endswith("-ru.pdf")
    file = client.get(link["url"])
    assert file.status_code == 200 and b"".join(file.streaming_content)[:4] == b"%PDF"
    link = client.get(
        f"{base(shop)}/journals/controlled/pdf/?branch={yunusobod.pk}&month=2026-10"
    ).json()
    assert link["url"].startswith("/api/v1/files/")


def test_settings_round_trip(shop, owner, owner_api):
    client = owner_api(owner)
    data = client.get(f"{base(shop)}/settings/").json()
    assert data["expiry_steps"] == [90, 60, 30] and data["rx_log"] is True
    assert data["rx_keep_months"]["narcotic"] == 60
    reply = client.patch(
        f"{base(shop)}/settings/",
        {
            "expiry_steps": [30, 120],
            "rx_max_markup_percent": "15.00",
            "rx_keep_months": {"regular": 6},
        },
        format="json",
    )
    assert reply.status_code == 200, reply.json()
    data = reply.json()
    assert data["expiry_steps"] == [120, 30] and data["rx_max_markup_percent"] == "15.00"
    assert data["rx_keep_months"]["regular"] == 6 and data["rx_keep_months"]["benefit"] == 36


def test_a_distributor_starts_without_the_prescription_log(company):
    from apps.inventory import conf

    company.business_kind = "distributor"
    company.save(update_fields=["business_kind"])
    assert conf.get_settings(company).rx_log is False


def test_the_app_says_which_medicine_a_batch_is_and_in_parts(shop, ali, api_as, chilonzor, product):
    """The mini app's expiry check names the medicine and reads quantities in packs and parts."""
    opening(chilonzor, product, "OLD", expires_on=DAY - timedelta(days=2), quantity=2)
    [row] = api_as(ali).get(f"{app(shop)}/expiry/").json()
    assert row["product"] == {"id": product.pk, "name": product.name}
    assert row["units_per_pack"] == product.units_per_pack
    assert row["part_label"] == product.part_label


def test_the_app_lookup_reads_form_strength_and_nearest_expiry(shop, ali, api_as, stocked):
    [row] = api_as(ali).get(f"{app(shop)}/lookup/?q=Parats").json()
    assert (row["dosage_form"], row["strength"]) == (stocked.dosage_form, stocked.strength)
    assert row["nearest_expiry"] is not None
    detail = api_as(ali).get(f"{app(shop)}/products/{stocked.pk}/").json()["product"]
    assert detail["nearest_expiry"] == row["nearest_expiry"]


def test_the_app_lists_open_counts_and_distributors(
    shop, owner, ali, api_as, stocked, chilonzor, supplier
):
    count = services.start_count(chilonzor, by=owner)
    [open_count] = api_as(ali).get(f"{app(shop)}/counts/").json()
    assert open_count["id"] == count.pk and open_count["counted"] == 0
    assert open_count["lines"] == count.lines.count()
    assert "expected" not in open_count
    distributors = api_as(ali).get(f"{app(shop)}/suppliers/").json()
    assert {"id": supplier.pk, "name": supplier.name} in distributors
    settings = api_as(ali).get(f"{app(shop)}/settings/").json()
    assert settings["expiry_steps"] == [90, 60, 30]
