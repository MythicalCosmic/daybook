"""Usernames and passwords (docs/DAVOMAT.md §1.2), in both editions.

    sign_in(request, username, password) -> User         raises WrongPassword, Locked, NoAccess
    change_password(user, *, current, new, request, keep_session)   raises FieldError
    set_password(membership, *, by, password, keep_session)         an administrator sets one
    clean_username(value, *, user=None) · check_password_rules(password, user)

**Lockout.** Five wrong passwords for one username from one address within 15 minutes lock that
pair for 15 minutes (counters in the Django cache); a right password clears the count. A wide
ceiling per address (any usernames) stops password spraying. Unknown usernames count, and cost
the same hashing as known ones, so answers never tell which usernames exist.
"""

from __future__ import annotations

import hashlib
import re
import time

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import update_last_login
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.core.exceptions import DomainError
from apps.davomat.audit_actions import DavomatAction
from apps.members.models import Membership
from apps.signin import services as signin

LOCK_AFTER = 5
WINDOW_S = 15 * 60
LOCK_S = 15 * 60
# Wrong passwords from one address, whatever the usernames, before it is locked too.
ADDRESS_CEILING = 100
MIN_USERNAME, MAX_USERNAME = 3, 150
USERNAME = re.compile(r"[\w.@+-]+")


class FieldError(DomainError):
    """A value the person typed is refused: `field` (dotted for nested ones) and its messages."""

    def __init__(self, field: str, *messages: str):
        super().__init__(messages[0] if messages else "")
        self.field = field
        self.messages = list(messages)


class WrongPassword(Exception):
    """Unknown username or wrong password (one answer for both)."""


class Locked(Exception):
    def __init__(self, retry_after: int):
        super().__init__(retry_after)
        self.retry_after = retry_after


class NoAccess(Exception):
    """The password is right, but the account may not use the web app (switched off, gone)."""


# Usernames and password rules -----------------------------------------------------------------


def clean_username(value: str, *, user: User | None = None, field: str = "username") -> str:
    """A username as typed (spaces trimmed): 3 to 150 letters, digits and . @ + - _, not taken by
    anyone else in any case ("Aziza" and "aziza" are one username)."""
    name = (value or "").strip()
    if not MIN_USERNAME <= len(name) <= MAX_USERNAME or not USERNAME.fullmatch(name):
        raise FieldError(field, _("A username is 3–150 letters, digits and . @ + - _ only."))
    taken = User.objects.filter(username__iexact=name)
    if user is not None and user.pk is not None:
        taken = taken.exclude(pk=user.pk)
    if taken.exists():
        raise FieldError(field, _("This username is taken. Pick another one."))
    return name


def check_password_rules(password: str, user: User, *, field: str = "password") -> None:
    """Django's validators: at least 8 characters, not too common, not all digits, not like the
    person's own name or username."""
    try:
        validate_password(password or "", user)
    except ValidationError as exc:
        raise FieldError(field, *exc.messages) from exc


# Signing in ---------------------------------------------------------------------------------


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:40]


def _keys(username: str, address: str) -> tuple[str, str, str, str]:
    pair = _digest(username.casefold(), address)
    where = _digest(address)
    return (
        f"davomat:pw:fail:{pair}",
        f"davomat:pw:lock:{pair}",
        f"davomat:pw:afail:{where}",
        f"davomat:pw:alock:{where}",
    )


def _count(key: str) -> int:
    if cache.add(key, 1, WINDOW_S):
        return 1
    try:
        return cache.incr(key)
    except ValueError:  # it ran out in between: this one starts a new window
        cache.set(key, 1, WINDOW_S)
        return 1


def _lock(key: str) -> None:
    cache.set(key, time.time() + LOCK_S, LOCK_S)


def locked_for(username: str, address: str) -> int:
    """Seconds left of a lock on this username and address (or on the address), else 0."""
    _fail_key, lock_key, _address_key, address_lock = _keys(username, address)
    found = [cache.get(lock_key), cache.get(address_lock)]
    left = max((until - time.time() for until in found if until), default=0)
    return max(int(left) + 1, 1) if left > 0 else 0


