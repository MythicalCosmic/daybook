"""The W0 finance contract (docs/PLAN-OWNER.md §3.7 and §13.3): sales, payroll, invoices, claims
and the AI code against these signatures without reading the code, so they never change by
accident. A change here needs the lead's OK."""

import inspect

import pytest

from apps.finance import queries, rates, services, sources

CONTRACT = {
    services.create_defaults: "company",
    services.get_settings: "company",
    services.rate_for: "company, currency, day",
    services.create_account: (
        "company, *, by, kind, name, currency='UZS', branch=None, holder=None"
    ),
    services.account_for_holder: "company, membership, *, kind='employee', currency='UZS'",
    services.account_for_branch: "branch, *, kind='safe', currency='UZS'",
    services.record_transaction: (
        "company, *, by, kind, amount, occurred_on, account=None, currency=None, "
        "category=None, counterparty=None, membership=None, branch=None, debt=None, "
        "debt_amount=None, description='', rate=None, is_contra=False, status='posted', "
        "source=None, project=None"
    ),
    services.approve_transaction: "txn, *, by",
    services.reject_transaction: "txn, *, by, reason",
    services.void_transaction: "txn, *, by, reason",
    services.transfer: (
        "company, *, by, from_account, to_account, amount_out, occurred_on, amount_in=None, "
        "rate=None, fee=Decimal('0'), description='', source=None"
    ),
    services.void_transfer: "transfer, *, by, reason",
    services.open_debt: (
        "company, *, by, direction, kind, amount, currency, issued_on, counterparty=None, "
        "membership=None, due_on=None, account=None, category=None, branch=None, "
        "description='', responsible=None, is_opening=False, source=None, project=None"
    ),
    services.pay_debt: "debt, *, by, amount, paid_on, account=None, debt_amount=None, source=None",
    services.write_off: "debt, *, by, reason, amount=None",
    services.cancel_debt: "debt, *, by, reason",
    services.lock_debt: "debt, *, source",
    services.unlock_debt: "debt, *, source",
    queries.balance: "account, on=None",
    queries.open_debts: (
        "company, *, membership=None, counterparty=None, kind=None, direction=None"
    ),
    queries.has_ledger_rows: "company",
    sources.register: "type, *, label, url_template",
}


def shape(function) -> str:
    """The parameters as they're called: names, keyword-only marker and defaults, no types."""
    parts, star = [], False
    for parameter in inspect.signature(function).parameters.values():
        if parameter.kind is parameter.KEYWORD_ONLY and not star:
            parts.append("*")
            star = True
        text = parameter.name
        if parameter.default is not parameter.empty:
            default = parameter.default
            text += f"={str(default)!r}" if isinstance(default, str) else f"={default!r}"
        parts.append(text)
    return ", ".join(parts)


@pytest.mark.parametrize("function", CONTRACT, ids=lambda f: f.__name__)
def test_the_contract_keeps_its_signature(function):
    assert shape(function) == CONTRACT[function]


def test_the_shared_types():
    assert services.Source is sources.Source
    assert services.Source._fields == ("type", "id", "key")
    assert services.Source("sales.cashshift", 1).key == ""
    assert services.RateQuote is rates.RateQuote
    assert rates.RateQuote._fields == ("rate", "stale", "source")
    assert services.rate_for is rates.rate_for
