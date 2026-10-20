"""Whether AI may run for a company right now (docs/PLAN-OWNER.md §8.1, §8.8).

Every AI surface asks before it shows itself:

    if availability.status(company, membership=member).available: ...

AI runs only when `ANTHROPIC_API_KEY` is set, "ai" is in `Company.features`, an owner has
consented (`AISettings.enabled`), the platform hasn't blocked the tenant and the month's
budget isn't spent. Until package K builds the runtime, the answer is always
`not_configured`, so every caller already takes its no-AI path.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


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
    return AIStatus(AIState.NOT_CONFIGURED)
