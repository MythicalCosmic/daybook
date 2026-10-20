"""Several writers at once, each on its own database connection, as gunicorn workers and Celery
would be: no deadlocks, no lost balance updates, no double bookings."""

import threading
from decimal import Decimal

import pytest
from django.db import connection

from apps.finance import queries, services
from apps.finance.models import Debt, MoneyAccount
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
