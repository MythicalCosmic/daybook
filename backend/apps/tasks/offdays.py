"""Who gets no daily tasks on a given day, beyond company holidays and approved time off.

Modules register a provider in `hooks.py`; daily task generation leaves out everyone any
provider names for that day:

    offdays.register(suspended_members)          # members: suspended people
    offdays.register(not_rostered)               # attendance: "tasks follow shifts"

A provider is `(company, day) -> set[int]` of membership ids. Registering the same provider
twice raises.
"""

import logging
from collections.abc import Callable
from datetime import date

logger = logging.getLogger(__name__)

Provider = Callable[[object, date], set[int]]

_providers: list[Provider] = []


class DuplicateProvider(ValueError):
    pass


def register(provider: Provider) -> None:
    if provider in _providers:
        raise DuplicateProvider(f"{provider!r} is already registered.")
    _providers.append(provider)


def providers() -> list[Provider]:
    return list(_providers)


def people_off(company, day: date) -> set[int]:
    """Membership ids that every registered provider together names for `day`."""
    off: set[int] = set()
    for provider in _providers:
        off |= set(provider(company, day))
    return off
