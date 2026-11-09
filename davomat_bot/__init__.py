"""Davomat's Telegram bot (aiogram): link codes, `/today`, `/me` and notification buttons.

One bot per install, the organization's own: its token is pasted in Settings and kept in the
database (apps.davomat), so the bot reads it there and restarts when it changes. Run it from the
repository root with `python -m davomat_bot`. Code and tests live inside this package, so nothing
clashes with the other bots' modules when pytest collects them all.

Keep this file free of imports: `python -m davomat_bot.health` runs without Django.
"""
