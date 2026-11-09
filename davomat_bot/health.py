"""`python -m davomat_bot.health`: the container's health check.

Exits 0 while the bot's heartbeat file is fresh (the bot touches it every few seconds, also while
it waits for a token), 1 when it is missing or stale. No Django: it only looks at a file.
"""

import os
import sys
import time

DEFAULT_HEARTBEAT = "/tmp/davomat-bot.heartbeat"
STALE_AFTER_SECONDS = 90


def heartbeat_path() -> str:
    return os.environ.get("DAVOMAT_BOT_HEARTBEAT") or DEFAULT_HEARTBEAT


def beat(path: str | None = None) -> None:
    """Touch the heartbeat file (best effort: a read-only disk must not stop the bot)."""
    path = path or heartbeat_path()
    try:
        with open(path, "a"):
            pass
        os.utime(path)
    except OSError:
        pass


def is_alive(path: str | None = None, *, now: float | None = None) -> bool:
    path = path or heartbeat_path()
    try:
        last = os.path.getmtime(path)
    except OSError:
        return False
    return (now if now is not None else time.time()) - last < STALE_AFTER_SECONDS


if __name__ == "__main__":
    sys.exit(0 if is_alive() else 1)
