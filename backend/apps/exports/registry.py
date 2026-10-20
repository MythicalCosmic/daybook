"""Exporters: every table and report a module offers as Excel/CSV, registered in `hooks.py`.

    register_exporter(
        "tasks.tasks",
        perm=Perm.TASKS_VIEW_ALL,
        label=_("Tasks"),
        columns=[Column("title", _("Title")), Column("due_at", _("Due"), "datetime")],
        rows=lambda member, params: queries.export_rows(member, params),
    )

`rows(member, params)` yields dicts keyed by column key and applies the member's branch scope
itself. `sensitive=True` for anything that needs `payroll.view`, `hr.sensitive` or per-person
`finance.view` detail (the dashboard warns before sending those to Telegram). An optional DRF
serializer class in `params` validates the request's `params`. Requesting an export needs
`data.export` plus the exporter's `perm`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from apps.console.perms import PermSpec
from apps.console.registry import Entry, Registry, RegistryError, calling_app, usable
from apps.members.permissions import Perm

if TYPE_CHECKING:
    from rest_framework.serializers import Serializer

    from apps.members.models import Membership

COLUMN_KINDS = ("text", "number", "money", "date", "datetime", "bool")
FORMATS = ("xlsx", "csv")


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: str = "text"

    def __post_init__(self):
        if self.kind not in COLUMN_KINDS:
            raise ValueError(f"Column kind must be one of {COLUMN_KINDS}.")


@dataclass(frozen=True)
class Exporter(Entry):
    label: str
    columns: tuple[Column, ...]
    rows: Callable[[Membership, dict], Iterable[dict]]
    sensitive: bool
    params: type[Serializer] | None
    formats: tuple[str, ...]


EXPORTERS: Registry[Exporter] = Registry("exporters")


def register_exporter(
    kind: str,
    *,
    perm: PermSpec,
    label: str,
    columns: Sequence[Column | tuple[str, str] | tuple[str, str, str]],
    rows: Callable[[Membership, dict], Iterable[dict]],
    sensitive: bool = False,
    params: type[Serializer] | None = None,
    formats: Sequence[str] = FORMATS,
    feature: str | None = None,
) -> None:
    built = tuple(column if isinstance(column, Column) else Column(*column) for column in columns)
    if not built:
        raise RegistryError(f"exporter {kind!r}: give at least one column.")
    if len({column.key for column in built}) != len(built):
        raise RegistryError(f"exporter {kind!r}: column keys must be unique.")
    unknown = set(formats) - set(FORMATS)
    if unknown:
        raise RegistryError(f"exporter {kind!r}: unsupported formats {sorted(unknown)}.")
    EXPORTERS.add(
        Exporter(
            kind,
            calling_app(),
            perm,
            feature,
            label,
            built,
            rows,
            sensitive,
            params,
            tuple(formats),
        )
    )


def get_exporter(kind: str) -> Exporter | None:
    return EXPORTERS.get(kind)


def may_export(member: Membership, exporter: Exporter) -> bool:
    """`data.export` plus the exporter's own permission, with its module switched on."""
    return member.has_perm(Perm.DATA_EXPORT) and usable(exporter, member)
