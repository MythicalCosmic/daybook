"""Several writers at once, each on its own database connection, as gunicorn workers and Celery
would be: no deadlocks, no lost balance updates, no double bookings."""

import threading
from decimal import Decimal

import pytest
from django.db import OperationalError, connection, transaction

from apps.core.exceptions import DomainError
from apps.finance import queries, services
from apps.finance.models import Debt, FinanceSettings, MoneyAccount
from apps.finance.tests.factories import CounterpartyFactory

pytestmark = pytest.mark.django_db(transaction=True)

D = Decimal


def run_together(*jobs):
    """Start every job at the same moment in its own thread; re-raise the first error."""
    barrier = threading.Barrier(len(jobs))
    errors = []

    def wrap(job):
        try:
            barrier.wait()
            job()
        except Exception as exc:  # handed back to the test
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=wrap, args=(job,)) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    if errors:
        raise errors[0]


def test_opposite_transfers_neither_deadlock_nor_lose_money(books, owner, cash, bank, day):
    for account in (cash, bank):
        services.record_transaction(
            books, by=owner, kind="opening", amount=1000, occurred_on=day, account=account
        )

    def shuttle(source, target):
        def job():
            for _ in range(15):
                services.transfer(
                    books,
                    by=owner,
                    from_account=source,
                    to_account=target,
                    amount_out=10,
                    occurred_on=day,
                )

        return job

    run_together(shuttle(cash, bank), shuttle(bank, cash), shuttle(cash, bank))

    assert queries.balance(cash) == D("850.00")
    assert queries.balance(bank) == D("1150.00")
    for account in (cash, bank):
        assert queries.balance(account) == queries.ledger_balance(account)


def test_parallel_incomes_add_up(books, owner, cash, day):
    def job():
        for _ in range(10):
            services.record_transaction(
                books,
                by=owner,
                kind="income",
                amount=1,
                occurred_on=day,
                account=cash,
                category="sales",
            )

    run_together(job, job, job, job)

    assert queries.balance(cash) == D("40.00") == queries.ledger_balance(cash)


def test_one_holder_account_however_many_ask(books, member):
    worker = member(books)
    found = []

    def job():
        found.append(services.account_for_holder(books, worker).pk)

    run_together(*[job] * 4)

    assert len(set(found)) == 1
    assert MoneyAccount.objects.filter(holder=worker).count() == 1


def test_one_branch_safe_however_many_ask(books):
    branch = books.branches.create(name="Yunusobod")
    found = []

    def job():
        found.append(services.account_for_branch(branch, kind="cash").pk)

    run_together(*[job] * 4)

    assert len(set(found)) == 1


def test_a_source_booked_twice_at_once_is_booked_once(books, day, src):
    customer = CounterpartyFactory(company=books)
    made = []

    def job():
        made.append(
            services.open_debt(
                books,
                by=None,
                direction="receivable",
                kind="trade",
                amount=100,
                currency="UZS",
                issued_on=day,
                counterparty=customer,
                category="sales",
                source=src(77, "issue"),
            ).pk
        )

    run_together(*[job] * 4)

    assert len(set(made)) == 1
    assert Debt.objects.count() == 1


def test_two_payments_on_one_debt_never_pay_more_than_is_owed(books, owner, cash, day):
    debt = services.open_debt(
        books,
        by=owner,
        direction="receivable",
        kind="trade",
        amount=100,
        currency="UZS",
        issued_on=day,
        counterparty=CounterpartyFactory(company=books),
        category="sales",
    )
    refused = []

    def job():
        try:
            services.pay_debt(debt, by=owner, amount=60, paid_on=day, account=cash)
        except DomainError as exc:
            refused.append(exc)

    run_together(job, job, job)

    debt.refresh_from_db()
    assert (debt.paid, debt.status, len(refused)) == (D("60.00"), Debt.Status.OPEN, 2)
    assert queries.balance(cash) == D("60.00") == queries.ledger_balance(cash)


def test_a_full_payment_retried_at_once_is_booked_once(books, owner, cash, day, src):
    debt = services.open_debt(
        books,
        by=owner,
        direction="receivable",
        kind="trade",
        amount=100,
        currency="UZS",
        issued_on=day,
        counterparty=CounterpartyFactory(company=books),
        category="sales",
    )
    paid = []

    def job():
        row = services.pay_debt(debt, by=None, amount=100, paid_on=day, account=cash, source=src(3))
        paid.append(row.pk)

    run_together(*[job] * 3)

    assert len(set(paid)) == 1
    assert queries.balance(cash) == D("100.00")


def test_closing_a_period_waits_for_the_writes_already_running(books, owner, cash, day):
    """A write holds the books' share lock until it commits: the UPDATE that closes the period
    can't slip in between its check and its insert."""
    services.get_settings(books)  # the settings row exists before either starts
    written, release = threading.Event(), threading.Event()
    outcome = {}

    def writer():
        try:
            with transaction.atomic():
                services.record_transaction(
                    books, by=owner, kind="opening", amount=5, occurred_on=day, account=cash
                )
                written.set()
                release.wait(timeout=30)
        finally:
            connection.close()

    def closer():
        try:
            written.wait(timeout=30)
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '300ms'")
                try:
                    with transaction.atomic():
                        FinanceSettings.objects.filter(company=books).update(locked_until=day)
                    outcome["while_writing"] = "closed"
                except OperationalError:
                    outcome["while_writing"] = "waited"
            release.set()
            FinanceSettings.objects.filter(company=books).update(locked_until=day)
        finally:
            release.set()
            connection.close()

    threads = [threading.Thread(target=writer), threading.Thread(target=closer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert outcome == {"while_writing": "waited"}
    assert FinanceSettings.objects.get(company=books).locked_until == day
    assert queries.balance(cash) == D("5.00")  # committed before the period closed
    with pytest.raises(DomainError, match="closed"):
        services.record_transaction(
            books, by=owner, kind="opening", amount=5, occurred_on=day, account=cash
        )
