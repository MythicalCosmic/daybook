"""Employee bot, Package A. Dashboard sign-in while the owner bot has no token: the
number-matching buttons after `/start login_…` (the deep link is registered with
`bot.deeplinks.register_start_param`).

Registered before the start router and the member gate, so whoever signs in reaches it
whatever the state of their memberships.
"""

from aiogram import Router

router = Router(name="feature_signin")
