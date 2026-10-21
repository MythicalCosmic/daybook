"""Owner endpoints under `sales/`: permissions (200/403), another company (404), the module
switch, branch isolation (§2.6), hidden fields and money as strings."""

from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.members.permissions import Perm
from apps.sales import services
from apps.sales.models import CashMovement, CashShift, PaymentMethod, Register, SalesSettings
from apps.sales.tests.factories import make_member, make_shop, open_and_close, scoped_role


def url(company, path: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/sales/{path}"


@pytest.fixture
def closed(shop):
    return open_and_close(shop, counted="1185000")  # 15 000 short


@pytest.fixture
def branch_lead(shop):
    """Sees and manages sales, but only in Yunusobod."""
    role = scoped_role(shop.company, Perm.SALES_VIEW, Perm.SALES_MANAGE)
    lead = make_member(shop.company, "Owner", branches=(shop.other_branch,))
    lead.role = role
    lead.save(update_fields=["role"])
    return lead


@pytest.fixture
def viewer(shop):
    role = scoped_role(shop.company, Perm.SALES_VIEW, Perm.BRANCHES_ALL)
    member = make_member(shop.company, "Owner", branches=(shop.branch,))
    member.role = role
    member.save(update_fields=["role"])
    return member


READS = [
    "settings/",
    "payment-methods/",
    "registers/",
    "targets/",
    "today/",
    "summary/",
    "daily/",
    "cashiers/",
    "shifts/",
    "cash/positions/",
    "cash-movements/",
    "entries/",
    "options/",
]


@pytest.mark.parametrize("path", READS)
def test_reads_need_sales_view_and_hide_other_companies(
    shop, owner_api, other_company, member, path
):
    assert owner_api(shop.owner).get(url(shop.company, path)).status_code == 200
    no_sales = scoped_role(shop.company, Perm.BRANCHES_ALL)
    person = make_member(shop.company, "Owner")
    person.role = no_sales
    person.save(update_fields=["role"])
    assert owner_api(person).get(url(shop.company, path)).status_code == 403
    stranger = member(other_company, "Owner")
    assert owner_api(stranger).get(url(shop.company, path)).status_code == 404


def test_endpoints_vanish_while_the_module_is_off(shop, owner_api):
    shop.company.features = ["finance"]
    shop.company.save(update_fields=["features"])
    assert owner_api(shop.owner).get(url(shop.company, "today/")).status_code == 404


def test_a_mini_app_token_is_refused(shop, api_as):
    assert api_as(shop.owner).get(url(shop.company, "today/")).status_code == 401


def test_writes_need_sales_manage(shop, owner_api, viewer, closed):
    client = owner_api(viewer)
    assert (
        client.patch(
            url(shop.company, "settings/"), {"cash_tolerance": "1000"}, format="json"
        ).status_code
        == 403
    )
    assert (
        client.post(url(shop.company, f"shifts/{closed.pk}/verify/"), {}, format="json").status_code
        == 403
    )
    assert (
        client.post(
            url(shop.company, "registers/"), {"name": "X", "branch_id": shop.branch.pk}
        ).status_code
        == 403
    )
    assert (
        client.post(
            url(shop.company, "payment-methods/"), {"name": "X", "kind": "card"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            url(shop.company, "targets/"), {"month": "2026-10-01", "amount": "1"}
        ).status_code
        == 403
    )


# Shifts ---------------------------------------------------------------------------------------


def test_shift_list_and_detail_send_money_as_strings(shop, owner_api, closed):
    client = owner_api(shop.owner)
    data = client.get(url(shop.company, "shifts/")).json()
    [row] = data["results"]
    assert row["code"] == closed.code and row["net"] == "1500000.00"
    assert row["difference"] == "-15000.00" and row["counted_cash"] == "1185000.00"
    detail = client.get(url(shop.company, f"shifts/{closed.pk}/")).json()
    assert detail["cash_flow"]["expected"] == "1200000.00"
    assert {p["method"]["name"] for p in detail["payments"]} == {"Cash", "Uzcard"}
    assert detail["z_photo"].startswith("/api/v1/files/")
    assert detail["actions"] == {
        "verify": True,
        "dispute": True,
        "correct": True,
        "force_close": False,
    }
    kinds = [event["kind"] for event in detail["timeline"]]
    assert kinds[0] == "opened" and "closed" in kinds
    # The owner holds finance.view: the shift's ledger rows are listed.
    assert {row["key"] for row in detail["ledger"]} >= {"diff", "float"}


def test_ledger_rows_need_finance_view(shop, owner_api, closed):
    detail = owner_api(shop.manager).get(url(shop.company, f"shifts/{closed.pk}/")).json()
    assert detail["ledger"] == []


def test_shift_filters(shop, owner_api, closed):
    open_and_close(shop, cashier=shop.colleague, register=shop.other_register)
    client = owner_api(shop.owner)
    assert (
        client.get(url(shop.company, f"shifts/?branch={shop.other_branch.pk}")).json()["count"] == 1
    )
    assert client.get(url(shop.company, "shifts/?has_difference=true")).json()["count"] == 1
    assert client.get(url(shop.company, f"shifts/?q={closed.code}")).json()["count"] == 1
    assert client.get(url(shop.company, "shifts/?status=verified")).json()["count"] == 0


def test_verify_dispute_correct_and_force_close(shop, owner_api, closed):
    client = owner_api(shop.manager)
    response = client.post(url(shop.company, f"shifts/{closed.pk}/dispute/"), {}, format="json")
    assert response.status_code == 400  # a reason is required
    response = client.post(
        url(shop.company, f"shifts/{closed.pk}/dispute/"), {"reason": "Photo blurry"}, format="json"
    )
    assert response.json()["status"] == "disputed"
    response = client.patch(
        url(shop.company, f"shifts/{closed.pk}/payments/"),
        {
            "reason": "Cash total typo",
            "payments": [
                {"method_id": shop.method("cash").pk, "sales": "985000"},
                {"method_id": shop.method("uzcard").pk, "sales": "500000"},
            ],
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["difference"] == "0.00"
    response = client.post(
        url(shop.company, f"shifts/{closed.pk}/verify/"), {"note": "OK"}, format="json"
    )
    assert response.json()["status"] == "verified"
    assert AuditLog.objects.filter(
        target_type="cashshift", target_id=closed.pk, action="sales.shift_corrected"
    ).exists()

    shift = services.open_shift(by=shop.colleague, register=shop.other_register, opening_float="0")
    response = client.post(
        url(shop.company, f"shifts/{shift.pk}/force-close/"), {"reason": "Went home"}, format="json"
    )
    assert response.json()["forced"] is True and response.json()["status"] == "closed"


def test_queue_items_carry_working_actions(shop, owner_api, closed):
    client = owner_api(shop.manager)
    items = client.get(
        f"/api/v1/owner/companies/{shop.company.pk}/queue/?kind=sales.verify"
    ).json()["items"]
    [item] = items
    verify = next(action for action in item["actions"] if action["key"] == "verify")
    response = client.post(
        f"/api/v1/owner/companies/{shop.company.pk}/{verify['endpoint']}", {}, format="json"
    )
    assert response.status_code == 200
    assert CashShift.objects.get(pk=closed.pk).status == "verified"


# Branch isolation ----------------------------------------------------------------------------


def test_a_branch_lead_sees_only_their_branch(shop, owner_api, branch_lead, closed):
    theirs = open_and_close(shop, cashier=shop.colleague, register=shop.other_register)
    client = owner_api(branch_lead)
    codes = [row["code"] for row in client.get(url(shop.company, "shifts/")).json()["results"]]
    assert codes == [theirs.code]
    assert client.get(url(shop.company, f"shifts/{closed.pk}/")).status_code == 404
    assert (
        client.post(url(shop.company, f"shifts/{closed.pk}/verify/"), {}, format="json").status_code
        == 404
    )
    assert [b["id"] for b in client.get(url(shop.company, "today/")).json()["branches"]] == [
        shop.other_branch.pk
    ]
    assert [r["id"] for r in client.get(url(shop.company, "registers/")).json()] == [
        shop.other_register.pk
    ]
    summary = client.get(url(shop.company, "summary/?preset=month")).json()
    assert summary["totals"]["net"] == "1500000.00"
    assert [row["key"] for row in summary["breakdown"]] == [str(shop.other_branch.pk)]
    positions = client.get(url(shop.company, "cash/positions/")).json()
    assert [b["id"] for b in positions["branches"]] == [shop.other_branch.pk]
    # Asking for another branch through the filter gives nothing.
    other = client.get(url(shop.company, f"summary/?branch={shop.branch.pk}")).json()
    assert other["totals"]["net"] == "0.00"
    # Managing their branch works; another branch's till is refused.
    response = client.post(
        url(shop.company, "cash-movements/"),
        {"register_id": shop.register.pk, "kind": "to_safe", "amount": "1000"},
        format="json",
    )
    assert response.status_code == 400


def test_an_empty_scope_sees_nothing(shop, owner_api, closed):
    role = scoped_role(shop.company, Perm.SALES_VIEW)
    nobody = make_member(shop.company, "Owner")
    nobody.role = role
    nobody.save(update_fields=["role"])
    client = owner_api(nobody)
    assert client.get(url(shop.company, "shifts/")).json()["count"] == 0
    assert client.get(url(shop.company, "today/")).json()["branches"] == []


# Settings, tills, methods, targets ----------------------------------------------------------


def test_settings_patch_is_audited(shop, owner_api):
    client = owner_api(shop.owner)
    response = client.patch(
        url(shop.company, "settings/"),
        {"cash_tolerance": "10000", "blind_cash_count": False, "business_day_ends_at": "05:00"},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["cash_tolerance"] == "10000.00"
    assert response.json()["business_day_ends_at"] == "05:00"
    assert SalesSettings.objects.get(company=shop.company).blind_cash_count is False
    assert AuditLog.objects.filter(action="sales.settings_changed").exists()
    assert (
        client.patch(
            url(shop.company, "settings/"), {"mode": "invoices"}, format="json"
        ).status_code
        == 400
    )


def test_registers_make_their_cash_account_and_refuse_archiving_while_open(shop, owner_api):
    client = owner_api(shop.owner)
    response = client.post(
        url(shop.company, "registers/"),
        {"name": "Kassa 2", "branch_id": shop.branch.pk},
        format="json",
    )
    assert response.status_code == 201, response.json()
    register = Register.objects.get(pk=response.json()["id"])
    assert (
        register.cash_account.allow_negative and register.cash_account.branch_id == shop.branch.pk
    )
    services.open_shift(by=shop.cashier, register=register, opening_float="0")
    response = client.patch(
        url(shop.company, f"registers/{register.pk}/"), {"is_active": False}, format="json"
    )
    assert response.status_code == 400
    listed = {row["id"]: row for row in client.get(url(shop.company, "registers/")).json()}
    assert listed[register.pk]["open_shift"]["cashier"]["id"] == shop.cashier.pk
    assert listed[register.pk]["cash_now"] == "0.00"


def test_payment_methods_create_update_reorder(shop, owner_api):
    client = owner_api(shop.owner)
    response = client.post(
        url(shop.company, "payment-methods/"),
        {"name": "Alif Nasiya", "kind": "installment", "fee_percent": "3.5"},
        format="json",
    )
    assert response.status_code == 201, response.json()
    method_id = response.json()["id"]
    assert response.json()["fee_percent"] == "3.50"
    response = client.patch(
        url(shop.company, f"payment-methods/{method_id}/"), {"is_active": False}, format="json"
    )
    assert response.json()["is_active"] is False
    cash = shop.method("cash")
    response = client.patch(
        url(shop.company, f"payment-methods/{cash.pk}/"), {"is_active": False}, format="json"
    )
    assert response.status_code == 400  # every till takes cash
    ids = list(
        PaymentMethod.objects.filter(company=shop.company)
        .order_by("-order")
        .values_list("pk", flat=True)
    )
    response = client.post(
        url(shop.company, "payment-methods/reorder/"), {"ids": ids}, format="json"
    )
    assert [row["id"] for row in response.json()] == ids


def test_targets_with_pacing(shop, owner_api, closed):
    client = owner_api(shop.owner)
    month = closed.business_day.replace(day=1).isoformat()
    assert (
        client.post(
            url(shop.company, "targets/"), {"month": month, "amount": "30000000"}, format="json"
        ).status_code
        == 201
    )
    response = client.post(
        url(shop.company, "targets/"),
        {"month": month, "amount": "20000000", "branch_id": shop.branch.pk},
        format="json",
    )
    target_id = response.json()["id"]
    data = client.get(url(shop.company, f"targets/?month={month[:7]}")).json()
    scopes = [row["scope"] for row in data["targets"]]
    assert scopes == ["company", "branch"]
    assert data["targets"][1]["actual"] == "1500000.00"
    assert len(data["series"]) >= 28
    assert (
        client.patch(
            url(shop.company, f"targets/{target_id}/"), {"amount": "25000000"}, format="json"
        ).status_code
        == 200
    )
    assert client.delete(url(shop.company, f"targets/{target_id}/")).status_code == 204


# Analytics ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "group_by", ["day", "week", "month", "branch", "cashier", "method", "hour", "weekday_hour"]
)
def test_summary_has_the_analytics_shape(shop, owner_api, closed, group_by):
    response = owner_api(shop.owner).get(
        url(shop.company, f"summary/?preset=month&compare=prev&group_by={group_by}")
    )
    data = response.json()
    assert set(data) >= {
        "range",
        "compare",
        "currency",
        "totals",
        "previous",
        "series",
        "breakdown",
    }
    assert data["totals"]["net"] == "1500000.00" and data["totals"]["receipts"] == 20
    assert data["totals"]["avg_check"] == "75000.00"
    assert data["previous"]["net"] == "0.00"
    if group_by == "hour":
        assert len(data["series"]) == 24 and data["estimated"] is True
    if group_by == "weekday_hour":
        assert len(data["series"]) == 168
    if group_by == "method":
        assert {row["label"] for row in data["breakdown"]} == {"Cash", "Uzcard"}


def test_cashier_scorecard(shop, owner_api, closed):
    open_and_close(shop)
    rows = owner_api(shop.owner).get(url(shop.company, "cashiers/?preset=month")).json()["results"]
    [madina] = rows
    assert madina["member"]["id"] == shop.cashier.pk and madina["shifts"] == 2
    assert madina["accuracy"] == "50.0" and madina["shortages"] == 1
    assert madina["shortage_total"] == "-15000.00"


def test_today_and_cash_positions(shop, owner_api, closed):
    services.open_shift(by=shop.colleague, register=shop.other_register, opening_float="300000")
    services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind="handover",
        amount="500000",
        receiver=shop.owner,
    )
    client = owner_api(shop.owner)
    branches = {
        row["id"]: row for row in client.get(url(shop.company, "today/")).json()["branches"]
    }
    assert branches[shop.branch.pk]["net"] == "1500000.00"
    assert branches[shop.other_branch.pk]["open_tills"][0]["cashier"]["id"] == shop.colleague.pk
    positions = client.get(url(shop.company, "cash/positions/")).json()
    assert positions["totals"]["in_transit"] == "500000.00"
    assert positions["oldest_pending"]["to"]["id"] == shop.owner.pk
    chilonzor = next(b for b in positions["branches"] if b["id"] == shop.branch.pk)
    # The till holds what was counted minus the handover that left it.
    assert chilonzor["tills"][0]["amount"] == "685000.00"


def test_movements_record_and_void(shop, owner_api):
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="500000")
    client = owner_api(shop.manager)
    response = client.post(
        url(shop.company, "cash-movements/"),
        {"register_id": shop.register.pk, "kind": "payout", "amount": "120000", "reason": "Taxi"},
        format="json",
    )
    assert response.status_code == 201, response.json()
    movement_id = response.json()["id"]
    assert response.json()["category"]["name"] == "Other expenses"
    listed = client.get(url(shop.company, "cash-movements/?kind=payout")).json()
    assert listed["count"] == 1 and listed["results"][0]["amount"] == "120000.00"
    response = client.post(
        url(shop.company, f"cash-movements/{movement_id}/void/"),
        {"reason": "Mistake"},
        format="json",
    )
    assert response.json()["status"] == "void"


def test_handover_answers_only_by_the_receiver(shop, owner_api):
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="500000")
    movement = services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind="handover",
        amount="300000",
        receiver=shop.owner,
    )
    assert (
        owner_api(shop.manager)
        .post(url(shop.company, f"handovers/{movement.pk}/confirm/"))
        .status_code
        == 404
    )
    response = owner_api(shop.owner).post(url(shop.company, f"handovers/{movement.pk}/confirm/"))
    assert response.json()["status"] == "done"
    assert CashMovement.objects.get(pk=movement.pk).transfer_id is not None


