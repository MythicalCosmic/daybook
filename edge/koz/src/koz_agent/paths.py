"""Where the agent keeps its things on the PC.

Windows: ``%LOCALAPPDATA%\\Daybook\\Koz``; Linux: ``$XDG_DATA_HOME/daybook-koz`` (by default
``~/.local/share/daybook-koz``). ``KOZ_HOME`` overrides both (tests, a second agent).
"""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("KOZ_HOME")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Daybook" / "Koz"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "daybook-koz"


def models_dir(root: Path | None = None) -> Path:
    return (root or data_dir()) / "models"
