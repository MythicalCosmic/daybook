"""What the audit log knows about each app: action labels, secret fields and record history.

    register(actions)                    action codes and their labels (a TextChoices class or
                                         {code: label}); apps call it from `hooks.py` with the
                                         choices in their `audit_actions.py`
    label(code)                          the translated label ("Approved a join request")
    register_sensitive(model, fields)    see apps.audit.redaction
    register_target(model_name, perm, check=None)
                                         who may open a record's History tab without
                                         audit.view: holders of `perm`, and only when
                                         `check(member, target_id)` (if given) says the record
                                         exists in their scope

Registering a code or target twice raises. Recording an unregistered code still works (its
label is the code itself), so a missing registration never loses an audit row.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from django.utils.functional import Promise

from apps.audit.redaction import SECRET, register_sensitive
from apps.members.permissions import Perm

__all__ = [
    "SECRET",
    "DuplicateAction",
    "DuplicateTarget",
    "Target",
    "codes",
    "label",
    "register",
    "register_sensitive",
    "register_target",
    "target",
]


class DuplicateAction(ValueError):
    pass


class DuplicateTarget(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    model_name: str
    perm: Perm
    check: Callable[[object, int], bool] | None = None


_labels: dict[str, str | Promise] = {}
_targets: dict[str, Target] = {}


def register(actions: type | Mapping[str, str | Promise]) -> None:
    """Register action codes with their labels."""
    items: Iterable[tuple[str, str | Promise]] = (
        actions.choices if hasattr(actions, "choices") else actions.items()
    )
    items = list(items)
    for code, _label in items:
        if not isinstance(code, str) or not code or len(code) > 48:
            raise ValueError(f"Audit action codes are 1–48 characters, not {code!r}.")
        if code in _labels:
            raise DuplicateAction(f"Audit action {code!r} is already registered.")
    _labels.update(items)


def label(code: str) -> str:
    return str(_labels.get(code, code))


def codes() -> dict[str, str]:
    """Every registered code with its label, sorted by code."""
    return {code: str(_labels[code]) for code in sorted(_labels)}


def register_target(
    model_name: str, perm: Perm, *, check: Callable[[object, int], bool] | None = None
) -> None:
    """Let holders of `perm` see the history of `model_name` records ("task", "membership":
    the `target_type` audit rows carry)."""
    if model_name != model_name.lower() or not model_name:
        raise ValueError(f"Use the model name in lower case, as audit rows store it: {model_name}")
    if model_name in _targets:
        raise DuplicateTarget(f"A history permission for {model_name!r} is already registered.")
    _targets[model_name] = Target(model_name, Perm(perm), check)


def target(model_name: str) -> Target | None:
    return _targets.get(model_name)
