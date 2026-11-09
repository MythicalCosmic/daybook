"""`python -m davomat_bot` (from the repository root): the bot in polling mode.

Exits with code 0 when the token changes (app.py); Docker starts it again with the new one.
Logging is the backend's LOGGING (the root logger at LOG_LEVEL, INFO by default).
"""

import asyncio

from davomat_bot.setup import setup_django

setup_django()

from davomat_bot.app import run  # noqa: E402

if __name__ == "__main__":
    asyncio.run(run())
