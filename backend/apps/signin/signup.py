"""Who may create a company (`COMPANY_SIGNUP`, §12.2 default 10) and the signup codes.

    COMPANY_SIGNUP=open   anyone signed in to Telegram may create a company
    COMPANY_SIGNUP=code   a platform admin hands out codes ("K7M2-QX9P"); someone who already
                          owns an active company may add more without one (they were let in
                          once; `MAX_COMPANIES_PER_USER` still applies)
    COMPANY_SIGNUP=off    only platform admins

Codes are stored as hashes, like every other secret here, so the admin sees one only when it
is made (Django admin or `manage.py signup_code`).
"""

import hashlib
import secrets
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from apps.signin.models import SignupCode

# No 0/O, 1/I/L: codes are read off a screen and typed on a phone.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


def normalize(raw: str) -> str:
    """The inputs "k7m2 qx9p", "K7M2-QX9P" and "new_K7M2QX9P" are the same code."""
    return "".join(char for char in (raw or "").upper() if char.isalnum())


def code_hash(raw: str) -> str:
    return hashlib.sha256(normalize(raw).encode()).hexdigest()


def generate() -> str:
    """A fresh code like "K7M2-QX9P"."""
    body = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return f"{body[:4]}-{body[4:]}"


def create_code(
    *, uses: int = 1, expires_at=None, note: str = "", created_by: User | None = None
) -> tuple[SignupCode, str]:
    """A new signup code and its only plain copy."""
    if uses < 1:
        raise DomainError(_("A signup code needs at least one use."))
    while True:
        raw = generate()
        if not SignupCode.objects.filter(code_hash=code_hash(raw)).exists():
            break
    code = SignupCode.objects.create(
        code_hash=code_hash(raw),
        uses_left=uses,
        expires_at=expires_at,
        note=note[:120],
        created_by=created_by,
    )
    return code, raw


def find(raw: str) -> SignupCode | None:
    """A usable code (uses left, not expired), without using it up."""
    if len(normalize(raw)) != CODE_LENGTH:
        return None
    code = SignupCode.objects.filter(code_hash=code_hash(raw), uses_left__gt=0).first()
    if code is None or (code.expires_at is not None and code.expires_at <= timezone.now()):
        return None
    return code


@transaction.atomic
def consume(raw: str) -> SignupCode:
    """Use up one go of a code, under a row lock (two people can't share the last use)."""
    found = find(raw)
    code = SignupCode.objects.select_for_update().filter(pk=found.pk).first() if found else None
    if code is None or code.uses_left < 1:
        raise DomainError(_("This signup code isn't valid. Check it, or ask for a new one."))
    code.uses_left -= 1
    code.save(update_fields=["uses_left"])
    return code


def owns_a_company(user: User) -> bool:
    return Membership.objects.filter(
        user=user,
        status=Membership.Status.APPROVED,
        role__is_owner=True,
        company__is_active=True,
    ).exists()


@dataclass(frozen=True)
class Policy:
    mode: str  # open | code | off
    allowed: bool  # may create a company at all (with a code when needs_code)
    needs_code: bool
    reason: str  # why not, when not allowed


def policy(user: User) -> Policy:
    mode = settings.COMPANY_SIGNUP
    if user.is_platform_admin:
        return Policy(mode, True, False, "")
    if mode == "open":
        return Policy(mode, True, False, "")
    if mode == "off":
        return Policy(
            mode, False, False, _("New companies are created by the platform team for now.")
        )
    return Policy(mode, True, not owns_a_company(user), "")


def admit(user: User, raw_code: str | None) -> SignupCode | None:
    """Check `user` may create a company now, using up a code when the policy needs one.
    Call inside the transaction that creates the company. Raises DomainError."""
    rules = policy(user)
    if not rules.allowed:
        raise DomainError(rules.reason)
    if not rules.needs_code:
        return None
    if not raw_code:
        raise DomainError(_("Enter the signup code you were given."))
    return consume(raw_code)
