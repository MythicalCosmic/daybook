"""Property test: whatever sequence of writes happens, the cached numbers equal their rows.

A seeded random walk of incomes, expenses, owner draws, transfers across currencies, debts in
both currencies, payments, write-offs, voids and cancellations. Refused writes (not enough
money, more than is owed…) are part of the walk. After every step:

- each account's balance = Σ amount of its posted rows (and `balance(on=day)` agrees day by day);
- each row's `base_amount` = its amount converted at its frozen rate (a settlement that moves no
  money, valued by its debt's running totals, within a tiyin of it);
- each debt's `paid` = Σ debt_amount of its posted payments and write-offs, and its status fits;
- what the settlements of a debt took off it, in the base currency, adds up exactly to `paid` at
  the debt's rate;
- each posted transfer's account rows differ in the base currency by exactly its `fx` row.
"""

import random
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.core.exceptions import DomainError
from apps.finance import queries, services
from apps.finance.models import Debt, MoneyAccount, Transaction, Transfer
from apps.finance.rates import convert
from apps.finance.tests.factories import CounterpartyFactory, ExchangeRateFactory

pytestmark = pytest.mark.django_db

D = Decimal
K = Transaction.Kind
POSTED = Transaction.Status.POSTED


class Walk:
    def __init__(self, seed, company, owner, accounts, day):
        self.rng = random.Random(seed)
        self.company = company
        self.owner = owner
        self.accounts = accounts
        self.days = [day + timedelta(days=n) for n in range(6)]
        self.party = CounterpartyFactory(company=company)
        self.refused = 0

    def amount(self, account=None):
        if account is not None and account.currency == "USD":
            return D(self.rng.randint(1, 30000)) / 100
        return D(self.rng.randint(1, 400)) * 1000

    def pick(self, items):
        return self.rng.choice(list(items)) if items else None

    def account(self):
        return self.pick(self.accounts)

    def day(self):
        return self.pick(self.days)

    def step(self):
        action = self.pick(
            [
                *(self.income, self.expense, self.owner_entry, self.transfer, self.transfer),
                *(self.open_debt, self.pay_debt, self.pay_debt, self.write_off),
                *(self.void_row, self.void_transfer, self.cancel_debt),
            ]
        )
        try:
            action()
        except DomainError:
            self.refused += 1

    def income(self):
        account = self.account()
        services.record_transaction(
            self.company,
            by=self.owner,
            kind="income",
            amount=self.amount(account),
            occurred_on=self.day(),
            account=account,
            category="sales",
            is_contra=self.rng.random() < 0.1,
        )

    def expense(self):
        account = self.account()
        services.record_transaction(
            self.company,
            by=self.owner,
            kind="expense",
            amount=self.amount(account),
            occurred_on=self.day(),
            account=account,
            category="rent",
            status="pending" if self.rng.random() < 0.2 else "posted",
        )

    def owner_entry(self):
        account = self.account()
        sign = 1 if self.rng.random() < 0.6 else -1
        services.record_transaction(
            self.company,
            by=self.owner,
            kind="owner",
            amount=sign * self.amount(account),
            occurred_on=self.day(),
            account=account,
        )

    def transfer(self):
        source, target = self.rng.sample(self.accounts, 2)
        kwargs = {}
        if source.currency != target.currency and self.rng.random() < 0.5:
            kwargs["amount_in"] = self.amount(target)
        if self.rng.random() < 0.3:
            kwargs["fee"] = self.amount(source) / 100
        services.transfer(
            self.company,
            by=self.owner,
            from_account=source,
            to_account=target,
            amount_out=self.amount(source),
            occurred_on=self.day(),
            **kwargs,
        )

    def open_debt(self):
        currency = self.pick(["UZS", "USD"])
        matching = [a for a in self.accounts if a.currency == currency]
        how = self.pick(["account", "category", "neither"])
        direction = self.pick(["receivable", "payable"])
        services.open_debt(
            self.company,
            by=self.owner,
            direction=direction,
            kind="trade",
            amount=self.amount(matching[0]),
            currency=currency,
            issued_on=self.pick(self.days[:2]),
            counterparty=self.party,
            account=self.pick(matching) if how == "account" else None,
            category=self.pick(["other_income" if direction == "receivable" else "other_expense"])
            if how == "category"
            else None,
            is_opening=how == "neither",
        )

    def pay_debt(self):
        debt = self.pick(Debt.objects.filter(company=self.company, status="open"))
        if debt is None:
            return
        left = debt.amount - debt.paid
        account = self.pick([*self.accounts, None])
        if account is None or account.currency == debt.currency:
            amount = max(D("0.01"), (left * D(self.rng.randint(1, 100)) / 100).quantize(D("0.01")))
            services.pay_debt(
                debt, by=self.owner, amount=amount, paid_on=self.day(), account=account
            )
        else:
            services.pay_debt(
                debt,
                by=self.owner,
                amount=self.amount(account),
                paid_on=self.day(),
                account=account,
            )

    def write_off(self):
        debt = self.pick(Debt.objects.filter(company=self.company, status="open"))
        if debt is not None:
            services.write_off(debt, by=self.owner, reason="Walk")

    def void_row(self):
        row = self.pick(
            Transaction.objects.filter(
                company=self.company,
                status__in=["posted", "pending"],
                transfer=None,
                kind__in=[K.INCOME, K.EXPENSE, K.OWNER, K.DEBT_PAYMENT, K.WRITE_OFF],
            ).exclude(account=None, kind__in=[K.INCOME, K.EXPENSE])
        )
        if row is None:
            return
        if row.status == "pending" and self.rng.random() < 0.5:
            services.approve_transaction(row, by=self.owner)
        else:
            services.void_transaction(row, by=self.owner, reason="Walk")

    def void_transfer(self):
        moved = self.pick(Transfer.objects.filter(company=self.company, status="posted"))
        if moved is not None:
            services.void_transfer(moved, by=self.owner, reason="Walk")

    def cancel_debt(self):
        debt = self.pick(Debt.objects.filter(company=self.company).exclude(status="cancelled"))
        if debt is not None and self.rng.random() < 0.3:
            services.cancel_debt(debt, by=self.owner, reason="Walk")

    def check(self):
        company = self.company
        rows = list(Transaction.objects.filter(company=company))
        for account in MoneyAccount.objects.filter(company=company):
            posted = [r for r in rows if r.account_id == account.pk and r.status == POSTED]
            assert account.balance == sum((r.amount for r in posted), D(0)), account
            assert queries.balance(account) == queries.ledger_balance(account)
            for day in self.days:
                expected = sum((r.amount for r in posted if r.occurred_on <= day), D(0))
                assert queries.balance(account, on=day) == expected
        base = company.base_currency
        for row in rows:
            converted = convert(row.amount, row.currency, base, row.rate)
            if row.account_id is None and row.kind in (K.DEBT_PAYMENT, K.WRITE_OFF):
                # Valued by the running totals of its debt: within a tiyin of amount x rate.
                assert abs(row.base_amount - converted) <= D("0.01"), row
            else:
                assert row.base_amount == converted, row
        exchange = {
            r.source_id: r.base_amount
            for r in rows
            if r.kind == K.FX and r.source_type == services.ROW_SOURCE and r.status == POSTED
        }
        for debt in Debt.objects.filter(company=company):
            settlements = [
                r for r in rows if r.debt_id == debt.pk and r.kind in (K.DEBT_PAYMENT, K.WRITE_OFF)
            ]
            if debt.status != Debt.Status.CANCELLED and all(
                r.status == POSTED for r in settlements
            ):
                # Never voided: what the settlements took off the debt adds up to `paid` at the
                # debt's rate exactly, so its income or expense equals the cash it brought.
                sign = 1 if debt.direction == Debt.Direction.RECEIVABLE else -1
                book = sum(
                    (
                        abs(r.base_amount)
                        if r.kind == K.WRITE_OFF
                        else sign * (r.base_amount - exchange.get(r.pk, D(0)))
                        for r in settlements
                    ),
                    D(0),
                )
                assert book == convert(debt.paid, debt.currency, base, debt.rate), debt
        for debt in Debt.objects.filter(company=company):
            settled = sum(
                (
                    r.debt_amount
                    for r in rows
                    if r.debt_id == debt.pk
                    and r.status == POSTED
                    and r.kind in (K.DEBT_PAYMENT, K.WRITE_OFF)
                ),
                D(0),
            )
            if debt.status == Debt.Status.CANCELLED:
                assert debt.paid == 0
                assert all(r.status == "void" for r in rows if r.debt_id == debt.pk)
            else:
                assert debt.paid == settled
                assert (debt.status == Debt.Status.OPEN) == (debt.paid < debt.amount)
        for moved in Transfer.objects.filter(company=company, status="posted"):
            mine = [r for r in rows if r.transfer_id == moved.pk]
            sides = sum((r.base_amount for r in mine if r.kind == K.TRANSFER), D(0))
            fx = sum((r.base_amount for r in mine if r.kind == K.FX), D(0))
            assert sides == fx


@pytest.mark.parametrize("seed", [1, 2, 5, 10])  # 5 and 10 split foreign debts unevenly
def test_balances_always_equal_their_rows(books, owner, cash, bank, dollars, day, seed):
    ExchangeRateFactory(date=day, rate=D("12800"))
    ExchangeRateFactory(date=day + timedelta(days=1), rate=D("12345.678901"))
    ExchangeRateFactory(date=day + timedelta(days=3), rate=D("12950.5"))
    walk = Walk(seed, books, owner, [cash, bank, dollars], day)
    for account in walk.accounts:
        services.record_transaction(
            books,
            by=owner,
            kind="opening",
            amount=walk.amount(account) * 20,
            occurred_on=day,
            account=account,
        )

    for _ in range(70):
        walk.step()
        walk.check()

    assert walk.refused < 35  # the walk mostly writes rather than gets refused
