"""Stock documents (docs/PLAN-OWNER.md §14.6.2 and its acceptance): receipts and their payable,
transfers, write-offs and the destruction act, counts, recalls and the controlled register."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.exceptions import DomainError
from apps.core.uploads import sanitize_image
from apps.finance.models import Debt, Transaction
from apps.inventory import queries, register, services
from apps.inventory.models import (
    BatchStock,
    ControlledPeriod,
    GoodsReceipt,
    RecallNotice,
    StockBatch,
    StockCount,
    StockLevel,
    StockMovement,
    StockTransfer,
    WriteOff,
)
from apps.inventory.tests.conftest import DAY, TZ, D, line, local, opening, receive
from apps.inventory.tests.factories import ProductFactory
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


def held(branch, batch) -> Decimal:
    row = BatchStock.objects.filter(branch=branch, batch=batch).first()
    return row.quantity if row else Decimal(0)


def photo():
    from io import BytesIO

    from PIL import Image

    data = BytesIO()
    Image.new("RGB", (8, 8), "white").save(data, "PNG")
    return sanitize_image(SimpleUploadedFile("p.png", data.getvalue(), content_type="image/png"))


# Receipts -----------------------------------------------------------------------------------


def test_posting_opens_one_payable_due_after_the_terms(shop, owner, chilonzor, supplier, product):
    receipt = receive(
        shop,
        owner,
        chilonzor,
        supplier,
        [line(product, "A1", packs=10, cost="10340")],
        invoice_date=date(2026, 10, 5),
    )
    assert receipt.status == GoodsReceipt.Status.POSTED
    assert receipt.number == "KR-CHL-0001"
    assert receipt.total == D("103400.00")
    assert receipt.due_on == date(2026, 11, 4)  # invoice 05.10.2026, 30 days
    debt = Debt.objects.get(pk=receipt.debt_id)
    assert (debt.direction, debt.kind, debt.amount, debt.due_on) == (
        "payable",
        "trade",
        D("103400.00"),
        date(2026, 11, 4),
    )
    assert debt.counterparty_id == supplier.pk and debt.branch_id == chilonzor.pk
    assert (debt.source_type, debt.source_id) == ("inventory.goodsreceipt", receipt.pk)
    accrual = Transaction.objects.get(debt=debt)
    assert accrual.category.system_code == "goods" and accrual.amount == D("-103400.00")

    # A retried post opens none and changes nothing.
    again = services.post_receipt(receipt, by=owner)
    assert again.debt_id == debt.pk
    assert Debt.objects.count() == 1 and StockBatch.objects.count() == 1
    batch = StockBatch.objects.get()
    assert batch.receipt_line.receipt_id == receipt.pk and held(chilonzor, batch) == 20
    product.refresh_from_db()
    assert product.cost_price == D("10340.00") and product.sale_price == D("13000.00")


def test_without_finance_no_payable_is_opened(shop, owner, chilonzor, supplier, product):
    shop.features = ["stock"]
    shop.save(update_fields=["features"])
    receipt = receive(shop, owner, chilonzor, supplier, [line(product)])
    assert receipt.status == GoodsReceipt.Status.POSTED and receipt.debt_id is None
    assert not Debt.objects.exists()


def test_receipt_warnings(shop, owner, chilonzor, supplier, product, rx):
    services.add_opening_stock(
        chilonzor,
        by=owner,
        product=product,
        series="OLD",
        expires_on=DAY + timedelta(days=400),
        quantity=2,
        unit_cost=D(10000),
    )
    rx.registration_until = date(2026, 1, 1)
    rx.save()
    services.register_recall(
        shop,
        by=owner,
        series="BAD-1",
        reason="Sifatsiz",
        source="Rejected series list No. 12, 01.11.2026",
        received_on=DAY,
        product=rx,
    )
    receipt = receive(
        shop,
        owner,
        chilonzor,
        supplier,
        [
            line(product, "SHORT", expires_on=DAY + timedelta(days=100), cost="11500"),
            line(rx, "BAD-1", supplier_rx=True),
            line(product, "OK", cost="10200", supplier_rx=True),
        ],
        post=False,
    )
    warnings = [set(row.warnings) for row in receipt.lines.order_by("order")]
    assert warnings[0] == {"short_shelf_life", "cost_jump"}
    assert warnings[1] == {"recalled_series", "registration_expired"}
    assert warnings[2] == {"rx_flag_mismatch"}
    receipt = services.post_receipt(receipt, by=owner)
    assert receipt.status == GoodsReceipt.Status.POSTED  # warnings never block
    recalled = StockBatch.objects.get(series="BAD-1")
    assert recalled.status == StockBatch.Status.RECALLED


def test_a_controlled_item_is_refused_at_an_unlicensed_branch(
    shop, owner, chilonzor, yunusobod, supplier
):
    narcotic = ProductFactory(company=shop, control_class="narcotic", rx_required=True)
    with pytest.raises(DomainError, match="isn't licensed"):
        receive(shop, owner, chilonzor, supplier, [line(narcotic)])
    starred = ProductFactory(company=shop, control_class="strong", restricted_channel=True)
    with pytest.raises(DomainError):
        receive(shop, owner, chilonzor, supplier, [line(starred)], invoice="N-2")
    chilonzor.social_pharmacy = True
    chilonzor.save()
    receive(shop, owner, chilonzor, supplier, [line(starred)], invoice="N-3")
    receive(shop, owner, yunusobod, supplier, [line(narcotic)], invoice="N-4")


def test_void_only_while_no_batch_moved(shop, owner, chilonzor, supplier, product):
    receipt = receive(shop, owner, chilonzor, supplier, [line(product, "V1", packs=5)])
    services.deduct(chilonzor, product, 1, by=None, document=("sales.sale", 1))
    with pytest.raises(DomainError, match="already sold"):
        services.void_receipt(receipt, by=owner, reason="Wrong invoice")

    other = receive(shop, owner, chilonzor, supplier, [line(product, "V2", packs=5)], invoice="N-2")
    debt = Debt.objects.get(pk=other.debt_id)
    voided = services.void_receipt(other, by=owner, reason="Wrong invoice")
    assert voided.status == GoodsReceipt.Status.VOID
    debt.refresh_from_db()
    assert debt.status == Debt.Status.CANCELLED
    batch = StockBatch.objects.get(series="V2")
    assert held(chilonzor, batch) == 0
    assert StockLevel.objects.get(branch=chilonzor, product=product).quantity == 9


def test_a_paid_payable_refuses_the_void(shop, owner, chilonzor, supplier, product):
    receipt = receive(shop, owner, chilonzor, supplier, [line(product, "P1")])
    Debt.objects.filter(pk=receipt.debt_id).update(paid=D(1000))
    with pytest.raises(DomainError, match="already paid"):
        services.void_receipt(receipt, by=owner, reason="Mistake")


def test_one_invoice_number_per_distributor(shop, owner, chilonzor, supplier, product):
    receive(shop, owner, chilonzor, supplier, [line(product)], invoice="N-7")
    with pytest.raises(DomainError, match="already in"):
        receive(shop, owner, chilonzor, supplier, [line(product)], invoice="N-7", post=False)


# Transfers -----------------------------------------------------------------------------------


def test_a_transfer_moves_the_same_batches(shop, owner, chilonzor, yunusobod, product):
    a = opening(chilonzor, product, "A", expires_on=date(2027, 1, 31), quantity=4)
    b = opening(chilonzor, product, "B", expires_on=date(2027, 6, 30), quantity=10)
    transfer = services.create_transfer(
        shop,
        by=owner,
        from_branch=chilonzor,
        to_branch=yunusobod,
        lines=[{"product": product, "quantity": D(6)}],
    )
    transfer = services.send_transfer(transfer, by=owner)
    assert transfer.number == "TR-CHL-0001"
    assert held(chilonzor, a) == 0 and held(chilonzor, b) == 8
    lines = list(transfer.lines.order_by("pk"))
    assert [(row.batch_id, row.quantity_sent) for row in lines] == [(a.pk, 4), (b.pk, 2)]

    transfer = services.receive_transfer(transfer, by=owner)
    assert transfer.status == StockTransfer.Status.RECEIVED
    assert held(yunusobod, a) == 4 and held(yunusobod, b) == 2


def test_a_short_receipt_makes_it_disputed(shop, owner, chilonzor, yunusobod, product):
    a = opening(chilonzor, product, "A", expires_on=date(2027, 1, 31), quantity=10)
    transfer = services.create_transfer(
        shop,
        by=owner,
        from_branch=chilonzor,
        to_branch=yunusobod,
        lines=[{"product": product, "batch": a, "quantity": D(6)}],
    )
    services.send_transfer(transfer, by=owner)
    [row] = transfer.lines.all()
    transfer = services.receive_transfer(transfer, by=owner, received={row.pk: D(4)})
    assert transfer.status == StockTransfer.Status.DISPUTED
    assert held(yunusobod, a) == 4 and held(chilonzor, a) == 4

    transfer = services.resolve_transfer(transfer, by=owner, outcome="shortage")
    assert transfer.status == StockTransfer.Status.RECEIVED
    writeoff = WriteOff.objects.get(transfer=transfer)
    assert writeoff.reason == "shortage" and writeoff.value == D("10340.00")  # 2 parts = 1 pack
    assert held(chilonzor, a) == 4  # already left when it was sent


def test_an_expired_batch_isnt_sent(shop, owner, chilonzor, yunusobod, product):
    old = opening(chilonzor, product, "OLD", expires_on=date(2026, 11, 1), quantity=4)
    transfer = services.create_transfer(
        shop,
        by=owner,
        from_branch=chilonzor,
        to_branch=yunusobod,
        lines=[{"product": product, "batch": old, "quantity": D(2)}],
    )
    with pytest.raises(DomainError, match="expired"):
        services.send_transfer(transfer, by=owner)


# Write-offs ------------------------------------------------------------------------------------


def test_write_off_and_destruction(shop, owner, head, chilonzor, product):
    old = opening(chilonzor, product, "EXP", expires_on=date(2026, 10, 31), quantity=6)
    ledger_before = Transaction.objects.count()
    writeoff = services.propose_writeoff(
        shop,
        by=head,
        branch=chilonzor,
        reason="expired",
        lines=[{"batch": old, "quantity": D(6)}],
        files=[(photo(), "photo")],
    )
    assert writeoff.status == WriteOff.Status.PROPOSED and held(chilonzor, old) == 6
    writeoff = services.approve_writeoff(writeoff, by=owner)
    assert writeoff.status == WriteOff.Status.APPROVED
    assert writeoff.number == "AKT-CHL-0001"
    assert writeoff.value == D("31020.00")  # 3 packs at 10 340
    assert writeoff.destroy_by == DAY + timedelta(days=30)
    assert held(chilonzor, old) == 0
    movement = StockMovement.objects.get(kind="writeoff")
    assert movement.unit_cost == D("5170.00") and movement.quantity == -6
    assert Transaction.objects.count() == ledger_before  # no ledger row

    members = [
        {"name": f"Member {index}", "organisation": "Org", "role": "r"} for index in range(4)
    ]
    kwargs = {
        "method": "incinerate",
        "place": "Toshkent, Sergeli",
        "destroyed_at": local(DAY, 11),
        "responsible": "Bekzod Mirzayev",
        "order_number": "12-B",
        "sent_to": ["Sanitary inspection"],
    }
    with pytest.raises(DomainError, match="at least 5"):
        services.mark_destroyed(writeoff, by=owner, commission=members, **kwargs)
    members.append({"name": "Member 5", "organisation": "Org", "role": "r"})
    writeoff = services.mark_destroyed(writeoff, by=owner, commission=members, **kwargs)
    assert writeoff.status == WriteOff.Status.DESTROYED
    writeoff.act_pdf.open("rb")
    assert writeoff.act_pdf.read(4) == b"%PDF"
    writeoff.act_pdf.close()
    from apps.inventory import journals

    assert journals.act_pdf(writeoff, language="ru")[:4] == b"%PDF"


def test_a_destruction_needs_a_photo(shop, owner, chilonzor, product):
    old = opening(chilonzor, product, "EXP", expires_on=date(2026, 10, 31), quantity=2)
    writeoff = services.propose_writeoff(
        shop, by=owner, branch=chilonzor, reason="damaged", lines=[{"batch": old, "quantity": 2}]
    )
    services.approve_writeoff(writeoff, by=owner)
    members = [{"name": f"M{index}"} for index in range(5)]
    with pytest.raises(DomainError, match="photo"):
        services.mark_destroyed(
            writeoff,
            by=owner,
            method="crush",
            place="Here",
            destroyed_at=local(DAY),
            responsible="R",
            order_number="1",
            commission=members,
        )


def test_without_approval_a_write_off_is_approved_at_once(shop, owner, chilonzor, product):
    from apps.inventory import conf

    settings = conf.get_settings(shop)
    settings.writeoff_approval = False
    settings.save()
    batch = opening(chilonzor, product, "A", expires_on=date(2027, 1, 1), quantity=2)
    writeoff = services.propose_writeoff(
        shop,
        by=owner,
        branch=chilonzor,
        reason="internal_use",
        lines=[{"batch": batch, "quantity": 1}],
    )
    assert writeoff.status == WriteOff.Status.APPROVED and writeoff.destroy_by is None


# Counts ---------------------------------------------------------------------------------------


def test_a_count_books_the_differences_at_cost(shop, owner, ali, chilonzor, product):
    a = opening(chilonzor, product, "A", expires_on=date(2027, 1, 31), quantity=10)
    b = opening(chilonzor, product, "B", expires_on=date(2027, 6, 30), quantity=4)
    count = services.start_count(chilonzor, by=owner, kind="full")
    lines = {line.batch_id: line for line in count.lines.all()}
    services.record_counted(count, by=ali, counted={lines[a.pk].pk: D(7), lines[b.pk].pk: D(4)})
    services.add_found(
        count, by=ali, product=product, series="NEW", expires_on=date(2027, 9, 1), counted=2
    )
    services.submit_count(count, by=ali)
    count = services.apply_count(count, by=owner)
    assert count.status == StockCount.Status.APPLIED
    assert count.value_difference == D("-15510.00") + D("10340.00")  # 3 parts short, 2 found
    assert held(chilonzor, a) == 7
    found = StockBatch.objects.get(series="NEW")
    assert held(chilonzor, found) == 2 and found.receipt_line_id is None
    assert queries.last_applied_count(chilonzor, kind="full") == count.applied_at


def test_a_big_shortage_tells_the_owners(
    shop, owner, ali, chilonzor, product, django_capture_on_commit_callbacks
):
    from apps.inbox.models import Notification

    a = opening(chilonzor, product, "A", expires_on=date(2027, 1, 31), quantity=40, cost=10000)
    count = services.start_count(chilonzor, by=owner)
    [row] = count.lines.all()
    services.record_counted(count, by=ali, counted={row.pk: D(20)})
    with django_capture_on_commit_callbacks(execute=True):
        services.apply_count(count, by=owner)
    assert held(chilonzor, a) == 20
    [note] = Notification.objects.filter(kind="inventory.count_shortage")
    assert note.recipient_id == owner.pk


# Recalls --------------------------------------------------------------------------------------


def test_a_recall_finds_the_series_everywhere(
    shop, owner, head, chilonzor, yunusobod, product, nigora
):
    a = opening(chilonzor, product, "230415", expires_on=date(2027, 3, 1), quantity=6)
    opening(yunusobod, product, "230415", expires_on=date(2027, 3, 1), quantity=2)
    yunusobod.manager = nigora
    yunusobod.save()
    recall = services.register_recall(
        shop,
        by=owner,
        series="230415",
        reason="Falsified",
        source="Rejected series list No. 7, 05.11.2026",
        received_on=DAY,
        inn_or_name="paracetamol",
    )
    batches = StockBatch.objects.filter(series="230415")
    assert {batch.status for batch in batches} == {StockBatch.Status.RECALLED}
    assert sorted(row["branch"] for row in recall.found) == ["Chilonzor", "Yunusobod"]
    tasks = Task.objects.filter(company=shop, created_by__isnull=True)
    assert tasks.count() == 2
    assert {task.assignee_id for task in tasks} == {head.pk, nigora.pk}
    assert all("230415" in task.title for task in tasks)
    with pytest.raises(DomainError):
        services.close_recall(recall, by=owner)
    for branch in (chilonzor, yunusobod):
        batch = BatchStock.objects.get(branch=branch, batch__series="230415").batch
        writeoff = services.propose_writeoff(
            shop,
            by=owner,
            branch=branch,
            reason="recall",
            lines=[{"batch": batch, "quantity": held(branch, batch)}],
            recall=recall,
        )
        services.approve_writeoff(writeoff, by=owner)
    recall.refresh_from_db()
    assert recall.status == RecallNotice.Status.CLOSED
    assert (
        services.deduct(chilonzor, product, 1, by=None, document=("sales.sale", 9))[0].batch_id
        is None
    )
    assert held(chilonzor, a) == 0


# The controlled register -------------------------------------------------------------------------


def test_the_register_balances_and_closes(
    shop, owner, nigora, yunusobod, supplier, freeze, django_capture_on_commit_callbacks
):
    drug = ProductFactory(
        company=shop,
        name="Tramadol 50 mg kapsula №10",
        control_class="psychotropic",
        rx_required=True,
        units_per_pack=1,
    )
    freeze(datetime(2026, 9, 20, 12, tzinfo=TZ))
    opening(yunusobod, drug, "T0", expires_on=date(2027, 12, 1), quantity=5)
    freeze(datetime(2026, 10, 3, 12, tzinfo=TZ))
    receive(
        shop,
        owner,
        yunusobod,
        supplier,
        [line(drug, "T1", packs=10)],
        invoice_date=date(2026, 10, 3),
    )
    freeze(datetime(2026, 10, 10, 12, tzinfo=TZ))
    services.deduct(yunusobod, drug, 4, by=None, document=("sales.sale", 1))
    batch = StockBatch.objects.get(series="T1")
    writeoff = services.propose_writeoff(
        shop, by=owner, branch=yunusobod, reason="damaged", lines=[{"batch": batch, "quantity": 1}]
    )
    services.approve_writeoff(writeoff, by=owner)

    [row] = register.rows(yunusobod, date(2026, 10, 1))
    assert (row["opening"], row["received"], row["issued"], row["written_off"]) == (5, 10, 4, 1)
    assert row["closing"] == row["opening"] + row["received"] - row["issued"] - row["written_off"]
    assert row["closing"] == 10

    freeze(datetime(2026, 11, 2, 9, tzinfo=TZ))
    with pytest.raises(DomainError):
        register.close_month(yunusobod, date(2026, 11, 1), by=nigora)
    with django_capture_on_commit_callbacks(execute=True):
        [period] = register.close_month(
            yunusobod, date(2026, 10, 1), by=nigora, counted={drug.pk: D(9)}
        )
    assert period.difference == -1 and period.closing == 10
    from apps.inbox.models import Notification

    assert Notification.objects.filter(kind="inventory.controlled_mismatch").exists()
    register.mark_reported(period, by=owner, reported_on=date(2026, 11, 3))
    with pytest.raises(DomainError):
        register.close_month(yunusobod, date(2026, 10, 1), by=nigora)
    assert ControlledPeriod.objects.get().reported_on == date(2026, 11, 3)
    from apps.inventory import journals

    assert (
        journals.pdf("controlled", branch=yunusobod, month=date(2026, 10, 1), language="uz")[:4]
        == b"%PDF"
    )
