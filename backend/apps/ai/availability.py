"""Whether Claude may run for a company right now (docs/PLAN-OWNER.md §8.1, §8.7, §8.8).

Every Claude feature asks before it calls:

    if availability.status(company, membership=member).available: ...

Claude runs when `ANTHROPIC_API_KEY` is set (or `AI_FAKE` gives canned answers), the company's
AI is on (`apps.ai.conf.ai_on`: an owner's consent, the "ai" module, no platform block), this
month's budget isn't spent (the company's and the platform's) and Anthropic isn't failing (the
circuit breaker is closed). Features that also work without Claude (voice and typed task
drafts: the rules engine) ask `conf.ai_on` instead and use Claude only when this says so.

Spending is the month's sum of `AIUsage.cost_micro_usd`, cached in the Django cache and bumped
by every recorded call (`add_spend`); the cache is only a speed-up, AIUsage is the truth.
"""

import contextlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone

from apps.ai import conf
from apps.members.permissions import Perm

SPEND_TTL = 10 * 60
# The circuit breaker (§8.7): this many failures within the window open it for a while.
BREAKER_FAILURES = 5
BREAKER_WINDOW = 120
BREAKER_OPEN_FOR = 300
_FAILURES_KEY = "ai:breaker:failures"
_OPEN_KEY = "ai:breaker:open"


class AIState(StrEnum):
    AVAILABLE = "available"
    NOT_CONFIGURED = "not_configured"  # no API key on this server
    DISABLED = "disabled"  # the module is off, or no owner has consented yet
    BLOCKED = "blocked"  # the platform switched AI off for this tenant
    BUDGET_REACHED = "budget_reached"  # this month's budget is spent
    UNAVAILABLE = "unavailable"  # Anthropic keeps failing (circuit breaker open)


@dataclass(frozen=True)
class AIStatus:
    state: AIState
    # Whether the asking member may switch AI on or raise the budget (ai.configure); the UI
    # offers "Enable AI" instead of hiding the surface.
    can_configure: bool = False
    # For budget_reached: the first day of next month, when the budget resets.
    resets_on: date | None = None

    @property
    def available(self) -> bool:
        return self.state == AIState.AVAILABLE


def status(company, *, membership=None) -> AIStatus:
    """The AI state of `company`, as `membership` (when given) should see it."""
    can_configure = membership is not None and membership.has_perm(Perm.AI_CONFIGURE)
    if not configured():
        return AIStatus(AIState.NOT_CONFIGURED, can_configure)
    row = conf.get_settings(company)
    if row.platform_blocked:
        return AIStatus(AIState.BLOCKED, can_configure)
    if not conf.ai_on(company, row):
        return AIStatus(AIState.DISABLED, can_configure)
    if budget_reached(company, row.monthly_budget_usd):
        return AIStatus(AIState.BUDGET_REACHED, can_configure, resets_on=resets_on(company))
    if breaker_open():
        return AIStatus(AIState.UNAVAILABLE, can_configure)
    return AIStatus(AIState.AVAILABLE, can_configure)


def configured() -> bool:
    """A key is set, or AI_FAKE answers instead (development and demos)."""
    return bool(settings.ANTHROPIC_API_KEY) or fake()


def fake() -> bool:
    """Canned, deterministic answers instead of Claude (AI_FAKE, development and demos)."""
    return bool(settings.AI_FAKE)


def claude_state(company) -> str:
    """How Claude stands for the company, whatever its AI switch says (the dashboard's status
    pill): connected, not_configured, fake, blocked, budget_reached or unavailable."""
    if not configured():
        return "not_configured"
    row = conf.get_settings(company)
    if row.platform_blocked:
        return "blocked"
    if fake():
        return "fake"
    if budget_reached(company, row.monthly_budget_usd):
        return "budget_reached"
    if breaker_open():
        return "unavailable"
    return "connected"


# Spending ---------------------------------------------------------------------------------------


def _local_today(company) -> date:
    return timezone.localtime(timezone.now(), ZoneInfo(company.timezone)).date()


def month_start(company, today: date | None = None) -> datetime:
    """The first moment of the company's current month, in its timezone."""
    today = today or _local_today(company)
    return datetime(today.year, today.month, 1, tzinfo=ZoneInfo(company.timezone))


def resets_on(company, today: date | None = None) -> date:
    today = today or _local_today(company)
    return date(today.year + today.month // 12, today.month % 12 + 1, 1)


def _spend_key(company_id: int | str, today: date) -> str:
    return f"ai:spend:{company_id}:{today:%Y%m}"


def month_spend_micro(company) -> int:
    """What the company's Claude calls cost this month, in micro-dollars."""
    from apps.ai.models import AIUsage

    today = _local_today(company)
    key = _spend_key(company.pk, today)
    spent = cache.get(key)
    if spent is None:
        spent = (
            AIUsage.objects.filter(
                company=company, created_at__gte=month_start(company, today)
            ).aggregate(total=Sum("cost_micro_usd"))["total"]
            or 0
        )
        cache.set(key, spent, SPEND_TTL)
    return int(spent)


def platform_spend_micro() -> int:
    """What every company's calls cost this calendar month (UTC), in micro-dollars."""
    from apps.ai.models import AIUsage

    now = timezone.now()
    key = _spend_key("all", now.date())
    spent = cache.get(key)
    if spent is None:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        spent = (
            AIUsage.objects.filter(created_at__gte=start).aggregate(total=Sum("cost_micro_usd"))[
                "total"
            ]
            or 0
        )
        cache.set(key, spent, SPEND_TTL)
    return int(spent)


def add_spend(company, micro_usd: int) -> None:
    """Count a recorded call in the cached sums (they are rebuilt from AIUsage when missing)."""
    if micro_usd <= 0:
        return
    for key in (_spend_key(company.pk, _local_today(company)), _spend_key("all", timezone.now())):
        # Not cached yet: the next read sums AIUsage, this call included.
        with contextlib.suppress(ValueError):
            cache.incr(key, micro_usd)


def to_usd(micro_usd: int) -> Decimal:
    return (Decimal(micro_usd) / Decimal(1_000_000)).quantize(Decimal("0.01"))


def budget_reached(company, monthly_budget_usd: Decimal) -> bool:
    spent = month_spend_micro(company)
    if spent >= int(Decimal(monthly_budget_usd) * 1_000_000):
        return True
    cap = settings.AI_GLOBAL_MONTHLY_CAP_USD
    return cap is not None and platform_spend_micro() >= int(Decimal(cap) * 1_000_000)


# The circuit breaker ----------------------------------------------------------------------------


def breaker_open() -> bool:
    return bool(cache.get(_OPEN_KEY))


def record_failure() -> None:
    """One failed call (429, 5xx, timeout, connection). Enough of them open the breaker, and
    every Claude feature takes its no-AI path until it closes."""
    cache.add(_FAILURES_KEY, 0, BREAKER_WINDOW)
    try:
        failures = cache.incr(_FAILURES_KEY)
    except ValueError:
        cache.set(_FAILURES_KEY, 1, BREAKER_WINDOW)
        failures = 1
    if failures >= BREAKER_FAILURES:
        cache.set(_OPEN_KEY, 1, BREAKER_OPEN_FOR)
        cache.delete(_FAILURES_KEY)


def reset_breaker() -> None:
    cache.delete_many([_FAILURES_KEY, _OPEN_KEY])
