"""The Should parts: price tags, a distributor's invoice into receipt lines, the prescription
log, pricing rules and the branch list for transfers."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.inventory import journals, queries, services
from apps.inventory.models import PricingRule, RxRecord
from apps.inventory.tests.conftest import DAY, D, line, opening, receive
from apps.inventory.tests.factories import ProductFactory

pytestmark = pytest.mark.django_db


def base(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/stock"


def test_price_tags(shop, owner, owner_api, chilonzor, product, rx):
    opening(chilonzor, product, "A", expires_on=date(2027, 5, 1), quantity=4)
    opening(chilonzor, rx, "R", expires_on=date(2027, 5, 1), quantity=4)
    assert journals.price_tags_pdf(chilonzor, [product, rx], language="uz")[:4] == b"%PDF"
    changed = queries.price_changes(shop, chilonzor, DAY)
    assert {row.pk for row in changed} == {product.pk, rx.pk}
    reply = owner_api(owner).post(
        f"{base(shop)}/price-tags/", {"branch": chilonzor.pk}, format="json"
    )
    assert reply.status_code == 200, reply.json()
    assert reply.json()["name"].endswith(".pdf")


def test_an_invoice_spreadsheet_becomes_lines(
    shop, owner, owner_api, chilonzor, supplier, product, rx
):
    receipt = services.create_receipt(
        shop,
        by=owner,
        branch=chilonzor,
        supplier=supplier,
        supplier_invoice_number="X-1",
        supplier_invoice_date=DAY,
    )
    services.remember_code(rx, by=owner, kind="supplier", code="KK-77", supplier=supplier)
    text = (
        "Kod;Nomi;Seriya;Yaroqlilik muddati;Soni;Narx\n"
        f"KK-77;Amoks;RX1;31.12.2027;5;10340\n"
        f";{product.name};P1;12.2027;3;10 000\n"
        ";Unknown thing;U1;2027-01-01;2;5000\n"
        ";No expiry;N1;;2;5000\n"
    )
    upload = SimpleUploadedFile("invoice.csv", text.encode(), content_type="text/csv")
    client = owner_api(owner)
    reply = client.post(
        f"{base(shop)}/receipts/{receipt.pk}/lines/import/",
        {"file": upload, "dry_run": "true"},
        format="multipart",
    )
    assert reply.status_code == 200, reply.json()
    result = reply.json()
    assert [row["action"] for row in result["rows"]] == ["add", "add", "unmatched", "skip"]
    assert receipt.lines.count() == 0
    upload.seek(0)
    result = client.post(
        f"{base(shop)}/receipts/{receipt.pk}/lines/import/",
        {"file": upload, "dry_run": "false"},
        format="multipart",
    ).json()
    assert result["added"] == 2
    lines = {row.product_id: row for row in receipt.lines.all()}
    assert lines[rx.pk].expires_on == date(2027, 12, 31) and lines[rx.pk].packs == 5
    assert lines[product.pk].expires_on == date(2027, 12, 31)
    assert lines[product.pk].unit_cost == D(10000)
    supplier.supplier_profile.refresh_from_db()
    assert supplier.supplier_profile.price_list_mapping["invoice"]["Soni"] == "packs"


def test_the_prescription_log(shop, owner, nigora, owner_api, yunusobod, rx):
    record = services.record_rx(
        by=nigora,
        branch=yunusobod,
        product=rx,
        quantity=Decimal(2),
        prescription_number="148-77",
        prescribed_on=DAY,
        prescriber="Dr. A",
        rx_kind="regular",
        document=("sales.saleline", 5),
    )
    assert record is not None and record.keep_until == date(2027, 2, 7)
    again = services.record_rx(
        by=nigora,
        branch=yunusobod,
        product=rx,
        quantity=Decimal(2),
        prescription_number="148-78",
        document=("sales.saleline", 5),
    )
    assert again.pk == record.pk and RxRecord.objects.count() == 1
    assert (
        services.record_rx(
            by=nigora, branch=yunusobod, product=ProductFactory(company=shop), quantity=1
        )
        is None
    )
    rows = (
        owner_api(owner)
        .get(f"{base(shop)}/journals/rx/?branch={yunusobod.pk}&month=2026-11")
        .json()["rows"]
    )
    # An antibiotic of the e-prescription group without an e-prescription id is flagged.
    rx.e_rx_group = True
    rx.save()
    rows = (
        owner_api(owner)
        .get(f"{base(shop)}/journals/rx/?branch={yunusobod.pk}&month=2026-11")
        .json()["rows"]
    )
    assert rows[0]["flags"] == ["no_e_prescription"]
    assert services.journal_pdf("rx", branch=yunusobod, month=DAY, language="ru")[:4] == b"%PDF"


def test_a_pricing_rule_sets_the_markup(shop, owner, chilonzor, supplier, product):
    PricingRule.objects.create(
        company=shop, cost_from=D(5000), cost_to=D(20000), markup_percent=D(40), order=1
    )
    receive(shop, owner, chilonzor, supplier, [line(product, "PR1", cost="10000")])
    batch = product.batches.get(series="PR1")
    assert batch.retail_price == D("14000.00")


def test_every_branch_for_a_transfer(shop, head, owner_api, chilonzor, yunusobod):
    rows = owner_api(head).get(f"{base(shop)}/branches/").json()
    assert {(row["name"], row["in_scope"]) for row in rows} == {
        ("Chilonzor", True),
        ("Yunusobod", False),
    }
