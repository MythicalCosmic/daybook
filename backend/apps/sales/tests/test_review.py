"""Review fixes: bad filters are 400s, ids in payloads stay inside the company and the caller's
branches, list endpoints don't grow a query per row, USD companies, fees on loose receipts,
cash groups hear about handovers, and the contracts other packages code against."""

import inspect
import json
from decimal import Decimal
from unittest import mock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.finance import services as finance
from apps.finance.models import LIVE_STATUSES, MoneyAccount, Transaction
from apps.members.permissions import Perm
from apps.sales import queries, services
from apps.sales.models import CashMovement, Sale
from apps.sales.tests.factories import jpeg, make_member, make_shop, open_and_close, scoped_role


def owner_url(company, path: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/sales/{path}"


def app_url(company, path: str) -> str:
    return f"/api/v1/companies/{company.pk}/sales/{path}"


@pytest.fixture
def branch_lead(shop):
    """Sees and manages sales, but only in Yunusobod."""
    role = scoped_role(shop.company, Perm.SALES_VIEW, Perm.SALES_MANAGE)
    lead = make_member(shop.company, "Owner", branches=(shop.other_branch,))
    lead.role = role
    lead.save(update_fields=["role"])
    return lead


# Filters --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "shifts/?from=yesterday",
        "shifts/?to=2026-13-40",
        "shifts/?register=abc",
        "cash-movements/?shift=x",
        "cash-movements/?register=1;drop",
        "cash-movements/?from=nope",
        "entries/?shift=abc",
        "entries/?from=31.10.2026",
    ],
)
def test_bad_filters_answer_400_not_a_server_error(shop, owner_api, path):
    response = owner_api(shop.owner).get(owner_url(shop.company, path))
    assert response.status_code == 400


def test_good_filters_still_filter(shop, owner_api):
    closed = open_and_close(shop)
    client = owner_api(shop.owner)
    day = closed.business_day.isoformat()
    rows = client.get(owner_url(shop.company, f"shifts/?from={day}&to={day}")).json()["results"]
    assert [row["id"] for row in rows] == [closed.pk]
    rows = client.get(owner_url(shop.company, f"shifts/?register={shop.other_register.pk}")).json()
    assert rows["count"] == 0
    assert client.get(owner_url(shop.company, "entries/?kind=whatever")).status_code == 200


def test_movement_days_follow_the_company_calendar(shop, owner_api):
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="500000")
    movement = services.record_movement(
        by=shop.cashier, register=shop.register, kind="to_safe", amount="100000"
    )
    from apps.sales.days import local

    day = local(shop.company, movement.created_at).date().isoformat()
    client = owner_api(shop.owner)
    rows = client.get(owner_url(shop.company, f"cash-movements/?from={day}&to={day}")).json()
    assert [row["id"] for row in rows["results"]] == [movement.pk]


# Ids in payloads ------------------------------------------------------------------------------


def test_ids_from_another_company_are_refused(shop, owner_api, api_as):
    other = make_shop()
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="0")
    shift = shop.cashier.cash_shifts.get(status="open")
    app = api_as(shop.cashier)
    stranger = other.manager
    response = app.post(
        app_url(shop.company, f"shifts/{shift.pk}/movements/"),
        {"kind": "handover", "amount": "1000", "receiver_id": stranger.pk},
        format="json",
    )
    assert response.status_code == 400 and "receiver_id" in response.json()
    from apps.finance.models import Category

    category = Category.objects.get(company=other.company, system_code="goods")
    response = app.post(
        app_url(shop.company, f"shifts/{shift.pk}/movements/"),
        {"kind": "payout", "amount": "1000", "reason": "x", "category_id": category.pk},
        format="json",
    )
    assert response.status_code == 400 and "category_id" in response.json()
    response = app.post(
        app_url(shop.company, f"shifts/{shift.pk}/close/"),
        {
            "payments": json.dumps([{"method_id": other.method("cash").pk, "sales": "1"}]),
            "counted_cash": "0",
            "z_photo": jpeg(),
        },
        format="multipart",
    )
    assert response.status_code == 400
    account = MoneyAccount.objects.filter(company=other.company).first()
    response = owner_api(shop.owner).post(
        owner_url(shop.company, "cash-movements/"),
        {
            "register_id": shop.register.pk,
            "kind": "to_bank",
            "amount": "1000",
            "to_account_id": account.pk,
        },
        format="json",
    )
    assert response.status_code == 400 and "to_account_id" in response.json()
    assert not CashMovement.objects.filter(kind="to_bank").exists()


