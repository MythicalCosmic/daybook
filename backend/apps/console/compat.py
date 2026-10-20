"""Bridges to the two registries W0-L2 writes in the same wave: `apps.audit.registry`
(audit action labels) and `apps.core.files` (signed private downloads).

Wave 0 tracks merge in any order, so the platform apps call them through here: while a module
is missing, labels fall back to the codes and private files get no download link. After the
integration merge both exist and these become plain calls.
"""

import importlib
import importlib.util
from types import ModuleType


def _module(name: str) -> ModuleType | None:
    try:
        if importlib.util.find_spec(name) is None:
            return None
    except ModuleNotFoundError:
        return None
    return importlib.import_module(name)


def audit_registry() -> ModuleType | None:
    return _module("apps.audit.registry")


def files() -> ModuleType | None:
    return _module("apps.core.files")


def register_audit_actions(actions) -> bool:
    """`apps.audit.registry.register(actions)`: a TextChoices of `code -> label`."""
    module = audit_registry()
    if module is None:
        return False
    module.register(actions)
    return True


def register_file_check(kind: str, check) -> bool:
    """`apps.core.files.register_file_check(kind, check)`, `check(user, company_id, id)`."""
    module = files()
    if module is None:
        return False
    module.register_file_check(kind, check)
    return True


def signed_url(file, *, user, company_id: int, check: str, ttl: int = 600) -> str | None:
    """`apps.core.files.signed_url(...)`: `/api/v1/files/<token>/`, or None without it."""
    module = files()
    if module is None or not file:
        return None
    return module.signed_url(file, user=user, company_id=company_id, check=check, ttl=ttl)
