"""Logging that never shows a secret: passwords in URLs, bearer tokens and Ko‘z tokens are masked
in every log line, whatever logger wrote it."""

from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path

_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@")
_BEARER = re.compile(r"(?i)(bearer\s+)\S+")
_KOZ_TOKEN = re.compile(r"koz_[A-Za-z0-9_-]{8,}")
_PASSWORD_KV = re.compile(r"(?i)(password|passwd|pwd)(\s*[=:]\s*)\S+")


def mask_url(url: str) -> str:
    """``rtsp://admin:secret@192.168.0.250:554/…`` → ``rtsp://***@192.168.0.250:554/…``."""
    return _URL_USERINFO.sub(r"\1***@", url)


def redact(text: str) -> str:
    text = _URL_USERINFO.sub(r"\1***@", text)
    text = _BEARER.sub(r"\1***", text)
    text = _KOZ_TOKEN.sub("koz_***", text)
    return _PASSWORD_KV.sub(r"\1\2***", text)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # a broken format string: keep it as it is
            return True
        cleaned = redact(message)
        if cleaned != message or record.args:
            record.msg = cleaned
            record.args = None
        return True


def setup_logging(log_dir: Path | None = None, *, verbose: bool = False) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(RedactingFilter())
    root.addHandler(console)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "agent.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        file_handler.addFilter(RedactingFilter())
        root.addHandler(file_handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
