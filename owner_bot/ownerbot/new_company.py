"""The `/new` conversation's backend side (sync; handlers call it through sync_to_async)."""

import zoneinfo

from apps.accounts.models import User
from apps.companies.models import Company
from apps.companies.services import create_company_for
from apps.core.exceptions import DomainError
from apps.signin import signup

# What people type instead of a zone name.
ALIASES = {
    "toshkent": "Asia/Tashkent",
    "ташкент": "Asia/Tashkent",
    "uzbekistan": "Asia/Tashkent",
    "o‘zbekiston": "Asia/Tashkent",
    "узбекистан": "Asia/Tashkent",
    "samarqand": "Asia/Samarkand",
    "самарканд": "Asia/Samarkand",
    "москва": "Europe/Moscow",
    "алматы": "Asia/Almaty",
    "бишкек": "Asia/Bishkek",
    "душанбе": "Asia/Dushanbe",
    "дубай": "Asia/Dubai",
}


def policy(user: User) -> signup.Policy:
    return signup.policy(user)


def code_ok(raw: str) -> str | None:
    """The normalized code when it can be used, else None (nothing is used up yet)."""
    return signup.normalize(raw) if signup.find(raw) else None


def resolve_timezone(text: str) -> str | None:
    """Typed text like "Asia/Samarkand", "samarkand" or "Ташкент" → a zone name, or None."""
    typed = (text or "").strip()
    if not typed:
        return None
    lowered = typed.lower()
    if lowered in ALIASES:
        return ALIASES[lowered]
    wanted = lowered.replace(" ", "_")
    zones = zoneinfo.available_timezones()
    for zone in sorted(zones):
        name = zone.lower()
        if name == wanted or name.endswith("/" + wanted):
            return zone
    return None


def create(user: User, *, name: str, timezone: str, code: str | None) -> Company:
    """Raises DomainError with a message for the person."""
    company, _copied = create_company_for(
        user, name=name, timezone=timezone, language=user.language, signup_code=code
    )
    return company


__all__ = ["DomainError", "code_ok", "create", "policy", "resolve_timezone"]
