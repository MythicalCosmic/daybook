"""Business contracts: the dates (statuses, terms, notice deadlines), renewals, termination,
and the recurring payment in Finance that puts the rent into the cash forecast."""

from datetime import date
from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.contracts import conf, services
from apps.contracts.models import BusinessContract
from apps.contracts.tests.conftest import DAY, local, money
from apps.core.exceptions import DomainError
from apps.finance import recurring
from apps.finance import services as finance
from apps.finance.models import Category, RecurringRule

pytestmark = pytest.mark.django_db
Status = BusinessContract.Status


def contract(**fields) -> BusinessContract:
    values = {
        "title": "Ijara",
        "status": Status.ACTIVE,
        "starts_on": date(2026, 1, 1),
        "ends_on": date(2026, 12, 31),
        "notice_days": 30,
        "renewal_months": 12,
    }
    values.update(fields)
    return BusinessContract(**values)


# Dates ------------------------------------------------------------------------------------------


def test_a_term_renews_for_whole_months_ending_the_day_before():
    assert services.next_term_end(date(2026, 12, 31), 12) == date(2027, 12, 31)
    assert services.next_term_end(date(2026, 11, 30), 11) == date(2027, 10, 31)
    # A term ending on the last day of February ends on it in the next one, leap year or not.
    assert services.next_term_end(date(2027, 2, 28), 12) == date(2028, 2, 29)
    assert services.next_term_end(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_the_notice_deadline_is_the_notice_days_before_the_end():
    assert contract(auto_renews=True).notice_deadline == date(2026, 12, 1)
    assert contract(auto_renews=True, notice_days=60).notice_deadline == date(2026, 11, 1)
    assert contract(auto_renews=True, notice_days=0).notice_deadline == date(2026, 12, 31)
    # Only an auto-renewing contract with an end has one.
    assert contract(auto_renews=False).notice_deadline is None
    assert contract(auto_renews=True, ends_on=None).notice_deadline is None


@pytest.mark.parametrize(
    ("today", "fields", "expected"),
    [
        (date(2026, 11, 7), {}, Status.ACTIVE),  # 54 days left, warning from 30
        (date(2026, 12, 1), {}, Status.ENDING),  # 30 days left
        (date(2026, 12, 31), {}, Status.ENDING),  # its last day
        (date(2027, 1, 1), {}, Status.ENDED),
        (date(2027, 1, 1), {"auto_renews": True}, Status.ACTIVE),  # the job moves it on
        (date(2026, 12, 20), {"auto_renews": True}, Status.ACTIVE),  # renews: never "ending"
        (date(2026, 11, 7), {"ends_on": None}, Status.ACTIVE),
        (date(2026, 11, 7), {"status": Status.DRAFT}, Status.DRAFT),
        (date(2026, 11, 7), {"terminated_on": date(2026, 11, 7)}, Status.TERMINATED),
        (
            date(2026, 11, 7),
            {"terminated_on": date(2026, 11, 30), "ends_on": date(2026, 11, 30)},
            Status.ENDING,
        ),
    ],
)
def test_the_status_follows_the_dates(today, fields, expected):
    assert services.status_on(contract(**fields), today, 30) == expected


def test_notice_due_until_the_renewal_is_confirmed():
    row = contract(auto_renews=True, notice_days=30)  # deadline 1 December
    assert not services.notice_due(row, date(2026, 11, 16), 14)
    assert services.notice_due(row, date(2026, 11, 17), 14)
    assert services.notice_due(row, date(2026, 12, 1), 14)
    assert not services.notice_due(row, date(2026, 12, 2), 14)  # passed: it will renew
    row.renewal_confirmed_for = date(2026, 12, 31)
    assert not services.notice_due(row, date(2026, 11, 20), 14)


# The life of a contract -------------------------------------------------------------------------


def test_creating_one_is_audited_and_its_status_follows_its_dates(shop, owner, lease):
    assert lease.status == Status.ACTIVE  # 54 days before its end
    assert lease.counterparty.name == "Rustam Qodirov (ijara)"
    log = AuditLog.objects.get(action="contracts.created", target_id=lease.pk)
    assert log.target_type == "businesscontract"
    assert log.required_perm == "finance.view"


def test_a_counterparty_given_by_name_is_found_or_added(shop, owner, chilonzor, landlord):
    first = services.create_contract(
        shop,
        by=owner,
        kind="supply",
        title="Yetkazib berish",
        counterparty_name="  ko‘kterak  farm ",
        starts_on=date(2026, 1, 1),
    )
    assert first.counterparty.name == "ko‘kterak farm"
    assert first.counterparty.kind == "supplier"
    again = services.create_contract(
        shop,
        by=owner,
        kind="lease",
        title="Ijara",
        counterparty_name="RUSTAM QODIROV (IJARA)",
        starts_on=date(2026, 1, 1),
    )
    assert again.counterparty_id == landlord.pk


def test_what_a_contract_must_keep(shop, owner):
    def make(**fields):
        values = {"kind": "lease", "title": "Ijara", "starts_on": date(2026, 1, 1)}
        values.update(fields)
        return services.create_contract(shop, by=owner, **values)

    with pytest.raises(DomainError):
        make(title="  ")
    with pytest.raises(DomainError):
        make(ends_on=date(2025, 12, 31))
    with pytest.raises(DomainError):
        make(auto_renews=True)  # renewing needs an end date
    with pytest.raises(DomainError):
        make(starts_on=None)  # in force: needs its start
    with pytest.raises(DomainError):
        make(status=Status.ENDED)  # follows the dates, never set by hand
    with pytest.raises(DomainError):
        make(in_forecast=True, period="once", amount=Decimal(100))
    draft = make(status=Status.DRAFT, starts_on=None)
    assert draft.status == Status.DRAFT


def test_ending_soon_then_ended(shop, owner, lease, freeze):
    settings = conf.get_settings(shop)
    assert not services.refresh_status(lease, date(2026, 11, 7), settings)
    assert services.refresh_status(lease, date(2026, 12, 1), settings)
    assert lease.status == Status.ENDING
    assert services.refresh_status(lease, date(2027, 1, 1), settings)
    lease.refresh_from_db()
    assert lease.status == Status.ENDED
    assert AuditLog.objects.filter(action="contracts.status", actor__isnull=True).count() == 2


def test_an_auto_renewing_contract_moves_on_by_whole_terms(shop, owner, lease):
    services.update_contract(lease, by=owner, auto_renews=True, renewal_months=12)
    lease.refresh_from_db()
    settings = conf.get_settings(shop)
    assert not services.renew_by_itself(lease, date(2026, 12, 31), settings)  # its last day
    assert services.renew_by_itself(lease, date(2027, 1, 1), settings)
    lease.refresh_from_db()
    assert lease.ends_on == date(2027, 12, 31)
    assert lease.last_renewed_on == date(2027, 1, 1)
    assert lease.status == Status.ACTIVE
    # The job was down for more than a year: as many terms as it takes.
    lease.ends_on = date(2026, 12, 31)
    assert services.renew_by_itself(lease, date(2028, 3, 1), settings)
    assert lease.ends_on == date(2028, 12, 31)
    log = AuditLog.objects.filter(action="contracts.renewed").latest("pk")
    assert log.actor is None and log.details["auto"] is True


def test_renewing_by_hand_sets_a_new_end(shop, owner, lease, freeze):
    freeze(local(date(2026, 12, 10), 10))
    services.refresh_status(lease, date(2026, 12, 10), conf.get_settings(shop))
    with pytest.raises(DomainError):
        services.renew(lease, by=owner, ends_on=date(2026, 12, 1))
    renewed = services.renew(lease, by=owner, ends_on=date(2027, 12, 31))
    assert renewed.ends_on == date(2027, 12, 31)
    assert renewed.status == Status.ACTIVE
    assert renewed.last_renewed_on == date(2026, 12, 10)
    # A person renewed it: the "renewed by itself" notice is not for this term.
    assert "renewed:2027-12-31:auto" in renewed.reminders_sent


def test_keep_or_stop_an_auto_renewal(shop, owner, lease):
    with pytest.raises(DomainError):
        services.confirm_renewal(lease, by=owner)  # it doesn't renew by itself
    lease = services.update_contract(lease, by=owner, auto_renews=True)
    kept = services.confirm_renewal(lease, by=owner)
    assert kept.renewal_confirmed_for == date(2026, 12, 31)
    stopped = services.stop_renewal(kept, by=owner)
    assert not stopped.auto_renews
    # A new end date asks the question again.
    again = services.update_contract(stopped, by=owner, auto_renews=True, ends_on=date(2027, 6, 30))
    assert again.renewal_confirmed_for is None


def test_terminating_today_or_ahead(shop, owner, lease):
    with pytest.raises(DomainError):
        services.terminate(lease, by=owner, on=date(2027, 2, 1))  # it ends before anyway
    ahead = services.terminate(lease, by=owner, on=date(2026, 11, 30), reason="Ko‘chamiz")
    assert ahead.status == Status.ENDING
    assert ahead.ends_on == date(2026, 11, 30)
    assert ahead.termination_reason == "Ko‘chamiz"
    now = services.terminate(ahead, by=owner, on=DAY)
    assert now.status == Status.TERMINATED
    with pytest.raises(DomainError):
        services.terminate(now, by=owner, on=DAY)
    # Brought back by hand: the termination is undone.
    back = services.update_contract(now, by=owner, status=Status.ACTIVE, ends_on=date(2026, 12, 31))
    assert back.status == Status.ACTIVE and back.terminated_on is None


# The recurring payment --------------------------------------------------------------------------


def test_the_rent_goes_into_the_forecast_as_a_recurring_bill(shop, owner, lease, bank):
    lease = services.update_contract(lease, by=owner, in_forecast=True)
    rule = lease.rule
    assert rule is not None and rule.is_active
    assert rule.name == "Chilonzor dorixonasi ijarasi"
    assert (rule.kind, rule.mode, rule.frequency, rule.day) == ("expense", "bill", "monthly", 3)
    assert rule.amount == money(9_000_000) and rule.currency == "UZS"
    assert rule.category.system_code == "rent"
    assert rule.counterparty_id == lease.counterparty_id
    assert rule.branch_id == lease.branch_id
    assert rule.ends_on == date(2026, 12, 31)  # it doesn't renew: the payments end with it
    assert rule.next_due_on == date(2026, 12, 3)  # the first one from today on
    # The forecast sees it.
    due = recurring.due_items(shop, DAY, date(2026, 12, 31), branch_ids=None)
    assert [item.rule.pk for item in due] == [rule.pk]
    # A new amount and payment day reach it.
    services.update_contract(lease, by=owner, amount=Decimal(9_500_000), payment_day=5)
    rule.refresh_from_db()
    assert (rule.amount, rule.day) == (money(9_500_000), 5)
    # Renewing by itself: the rule runs on.
    services.update_contract(lease, by=owner, auto_renews=True)
    rule.refresh_from_db()
    assert rule.ends_on is None
    assert AuditLog.objects.filter(action="finance.recurring_updated").exists()


def test_terminating_or_deleting_ends_the_payment(shop, owner, lease):
    lease = services.update_contract(lease, by=owner, in_forecast=True)
    ahead = services.terminate(lease, by=owner, on=date(2026, 11, 30))
    rule = RecurringRule.objects.get(pk=ahead.rule_id)
    assert rule.is_active and rule.ends_on == date(2026, 11, 30)
    services.terminate(ahead, by=owner, on=DAY)
    rule.refresh_from_db()
    assert not rule.is_active

    other = services.create_contract(
        shop,
        by=owner,
        kind="service",
        title="Tozalash xizmati",
        starts_on=date(2026, 1, 1),
        amount=Decimal(1_200_000),
        period="monthly",
        in_forecast=True,
    )
    other_rule = other.rule
    assert other_rule.category.system_code == "other_expense"
    services.delete_contract(other, by=owner)
    other_rule.refresh_from_db()
    assert not other_rule.is_active  # switched off; what it booked stays
    assert not BusinessContract.objects.filter(pk=other.pk).exists()


def test_switching_the_forecast_off_and_on_reuses_the_payment(shop, owner, lease):
    lease = services.update_contract(lease, by=owner, in_forecast=True)
    rule_id = lease.rule_id
    lease = services.update_contract(lease, by=owner, in_forecast=False)
    assert not RecurringRule.objects.get(pk=rule_id).is_active
    lease = services.update_contract(lease, by=owner, in_forecast=True)
    assert lease.rule_id == rule_id
    assert RecurringRule.objects.get(pk=rule_id).is_active


def test_a_dollar_lease_is_paid_from_dollars(shop, owner, yunusobod, dollars):
    lease = services.create_contract(
        shop,
        by=owner,
        kind="lease",
        title="Yunusobod ijarasi",
        branch=yunusobod,
        starts_on=date(2026, 1, 1),
        ends_on=date(2026, 12, 21),
        amount=Decimal(1400),
        currency="USD",
        period="monthly",
        payment_day=1,
        in_forecast=True,
    )
    assert lease.rule.currency == "USD"
    assert lease.rule.account_id == dollars.pk


def test_a_dollar_lease_without_a_dollar_account_is_refused(shop, owner):
    with pytest.raises(DomainError):
        services.create_contract(
            shop,
            by=owner,
            kind="lease",
            title="Yunusobod ijarasi",
            starts_on=date(2026, 1, 1),
            amount=Decimal(1400),
            currency="USD",
            in_forecast=True,
        )
    assert not BusinessContract.objects.exists()  # all or nothing


def test_taking_over_a_recurring_payment_already_planned(shop, owner, lease, landlord, chilonzor):
    rent = Category.objects.get(company=shop, system_code="rent")
    planned = recurring.create_rule(
        shop,
        by=owner,
        name="Ijara: Chilonzor",
        kind="expense",
        mode="bill",
        frequency="monthly",
        day=3,
        category=rent,
        counterparty=landlord,
        branch=chilonzor,
        amount=Decimal(9_000_000),
        starts_on=date(2026, 9, 1),
    )
    lease = services.update_contract(
        lease, by=owner, in_forecast=True, money=services.RuleChoice(rule=planned)
    )
    assert lease.rule_id == planned.pk
    assert RecurringRule.objects.filter(company=shop).count() == 1  # not counted twice
    planned.refresh_from_db()
    assert planned.name == "Ijara: Chilonzor"  # its own name stays
    assert planned.ends_on == date(2026, 12, 31)
    # Another contract can't take the same one.
    second = services.create_contract(
        shop, by=owner, kind="lease", title="Ikkinchi", starts_on=date(2026, 1, 1)
    )
    with pytest.raises(DomainError):
        services.update_contract(
            second,
            by=owner,
            in_forecast=True,
            amount=Decimal(1),
            money=services.RuleChoice(rule=planned),
        )


def test_the_forecast_needs_the_finance_module(shop, owner, lease):
    shop.features = []
    shop.save(update_fields=["features"])
    with pytest.raises(DomainError):
        services.update_contract(lease, by=owner, in_forecast=True)


def test_what_was_paid_under_it(shop, owner, lease, bank, landlord, chilonzor):
    from apps.contracts import queries

    lease = services.update_contract(lease, by=owner, in_forecast=True)
    rent = Category.objects.get(company=shop, system_code="rent")
    # October's rent, paid before the contract had its rule (straight to the landlord).
    finance.record_transaction(
        shop,
        by=owner,
        kind="expense",
        amount=Decimal(9_000_000),
        occurred_on=date(2026, 10, 3),
        account=bank,
        category=rent,
        counterparty=landlord,
        branch=chilonzor,
    )
    # December's bill, paid through the recurring payment.
    recurring.pay_occurrence(lease.rule, by=owner, account=bank, paid_on=DAY)
    # Something to the landlord before the contract started doesn't count.
    finance.record_transaction(
        shop,
        by=owner,
        kind="expense",
        amount=Decimal(500_000),
        occurred_on=date(2025, 12, 1),
        account=bank,
        category=rent,
        counterparty=landlord,
    )
    lease = BusinessContract.objects.select_related("rule").get(pk=lease.pk)
    paid = queries.payments(lease, branch_ids=None, today=DAY)
    assert paid["count"] == 2
    assert paid["total"] == money(18_000_000)
    assert [item["by_rule"] for item in paid["items"]] == [True, False]
    assert paid["last_paid_on"] == DAY
    # December's bill was the last one: the lease ends on 31 December.
    assert paid["next"] is None
    services.update_contract(lease, by=owner, auto_renews=True)
    lease = BusinessContract.objects.select_related("rule").get(pk=lease.pk)
    following = queries.payments(lease, branch_ids=None, today=DAY)["next"]
    assert following == {"due_on": date(2027, 1, 3), "amount": money(9_000_000), "currency": "UZS"}
    # A branch manager of Yunusobod sees none of the Chilonzor payments.
    assert queries.payments(lease, branch_ids=[], today=DAY)["count"] == 0
