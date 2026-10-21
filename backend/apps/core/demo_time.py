"""Running demo code as if it happened earlier (development only).

The demo builds in one transaction, so whatever the services leave for "after commit" (alerts,
notifications, signals) would all run at the very end, stamped with the real time: six weeks of
shift alerts arriving at once, "just now". `moment(at)` sets the clock to `at` for the code
inside and runs what that code left for after commit before it ends, still at `at`.

`quiet()` keeps a demo build from queueing background jobs (Telegram copies to the made-up demo
accounts, rollups the demo rebuilds itself) and from bumping pulse keys thousands of times; the
dashboard refetches everything after a rebuild anyway.
"""

import logging
from contextlib import contextmanager
from datetime import datetime
from unittest import mock

from django.db import DEFAULT_DB_ALIAS, connections

logger = logging.getLogger(__name__)


@contextmanager
def moment(at: datetime):
    """The clock reads `at` inside; after-commit work runs before leaving, at `at` too."""
    with mock.patch("django.utils.timezone.now", return_value=at), run_hooks():
        yield


@contextmanager
def run_hooks(using: str = DEFAULT_DB_ALIAS):
    """Run the after-commit callbacks registered inside the block when it ends (in order, and
    those they register in turn) instead of at the outer commit. Outside a transaction Django
    runs them at once anyway."""
    connection = connections[using]
    start = len(connection.run_on_commit)
    yield
    if not connection.in_atomic_block:
        return
    while len(connection.run_on_commit) > start:
        pending = connection.run_on_commit[start:]
        del connection.run_on_commit[start:]
        for _savepoints, callback, robust in pending:
            if not robust:
                callback()
                continue
            try:
                callback()
            except Exception:
                logger.exception("Demo after-commit callback %r failed", callback)


@contextmanager
def quiet():
    """No Celery jobs and no pulse bumps while the demo builds."""
    with (
        mock.patch("celery.app.task.Task.apply_async", _skip_job),
        mock.patch("apps.console.pulse.bump", _skip_bump),
    ):
        yield


def _skip_job(task, *args, **kwargs):
    return None


def _skip_bump(*args, **kwargs):
    return None
