"""Fixed shapes that modules hand to the console (docs/PLAN-OWNER.md §2.5, §13.2).

Money is a string ("48120000.00") and a time an ISO string in the company's timezone. A key
is absent when its module is off or the caller lacks its permission; when present it has exactly
these fields. Providers check their output in their own tests with `problems()`:

    assert contracts.problems(contracts.BRANCH_FACTS["sales"], facts[branch.pk]) == []
"""

import types
import typing
from typing import Any, NotRequired, TypedDict, get_type_hints, is_typeddict


class Person(TypedDict):
    id: int
    name: str


# Branch cards: register_branch_facts(key) with key in BRANCH_FACTS ------------------------


class SalesFacts(TypedDict):
    opened_at: str | None
    opened_by: Person | None
    open_tills: int
    net: str
    cash_in_branch: str


class AttendanceFacts(TypedDict):
    rostered: int
    checked_in: int
    first_check_in: str | None


class TasksFacts(TypedDict):
    done: int
    total: int
    late: int


class FinanceFacts(TypedDict):
    cash: str


BRANCH_FACTS: dict[str, type] = {
    "sales": SalesFacts,
    "attendance": AttendanceFacts,
    "tasks": TasksFacts,
    "finance": FinanceFacts,
}


# Portfolio cards: register_company_facts(key) with key in COMPANY_FACTS -----------------


class TasksCompanyFacts(TypedDict):
    done: int
    total: int
    late: int


class SalesCompanyFacts(TypedDict):
    net: str
    prev_net: str


class FinanceCompanyFacts(TypedDict):
    cash: str
    income: str
    expenses: str
    profit: str


class AttendanceCompanyFacts(TypedDict):
    present: int
    rostered: int


class PayrollCompanyFacts(TypedDict):
    next_run_on: str | None
    next_run_amount: str | None


class InboxCompanyFacts(TypedDict):
    waiting: int


class InsightsCompanyFacts(TypedDict):
    alerts: int


COMPANY_FACTS: dict[str, type] = {
    "tasks": TasksCompanyFacts,
    "sales": SalesCompanyFacts,
    "finance": FinanceCompanyFacts,
    "attendance": AttendanceCompanyFacts,
    "payroll": PayrollCompanyFacts,
    "inbox": InboxCompanyFacts,
    "insights": InsightsCompanyFacts,
}


# Person fields: register_person_fields(key); these keys have fixed fields --------------


class Salary(TypedDict):
    amount: str
    currency: str
    pay_type: str


class AttendancePersonFields(TypedDict):
    attendance_today: str | None  # "in" | "late" | "not_yet" | "absent" | "off" | None
    attendance_30d: str | None  # "93.5"


class PayrollPersonFields(TypedDict):
    salary: Salary | None


PERSON_FIELDS: dict[str, type] = {
    "attendance": AttendancePersonFields,
    "payroll": PayrollPersonFields,
}
ATTENDANCE_TODAY = ("in", "late", "not_yet", "absent", "off")


def problems(shape: type, value: Any, path: str = "") -> list[str]:
    """What's wrong with `value` as a `shape` TypedDict: missing, unexpected and mistyped
    fields (nested TypedDicts included). Empty means it fits."""
    if not isinstance(value, dict):
        return [f"{path or 'value'}: expected a dict, got {type(value).__name__}"]
    hints = get_type_hints(shape)
    required = {name for name in hints if name in shape.__required_keys__}
    found: list[str] = []
    for name in sorted(required - value.keys()):
        found.append(f"{path}{name}: missing")
    for name in sorted(value.keys() - hints.keys()):
        found.append(f"{path}{name}: not part of {shape.__name__}")
    for name, hint in hints.items():
        if name in value:
            found += _check(hint, value[name], f"{path}{name}")
    return found


def _check(hint: Any, value: Any, path: str) -> list[str]:
    options = getattr(hint, "__args__", None) if _is_union(hint) else None
    if options is not None:
        results = [_check(option, value, path) for option in options]
        if any(not result for result in results):
            return []
        return [f"{path}: {value!r} fits none of {hint}"]
    if hint is type(None):
        return [] if value is None else [f"{path}: expected None"]
    if getattr(hint, "__origin__", None) is NotRequired:
        return _check(hint.__args__[0], value, path)
    if is_typeddict(hint):
        return problems(hint, value, f"{path}.")
    if hint is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
        return [] if ok else [f"{path}: expected an int, got {value!r}"]
    if hint is str:
        return [] if isinstance(value, str) else [f"{path}: expected a string, got {value!r}"]
    return []


def _is_union(hint: Any) -> bool:
    return isinstance(hint, types.UnionType) or getattr(hint, "__origin__", None) is typing.Union
