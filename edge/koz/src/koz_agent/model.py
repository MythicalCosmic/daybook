"""The YOLOX-tiny model (Apache-2.0), fetched on first use from Megvii's official release and
checked against a pinned SHA-256. It lives in the agent's data folder and is never committed."""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Callable
from pathlib import Path

import httpx

from .paths import models_dir

log = logging.getLogger(__name__)

MODEL_URL = (
    "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx"
)
MODEL_FILE = "yolox_tiny.onnx"
# Observed on 2026-11-23 (20,219,662 bytes; input "images" 1×3×416×416, output 1×3549×85).
MODEL_SHA256 = "427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7"


class ModelError(RuntimeError):
    pass


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_file(root: Path | None = None) -> Path:
    return models_dir(root) / MODEL_FILE


def ensure_model(
    root: Path | None = None,
    *,
    download: bool = True,
    expected: str | None = None,
    transport: httpx.BaseTransport | None = None,
    progress: Callable[[int, int | None], None] | None = None,
) -> Path:
    """The model's path, downloading it when missing. A file whose SHA-256 differs from the pinned
    one is deleted and fetched again; a download that does not match is refused."""
    want = MODEL_SHA256 if expected is None else expected
    path = model_file(root)
    if path.exists():
        if not want or sha256_of(path) == want:
            return path
        log.warning("the model file does not match its checksum; fetching it again")
        path.unlink()
    if not download:
        raise ModelError(f"the model is missing: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    digest = hashlib.sha256()
    log.info("downloading the YOLOX-tiny model from %s", MODEL_URL)
    with httpx.Client(transport=transport, follow_redirects=True, timeout=60.0) as client:
        with client.stream("GET", MODEL_URL) as response:
            if response.status_code != 200:
                raise ModelError(f"model download failed: HTTP {response.status_code}")
            total = int(response.headers.get("content-length") or 0) or None
            done = 0
            with part.open("wb") as fh:
                for chunk in response.iter_bytes(1 << 16):
                    fh.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
    got = digest.hexdigest()
    if want and got != want:
        part.unlink(missing_ok=True)
        raise ModelError(f"the downloaded model has SHA-256 {got}, expected {want}")
    os.replace(part, path)
    return path
