"""What `/start <parameter>` does: a registry of parameter prefixes, so features add deep links
(`login_…` for dashboard sign-in, `job_…` for applicants) without touching the start router.

A feature registers its prefix when its router module is imported (the dispatcher imports every
feature router when it is built)::

    from bot.deeplinks import register_start_param

    async def open_vacancy(message: Message, payload: str, *, user: User, state: FSMContext):
        ...

    register_start_param("job_", open_vacancy)

The start router calls `dispatch()` first; a parameter no prefix claims is a company invite
(`c_…`) or a team link (`j_…`). Handlers run before the member gate, so they must check access
themselves.
"""

import re
from collections.abc import Awaitable
from typing import Protocol

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from apps.accounts.models import User
from apps.companies.models import Company
from apps.members.models import JoinLink


class StartHandler(Protocol):
    def __call__(
        self, message: Message, payload: str, *, user: User, state: FSMContext
    ) -> Awaitable[None]: ...


# Lowercase letters and digits, then one underscore: "login_", "job_". A prefix can never be the
# start of another, so the first match is the only match.
PREFIX = re.compile(r"[a-z][a-z0-9]{0,15}_")
# Telegram allows A-Z, a-z, 0-9, _ and - in a start parameter, 64 characters at most.
PARAMETER = re.compile(r"[A-Za-z0-9_-]{1,64}")
# Prefixes the start router handles itself: company invites and team links.
RESERVED = frozenset({Company.INVITE_PREFIX, JoinLink.PREFIX})

_handlers: dict[str, StartHandler] = {}


class StartParamError(ValueError):
    """A prefix that is malformed, reserved or already registered."""


def register_start_param(prefix: str, handler: StartHandler) -> StartHandler:
    """Send `/start <prefix><payload>` to `handler(message, payload, user=…, state=…)`."""
    if not PREFIX.fullmatch(prefix):
        raise StartParamError(
            f"Start parameter prefix {prefix!r} must be lowercase letters and digits ending "
            "with one underscore, like 'login_'."
        )
    if prefix in RESERVED:
        raise StartParamError(f"Start parameter prefix {prefix!r} is reserved.")
    if prefix in _handlers:
        raise StartParamError(f"Start parameter prefix {prefix!r} is already registered.")
    _handlers[prefix] = handler
    return handler


def unregister_start_param(prefix: str) -> None:
    """Forget a prefix (tests that register their own handlers clean up with this)."""
    _handlers.pop(prefix, None)


def registered_prefixes() -> list[str]:
    return sorted(_handlers)


def resolve(start_param: str | None) -> tuple[StartHandler, str] | None:
    """The handler a start parameter belongs to and the payload after its prefix, if any."""
    if not start_param or not PARAMETER.fullmatch(start_param):
        return None
    prefix, separator, _rest = start_param.partition("_")
    handler = _handlers.get(f"{prefix}{separator}") if separator else None
    if handler is None:
        return None
    return handler, start_param.removeprefix(f"{prefix}{separator}")


async def dispatch(
    message: Message, start_param: str | None, *, user: User, state: FSMContext
) -> bool:
    """Run the handler registered for `start_param`. False when no prefix claims it."""
    found = resolve(start_param)
    if found is None:
        return False
    handler, payload = found
    await handler(message, payload, user=user, state=state)
    return True