def test_the_other_account_must_be_in_the_callers_branches(shop, owner_api, branch_lead):
    services.open_shift(by=shop.colleague, register=shop.other_register, opening_float="900000")
    company_bank = finance.create_account(
        shop.company, by=shop.owner, kind="bank", name="Kapitalbank"
    )
    branch_bank = finance.create_account(
        shop.company, by=shop.owner, kind="bank", name="Yunusobod bank", branch=shop.other_branch
    )
    client = owner_api(branch_lead)
    body = {"register_id": shop.other_register.pk, "kind": "to_bank", "amount": "100000"}
    refused = client.post(
        owner_url(shop.company, "cash-movements/"),
        {**body, "to_account_id": company_bank.pk},
        format="json",
    )
    assert refused.status_code == 400 and "to_account_id" in refused.json()
    done = client.post(
        owner_url(shop.company, "cash-movements/"),
        {**body, "to_account_id": branch_bank.pk},
        format="json",
    )
    assert done.status_code == 201
    # The owner sees every branch, so a company-level account is fine for them.
    owner = owner_api(shop.owner).post(
        owner_url(shop.company, "cash-movements/"),
        {**body, "to_account_id": company_bank.pk},
        format="json",
    )
    assert owner.status_code == 201


def test_a_target_for_someone_outside_the_branches_is_refused(shop, owner_api, branch_lead):
    client = owner_api(branch_lead)
    refused = client.post(
        owner_url(shop.company, "targets/"),
        {"month": "2026-10-01", "amount": "1000000", "member_id": shop.cashier.pk},
        format="json",
    )
    assert refused.status_code == 400 and "member_id" in refused.json()
    done = client.post(
        owner_url(shop.company, "targets/"),
        {"month": "2026-10-01", "amount": "1000000", "member_id": shop.colleague.pk},
        format="json",
    )
    assert done.status_code == 201


def test_another_branchs_records_are_404_for_a_branch_lead(shop, owner_api, branch_lead):
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="500000")
    movement = services.record_movement(
        by=shop.cashier, register=shop.register, kind="to_safe", amount="100000"
    )
    sale = services.record_sale(
        by=shop.owner,
        payments=[(shop.method("cash"), "50000")],
        branch=shop.branch,
        source=Sale.Source.DASHBOARD,
    )
    client = owner_api(branch_lead)
    assert client.get(owner_url(shop.company, f"cash-movements/{movement.pk}/")).status_code == 404
    voided = client.post(
        owner_url(shop.company, f"cash-movements/{movement.pk}/void/"), {"reason": "x"}
    )
    assert voided.status_code == 404
    assert client.get(owner_url(shop.company, f"entries/{sale.pk}/")).status_code == 404
    voided = client.post(owner_url(shop.company, f"entries/{sale.pk}/void/"), {"reason": "x"})
    assert voided.status_code == 404


def test_a_huge_receipt_count_is_a_400(shop, api_as):
    shift = services.open_shift(by=shop.cashier, register=shop.register, opening_float="0")
    response = api_as(shop.cashier).post(
        app_url(shop.company, f"shifts/{shift.pk}/close/"),
        {
            "payments": json.dumps(
                [{"method_id": shop.method("cash").pk, "sales": "1", "receipts": 10**12}]
            ),
            "counted_cash": "1",
            "z_photo": jpeg(),
        },
        format="multipart",
    )
    assert response.status_code == 400


