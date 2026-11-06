"""Expense claims (Package I, §3.7 and §11.4 acceptance): own money becomes a reimbursement
payable (paid by payroll or in cash), held cash a pending expense on the holder's account,
below the threshold a claim is booked at once, and nobody approves their own claim."""

import io
from datetime import timedelta
from decimal import Decimal

import pytest
from PIL import Image

from apps.console import registry
from apps.core.exceptions import DomainError
from apps.finance import claims, conf, providers, queries, services
from apps.finance.models import Category, Claim, Debt, MoneyAccount, Receipt, Transaction
from apps.inbox.models import Notification
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db


def owner_url(company, path: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/finance/{path}"


def my_url(company, path: str) -> str:
    return f"/api/v1/companies/{company.pk}/finance/{path}"


def jpeg(name="receipt.jpg") -> io.BytesIO:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 120, 60)).save(out, "JPEG")
    out.seek(0)
    out.name = name
    return out


@pytest.fixture
def boss(fin, member):
    return member(fin, "Owner", first_name="Dilnoza")


@pytest.fixture
def jasur(fin, member):
    return member(fin, "Employee", first_name="Jasur")


@pytest.fixture
def kassa(fin, boss, today):
    account = MoneyAccount.objects.get(company=fin, kind=MoneyAccount.Kind.CASH)
    services.record_transaction(
        fin,
        by=boss,
        kind="income",
        amount=Decimal("10000000"),
        occurred_on=today,
        account=account,
        category="sales",
    )
    account.refresh_from_db()
    return account


@pytest.fixture
def today(fin):
    return queries.local_today(fin)


@pytest.fixture
def transport(fin):
    return Category.objects.get(company=fin, system_code="transport")


def claim(company, by, category, amount="450000", paid_from="own_money", **fields):
    values = {"spent_on": queries.local_today(company), "description": "Taxi to the distributor"}
    values.update(fields)
    return claims.submit_claim(
        company, by=by, amount=amount, category=category, paid_from=paid_from, **values
    )


def held_cash(company, by, member, amount, day):
    """`member` holds `amount` of the company's cash (moved to their employee account)."""
    account = services.account_for_holder(company, member)
    services.transfer(
        company,
        by=by,
        from_account=MoneyAccount.objects.get(company=company, kind="cash"),
        to_account=account,
        amount_out=Decimal(amount),
        occurred_on=day,
    )
    return account


# Own money -----------------------------------------------------------------------------------


