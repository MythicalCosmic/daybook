"""Permission specs for owner endpoints and registry entries.

A spec is a `Perm`, `AnyOf(...)` (one of them is enough, e.g. stock reads:
`AnyOf(Perm.SALES_VIEW, Perm.STOCK_MANAGE)`), `AllOf(...)` or a plain tuple (all of them), or
None (nothing beyond being an approved member with `dashboard.access`).
"""

from apps.members.models import Membership
from apps.members.permissions import Perm


class AnyOf(tuple):
    """At least one of these permissions."""

    def __new__(cls, *perms):
        return super().__new__(cls, perms)


class AllOf(tuple):
    """Every one of these permissions."""

    def __new__(cls, *perms):
        return super().__new__(cls, perms)


type PermSpec = Perm | AnyOf | AllOf | tuple | None


def holds(member: Membership, spec: PermSpec) -> bool:
    if spec is None:
        return True
    if isinstance(spec, AnyOf):
        return any(holds(member, part) for part in spec)
    if isinstance(spec, tuple | list):
        return all(holds(member, part) for part in spec)
    return member.has_perm(spec)


def describe(spec: PermSpec) -> list[str]:
    """The permission codes a spec mentions (for schema descriptions and error details)."""
    if spec is None:
        return []
    if isinstance(spec, tuple | list):
        return [code for part in spec for code in describe(part)]
    return [str(spec)]
