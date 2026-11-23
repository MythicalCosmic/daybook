"""Pairing codes and box tokens (docs/KOZ.md §5, §5.1).

A pairing code reads `KOZ-7F3K-92QD`: eight Crockford base32 characters (no I, L, O or U, so it
reads aloud and types without mix-ups), shown once and kept as an HMAC of the eight characters.
Typed back in, case, spaces and dashes don't matter, and I/L read as 1 and O as 0 (Crockford's
rule). A token is `koz_` and 40 URL-safe characters (240 random bits); Daybook keeps its SHA-256.
"""

import hashlib
import re
import secrets

from django.utils.crypto import salted_hmac

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 8
PREFIX = "KOZ"
TOKEN_PREFIX = "koz_"
TOKEN = re.compile(r"^koz_[A-Za-z0-9_-]{40}$")
_SEPARATORS = re.compile(r"[\s\-_.]+")
_READS_AS = str.maketrans({"I": "1", "L": "1", "O": "0"})


def new_code() -> str:
    """A fresh code as shown: `KOZ-XXXX-XXXX`."""
    chars = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return f"{PREFIX}-{chars[:4]}-{chars[4:]}"


def normalize(typed: str) -> str | None:
    """The eight characters of a typed code, or None when it can't be one."""
    text = _SEPARATORS.sub("", (typed or "").upper())
    if text.startswith(PREFIX) and len(text) == len(PREFIX) + CODE_LENGTH:
        text = text[len(PREFIX) :]
    text = text.translate(_READS_AS)
    if len(text) != CODE_LENGTH or any(char not in ALPHABET for char in text):
        return None
    return text


def code_hash(typed: str) -> str | None:
    """What is stored for a code (None for text that can't be a code)."""
    chars = normalize(typed)
    if chars is None:
        return None
    return salted_hmac("apps.vision.pairing", chars, algorithm="sha256").hexdigest()


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(30)


def token_hash(token: str) -> str | None:
    """The SHA-256 kept for a token (None for text that isn't one)."""
    if not token or not TOKEN.match(token):
        return None
    return hashlib.sha256(token.encode()).hexdigest()
