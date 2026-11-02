"""Identity numbers: how they are typed in, checked and shown masked.

    pinfl("3010 1900 1234 56") -> "30101900123456"     # 14 digits (JShShIR)
    passport("aa 1234567") -> "AA1234567"                # series + 7 digits (passport, ID card)
    card("8600 1234 5678 9012") -> "8600123456789012"
    masked("AA1234567") -> "AA•••••67"

Every function raises `DomainError` with a message safe to show, naming what is wrong.
"""

import re

from django.utils.translation import gettext as _

from apps.core.crypto import MASK_CHAR
from apps.core.exceptions import DomainError

PASSPORT = re.compile(r"^[A-Z]{2}\d{7}$")
DOCUMENT_NUMBER = re.compile(r"^[\w/№.-]{1,32}$")


def _compact(value: str | None) -> str:
    return "".join((value or "").split()).replace("-", "")


def pinfl(value: str | None) -> str:
    """A PINFL (JShShIR): 14 digits, or "" to clear it."""
    text = _compact(value)
    if text and not (text.isdigit() and len(text) == 14):
        raise DomainError(_("A PINFL is 14 digits."))
    return text


def passport(value: str | None) -> str:
    """A passport or ID card number: two letters and seven digits (AA1234567), or ""."""
    text = _compact(value).upper()
    if text and not PASSPORT.match(text):
        raise DomainError(_("A passport number is two letters and seven digits, like AA1234567."))
    return text


def tin(value: str | None) -> str:
    """A taxpayer number (STIR / INN): 9 digits, or ""."""
    text = _compact(value)
    if text and not (text.isdigit() and len(text) == 9):
        raise DomainError(_("A taxpayer number has 9 digits (a person's PINFL 14)."))
    return text


def card(value: str | None) -> str:
    """A bank card number: 16 to 19 digits (Uzcard, Humo, Visa), or ""."""
    text = _compact(value)
    if text and not (text.isdigit() and 16 <= len(text) <= 19):
        raise DomainError(_("A card number is 16 digits."))
    return text


PHONE = re.compile(r"^\+?[\d ()-]{7,20}$")


def phone(value: str | None, *, required: bool = False) -> str:
    """A phone number as people write it (+998 90 123 45 67), or "" when not `required`."""
    text = " ".join((value or "").split())
    if not text:
        if required:
            raise DomainError(_("A number like +998 90 123 45 67."))
        return ""
    if not PHONE.match(text) or sum(char.isdigit() for char in text) < 7:
        raise DomainError(_("A number like +998 90 123 45 67."))
    return text


def document_number(value: str | None) -> str:
    """A document's number as printed on it (letters, digits, №, / and -), or ""."""
    text = "".join((value or "").split()).upper()
    if text and not DOCUMENT_NUMBER.match(text):
        raise DomainError(_("Write the number as it is printed: letters and digits."))
    return text


def masked(value: str | None, *, head: int = 2, tail: int = 2) -> str:
    """`value` with all but its first `head` and last `tail` characters hidden: "AA•••••67".
    Short values hide more, so at least half of any value stays hidden."""
    if not value:
        return ""
    text = "".join(value.split())
    shown = len(text) // 2
    tail = min(tail, shown)
    head = min(head, shown - tail)
    return text[:head] + MASK_CHAR * (len(text) - head - tail) + (text[-tail:] if tail else "")
