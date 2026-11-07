"""Sale lines imported from the cash-register software (PLAN-OWNER §14.7), against the
acceptance of §14.7: idempotent on the receipt's external id, line facts and never money,
one row per batch, the match list, refunds into quarantine, the legal price check once per
branch and day, the day check, and the W2.a stock stub (lines without a batch or a cost)."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.exceptions import DomainError
from apps.finance.models import Transaction
from apps.inbox.models import Notification
from apps.inventory.services import Allocation
from apps.inventory.tests.factories import ProductFactory, StockBatchFactory
from apps.sales import importer, lines, queries, rollup, services
from apps.sales.models import (
    DailySales,
    PosCashier,
    Sale,
    SaleLine,
    SalesImport,
    SalesSettings,
)
from apps.sales.tests.factories import open_and_close

TASHKENT = ZoneInfo("Asia/Tashkent")
HEADER = (
    "Чек;Дата;Касса;Кассир;Штрихкод;Наименование;Кол-во;Ед.;Цена;Скидка;Сумма;Оплата;"
    "Возврат;Серия;Рецепт;Основание"
)
COLUMNS = {
    "receipt": "Чек",
    "sold_at": "Дата",
    "register": "Касса",
    "cashier": "Кассир",
    "code": "Штрихкод",
    "name": "Наименование",
    "quantity": "Кол-во",
    "unit": "Ед.",
    "price": "Цена",
    "discount": "Скидка",
    "total": "Сумма",
    "payment": "Оплата",
    "refund": "Возврат",
    "series": "Серия",
    "rx_number": "Рецепт",
    "refund_of": "Основание",
}
PARACETAMOL = "4780000000017"
AMOXICILLIN = "4780000000024"
UNKNOWN = "4780000000999"


def line(
    receipt="101",
    when="21.10.2026 10:15",
    register="1",
    cashier="K01",
    code=PARACETAMOL,
    name="Paratsetamol 500 mg №20",
    quantity="1",
    unit="уп",
    price="12900",
    discount="0",
    total="12900",
    payment="Naqd",
    refund="",
    series="",
    rx="",
    refund_of="",
) -> str:
    return ";".join(
        [
            receipt,
            when,
            register,
            cashier,
            code,
            name,
            quantity,
            unit,
            price,
            discount,
            total,
            payment,
            refund,
            series,
            rx,
            refund_of,
        ]
    )


def csv_file(*rows: str, encoding="utf-8") -> SimpleUploadedFile:
    text = "\n".join([HEADER, *rows]) + "\n"
    return SimpleUploadedFile("export.csv", text.encode(encoding), content_type="text/csv")


@pytest.fixture
def pharmacy(shop):
    """The shop with imported sale lines on, two medicines in the catalogue and a profile."""
    SalesSettings.objects.filter(company=shop.company).update(
        sales_lines=SalesSettings.Lines.IMPORT
    )
    shop.paracetamol = ProductFactory(
        company=shop.company, barcode=PARACETAMOL, units_per_pack=2, rx_required=False
    )
    shop.amoxicillin = ProductFactory(
        company=shop.company,
        name="Amoksitsillin 500 mg kapsula №16",
        inn="amoxicillin",
        barcode=AMOXICILLIN,
        units_per_pack=2,
        rx_required=True,
        reference_price=Decimal("12000.00"),
        sale_price=Decimal("12000.00"),
    )
    shop.profile = services.create_import_profile(
        shop.company,
        by=shop.owner,
        name="Apteka Pro",
        file_kind="csv",
        columns=COLUMNS,
        branch=shop.branch,
    )
    return shop


def run(shop, *rows, commit=None) -> SalesImport:
    """Upload a file and read it, as the background job does. With `commit` (the
    `django_capture_on_commit_callbacks` fixture) what runs after commit runs too (the
    notifications)."""
    imp = services.start_import(shop.profile, by=shop.owner, file=csv_file(*rows))
    if commit is None:
        lines.process(imp.pk)
    else:
        with commit(execute=True):
            lines.process(imp.pk)
    imp.refresh_from_db()
    return imp


# Reading files ------------------------------------------------------------------------------


def test_the_mapper_guesses_russian_headers_and_reads_russian_numbers():
    headers = HEADER.split(";")
    guessed = importer.guess(headers)
    assert guessed["receipt"] == "Чек" and guessed["code"] == "Штрихкод"
    assert guessed["quantity"] == "Кол-во" and guessed["total"] == "Сумма"
    assert guessed["date"] == "Дата" and "sold_at" not in guessed
    assert importer.amount("1 234,50") == Decimal("1234.50")
    assert importer.amount("1,234.50") == Decimal("1234.50")
    assert importer.amount("(12)") == Decimal("-12")
    assert importer.unit("Блистер", "pack") == "part" and importer.unit("уп", "part") == "pack"


def test_a_windows_1251_file_with_a_title_row_reads(pharmacy):
    data = ("Отчёт о продажах\n" + HEADER + "\n" + line() + "\n").encode("cp1251")
    layout = lines.layout(pharmacy.profile)
    layout.header_row = 2
    found, problems = importer.rows(data, layout, timezone="Asia/Tashkent", needs_branch=False)
    assert problems == []
    [row] = found
    assert row.name == "Paratsetamol 500 mg №20" and row.total == Decimal("12900.00")
    assert row.sold_at == datetime(2026, 10, 21, 10, 15, tzinfo=TASHKENT)


def test_an_xlsx_export_reads_like_a_csv(pharmacy):
    import io

    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(HEADER.split(";"))
    sheet.append(
        [
            "7",
            datetime(2026, 10, 21, 9, 5),
            "2",
            "K02",
            int(PARACETAMOL),
            "Paratsetamol",
            2,
            "уп",
            12900,
            0,
            25800,
            "Uzcard",
            None,
            None,
            None,
            None,
        ]
    )
    buffer = io.BytesIO()
    book.save(buffer)
    layout = lines.layout(pharmacy.profile)
    layout.file_kind = "xlsx"
    [row], problems = importer.rows(
        buffer.getvalue(), layout, timezone="Asia/Tashkent", needs_branch=False
    )
    assert problems == [] and row.code == PARACETAMOL and row.quantity == 2
    assert row.total == Decimal("25800.00") and row.register == "2"


def test_a_profile_must_name_what_an_import_needs(pharmacy):
    with pytest.raises(DomainError):
        services.create_import_profile(
            pharmacy.company, by=pharmacy.owner, name="Broken", columns={"receipt": "Чек"}
        )
    # Without a fixed branch the file needs a branch column.
    with pytest.raises(DomainError):
        services.create_import_profile(
            pharmacy.company, by=pharmacy.owner, name="No branch", columns=COLUMNS
        )


# The acceptance of §14.7 --------------------------------------------------------------------


def test_with_sale_lines_off_no_import_runs(pharmacy):
    SalesSettings.objects.filter(company=pharmacy.company).update(
        sales_lines=SalesSettings.Lines.NONE
    )
    with pytest.raises(DomainError):
        services.start_import(pharmacy.profile, by=pharmacy.owner, file=csv_file(line()))
    # An import queued before the switch went off reads nothing.
    imp = SalesImport.objects.create(
        company=pharmacy.company, profile=pharmacy.profile, file="sales/imports/x.csv"
    )
    lines.process(imp.pk)
    imp.refresh_from_db()
    assert imp.status == SalesImport.Status.FAILED
    assert not Sale.objects.filter(company=pharmacy.company).exists()
    assert not SaleLine.objects.exists()


def test_the_same_file_twice_adds_nothing_and_numbers_repeat_per_day_and_register(pharmacy):
    rows = (
        line(receipt="1", when="21.10.2026 10:00", register="1"),
        line(receipt="1", when="21.10.2026 10:05", register="2"),  # another till, same number
        line(receipt="1", when="22.10.2026 09:00", register="1"),  # the next day, same number
        line(receipt="2", when="21.10.2026 11:00", quantity="2", total="25800"),
    )
    first = run(pharmacy, *rows)
    assert first.status == SalesImport.Status.READY
    assert (first.receipts, first.lines, first.matched, first.duplicates) == (4, 4, 4, 0)
    again = run(pharmacy, *rows)
    assert again.status == SalesImport.Status.READY
    assert (again.receipts, again.matched, again.duplicates) == (0, 0, 4)
    assert Sale.objects.filter(company=pharmacy.company, source="import").count() == 4
    assert SaleLine.objects.count() == 4
    ids = set(Sale.objects.values_list("external_id", flat=True))
    profile = pharmacy.profile.pk
    assert f"{profile}:1:2026-10-21:1" in ids and f"{profile}:2:2026-10-21:1" in ids
    assert f"{profile}:1:2026-10-22:1" in ids


def test_a_file_with_a_pharmacy_column_keeps_each_pharmacys_receipts(pharmacy):
    """Two pharmacies whose tills are both "1" restart their numbers every day: receipt 1 of
    each is its own receipt, and the file again adds nothing."""
    profile = services.create_import_profile(
        pharmacy.company,
        by=pharmacy.owner,
        name="Chain export",
        columns={**COLUMNS, "branch": "Аптека"},
    )
    header = HEADER + ";Аптека"
    rows = [line(receipt="1") + ";CHL", line(receipt="1") + ";Yunusobod", line() + ";Sergeli"]
    text = "\n".join([header, *rows]) + "\n"

    def upload():
        imp = services.start_import(
            profile,
            by=pharmacy.owner,
            file=SimpleUploadedFile("chain.csv", text.encode(), content_type="text/csv"),
        )
        lines.process(imp.pk)
        imp.refresh_from_db()
        return imp

    first = upload()
    assert (first.receipts, first.duplicates) == (2, 0)
    assert first.problems == [{"row": 4, "message": "Unknown branch Sergeli."}]
    assert set(Sale.objects.filter(sales_import=first).values_list("branch_id", flat=True)) == {
        pharmacy.branch.pk,
        pharmacy.other_branch.pk,
    }
    again = upload()
    assert (again.receipts, again.duplicates) == (0, 2)


def test_a_long_external_id_is_its_sha1():
    long = lines.external_id(12, "Kassa-" + "x" * 40, date(2026, 10, 21), "R" * 30)
    assert len(long) == 40 and ":" not in long
    assert lines.external_id(12, "1", date(2026, 10, 21), "55") == "12:1:2026-10-21:55"


def test_an_import_changes_no_money(pharmacy):
    closed = open_and_close(pharmacy, cash_sales="1000000", card_sales="500000")
    day = closed.business_day
    stamp = day.strftime("%d.%m.%Y")

    def ledger():
        return sorted(
            Transaction.objects.filter(company=pharmacy.company).values_list(
                "pk", "kind", "amount", "status"
            )
        )

    def tills():
        return list(
            DailySales.objects.filter(company=pharmacy.company).values_list(
                "branch_id", "day", "sales", "refunds", "net", "receipts", "by_method"
            )
        )

    before_ledger, before_tills = ledger(), tills()
    summary_before = queries.summary(pharmacy.company, day, day, "day", branch_ids=None)
    run(
        pharmacy,
        line(receipt="5", when=f"{stamp} 12:00", quantity="10", total="129000"),
        line(receipt="6", when=f"{stamp} 12:30", code=AMOXICILLIN, total="12000"),
        line(receipt="7", when=f"{stamp} 13:00", refund="1", total="12900"),
    )
    assert Sale.objects.filter(company=pharmacy.company, source="import").count() == 3
    rollup.rebuild_day(pharmacy.branch.pk, day)
    rollup.rebuild_range(pharmacy.company, day - timedelta(days=1), day + timedelta(days=1))
    assert ledger() == before_ledger
    assert tills() == before_tills
    summary_after = queries.summary(pharmacy.company, day, day, "day", branch_ids=None)
    assert summary_after["totals"] == summary_before["totals"]
    # Today's figures and the hour chart don't count them either.
    today = queries._today_net(pharmacy.company, None, day)
    assert today[pharmacy.branch.pk]["net"] == Decimal("1500000.00")
    # And they never show among single receipts, nor can they be voided as money.
    imported = Sale.objects.filter(company=pharmacy.company, source="import").first()
    with pytest.raises(DomainError):
        services.void_sale(imported, by=pharmacy.owner, reason="test")


def test_with_the_w2a_stub_lines_have_no_batch_and_no_cost(pharmacy):
    imp = run(pharmacy, line(quantity="1", unit="уп", total="12900"))
    [row] = SaleLine.objects.filter(sale__sales_import=imp)
    assert row.status == SaleLine.Status.MATCHED and row.product_id == pharmacy.paracetamol.pk
    assert row.batch_id is None and row.cost is None
    # Counted in parts: one pack of two blisters.
    assert row.quantity == Decimal("2.000") and row.parts_per_pack == 2 and row.unit == "pack"
    sale = row.sale
    assert sale.shift_id is None and sale.register_id is None and sale.source == "import"


def test_a_line_spanning_two_batches_is_two_rows_whose_costs_add_up(pharmacy):
    first = StockBatchFactory(product=pharmacy.paracetamol, unit_cost=Decimal("10000.00"))
    second = StockBatchFactory(product=pharmacy.paracetamol, unit_cost=Decimal("11000.00"))
    allocations = [
        Allocation(first.pk, Decimal("1"), Decimal("5000.00")),
        Allocation(second.pk, Decimal("2"), Decimal("5500.00")),
    ]
    with mock.patch("apps.sales.lines.stock.deduct", return_value=allocations) as deduct:
        imp = run(pharmacy, line(quantity="3", unit="блистер", price="6450", total="19350"))
    args, kwargs = deduct.call_args
    assert args[1] == pharmacy.paracetamol and args[2] == Decimal("3.000")
    sale = Sale.objects.get(sales_import=imp)
    assert kwargs["document"] == ("sales.sale", sale.pk) and kwargs["kind"] == "sale"
    rows = list(SaleLine.objects.filter(sale=sale).order_by("pk"))
    assert [r.line_number for r in rows] == [1, 1]
    assert [r.batch_id for r in rows] == [first.pk, second.pk]
    assert [r.quantity for r in rows] == [Decimal("1"), Decimal("2")]
    assert [r.cost for r in rows] == [Decimal("5000.00"), Decimal("11000.00")]
    assert sum(r.total for r in rows) == Decimal("19350.00")
    assert sum(r.cost for r in rows) == Decimal("16000.00")
    assert imp.matched == 1  # one receipt line


def test_the_files_series_is_passed_to_the_stock(pharmacy):
    with mock.patch(
        "apps.sales.lines.stock.deduct", return_value=[Allocation(None, Decimal("2"), None)]
    ) as deduct:
        run(pharmacy, line(series="230415"))
    assert deduct.call_args.kwargs["series"] == "230415"


def test_an_unmatched_code_waits_and_matching_it_once_settles_every_waiting_line(pharmacy):
    imp = run(
        pharmacy,
        line(receipt="1", code=UNKNOWN, name="Ibuprofen 200 mg №10", quantity="1"),
        line(receipt="2", code=UNKNOWN, name="Ibuprofen 200 mg №10", quantity="2", total="9000"),
        line(receipt="3"),
    )
    assert (imp.matched, imp.unmatched) == (1, 2)
    assert queries.unmatched_count(pharmacy.owner) == 2
    [code] = lines.codes(pharmacy.company, branch_ids=None)
    assert code["code"] == UNKNOWN and code["lines"] == 2
    ibuprofen = ProductFactory(company=pharmacy.company, barcode="", units_per_pack=1)
    with (
        mock.patch("apps.sales.lines.stock.remember_code") as remember,
        mock.patch(
            "apps.sales.lines.stock.deduct",
            side_effect=lambda b, p, q, **k: [Allocation(None, q, None)],
        ) as deduct,
    ):
        done = services.match_code(
            pharmacy.company, by=pharmacy.owner, code=UNKNOWN, product=ibuprofen
        )
    assert done == 2
    remember.assert_called_once_with(ibuprofen, by=pharmacy.owner, kind="pos", code=UNKNOWN)
    assert deduct.call_count == 2
    rows = SaleLine.objects.filter(code=UNKNOWN)
    assert set(rows.values_list("status", flat=True)) == {SaleLine.Status.MATCHED}
    assert sorted(rows.values_list("quantity", flat=True)) == [Decimal("1"), Decimal("2")]
    assert queries.unmatched_count(pharmacy.owner) == 0
    imp.refresh_from_db()
    assert (imp.matched, imp.unmatched) == (3, 0)


def test_a_code_that_isnt_goods_can_be_skipped(pharmacy):
    run(pharmacy, line(code="PAKET", name="Paket"))
    assert services.skip_code(pharmacy.company, by=pharmacy.owner, code="PAKET") == 1
    assert queries.unmatched_count(pharmacy.owner) == 0
    assert SaleLine.objects.get(code="PAKET").status == SaleLine.Status.SKIPPED


def test_refunds_land_in_quarantine_with_the_original_receipts_batches(pharmacy):
    batch = StockBatchFactory(product=pharmacy.paracetamol, unit_cost=Decimal("10000.00"))
    with mock.patch(
        "apps.sales.lines.stock.deduct",
        return_value=[Allocation(batch.pk, Decimal("2"), Decimal("5000.00"))],
    ):
        run(pharmacy, line(receipt="40", when="21.10.2026 10:00"))
    with mock.patch("apps.sales.lines.stock.restock") as restock:
        imp = run(
            pharmacy,
            line(receipt="41", when="21.10.2026 15:00", refund="да", refund_of="40"),
            line(receipt="42", when="21.10.2026 16:00", quantity="-1", total="-12900"),
        )
    assert imp.receipts == 2
    refunds = Sale.objects.filter(company=pharmacy.company, kind="refund").order_by("number")
    assert [s.number for s in refunds] == ["41", "42"]
    first, second = restock.call_args_list
    assert first.kwargs["status"] == "quarantine" and second.kwargs["status"] == "quarantine"
    assert first.kwargs["document"] == ("sales.sale", refunds[0].pk)
    # The named receipt's batch goes back; an unnamed refund goes back without one.
    assert first.args[1] == [Allocation(batch.pk, Decimal("2.000"), Decimal("5000.00"))]
    assert second.args[1] == [Allocation(None, Decimal("2.000"), None)]


def test_an_rx_line_with_a_prescription_goes_to_the_prescription_log(pharmacy):
    with mock.patch("apps.sales.lines.stock.record_rx") as record_rx:
        run(pharmacy, line(code=AMOXICILLIN, total="12000", rx="R-778"), line(receipt="9"))
    [call] = record_rx.call_args_list
    row = SaleLine.objects.get(product=pharmacy.amoxicillin)
    assert call.kwargs["document"] == ("sales.saleline", row.pk)
    assert call.kwargs["prescription_number"] == "R-778"
    assert call.kwargs["product"] == pharmacy.amoxicillin and call.kwargs["quantity"] == 2


def test_an_rx_line_above_its_cap_is_listed_and_told_once_per_branch_and_day(
    pharmacy, django_capture_on_commit_callbacks
):
    commit = django_capture_on_commit_callbacks
    rows = (
        # Reference price 12 000 a pack: 13 500 is above it, 12 000 isn't.
        line(receipt="1", when="21.10.2026 10:00", code=AMOXICILLIN, total="13500"),
        line(receipt="2", when="21.10.2026 11:00", code=AMOXICILLIN, total="12000"),
        # One blister of two at 6 500 is 13 000 a pack: above.
        line(
            receipt="3",
            when="21.10.2026 12:00",
            code=AMOXICILLIN,
            quantity="1",
            unit="блистер",
            total="6500",
        ),
        # An OTC item has no cap.
        line(receipt="4", when="21.10.2026 12:30", total="99000"),
    )
    imp = run(pharmacy, *rows, commit=commit)
    assert imp.breaches == 2
    found = queries.cap_breaches(
        pharmacy.company, date(2026, 10, 21), date(2026, 10, 21), branch_ids=None
    )
    assert sorted(row["pack_price"] for row in found) == ["13000.00", "13500.00"]
    assert {row["cap"] for row in found} == {"12000.00"}
    told = Notification.objects.filter(kind="sales.price_cap_breach")
    assert set(told.values_list("recipient_id", flat=True)) == {
        pharmacy.owner.pk,
        pharmacy.manager.pk,
    }
    assert told.count() == 2  # one per person, for this branch and day
    assert "2" in told.first().title
    # Another file of the same day tells nobody again.
    run(
        pharmacy,
        line(receipt="5", when="21.10.2026 18:00", code=AMOXICILLIN, total="14000"),
        commit=commit,
    )
    assert Notification.objects.filter(kind="sales.price_cap_breach").count() == 2
    # Another branch or day is its own notification.
    run(
        pharmacy,
        line(receipt="6", when="22.10.2026 10:00", code=AMOXICILLIN, total="14000"),
        commit=commit,
    )
    assert Notification.objects.filter(kind="sales.price_cap_breach").count() == 4


def test_the_batch_cap_is_its_cost_plus_the_legal_markup(pharmacy):
    batch = StockBatchFactory(product=pharmacy.amoxicillin, unit_cost=Decimal("9000.00"))
    with mock.patch(
        "apps.sales.lines.stock.deduct",
        return_value=[Allocation(batch.pk, Decimal("2"), Decimal("4500.00"))],
    ):
        imp = run(pharmacy, line(code=AMOXICILLIN, total="11000"))
    row = SaleLine.objects.get(sale__sales_import=imp)
    # 9 000 at 20 % = 10 800, below the reference price of 12 000.
    assert row.cap == Decimal("10800.00") and row.over_cap is True


def test_the_day_check_against_hand_computed_tills(pharmacy):
    closed = open_and_close(pharmacy, cash_sales="100000", card_sales="0", receipts=3)
    day = closed.business_day
    stamp = day.strftime("%d.%m.%Y")
    imp = run(
        pharmacy,
        line(receipt="1", when=f"{stamp} 10:00", total="60000"),
        line(receipt="2", when=f"{stamp} 11:00", total="40000"),
        line(receipt="3", when=f"{stamp} 12:00", refund="1", total="4000"),
    )
    [check] = imp.day_check
    # Imported 60 000 + 40 000 - 4 000 = 96 000 against the tills' 100 000: 96 %, flagged.
    assert check["imported"] == "96000.00" and check["tills"] == "100000.00"
    assert check["coverage"] == "96.0" and check["gap"] == "-4000.00" and check["flagged"]
    # 99.5 % is within the 1 % tolerance.
    [close] = lines.day_check(pharmacy.company, [(pharmacy.branch.pk, day)])
    assert close["flagged"]
    run(pharmacy, line(receipt="4", when=f"{stamp} 13:00", total="3500"))
    [close] = lines.day_check(pharmacy.company, [(pharmacy.branch.pk, day)])
    assert close["imported"] == "99500.00" and close["coverage"] == "99.5"
    assert not close["flagged"]


def test_cashier_codes_map_to_people_once_and_earlier_receipts_follow(pharmacy):
    run(pharmacy, line(cashier="K07"))
    pos = PosCashier.objects.get(company=pharmacy.company, code="K07")
    sale = Sale.objects.get(company=pharmacy.company, source="import")
    assert sale.pos_cashier_id == pos.pk and sale.cashier_id is None
    services.map_cashier(pos, by=pharmacy.owner, membership=pharmacy.cashier)
    sale.refresh_from_db()
    assert sale.cashier_id == pharmacy.cashier.pk
    run(pharmacy, line(receipt="77", cashier="K07"))
    assert Sale.objects.get(number="77").cashier_id == pharmacy.cashier.pk


def test_line_facts_for_the_analytics(pharmacy):
    run(pharmacy, line(receipt="1"), line(receipt="2", code=UNKNOWN))
    facts = queries.line_facts(
        pharmacy.company, date(2026, 10, 21), date(2026, 10, 21), branch_ids=None
    )
    [row] = facts  # the waiting line isn't a fact yet
    assert row.sale.branch == pharmacy.branch and row.sale.business_day == date(2026, 10, 21)
    assert (
        queries.line_facts(
            pharmacy.company, date(2026, 10, 21), date(2026, 10, 21), branch_ids=[]
        ).count()
        == 0
    )


def test_a_failed_file_tells_who_uploaded_it(pharmacy, django_capture_on_commit_callbacks):
    bad = SimpleUploadedFile("x.csv", b"just;some;words\n1;2;3\n", content_type="text/csv")
    with django_capture_on_commit_callbacks(execute=True):
        imp = services.start_import(pharmacy.profile, by=pharmacy.owner, file=bad)
    imp.refresh_from_db()
    assert imp.status == SalesImport.Status.FAILED and imp.error
    [told] = Notification.objects.filter(kind="sales.import_failed")
    assert told.recipient_id == pharmacy.owner.pk


def test_the_settings_say_where_lines_come_from_and_the_step_is_done(pharmacy):
    company = pharmacy.company
    SalesSettings.objects.filter(company=company).update(sales_lines_confirmed_at=None)
    assert not queries.lines_told(company)
    services.update_settings(company, by=pharmacy.owner, sales_lines="none")
    assert queries.lines_told(company)
    with pytest.raises(DomainError):
        services.update_settings(company, by=pharmacy.owner, sales_lines="receipts")
