"""Notification kinds and their action handlers, registered by each module's `hooks.py`.

    from apps.inbox.registry import register_action, register_kind

    register_kind("finance.claim", label=_("Expense claim to approve"), audience="owner",
                  default_telegram=True, queue_kind="finance.claims")
    register_action("finance.claim", "approve", handlers.approve_claim)

A handler is `(notification, by: Membership, reason: str) -> str | None`: it calls the module's
service (which checks permissions and audits) and returns a short result message. The same
handler serves the bot buttons and the dashboard buttons (`inbox.services.run_action`).

Kinds follow the console's registry rules: app-prefixed, unique (§2.3 rule 14).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from apps.console.registry import Entry, Registry, RegistryError, calling_app

if TYPE_CHECKING:
    from apps.inbox.models import Notification
    from apps.members.models import Membership

AUDIENCES = ("owner", "employee")
# Short: it travels in Telegram callback data (64 bytes) next to the notification id.
ACTION_KEY = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
SEVERITIES = ("info", "warning", "critical")

type ActionHandler = Callable[[Notification, Membership, str], str | None]


@dataclass(frozen=True)
class Kind(Entry):
    label: str
    audience: str
    default_telegram: bool
    severity: str
    queue_kind: str | None


@dataclass(frozen=True)
class Action(Entry):
    kind: str
    action: str
    handler: ActionHandler


KINDS: Registry[Kind] = Registry("inbox kinds")
ACTIONS: Registry[Action] = Registry("inbox actions")


def register_kind(
    kind: str,
    *,
    label: str,
    audience: str,
    default_telegram: bool,
    severity: str = "info",
    queue_kind: str | None = None,
) -> None:
    """`audience="owner"` goes through the owner bot when the person started it; a kind with
    `queue_kind` gets a Telegram copy with buttons but no in-app row (its queue item is the
    in-app form)."""
    if audience not in AUDIENCES:
        raise RegistryError(f"inbox kind {kind!r}: audience must be one of {AUDIENCES}.")
    if severity not in SEVERITIES:
        raise RegistryError(f"inbox kind {kind!r}: severity must be one of {SEVERITIES}.")
    KINDS.add(
        Kind(
            kind,
            calling_app(),
            None,
            None,
            label,
            audience,
            default_telegram,
            severity,
            queue_kind,
        )
    )


def register_action(kind: str, key: str, handler: ActionHandler) -> None:
    """The handler for button `key` on notifications of `kind` (registered first)."""
    if kind not in KINDS:
        raise RegistryError(f"inbox action {key!r}: register the kind {kind!r} first.")
    if not ACTION_KEY.match(key):
        raise RegistryError(f"inbox action {key!r}: use lowercase letters, digits and _.")
    ACTIONS.add(Action(f"{kind}.{key}", calling_app(), None, None, kind, key, handler))


def get_kind(kind: str) -> Kind:
    found = KINDS.get(kind)
    if found is None:
        raise LookupError(f"Unknown notification kind {kind!r}; register it in hooks.py.")
    return found


def get_handler(kind: str, key: str) -> ActionHandler | None:
    action = ACTIONS.get(f"{kind}.{key}")
    return action.handler if action else None
