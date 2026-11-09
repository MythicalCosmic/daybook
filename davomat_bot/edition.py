"""What the bot needs from the edition core (apps.davomat, docs/DAVOMAT.md §1.5), in one place:
the organization, its bot token and the token's version, and claiming a link code.

All sync (Django); handlers call them through `sync_to_async`.
"""

from django.conf import settings

from apps.accounts.models import User
from apps.companies.models import Company
from apps.davomat import conf as davomat_conf
from apps.davomat import queries as davomat_queries
from apps.davomat import services as davomat_services
from apps.members.models import Membership

# Bumped by apps.davomat whenever the token is saved; the bot restarts when it changes.
TOKEN_VERSION_KEY = davomat_queries.TOKEN_VERSION_KEY


def organization() -> Company | None:
    """The install's organization: one install, one company."""
    return davomat_conf.organization()


def stored_token() -> str:
    """The organization's bot token from Settings (kept encrypted by apps.davomat), or "".

    Outside the Davomat edition (a developer running the bot against a Daybook database) the
    `OWNER_BOT_TOKEN` setting stands in, since nothing else sends through this bot there."""
    if settings.EDITION == "davomat":
        return davomat_queries.bot_token()
    return settings.OWNER_BOT_TOKEN or ""


def token_version() -> str | None:
    """The token's version (Redis, else the database), or None when it can't be read."""
    try:
        return str(davomat_queries.token_version())
    except Exception:  # no database right now: the next look tries again
        return None


def mark_refused() -> None:
    """Telegram refuses the stored token (revoked in BotFather): the Telegram settings say so."""
    company = organization()
    if company is not None and settings.EDITION == "davomat":
        davomat_services.mark_bot_refused(company)


def claim_link(code: str, *, telegram_id: int, username: str, first_name: str) -> Membership:
    """Links this Telegram account to the person a one-time link was made for. Raises
    `apps.davomat.services.LinkRefused` (a DomainError with the message to show) when the code is
    unknown, used by someone else, expired or the person is no longer active."""
    return davomat_services.claim_link(code, telegram_id, username, first_name)


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