def test_own_money_waits_then_becomes_a_reimbursement_payable(
    fin, boss, jasur, transport, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        made = claim(fin, jasur, transport)

    assert made.status == Claim.Status.SUBMITTED
    assert made.debt_id is None and made.transaction_id is None
    # The approver hears about it in Telegram with buttons; the in-app form is Needs you.
    [note] = Notification.objects.filter(kind="finance.claim")
    assert note.recipient_id == boss.pk and not note.in_app
    assert [a["key"] for a in note.actions] == ["approve", "reject"]
    assert claims.queue_count(boss) == 1
    assert claims.queue_count(jasur) == 0

    claims.decide_claim(made, by=boss, approve=True)

    made.refresh_from_db()
    debt = made.debt
    assert (made.status, debt.kind, debt.direction, debt.membership_id) == (
        "approved",
        "reimbursement",
        "payable",
        jasur.pk,
    )
    accrual = made.transaction
    assert (accrual.kind, accrual.category_id, accrual.account_id) == (
        "expense",
        transport.pk,
        None,
    )
    assert accrual.amount == Decimal("-450000.00")


def test_cash_route_pays_back_from_an_account(
    fin, boss, jasur, transport, kassa, django_capture_on_commit_callbacks
):
    conf.get_settings(fin)
    services.update_settings(fin, by=boss, reimburse_via="cash")
    made = claim(fin, jasur, transport)
    claims.decide_claim(made, by=boss, approve=True)
    made.refresh_from_db()
    assert claims.reimburse_route(fin) == "cash"
    assert claims.can_pay(boss, made)

    with django_capture_on_commit_callbacks(execute=True):
        claims.pay_claim(made, by=boss, account=kassa)

    made.refresh_from_db()
    assert made.status == "paid"
    assert made.debt.status == Debt.Status.PAID
    kassa.refresh_from_db()
    assert kassa.balance == Decimal("9550000.00")
    assert Notification.objects.filter(kind="finance.claim_decided", recipient=jasur).exists()


def test_payroll_route_is_paid_by_payroll_and_reads_paid(fin, boss, jasur, transport, kassa):
    fin.features = ["finance", "payroll"]
    fin.save(update_fields=["features"])
    made = claim(fin, jasur, transport)
    claims.decide_claim(made, by=boss, approve=True)
    made.refresh_from_db()
    assert claims.reimburse_route(fin) == "payroll"
    assert not claims.can_pay(boss, made)  # payroll pays it

    services.pay_debt(
        made.debt, by=boss, amount=Decimal("450000"), paid_on=made.spent_on, account=kassa
    )

    assert claims.sync_paid(fin) == 1
    made.refresh_from_db()
    assert made.status == "paid"


def test_with_payroll_off_the_payroll_route_falls_back_to_cash(fin, boss):
    services.update_settings(fin, by=boss, reimburse_via="payroll")

    assert claims.reimburse_route(fin) == "cash"


# Held cash -------------------------------------------------------------------------------------


def test_held_cash_is_a_pending_expense_posted_on_approval(
    fin, boss, jasur, transport, kassa, today
):
    account = held_cash(fin, boss, jasur, "1000000", today)

    made = claim(fin, jasur, transport, paid_from="held_cash", amount="300000")

    row = made.transaction
    assert (row.status, row.account_id, row.amount) == (
        "pending",
        account.pk,
        Decimal("-300000.00"),
    )
    account.refresh_from_db()
    assert account.balance == Decimal("1000000.00")  # pending rows move nothing

    claims.decide_claim(made, by=boss, approve=True)

    row.refresh_from_db()
    account.refresh_from_db()
    assert row.status == "posted"
    assert account.balance == Decimal("700000.00")


def test_rejecting_held_cash_rejects_its_entry(fin, boss, jasur, transport, kassa, today):
    held_cash(fin, boss, jasur, "1000000", today)
    made = claim(fin, jasur, transport, paid_from="held_cash", amount="300000")

    claims.decide_claim(made, by=boss, approve=False, reason="Not a company trip")

    made.refresh_from_db()
    assert (made.status, made.reject_reason) == ("rejected", "Not a company trip")
    assert made.transaction.status == "rejected"


def test_held_cash_needs_the_money(fin, jasur, transport):
    with pytest.raises(DomainError):
        claim(fin, jasur, transport, paid_from="held_cash")


# Rules -------------------------------------------------------------------------------------------


def test_below_the_threshold_a_claim_is_booked_at_once(fin, boss, jasur, transport, kassa, today):
    services.update_settings(fin, by=boss, approval_threshold="500000")
    held_cash(fin, boss, jasur, "1000000", today)

    small = claim(fin, jasur, transport, amount="499999")
    cash = claim(fin, jasur, transport, amount="200000", paid_from="held_cash")
    big = claim(fin, jasur, transport, amount="500000")

    small.refresh_from_db()
    cash.refresh_from_db()
    assert small.status == "approved" and small.debt.kind == "reimbursement"
    assert cash.status == "approved" and cash.transaction.status == "posted"
    assert big.status == "submitted"  # at or above waits


def test_without_a_threshold_every_claim_waits(fin, jasur, transport):
    assert conf.get_settings(fin).approval_threshold is None

    assert claim(fin, jasur, transport, amount="1000").status == "submitted"


def test_nobody_approves_their_own_claim(fin, boss, transport):
    made = claim(fin, boss, transport)

    with pytest.raises(DomainError):
        claims.decide_claim(made, by=boss, approve=True)
    assert claims.queue_count(boss) == 0
    assert not claims.can_decide(boss, made)


def test_deciding_needs_finance_approve(fin, jasur, transport, member):
    other = member(fin, "Employee", first_name="Madina")
    made = claim(fin, jasur, transport)

    with pytest.raises(DomainError):
        claims.decide_claim(made, by=other, approve=True)


def test_a_receipt_is_required_over_the_limit_and_belongs_to_the_claim(fin, boss, jasur, transport):
    services.update_settings(fin, by=boss, receipt_required_over="400000")

    with pytest.raises(DomainError):
        claim(fin, jasur, transport, amount="450000")
    made = claim(fin, jasur, transport, amount="450000", receipt_files=[jpeg()])

    [receipt] = made.receipts.all()
    assert receipt.transaction_id is None
    # Its approver may open it before anything is booked; a colleague may not.
    assert providers.receipt_check(boss.user, fin.pk, receipt.pk)
    claims.decide_claim(made, by=boss, approve=True)
    receipt.refresh_from_db()
    assert receipt.transaction_id == Claim.objects.get(pk=made.pk).transaction_id


def test_claim_receipts_outlive_the_orphan_purge(fin, jasur, transport):
    from django.utils import timezone

    from apps.finance import maintenance

    made = claim(fin, jasur, transport, receipt_files=[jpeg()])
    Receipt.objects.filter(claim=made).update(created_at=timezone.now() - timedelta(days=10))

    assert maintenance.purge_orphan_receipts() == 0
    assert made.receipts.count() == 1


def test_the_person_may_cancel_while_it_waits(fin, boss, jasur, transport, kassa, today):
    held_cash(fin, boss, jasur, "1000000", today)
    made = claim(fin, jasur, transport, paid_from="held_cash", amount="100000")

    with pytest.raises(DomainError):
        claims.cancel_claim(made, by=boss)
    claims.cancel_claim(made, by=jasur)

    made.refresh_from_db()
    assert made.status == "cancelled" and made.transaction.status == "rejected"


def test_system_categories_and_future_days_are_refused(fin, jasur, today):
    salaries = Category.objects.get(company=fin, system_code="salaries")
    transport = Category.objects.get(company=fin, system_code="transport")

    with pytest.raises(DomainError):
        claim(fin, jasur, salaries)
    with pytest.raises(DomainError):
        claim(fin, jasur, transport, spent_on=today + timedelta(days=1))


def test_the_inbox_buttons_decide(fin, boss, jasur, transport, django_capture_on_commit_callbacks):
    from apps.inbox import services as inbox

    with django_capture_on_commit_callbacks(execute=True):
        made = claim(fin, jasur, transport)
    note = Notification.objects.get(kind="finance.claim")

    outcome = inbox.run_action(note.pk, "approve", by=boss)

    assert outcome == "Expense approved."
    assert Claim.objects.get(pk=made.pk).status == "approved"


def test_claims_are_registered():
    assert registry.QUEUE.get("finance.claims").perm == Perm.FINANCE_APPROVE
    assert registry.PULSE.get("finance.claims") is not None


# Owner API ---------------------------------------------------------------------------------------


def test_the_owner_queue_and_decisions(fin, boss, jasur, transport, owner_api):
    made = claim(fin, jasur, transport)
    client = owner_api(boss)

    page = client.get(owner_url(fin, "claims/")).json()
    [row] = page["results"]
    assert row["id"] == made.pk
    assert row["member"]["name"] == str(jasur)
    assert (row["amount"], row["status"], row["can_decide"]) == ("450000.00", "submitted", True)

    rejected = client.post(
        owner_url(fin, f"claims/{made.pk}/reject/"), {"reason": "No receipt"}, format="json"
    )
    assert rejected.status_code == 200, rejected.content
    assert rejected.json()["status"] == "rejected"
    assert client.get(owner_url(fin, "claims/")).json()["results"] == []
    assert len(client.get(owner_url(fin, "claims/?status=all")).json()["results"]) == 1


def test_owner_claims_permissions_and_tenancy(
    fin, boss, jasur, transport, owner_api, role, person, other_company
):
    made = claim(fin, jasur, transport)
    viewer = owner_api(person(fin, role(fin, "Viewer", [Perm.FINANCE_VIEW])))

    assert viewer.get(owner_url(fin, "claims/")).status_code == 200
    assert viewer.post(owner_url(fin, f"claims/{made.pk}/approve/")).status_code == 403
    assert owner_api(boss).get(owner_url(other_company, "claims/")).status_code == 404
    nobody = owner_api(person(fin, role(fin, "Sales", [Perm.SALES_VIEW])))
    assert nobody.get(owner_url(fin, "claims/")).status_code == 403


# Employee API ------------------------------------------------------------------------------------


def test_the_mini_app_submits_lists_and_cancels(fin, jasur, transport, api_as):
    client = api_as(jasur)

    categories = client.get(my_url(fin, "categories/")).json()
    assert transport.pk in [row["id"] for row in categories]
    assert "salaries" not in [row["name"].lower() for row in categories]

    response = client.post(
        my_url(fin, "claims/"),
        {
            "amount": "450000",
            "category": transport.pk,
            "spent_on": queries.local_today(fin).isoformat(),
            "description": "Taxi",
            "paid_from": "own_money",
            "receipts": [jpeg("a.jpg"), jpeg("b.jpg")],
        },
        format="multipart",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["status"] == "submitted" and len(body["receipts"]) == 2
    assert body["receipts"][0]["url"].startswith("/api/v1/files/")
    assert body["can_cancel"] is True

    [mine] = client.get(my_url(fin, "claims/")).json()
    assert mine["id"] == body["id"]
    cancelled = client.post(my_url(fin, f"claims/{body['id']}/cancel/"))
    assert cancelled.json()["status"] == "cancelled"

    wallet = client.get(my_url(fin, "wallet/")).json()
    assert wallet == {
        "currency": "UZS",
        "held": [],
        "held_total": "0.00",
        "owed_to_me": "0.00",
        "approval_threshold": None,
        "receipt_required_over": None,
    }


def test_the_mini_app_refuses_bad_input_and_strangers(
    fin, jasur, transport, api_as, member, other_company
):
    client = api_as(jasur)
    salaries = Category.objects.get(company=fin, system_code="salaries")

    bad = client.post(
        my_url(fin, "claims/"),
        {
            "amount": "450000",
            "category": salaries.pk,
            "spent_on": "2026-01-01",
            "paid_from": "own_money",
        },
        format="multipart",
    )
    assert bad.status_code == 400
    assert client.get(my_url(other_company, "claims/")).status_code == 404
    stranger = member(fin, "Employee", first_name="Nigora")
    made = claim(fin, jasur, transport)
    assert api_as(stranger).post(my_url(fin, f"claims/{made.pk}/cancel/")).status_code == 404


def test_the_mini_app_needs_the_module_and_the_permission(fin, jasur, api_as, role, person):
    fin.features = []
    fin.save(update_fields=["features"])
    assert api_as(jasur).get(my_url(fin, "claims/")).status_code == 403
    fin.features = ["finance"]
    fin.save(update_fields=["features"])
    no_claims = person(fin, role(fin, "Nothing", []))
    assert api_as(no_claims).get(my_url(fin, "wallet/")).status_code == 403


def test_the_wallet_shows_held_cash_and_what_is_owed_back(
    fin, boss, jasur, transport, kassa, today, api_as
):
    held_cash(fin, boss, jasur, "800000", today)
    made = claim(fin, jasur, transport, amount="250000")
    claims.decide_claim(made, by=boss, approve=True)

    wallet = api_as(jasur).get(my_url(fin, "wallet/")).json()

    assert wallet["held_total"] == "800000.00"
    assert wallet["held"][0]["balance"] == "800000.00"
    assert wallet["owed_to_me"] == "250000.00"
    assert Transaction.objects.filter(source_type="finance.claim").count() == 1
