"""Employee bot, Package A. Dashboard sign-in while the owner bot has no token: the
number-matching buttons after `/start login_…` (the deep link is registered with
`bot.deeplinks.register_start_param`).

Registered before the start router and the member gate, so whoever signs in reaches it
whatever the state of their memberships. Private chats only: it comes before the group
router, and nothing here belongs in a group.
"""

from aiogram import F, Router
from aiogram.enums import ChatType

router = Router(name="feature_signin")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