def _failed(username: str, address: str, user: User | None) -> None:
    fail_key, lock_key, address_key, address_lock = _keys(username, address)
    if _count(address_key) >= ADDRESS_CEILING:
        _lock(address_lock)
        cache.delete(address_key)
    if _count(fail_key) < LOCK_AFTER:
        return
    _lock(lock_key)
    cache.delete(fail_key)
    for membership in _memberships(user):
        audit.record(
            DavomatAction.PASSWORD_LOCKED,
            company_id=membership.company_id,
            actor=None,
            target=membership,
            address=address,
        )


def _cleared(username: str, address: str) -> None:
    fail_key, _lock_key, _address_key, _address_lock = _keys(username, address)
    cache.delete(fail_key)


def has_password(user: User) -> bool:
    """Whether the account was ever given a password (accounts made through Telegram never
    were: theirs is unusable, or blank)."""
    return bool(user.password) and user.has_usable_password()


def find_user(username: str) -> User | None:
    """The account with this username: exactly as typed, else the only one in another case."""
    name = (username or "").strip()
    if not name:
        return None
    user = User.objects.filter(username=name).first()
    if user is None:
        found = list(User.objects.filter(username__iexact=name)[:2])
        user = found[0] if len(found) == 1 else None
    return user


def sign_in(request, username: str, password: str) -> User:
    """The account behind a username and password, allowed into the web app; its last sign-in
    is stamped and audited. Raises Locked, WrongPassword or NoAccess."""
    address = signin.client_ip(request) or "unknown"
    name = (username or "").strip()[:MAX_USERNAME]
    if left := locked_for(name, address):
        raise Locked(left)
    user = find_user(name)
    if user is None or not has_password(user):
        make_password(password or "")  # the same work as a real check
        _failed(name, address, user)
        raise WrongPassword
    if not user.check_password(password or ""):
        _failed(name, address, user)
        raise WrongPassword
    _cleared(name, address)
    if not signin.can_sign_in(user):
        raise NoAccess
    update_last_login(None, user)
    for membership in _memberships(user):
        audit.record(
            DavomatAction.PASSWORD_LOGIN,
            company_id=membership.company_id,
            actor=user,
            target=membership,
            address=address,
        )
    return user


def _memberships(user: User | None) -> list[Membership]:
    """The memberships an account's sign-in events are recorded on: its approved ones."""
    if user is None:
        return []
    return list(
        Membership.objects.filter(user=user, status=Membership.Status.APPROVED).order_by("pk")
    )


# Changing passwords --------------------------------------------------------------------------


def change_password(
    user: User, *, current: str, new: str, request, keep_session: int | None
) -> None:
    """Someone changes their own password: the current one first (someone who never had one,
    a Daybook account made through Telegram, sets their first one without it), then the new
    one by the rules. Every other browser of theirs is signed out."""
    if has_password(user):
        address = signin.client_ip(request) or "unknown"
        if left := locked_for(user.username, address):
            raise Locked(left)
        if not user.check_password(current or ""):
            _failed(user.username, address, user)
            raise FieldError("current", _("The current password is wrong."))
        if new == current:
            raise FieldError("new", _("The new password must differ from the current one."))
    check_password_rules(new, user, field="new")
    with transaction.atomic():
        user.set_password(new)
        user.save(update_fields=["password"])
        for membership in _memberships(user):
            audit.record(
                DavomatAction.PASSWORD_CHANGED,
                company_id=membership.company_id,
                actor=user,
                target=membership,
            )
        signin.revoke_others(user, keep=keep_session)


def set_password(
    membership: Membership, *, by: Membership, password: str, keep_session: int | None = None
) -> None:
    """An administrator gives someone a new password: every session of theirs ends (but the
    administrator's own browser, when they set their own)."""
    user = membership.user
    check_password_rules(password, user)
    with transaction.atomic():
        user.set_password(password)
        user.save(update_fields=["password"])
        audit.record(
            DavomatAction.PASSWORD_SET,
            company_id=membership.company_id,
            actor=by.user,
            target=membership,
        )
        if user.pk == by.user_id:
            signin.revoke_others(user, keep=keep_session)
        else:
            signin.revoke_all(user)
