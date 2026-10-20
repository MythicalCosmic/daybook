"""Encrypted columns and lookup digests for personal data (PINFL, passport and card numbers).

`EncryptedTextField` stores Fernet ciphertext in a **text** column. `FIELD_ENCRYPTION_KEY`
holds one or more Fernet keys, comma-separated and newest first: values are encrypted with the
first and decrypted with any of them, so a key is rotated by putting a new one in front and
running `reencrypt()` over the affected rows. The plain-text length is validated (`clean()` and
forms) through `plain_max_length`, never by the column, because ciphertext is much longer.

Ciphertext can't be searched, so a column that must be looked up or kept unique gets a digest
next to it: an HMAC-SHA256 with `FIELD_HASH_KEY` over the value with spaces removed and case
folded. `DigestField(of="pinfl")` fills it on every save (a `save(update_fields=[...])` that
names the value must name its digest too; `QuerySet.update()` never touches it).

    pinfl = EncryptedTextField(plain_max_length=14, blank=True)
    pinfl_digest = DigestField(of="pinfl")
    ...
    EmployeeProfile.objects.filter(pinfl_digest=digest(value))

An empty value is stored as an empty string, not encrypted, so "has a value" stays queryable
and blank digests never collide in a unique constraint (`condition=~Q(pinfl_digest="")`).
"""

import hashlib
import hmac
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models.lookups import Exact
from django.utils.translation import gettext_lazy as _

MASK_CHAR = "•"


class DecryptionError(ValueError):
    """A stored value can't be decrypted with any configured key."""


@lru_cache(maxsize=8)
def _fernet_for(keys: str) -> MultiFernet:
    parts = [key.strip() for key in keys.split(",") if key.strip()]
    if not parts:
        raise ImproperlyConfigured("Set FIELD_ENCRYPTION_KEY to store encrypted fields.")
    try:
        return MultiFernet([Fernet(key) for key in parts])
    except ValueError as exc:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY must hold Fernet keys (Fernet.generate_key()), comma-separated."
        ) from exc


def _fernet() -> MultiFernet:
    return _fernet_for(settings.FIELD_ENCRYPTION_KEY)


def encrypt(value: str) -> str:
    """Ciphertext for `value`; an empty string stays empty."""
    if value == "":
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    if token == "":
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError(
            "An encrypted value can't be read with FIELD_ENCRYPTION_KEY. Was a key removed?"
        ) from exc


def normalize(value: str) -> str:
    """What a digest is computed over: no whitespace anywhere, case folded ("aa 12 34" ==
    "AA1234")."""
    return "".join(value.split()).casefold()


def digest(value: str | None) -> str:
    """HMAC-SHA256 hex of the normalized value, for lookups; "" for an empty value."""
    if value is None:
        return ""
    normalized = normalize(value)
    if not normalized:
        return ""
    key = settings.FIELD_HASH_KEY
    if not key:
        raise ImproperlyConfigured("Set FIELD_HASH_KEY to compute lookup digests.")
    return hmac.new(key.encode(), normalized.encode(), hashlib.sha256).hexdigest()


def mask(value: str | None, keep: int = 4) -> str:
    """`mask("8600123412341234")` -> "••••••••••••1234": only the last `keep` characters shown
    (none when the value is that short). Whitespace is dropped first."""
    if not value:
        return ""
    compact = "".join(value.split())
    if keep <= 0 or len(compact) <= keep:
        return MASK_CHAR * len(compact)
    return MASK_CHAR * (len(compact) - keep) + compact[-keep:]


class _EmptyOnlyExact(Exact):
    """`field=""` works (empty values aren't encrypted); any other value can't match random
    ciphertext, so it raises instead of silently finding nothing."""

    def get_prep_lookup(self):
        if self.rhs != "":
            raise NotImplementedError("Encrypted fields can't be searched; use a DigestField.")
        return super().get_prep_lookup()


class EncryptedTextField(models.TextField):
    """A text column holding Fernet ciphertext; Python sees the plain text.

    Only `isnull` and comparisons with "" make sense in queries (ciphertext is random); look
    values up through a `DigestField`.
    """

    description = _("Encrypted text")

    def __init__(self, *args, plain_max_length: int | None = None, **kwargs):
        self.plain_max_length = plain_max_length
        super().__init__(*args, **kwargs)
        if plain_max_length is not None:
            self.validators.append(MaxLengthValidator(plain_max_length))

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.plain_max_length is not None:
            kwargs["plain_max_length"] = self.plain_max_length
        return name, path, args, kwargs

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        return decrypt(value)

    def to_python(self, value):
        return value if value is None else str(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None:
            return None
        return encrypt(str(value))

    def get_lookup(self, lookup_name):
        if lookup_name == "exact":
            return _EmptyOnlyExact
        if lookup_name != "isnull":
            raise NotImplementedError(
                f"Encrypted fields can't be searched with {lookup_name!r}; use a DigestField."
            )
        return super().get_lookup(lookup_name)

    def formfield(self, **kwargs):
        if self.plain_max_length is not None:
            kwargs.setdefault("max_length", self.plain_max_length)
        return super().formfield(**kwargs)


class DigestField(models.CharField):
    """The lookup digest of another field on the same model, recomputed on every save."""

    description = _("Lookup digest")

    def __init__(self, *args, of: str, **kwargs):
        self.of = of
        kwargs.setdefault("max_length", 64)
        kwargs.setdefault("blank", True)
        kwargs.setdefault("default", "")
        kwargs.setdefault("editable", False)
        kwargs.setdefault("db_index", True)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs["of"] = self.of
        return name, path, args, kwargs

    def pre_save(self, model_instance, add):
        value = digest(getattr(model_instance, self.of))
        setattr(model_instance, self.attname, value)
        return value


def reencrypt(queryset, *fields: str) -> int:
    """Re-encrypt `fields` of every row in `queryset` with the newest key; returns the rows
    changed. Run after putting a new key in front of FIELD_ENCRYPTION_KEY."""
    model = queryset.model
    changed = 0
    raw = model._base_manager.filter(pk__in=queryset.values("pk")).values_list("pk", *fields)
    for pk, *tokens in raw.iterator():
        # values_list goes through from_db_value, so these are plain values already; saving
        # them again encrypts with the first key.
        model._base_manager.filter(pk=pk).update(**dict(zip(fields, tokens, strict=True)))
        changed += 1
    return changed
