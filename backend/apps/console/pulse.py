"""Live badges without table scans: version counters in the Django cache.

After a change a module calls `bump(company_id, "sales.shifts")` (after commit; the owner base
views' `bump()` does that for you). Clients poll `pulse/` every 15 s, compare the versions and
refetch only what changed. Counters (badge numbers) come from the `register_pulse` providers
and are cached for 10 s per member.

Everything goes through the Django cache, so it works on the in-memory test cache, and keys
carry the cache's `KEY_PREFIX` (per test run and per package).
"""

import logging

from django.core.cache import cache

from apps.console import registry
from apps.members.models import Membership

logger = logging.getLogger(__name__)

COUNTERS_TTL = 10


def version_key(company_id: int, key: str) -> str:
    return f"pulse:{company_id}:{key}"


def bump(company_id: int, *keys: str) -> None:
    """Move each key's version on, so every open dashboard of the company refetches it."""
    for key in keys:
        if key not in registry.PULSE:
            logger.warning("pulse.bump(%s, %r): not a registered pulse key", company_id, key)
        name = version_key(company_id, key)
        try:
            cache.incr(name)
        except ValueError:
            # First change since the cache started: create it (unless another bump just did).
            if not cache.add(name, 1, timeout=None):
                cache.incr(name)


def versions(company_id: int, keys: list[str]) -> dict[str, str]:
    """{key: version} as strings; a key never bumped is "0"."""
    found = cache.get_many([version_key(company_id, key) for key in keys])
    return {key: str(found.get(version_key(company_id, key), 0)) for key in keys}


def counters(member: Membership) -> dict[str, int]:
    """The member's badge numbers, cached for `COUNTERS_TTL` seconds."""
    name = f"pulse:{member.company_id}:member:{member.pk}"
    found = cache.get(name)
    if found is None:
        found = registry.pulse_counts(member)
        cache.set(name, found, COUNTERS_TTL)
    return found


def snapshot(member: Membership) -> dict:
    """What `GET pulse/` answers: counters and versions for the keys `member` may see."""
    keys = [counter.key for counter in registry.PULSE.visible_to(member)]
    return {"counters": counters(member), "versions": versions(member.company_id, keys)}
