"""Settings that every app contributes to from its own file, merged at settings time.

`beat.py` (`SCHEDULE`, Celery beat entries) and `schema_enums.py` (`ENUM_NAME_OVERRIDES`,
drf-spectacular enum names) are read **by file path**, never imported as `apps.<app>.…`: the
settings load before Django, so these files may import only the standard library and Celery
(for example `celery.schedules.crontab`), never models or other app code. Enum overrides name
their choices with an import string (`"apps.sales.models.CashShift.Status"`).

This module needs no configured Django, so `config/settings` can use it.
"""

import importlib.util
from collections.abc import Iterator
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

APPS_DIR = Path(__file__).resolve().parent.parent


class DuplicateKey(ImproperlyConfigured):
    """Two apps (or an app and the base settings) claim the same key."""


def sources(filename: str, attribute: str, apps_dir: Path = APPS_DIR) -> Iterator[tuple[str, dict]]:
    """(app label, the file's `attribute` dict) for every `apps/<app>/<filename>`, by app name."""
    for path in sorted(apps_dir.glob(f"*/{filename}")):
        label = path.parent.name
        spec = importlib.util.spec_from_file_location(f"_collected_{label}_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        value = getattr(module, attribute, {})
        if not isinstance(value, dict):
            raise TypeError(f"{path}: {attribute} must be a dict, not {type(value).__name__}.")
        yield label, value


def collect(
    filename: str, attribute: str, base: dict | None = None, apps_dir: Path = APPS_DIR
) -> dict:
    """`base` merged with every app's `attribute` from `filename`; raises on a duplicate key."""
    merged = dict(base or {})
    owners = dict.fromkeys(merged, "settings")
    for label, entries in sources(filename, attribute, apps_dir):
        for name, value in entries.items():
            if name in merged:
                raise DuplicateKey(
                    f"{filename}: {attribute} key {name!r} from apps.{label} "
                    f"is already defined by {owners[name]}."
                )
            merged[name] = value
            owners[name] = f"apps.{label}"
    return merged