def test_dashboard_entries(shop, owner_api):
    client = owner_api(shop.manager)
    response = client.post(
        url(shop.company, "entries/"),
        {
            "branch_id": shop.branch.pk,
            "payments": [{"method_id": shop.method("transfer").pk, "amount": "2300000"}],
            "note": "Wholesale",
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    entry_id = response.json()["id"]
    assert response.json()["total"] == "2300000.00"
    assert client.get(url(shop.company, "entries/")).json()["count"] == 1
    response = client.post(
        url(shop.company, f"entries/{entry_id}/void/"), {"reason": "Duplicate"}, format="json"
    )
    assert response.json()["voided_at"] is not None


def test_options_list_what_forms_pick_from(shop, owner_api):
    data = owner_api(shop.owner).get(url(shop.company, "options/")).json()
    assert {b["name"] for b in data["branches"]} == {"Chilonzor", "Yunusobod"}
    assert len(data["methods"]) == 10
    assert {c["id"] for c in data["cashiers"]} >= {shop.cashier.pk, shop.colleague.pk}
    assert shop.manager.pk in {r["id"] for r in data["receivers"]}
    till_accounts = set(Register.objects.values_list("cash_account_id", flat=True))
    assert not till_accounts & {a["id"] for a in data["accounts"]}
    assert data["settings"]["cash_tolerance"] == "5000.00"


def test_money_is_never_a_float(shop, owner_api, closed):
    client = owner_api(shop.owner)
    for path in (
        "summary/?group_by=branch",
        "today/",
        "cash/positions/",
        f"shifts/{closed.pk}/",
        "cashiers/",
    ):
        text = client.get(url(shop.company, path)).content.decode()
        assert "1500000.0," not in text and "1500000," not in text


def test_two_companies_never_mix(db, owner_api):
    first, second = make_shop(), make_shop()
    open_and_close(second)
    data = owner_api(first.owner).get(url(first.company, "summary/")).json()
    assert data["totals"]["net"] == "0.00"
    assert owner_api(first.owner).get(url(second.company, "summary/")).status_code == 404


def test_settings_view_is_readable_with_sales_view(shop, owner_api, viewer):
    assert owner_api(viewer).get(url(shop.company, "settings/")).json()["blind_cash_count"] is True


_unused = Decimal
