"""Which audited fields are secret or need a permission to read (docs/PLAN-OWNER.md §3.2).

Apps register their sensitive fields once, in `hooks.py`:

    register_sensitive(EmployeeProfile, {"pinfl": SECRET, "passport": SECRET, "notes": SECRET})
    register_sensitive("payroll.Compensation", {"amount": Perm.PAYROLL_VIEW})

A `SECRET` value never reaches the audit log, not even masked: `snapshot()` turns it into a
`Redacted` marker that is stored as "•••" but still compares by a keyed digest of the hidden
value, so `diff()` sees that it changed. `record()` replaces it in any details it is handed
and stamps the row with the strictest permission among the fields it touched, so only
people holding that permission see the row at all.
"""

import hashlib
import hmac
from collections.abc import Iterable

from django.apps import apps as django_apps
from django.conf import settings
from django.db import models

from apps.members.permissions import DEFAULT_ROLES, Perm

MASK = "•••"


class _Secret:
    """Marks a field whose value is never written to the audit log."""

    def __repr__(self):
        return "SECRET"


SECRET = _Secret()

Sensitivity = _Secret | Perm

_registry: dict[str, dict[str, Sensitivity]] = {}


class DuplicateSensitiveField(ValueError):
    pass


class Redacted(str):
    """A secret value as the audit log holds it: "•••" in JSON, equal only to another
    `Redacted` of the same hidden value (compared through an HMAC, never the value)."""

    def __new__(cls, value):
        instance = super().__new__(cls, MASK)
        instance.fingerprint = _fingerprint(value)
        return instance

    def __eq__(self, other):
        if isinstance(other, Redacted):
            return self.fingerprint == other.fingerprint
        return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.fingerprint)

    def __reduce__(self):
        return (str, (MASK,))


def register_sensitive(model: type[models.Model] | str, fields: dict[str, Sensitivity]) -> None:
    """Declare `fields` of `model` as `SECRET` or readable only with a `Perm`."""
    label = _label(model)
    known = _registry.setdefault(label, {})
    for name, sensitivity in fields.items():
        if not isinstance(sensitivity, _Secret | Perm):
            raise TypeError(f"{label}.{name}: use SECRET or a Perm, not {sensitivity!r}.")
        if name in known:
            raise DuplicateSensitiveField(f"{label}.{name} is already registered.")
        known[name] = sensitivity


def sensitive_fields(model: type[models.Model] | str) -> dict[str, Sensitivity]:
    return dict(_registry.get(_label(model), {}))


def is_secret(model, field: str) -> bool:
    return isinstance(_registry.get(_label(model), {}).get(field), _Secret)


def redact(model, field: str, value):
    """`value` as a snapshot of `model` may hold it."""
    return Redacted(value) if is_secret(model, field) else value


def scrub(model, details: dict) -> dict:
    """`details` with every secret field's value replaced by "•••": top-level keys named after
    a secret field and the entries of a `changes` dict ({field: [old, new]})."""
    fields = _registry.get(_label(model), {})
    if not fields:
        return details
    clean = {}
    for key, value in details.items():
        if isinstance(fields.get(key), _Secret):
            clean[key] = _mask(value)
        elif key == "changes" and isinstance(value, dict):
            clean[key] = {
                name: _mask(change) if isinstance(fields.get(name), _Secret) else change
                for name, change in value.items()
            }
        else:
            clean[key] = value
    return clean


def touched_fields(details: dict) -> set[str]:
    """Field names a details dict talks about: its keys, the keys of `changes`, and the names
    listed in `fields` (the admin's changed fields)."""
    names = set(details)
    if isinstance(changes := details.get("changes"), dict):
        names |= set(changes)
    if isinstance(listed := details.get("fields"), list | tuple):
        names |= {name for name in listed if isinstance(name, str)}
    return names


def required_perm(model, field_names: Iterable[str]) -> str:
    """The strictest permission among the given fields' registered ones ("" for none)."""
    fields = _registry.get(_label(model), {})
    return strictest(
        fields[name] for name in field_names if name in fields and isinstance(fields[name], Perm)
    )


def strictest(perms: Iterable[str]) -> str:
    """The permission held by the fewest default roles (the owner holds all of them); ties go
    to the codename that sorts first, so the choice is stable."""
    candidates = {str(perm) for perm in perms if perm}
    if not candidates:
        return ""
    for perm in candidates:
        Perm(perm)  # an unknown codename is a bug, not "nobody may see it"
    return min(candidates, key=lambda perm: (_holders(perm), perm))


def _holders(perm: str) -> int:
    return sum(1 for role in DEFAULT_ROLES if perm in {str(p) for p in role.get("permissions", ())})


def _mask(value):
    if isinstance(value, list | tuple):
        return [MASK if item not in (None, "") else item for item in value]
    return MASK if value not in (None, "") else value


def _label(model: type[models.Model] | str) -> str:
    """ "app_label.ModelName" (a model class or that string) in lower case."""
    if isinstance(model, str):
        return django_apps.get_model(model)._meta.label_lower
    return model._meta.label_lower


def _fingerprint(value) -> str:
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, repr(value).encode(), hashlib.sha256).hexdigest()
