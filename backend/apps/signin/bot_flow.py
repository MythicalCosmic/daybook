"""The sign-in conversation both bots run (sync; handlers call it through `sync_to_async`).

/start login_<code>   → start(user, code)          the prompt with three numbers
a number / "not me"   → tap(user, link, pick)      the outcome that replaces the prompt
"Log out everywhere"  → log_out_everywhere(user)   every session ends at once
"""

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
    return bot_messages.logged_out_everywhere(services.revoke_all(user))
