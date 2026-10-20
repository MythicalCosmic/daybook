"""Where ledger rows come from: links a row to its shift, payslip, invoice or claim.

A module that posts to the ledger registers each source type once, in its `hooks.py`:

    from apps.finance import sources

    sources.register(
        "sales.cashshift", label=_("Cash shift"), url_template="/c/{company_id}/sales/shifts/{id}"
    )

and passes `Source("sales.cashshift", shift.id, "m3")` to the finance services. A repeated
source returns the rows it already made, so a retried job never books twice. The key tells
apart several bookings of one record (a payment method, "diff", "accrued", "paid").

The type is `<app label>.<name>` and starts with the registering app's label (rule 14). Types
and keys are at most 32 characters. Registering a type twice raises `DuplicateSource`.
"""

import re
from dataclasses import dataclass
from typing import NamedTuple

from django.apps import apps

MAX_LENGTH = 32
TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


class Source(NamedTuple):
    type: str
    id: int
    key: str = ""


class DuplicateSource(ValueError):
    pass


@dataclass(frozen=True)
class SourceType:
    type: str
    label: str  # usually a lazy translation
    url_template: str  # dashboard route with {company_id} and {id}


_registry: dict[str, SourceType] = {}


def register(type: str, *, label, url_template: str) -> SourceType:
    if len(type) > MAX_LENGTH or not TYPE_PATTERN.match(type):
        raise ValueError(
            f"A source type looks like 'sales.cashshift' (at most 32 characters): {type!r}"
        )
    app_label = type.split(".", 1)[0]
    if app_label not in {config.label for config in apps.get_app_configs()}:
        raise ValueError(f"Source type {type!r} must start with an installed app's label.")
    if type in _registry:
        raise DuplicateSource(f"Source type {type!r} is registered twice.")
    entry = SourceType(type=type, label=label, url_template=url_template)
    _registry[type] = entry
    return entry


def unregister(type: str) -> None:
    """For tests that register a throwaway type."""
    _registry.pop(type, None)


def get(type: str) -> SourceType | None:
    return _registry.get(type)


def registered() -> dict[str, SourceType]:
    return dict(_registry)


def label(type: str) -> str:
    entry = _registry.get(type)
    return str(entry.label) if entry else type


def url(type: str, id: int, company_id: int) -> str:
    """The dashboard route of a source record, or "" for a type nobody registered."""
    entry = _registry.get(type)
    if entry is None or not entry.url_template:
        return ""
    return entry.url_template.format(company_id=company_id, id=id)


def check(source) -> Source | None:
    """`source` as a `Source` (a plain tuple works too), after checking it. None stays None."""
    if source is None:
        return None
    source = Source(*source)
    if source.type not in _registry:
        raise ValueError(f"Register source type {source.type!r} with apps.finance.sources first.")
    if not isinstance(source.id, int) or isinstance(source.id, bool) or source.id <= 0:
        raise ValueError(f"A source id is a positive integer, not {source.id!r}.")
    if not isinstance(source.key, str) or len(source.key) > MAX_LENGTH:
        raise ValueError(f"A source key is a string of at most 32 characters: {source.key!r}")
    return source
