"""The sign-in conversation both bots run (sync; handlers call it through `sync_to_async`).

/start login_<code>   → start(user, code)          the prompt with three numbers
a number / "not me"   → tap(user, link, pick)      the outcome that replaces the prompt
"Log out everywhere"  → log_out_everywhere(user)   every session ends at once
"""

from django.conf import settings

from apps.accounts.models import User
from apps.signin import bot_messages, links, services
from apps.signin.callbacks import NOT_ME


def start(user: User, code: str) -> bot_messages.BotMessage:
    try:
        prompt = links.open_link(code, user)
    except links.LinkRefused as refused:
        return bot_messages.link_refused(refused.reason), None
    return bot_messages.login_prompt(prompt, user)


def tap(user: User, link: str, pick: str) -> tuple[str, bool]:
    """(the text that replaces the prompt, whether the person was signed in)."""
    outcome = links.decide(link, user, None if pick == NOT_ME else pick)
    return bot_messages.login_outcome(outcome), outcome == "approved"


def log_out_everywhere(user: User) -> str:
    """Every session ends at once. Where people sign in through Telegram (the Daybook edition)
    a password on the account stops working as well: whoever got in may have set one (a first
    password asks for no current one), and "nobody stays signed in" must hold for it too. The
    person sets a new one after signing in again. In the Davomat edition the password is how
    people sign in, so it stays."""
    count = services.revoke_all(user)
    if settings.EDITION != "davomat" and user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return bot_messages.logged_out_everywhere(count)
