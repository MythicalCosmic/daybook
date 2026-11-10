"""Messages some modules send through a company's own bot instead of the shared ones.

A module registers a router for its channel (`register("faceid", router)`); the senders ask
`route(channel, ...)` first and fall back to the shared bot when it answers None:

* `apps.inbox.delivery.deliver`: notification kinds named "<channel>.<…>";
* `apps.notifications.tasks.send_routed_message`: direct messages (attendance's Face ID scan
  message to the person);
* `apps.groups.tasks.post_to_group`: group posts queued with a channel.

A router returns None ("not mine: use the shared bot") or a `Routed`: handled, with the message
id when one was sent (None when it was skipped or refused, e.g. the person never pressed Start
in that bot). A router raises only what the senders retry on (Telegram network errors).
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Routed:
    message_id: int | None = None


# router(company_id, chat_id, text, reply_markup, photo, photo_storage, *, group) -> Routed | None
type Router = Callable[..., Routed | None]

_ROUTERS: dict[str, Router] = {}
_ACTIVE: dict[str, Callable[[int], bool]] = {}


def register(channel: str, router: Router, *, active: Callable[[int], bool]) -> None:
    """`active(company_id)`: whether the company has its own bot for the channel now (senders
    that queue a job ask it first, so without one nothing about their sending changes)."""
    _ROUTERS[channel] = router
    _ACTIVE[channel] = active


def active(channel: str, company_id: int | None) -> bool:
    check = _ACTIVE.get(channel)
    return bool(check and company_id and check(company_id))


def channel_of(kind: str) -> str:
    """The channel of a notification kind ("faceid.scan" -> "faceid"), when one is registered."""
    prefix = kind.split(".", 1)[0]
    return prefix if prefix in _ROUTERS else ""


def route(
    channel: str,
    company_id: int | None,
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    photo: str | None = None,
    photo_storage: str = "default",
    *,
    group: bool = False,
) -> Routed | None:
    router = _ROUTERS.get(channel) if channel and company_id else None
    if router is None:
        return None
    return router(company_id, chat_id, text, reply_markup, photo, photo_storage, group=group)
