"""What finance gives the shared registries: search, the overdue badge, branch cards, the
briefing, portfolio facts, calendar dates, the offboarding step and its receiver, the Get
started step, copy setup, receipt links and record history."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.companies.models import Branch
from apps.console import contracts, registry
from apps.core.files import signed_url
from apps.finance import providers, queries, services
from apps.finance.models import MoneyAccount, Transaction
from apps.finance.tests.factories import CounterpartyFactory, MoneyAccountFactory
from apps.members import services as member_services
from apps.members.permissions import Perm
from apps.reports.periods import parse_range

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def today(fin):
    return queries.local_today(fin)


@pytest.fixture
def boss(fin, member):
    return member(fin, "Owner")


def test_every_registration_is_in_place():
    assert "finance.transaction" in registry.SEARCH
    assert "finance.counterparty" in registry.SEARCH
    assert "finance.overdue" in registry.PULSE
    assert "finance" in registry.BRANCH_FACTS
    assert "finance" in registry.BRIEF_SECTIONS
    assert "finance" in registry.COMPANY_FACTS
    assert "finance.debts_due" in registry.CALENDAR_SOURCES
    assert "finance" in registry.OFFBOARD_STEPS
    assert "finance.opening_balances" in registry.SETUP_STEPS
    assert "finance.categories" in registry.COPY_PARTS


def test_search_finds_entries_and_parties_and_hides_salary_detail(
    fin, boss, cash, today, role, person, member
):
    party = CounterpartyFactory(company=fin, name="Agromir Savdo", phone="+998901234567")
    services.record_transaction(
        fin, by=boss, kind="opening", amount=D("9000000"), occurred_on=today, account=cash
    )
    services.record_transaction(
        fin,
        by=boss,
        kind="expense",
        amount=D("120000"),
        occurred_on=today,
        account=cash,
        category="goods",
        counterparty=party,
        description="Rice and oil",
    )
    worker = member(fin, "Employee", first_name="Alisher")
    services.record_transaction(
        fin,
        by=boss,
        kind="expense",
        amount=D("4000000"),
        occurred_on=today,
        account=cash,
        category="salaries",
        membership=worker,
        description="Alisher salary",
    )
    hits = registry.run_search(boss, "rice")
    assert [hit.type for hit in hits] == ["finance.transaction"]
    rice = Transaction.objects.get(description="Rice and oil")
    assert hits[0].url == f"/c/{fin.pk}/finance/transactions?txn={rice.pk}"
    assert [
        hit.title for hit in registry.run_search(boss, "agromir", types=["finance.counterparty"])
    ] == ["Agromir Savdo"]
    assert registry.run_search(boss, "1234567", types=["finance.counterparty"])
    viewer = person(fin, role(fin, "Books", [Perm.FINANCE_VIEW, Perm.BRANCHES_ALL]))
    assert registry.run_search(viewer, "Alisher salary", types=["finance.transaction"]) == []
    assert registry.run_search(boss, "Alisher salary", types=["finance.transaction"])


def test_the_overdue_badge_counts_open_debts_past_due(fin, boss, today):
    party = CounterpartyFactory(company=fin)
    for due in (today - timedelta(days=3), today + timedelta(days=3)):
        services.open_debt(
            fin,
            by=boss,
            direction="receivable",
            kind="trade",
            amount=D("100"),
            currency="UZS",
            issued_on=today - timedelta(days=10),
            due_on=due,
            counterparty=party,
            is_opening=True,
        )
    assert registry.pulse_counts(boss)["finance.overdue"] == 1


def test_branch_facts_fit_their_contract(fin, boss, today):
    main = fin.branches.first()
    kassa = MoneyAccountFactory(company=fin, name="Kassa", branch=main)
    MoneyAccountFactory(company=fin, name="Bank", kind="bank", branch=main)
    services.record_transaction(
        fin, by=boss, kind="opening", amount=D("750000"), occurred_on=today, account=kassa
    )
    facts = registry.collect_branch_facts(boss, today, timezone.now(), [main.pk])
    assert facts["finance"] == {main.pk: {"cash": "750000.00"}}
    assert contracts.problems(contracts.FinanceFacts, facts["finance"][main.pk]) == []


def test_portfolio_facts_fit_their_contract(fin, boss, cash, today):
    services.record_transaction(
        fin,
        by=boss,
        kind="income",
        amount=D("500"),
        occurred_on=today,
        account=cash,
        category="sales",
    )
    services.record_transaction(
        fin,
        by=boss,
        kind="expense",
        amount=D("200"),
        occurred_on=today,
        account=cash,
        category="rent",
    )
    range_ = parse_range({"preset": "month"}, fin, timezone.now())
    facts = registry.collect_company_facts(boss, range_)["finance"]
    assert facts == {"cash": "300.00", "income": "500.00", "expenses": "200.00", "profit": "300.00"}
    assert contracts.problems(contracts.FinanceCompanyFacts, facts) == []


def test_the_brief_section_is_silent_without_a_ledger(fin, boss, cash, today):
    now = timezone.now()
    assert providers.brief_section(fin, today, now, None) is None
    services.record_transaction(
        fin,
        by=boss,
        kind="income",
        amount=D("800"),
        occurred_on=today - timedelta(days=1),
        account=cash,
        category="sales",
    )
    section = dict(registry.collect_brief_sections(boss, today, now, branch_ids=None))["finance"]
    assert section["income_yesterday"] == "800.00"
    assert section["cash"] == "800.00"


def test_calendar_shows_due_dates_and_instalments(fin, boss, today, member):
    party = CounterpartyFactory(company=fin, name="Barakat")
    plain = services.open_debt(
        fin,
        by=boss,
        direction="payable",
        kind="bill",
        amount=D("1000"),
        currency="UZS",
        issued_on=today,
        due_on=today + timedelta(days=2),
        counterparty=party,
        is_opening=True,
    )
    planned = services.open_debt(
        fin,
        by=boss,
        direction="receivable",
        kind="trade",
        amount=D("200"),
        currency="UZS",
        issued_on=today,
        counterparty=party,
        is_opening=True,
    )
    services.set_installments(
        planned,
        by=boss,
        rows=[(today + timedelta(days=1), D("100")), (today + timedelta(days=40), D("100"))],
    )
    items = registry.collect_calendar(boss, today, today + timedelta(days=7))
    by_id = {item.id: item for item in items}
    assert by_id[f"debt-{plain.pk}"].color == "danger"
    assert "Pay Barakat" in by_id[f"debt-{plain.pk}"].title
    assert len([item for item in items if str(item.id).startswith("installment-")]) == 1


class TestOffboarding:
    def test_cash_held_is_a_blocker_with_a_transfer_target(self, fin, boss, member, today):
        main = fin.branches.first()
        leaver = member(fin, "Cashier", home_branch=main)
        held = services.account_for_holder(fin, leaver)
        services.record_transaction(
            fin, by=boss, kind="opening", amount=D("250000"), occurred_on=today, account=held
        )
        safe = services.account_for_branch(main)
        step = providers.offboard_preview(leaver)
        assert step.blockers
        assert "250 000" in step.blockers[0] or "250,000" in step.blockers[0]
        field = step.fields[0]
        assert field.name == "transfer_to"
        assert str(safe.pk) in dict(field.choices)
        assert step.defaults["transfer_to"] == str(safe.pk)
        wizard = registry.collect_offboard_steps(leaver, by=boss)
        assert [entry["key"] for entry in wizard] == ["finance"]

    def test_leaving_moves_the_cash_and_archives_the_account(
        self, fin, boss, member, today, django_capture_on_commit_callbacks
    ):
        main = fin.branches.first()
        leaver = member(fin, "Cashier", home_branch=main)
        held = services.account_for_holder(fin, leaver)
        services.record_transaction(
            fin, by=boss, kind="opening", amount=D("250000"), occurred_on=today, account=held
        )
        safe = services.account_for_branch(main)
        with django_capture_on_commit_callbacks(execute=True):
            member_services.offboard(
                leaver, by=boss.user, details={"finance": {"transfer_to": str(safe.pk)}}
            )
        held.refresh_from_db()
        safe.refresh_from_db()
        assert (held.balance, held.is_active) == (D("0.00"), False)
        assert safe.balance == D("250000.00")

    def test_nothing_held_says_so(self, fin, member):
        leaver = member(fin, "Employee")
        step = providers.offboard_preview(leaver)
        assert step.blockers == []
        assert step.fields == []
        assert len(step.lines) == 1


def test_the_get_started_step_is_done_after_an_opening_balance(fin, boss, cash, today):
    assert providers.opening_balances_done(fin) is False
    services.record_entry(
        fin, by=boss, kind="opening", amount="10", occurred_on=today, account=cash
    )
    assert providers.opening_balances_done(fin) is True
    steps = {step["key"]: step for step in registry.collect_setup_steps(boss)}
    assert steps["finance.opening_balances"]["done"] is True


def test_copy_setup_runs_through_the_registry(fin, boss, other_company, member):
    from apps.finance import defaults

    services.create_category(fin, by=boss, name="Packaging", kind="expense")
    defaults.ensure(other_company)
    other_company.features = ["finance"]
    other_company.save(update_fields=["features"])
    target = member(other_company, "Owner", user=boss.user)
    assert registry.run_copy(fin, other_company, ["finance.categories"], by=target) == {
        "finance.categories": 1
    }


def test_a_receipt_link_stops_working_without_access(fin, boss, cash, today, client, role, person):
    import io

    from PIL import Image

    picture = io.BytesIO()
    Image.new("RGB", (20, 20)).save(picture, "JPEG")
    services.record_transaction(
        fin, by=boss, kind="opening", amount=D("100"), occurred_on=today, account=cash
    )
    row = services.record_transaction(
        fin,
        by=boss,
        kind="expense",
        amount=D("10"),
        occurred_on=today,
        account=cash,
        category="rent",
    )
    receipt = services.upload_receipt(fin, by=boss, file=picture, txn=row)
    viewer = person(fin, role(fin, "Books", [Perm.FINANCE_VIEW, Perm.BRANCHES_ALL]))
    link = signed_url(
        receipt.file, user=viewer.user, company_id=fin.pk, check=f"finance.receipt:{receipt.pk}"
    )
    assert client.get(link).status_code == 200
    viewer.role.permissions = [Perm.DASHBOARD_ACCESS]
    viewer.role.save()
    assert client.get(link).status_code == 404


def test_history_tabs_open_for_finance_viewers_in_scope(fin, boss, owner_api, role, person, today):
    main = fin.branches.first()
    other = Branch.objects.create(company=fin, name="Elsewhere")
    there = MoneyAccountFactory(company=fin, name="There", branch=other)
    row = services.record_transaction(
        fin, by=boss, kind="opening", amount=D("5"), occurred_on=today, account=there
    )
    viewer = person(fin, role(fin, "Branch books", [Perm.FINANCE_VIEW]), branches=[main])
    api = owner_api(viewer)
    path = f"/api/v1/owner/companies/{fin.pk}/audit/records/"
    assert api.get(path, {"target_type": "transaction", "target_id": row.pk}).status_code == 404
    assert (
        owner_api(boss).get(path, {"target_type": "transaction", "target_id": row.pk}).status_code
        == 200
    )
    assert MoneyAccount.objects.filter(pk=there.pk).exists()