# Query counts ---------------------------------------------------------------------------------


def _queries(client, path: str) -> int:
    with CaptureQueriesContext(connection) as context:
        response = client.get(path)
    assert response.status_code == 200, response.content
    return len(context.captured_queries)


def _busy_day(shop, count: int) -> None:
    for _ in range(count):
        open_and_close(shop)
        open_and_close(shop, cashier=shop.colleague, register=shop.other_register)
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="100000")
    services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind="handover",
        amount="1000",
        receiver=shop.manager,
    )
    for _ in range(count):
        services.record_movement(
            by=shop.cashier, register=shop.register, kind="to_safe", amount="1000"
        )
        services.record_sale(
            by=shop.owner,
            payments=[(shop.method("cash"), "50000"), (shop.method("uzcard"), "10000")],
            branch=shop.other_branch,
            source=Sale.Source.DASHBOARD,
        )


OWNER_LISTS = [
    "shifts/",
    "cash-movements/",
    "entries/",
    "registers/",
    "today/",
    "cash/positions/",
    "options/",
    "payment-methods/",
]


@pytest.mark.parametrize("path", OWNER_LISTS)
def test_owner_lists_dont_grow_a_query_per_row(path, db, owner_api):
    small, big = make_shop(), make_shop()
    _busy_day(small, 1)
    _busy_day(big, 4)
    # A third till in each branch of the big shop, so per-till work would show.
    services.create_register(big.company, by=big.owner, branch=big.branch, name="Kassa 2")
    services.create_register(big.company, by=big.owner, branch=big.other_branch, name="Kassa 2")
    few = _queries(owner_api(small.owner), owner_url(small.company, path))
    many = _queries(owner_api(big.owner), owner_url(big.company, path))
    assert many <= few + 2, f"{path}: {few} queries for a few rows, {many} for more"


@pytest.mark.parametrize("path", ["shifts/", "shifts/current/"])
def test_kassa_lists_dont_grow_a_query_per_row(path, db, api_as):
    small, big = make_shop(), make_shop()
    for _ in range(1):
        open_and_close(small)
    for _ in range(5):
        open_and_close(big)
    few = _queries(api_as(small.cashier), app_url(small.company, path))
    many = _queries(api_as(big.cashier), app_url(big.company, path))
    assert many <= few + 1, f"{path}: {few} queries for one shift, {many} for five"


def test_batched_till_amounts_match_one_by_one(shop):
    from apps.sales import cash
    from apps.sales.models import CashShift, Register

    open_and_close(shop, counted="1190000")
    shift = services.open_shift(by=shop.cashier, register=shop.register, opening_float="1190000")
    services.record_movement(
        by=shop.cashier, register=shop.register, kind="payout", amount="90000", reason="Non"
    )
    services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind="handover",
        amount="300000",
        receiver=shop.manager,
    )
    registers = list(Register.objects.filter(company=shop.company))
    open_shifts = {
        row.register_id: row
        for row in CashShift.objects.filter(status="open", company=shop.company)
    }
    batched = cash.tills_now(registers, open_shifts)
    for register in registers:
        assert batched[register.pk] == cash.till_now(register, open_shifts.get(register.pk))
    assert batched[shop.register.pk] == Decimal("800000.00")
    assert shift.pk in {s.pk for s in open_shifts.values()}


# Money in other currencies, fees, groups, offboarding -----------------------------------------


def test_a_usd_company_hands_cash_over_in_dollars(db):
    shop = make_shop(base_currency="USD")
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="500")
    movement = services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind="handover",
        amount="200",
        receiver=shop.manager,
    )
    movement = services.confirm_handover(movement, by=shop.manager)
    held = MoneyAccount.objects.get(holder=shop.manager, kind="employee")
    assert held.currency == "USD" and held.balance == Decimal("200.00")
    assert movement.transfer.amount_in == Decimal("200.00")


