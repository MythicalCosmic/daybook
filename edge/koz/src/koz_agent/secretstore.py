"""Secrets that never leave the PC: the Daybook token and camera/NVR passwords.

Windows: the JSON is encrypted with DPAPI (``CryptProtectData`` through ``ctypes``), so only this
Windows user on this PC can read it. Linux: a JSON file with mode 600. Values are never logged.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
from pathlib import Path

ENTROPY = b"daybook-koz-agent"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    source, _keep1 = _blob(data)
    entropy, _keep2 = _blob(ENTROPY)
    out = _Blob()
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(source),
            "koz",
            ctypes.byref(entropy),
            None,
            None,
            flags,
            ctypes.byref(out),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            ctypes.byref(entropy),
            None,
            None,
            flags,
            ctypes.byref(out),
        )
    if not ok:
        raise OSError(ctypes.get_last_error() or "DPAPI failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def protect(data: bytes) -> bytes:
    return _dpapi(data, protect=True)


def unprotect(data: bytes) -> bytes:
    return _dpapi(data, protect=False)


class SecretStore:
    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.windows = sys.platform == "win32"
        self.path = self.folder / ("secrets.dpapi" if self.windows else "secrets.json")
        self._lock = threading.Lock()

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        raw = self.path.read_bytes()
        if self.windows:
            raw = unprotect(raw)
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, str]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(data, sort_keys=True).encode("utf-8")
        tmp = self.path.with_suffix(".tmp")
        if self.windows:
            tmp.write_bytes(protect(raw))
        else:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(raw)
            os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        if not self.windows:
            os.chmod(self.path, 0o600)

    def get(self, name: str) -> str | None:
        with self._lock:
            return self._load().get(name)

    def set(self, name: str, value: str) -> None:
        with self._lock:
            data = self._load()
            data[name] = value
            self._save(data)

    def delete(self, name: str) -> None:
        with self._lock:
            data = self._load()
            if data.pop(name, None) is not None:
                self._save(data)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._load())
