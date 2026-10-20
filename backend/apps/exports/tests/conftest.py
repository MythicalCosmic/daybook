from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from rest_framework import serializers

from apps.exports.registry import Column, register_exporter
from apps.members.permissions import Perm

ROWS = [
    {
        "title": "Count the till",
        "amount": Decimal("1250000.50"),
        "due": date(2026, 10, 20),
        "at": datetime(2026, 10, 20, 4, 30, tzinfo=UTC),  # 09:30 in Tashkent
        "done": True,
        "count": 3,
    },
    {
        "title": '=HYPERLINK("http://evil")',
        "amount": None,
        "due": None,
        "at": None,
        "done": False,
        "count": None,
    },
]


class StatusParams(serializers.Serializer):
    status = serializers.ChoiceField(["todo", "done"], required=False)


@pytest.fixture
def exporters(isolated_registries):
    """Two exporters as apps.exports would register them; `seen` records each call."""
    seen = SimpleNamespace(calls=[], rows=list(ROWS))

    def rows(member, params):
        seen.calls.append((member.pk, params))
        return iter(seen.rows)

    columns = [
        Column("title", "Title"),
        Column("amount", "Amount", "money"),
        Column("due", "Due", "date"),
        Column("at", "Done at", "datetime"),
        ("done", "Done", "bool"),
        ("count", "Count", "number"),
    ]
    register_exporter(
        "exports.tasks",
        perm=Perm.TASKS_VIEW_ALL,
        label="Tasks: today/all",
        columns=columns,
        rows=rows,
        params=StatusParams,
    )
    register_exporter(
        "exports.salaries",
        perm=Perm.PAYROLL_VIEW,
        label="Salaries",
        columns=[("name", "Name"), ("salary", "Salary", "money")],
        rows=lambda member, params: [{"name": "Ali", "salary": Decimal("5200000")}],
        sensitive=True,
    )
    register_exporter(
        "exports.sales_only",
        perm=None,
        label="Shifts",
        columns=[("n", "N")],
        rows=lambda member, params: [],
        feature="sales",
        formats=("csv",),
    )
    return seen
