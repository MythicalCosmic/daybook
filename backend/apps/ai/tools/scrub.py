"""Keeps contact details and identifiers out of everything the AI is sent (§8.3, §8.7).

`scrub(text)` replaces Uzbek phone numbers (+998…, 998…, 9X XXX XX XX), card numbers, any
run of nine or more digits (which covers Telegram ids), @usernames, t.me links and tg:// links
with "[hidden]". `scrub_data(value)` does it to every string in a tool result, drops keys that
name such data outright (phone, telegram_id…), and turns Decimals, dates and times into
strings. Numbers that are numbers (ints, Decimals) are never scrubbed, so a total of
5 200 000 000 so'm survives while the same digits typed into a comment don't.
"""

import re
from datetime import date, datetime, time
from decimal import Decimal

HIDDEN = "[hidden]"

# Keys whose values never go to the model, however they are spelled in a row.
BANNED_KEYS = frozenset(
    {
        "phone",
        "personal_phone",
        "contact_phone",
        "telegram_id",
        "telegram_username",
        "username",
        "chat_id",
        "invite_code",
        "token",
        "pinfl",
        "passport",
        "payout_card",
    }
)

_SEPARATOR = r"[\s\-.]*"
_PATTERNS = [
    re.compile(r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/\S*", re.I),
    re.compile(r"tg://\S+", re.I),
    re.compile(r"(?<![\w.@])@[A-Za-z][A-Za-z0-9_]{3,31}\b"),
    re.compile(r"(?<!\d)\d{4}(?:[\s\-]?\d{4}){3}(?!\d)"),  # card numbers, spaced or not
    re.compile(
        rf"(?<!\d)(?:\+?998{_SEPARATOR})?\(?[3-9]\d\)?{_SEPARATOR}\d{{3}}{_SEPARATOR}"
        rf"\d{{2}}{_SEPARATOR}\d{{2}}(?!\d)"
    ),
    re.compile(r"\+?\d{9,}"),
]


def scrub(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(HIDDEN, text)
    return text


def scrub_data(value):
    """A JSON-ready copy of `value` with every string scrubbed and banned keys dropped."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, bool) or value is None or isinstance(value, int | float):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): scrub_data(item)
            for key, item in value.items()
            if str(key).lower() not in BANNED_KEYS
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [scrub_data(item) for item in value]
    return scrub(str(value))
