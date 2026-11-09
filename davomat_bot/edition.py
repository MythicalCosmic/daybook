"""What the bot needs from the edition core (apps.davomat, docs/DAVOMAT.md §1.5), in one place:
the organization, its bot token and the token's version, and claiming a link code.

All sync (Django); handlers call them through `sync_to_async`.
"""

import logging

from django.conf import settings

from apps.accounts.models import User
from apps.companies.models import Company
from apps.core import redis as core_redis
from apps.members.models import Membership

logger = logging.getLogger(__name__)

# Bumped by apps.davomat whenever the token is saved; the bot restarts when it changes.
TOKEN_VERSION_KEY = ("davomat", "bot_token_version")


def organization() -> Company | None:
    """The install's organization: one install, one company (the first active one)."""
    return Company.objects.filter(is_active=True).order_by("pk").first()


def stored_token() -> str:
    """The organization's bot token from Settings (kept encrypted by apps.davomat), else the
    `OWNER_BOT_TOKEN` setting, else ""."""
    token = ""
    try:
        from apps.davomat import services as davomat
    except ImportError:  # an install without the edition core: the setting only
        davomat = None
    reader = getattr(davomat, "bot_token", None)
    if reader is not None:
        company = organization()
        if company is not None:
            token = reader(company) or ""
    return token or settings.OWNER_BOT_TOKEN or ""


def token_version() -> str | None:
    """The token's version as apps.davomat wrote it to Redis; None when unset or unreachable."""
    try:
        value = core_redis.get_redis().get(core_redis.key(*TOKEN_VERSION_KEY))
    except Exception as exc:  # Redis down: the stored-token check still catches a change
        logger.warning("Couldn't read the bot token version from Redis: %s", exc)
        return None
    return str(value) if value is not None else None


def claim_link(code: str, *, telegram_id: int, username: str, first_name: str) -> Membership:
    """Links this Telegram account to the person a one-time link was made for (apps.davomat).
    Raises `DomainError` with a message to show when the code is unknown, used or expired."""
    from apps.davomat.services import claim_link as claim

    return claim(code, telegram_id=telegram_id, username=username, first_name=first_name)


def linked_user(telegram_id: int) -> User | None:
    """The person whose Telegram this is, when they linked it (nobody else gets a row here:
    the bot never creates users)."""
    return User.objects.filter(telegram_id=telegram_id, is_active=True).first()


def membership(user: User | None, company: Company | None = None) -> Membership | None:
    """The person's current membership in the organization (approved or suspended)."""
    company = company or organization()
    if user is None or company is None:
        return None
    return (
        Membership.objects.filter(
            user=user,
            company=company,
            status__in=(Membership.Status.APPROVED, Membership.Status.SUSPENDED),
        )
        .select_related("company", "role", "position", "home_branch", "department", "user")
        .order_by("pk")
        .first()
    )
