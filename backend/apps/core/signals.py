"""Sending the platform's domain signals (members, companies, time off…) after commit.

Receivers live in other apps (finance defaults, HR profiles, AI clean-up…), so one failing
receiver must neither undo the change that already happened nor keep the others from running:
every receiver gets the signal, and a failure is logged with its traceback.

    send_on_commit(member_left, sender=Membership, membership=m, reason="left", by=actor)
"""

import logging
from functools import partial

from django.db import transaction
from django.dispatch import Signal

logger = logging.getLogger(__name__)


def send_on_commit(signal: Signal, *, sender, **kwargs) -> None:
    """Send `signal` once the current transaction commits (at once outside a transaction)."""
    transaction.on_commit(partial(send_now, signal, sender=sender, **kwargs))


def send_now(signal: Signal, *, sender, **kwargs) -> None:
    for receiver, result in signal.send_robust(sender=sender, **kwargs):
        if isinstance(result, Exception):
            logger.error(
                "Receiver %r of %s failed",
                receiver,
                getattr(signal, "name", signal),
                exc_info=(type(result), result, result.__traceback__),
            )