def test_a_dashboard_receipt_books_the_providers_fee(shop):
    uzcard = shop.method("uzcard")
    uzcard.fee_percent = Decimal("1.00")
    uzcard.save(update_fields=["fee_percent"])
    sale = services.record_sale(
        by=shop.owner,
        payments=[(uzcard, "200000"), (shop.method("cash"), "50000")],
        branch=shop.branch,
        source=Sale.Source.DASHBOARD,
    )
    rows = Transaction.objects.filter(
        source_type="sales.sale", source_id=sale.pk, status__in=LIVE_STATUSES
    )
    by_key = {row.source_key: row for row in rows}
    assert by_key[f"f{uzcard.pk}"].amount == Decimal("-2000.00")
    assert by_key[f"f{uzcard.pk}"].category.system_code == "bank_fees"
    assert f"f{shop.method('cash').pk}" not in by_key
    services.void_sale(sale, by=shop.owner, reason="Typed twice")
    assert not rows.filter(status__in=LIVE_STATUSES).exists()


def test_handover_answers_reach_the_cash_groups(shop, django_capture_on_commit_callbacks):
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="900000")
    first = services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind="handover",
        amount="300000",
        receiver=shop.manager,
    )
    second = services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind="handover",
        amount="100000",
        receiver=shop.manager,
    )
    with (
        mock.patch("apps.sales.alerts.broadcast") as broadcast,
        django_capture_on_commit_callbacks(execute=True),
    ):
        services.confirm_handover(first, by=shop.manager)
        services.decline_handover(second, by=shop.manager, reason="Not in the envelope")
    texts = [call.args[2] for call in broadcast.call_args_list]
    assert [call.args[1] for call in broadcast.call_args_list] == ["cash", "cash"]
    assert "✓" in texts[0] and "300" in texts[0]
    assert "NOT" in texts[1]


def test_group_posts_escape_names(shop, django_capture_on_commit_callbacks):
    shop.branch.name = "Chilonzor <b>"
    shop.branch.save(update_fields=["name"])
    with (
        mock.patch("apps.sales.alerts.broadcast") as broadcast,
        django_capture_on_commit_callbacks(execute=True),
    ):
        open_and_close(shop)
    text = broadcast.call_args.args[2]
    assert "&lt;b&gt;" in text


def test_offboarding_lists_cash_the_person_holds(shop):
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="900000")
    movement = services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind="handover",
        amount="250000",
        receiver=shop.manager,
    )
    services.confirm_handover(movement, by=shop.manager)
    step = queries.offboard_preview(shop.manager)
    assert any("250" in line for line in step.lines)
    assert step.blockers == []


# Contracts other packages code against blindly -------------------------------------------------


def test_contract_signatures():
    def keyword_only(func) -> set[str]:
        return {
            name
            for name, param in inspect.signature(func).parameters.items()
            if param.kind is param.KEYWORD_ONLY
        }

    def positional(func) -> list[str]:
        return [
            name
            for name, param in inspect.signature(func).parameters.items()
            if param.kind is param.POSITIONAL_OR_KEYWORD
        ]

    assert positional(queries.summary) == ["company", "start", "end", "group_by"]
    assert "branch_ids" in keyword_only(queries.summary)
    assert inspect.signature(queries.summary).parameters["branch_ids"].default is inspect._empty
    assert positional(queries.shifts) == ["company", "filters", "limit"]
    assert keyword_only(queries.shifts) == {"branch_ids"}
    assert positional(queries.cashier_scorecard) == ["company", "start", "end"]
    assert keyword_only(queries.cashier_scorecard) == {"branch_ids"}
    assert positional(services.record_ai_reading) == ["shift"]
    assert keyword_only(services.record_ai_reading) == {"reading", "mismatch"}
    from apps.sales import signals

    assert signals.shift_closed and signals.shift_verified
