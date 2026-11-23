"""The agent's own settings on the PC (``agent.json`` in the data folder). Secrets are not here:
they live in the ``SecretStore``."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class NvrSettings:
    host: str
    port: int = 80
    rtsp_port: int = 554
    user: str = "admin"
    time: str = "auto"  # "auto" (ask the NVR), "utc", or an offset such as "+05:00"
    channels: list[dict] = field(default_factory=list)  # the last list seen: [{id, name}]
    auth_failed_at: str | None = None  # set on a 401; cleared by `nvr set`

    @property
    def secret_name(self) -> str:
        return f"nvr:{self.host}:password"


@dataclass
class SourceSettings:
    key: str
    kind: str  # "rtsp", "file" or "webcam"
    name: str
    target: str = ""  # a file path or a webcam index; an RTSP URL lives in the secrets

    @property
    def secret_name(self) -> str:
        return f"source:{self.key}"


@dataclass
class Settings:
    server: str | None = None
    agent: dict | None = None
    nvrs: list[NvrSettings] = field(default_factory=list)
    sources: list[SourceSettings] = field(default_factory=list)
    detector: str = "yolox"
    language: str = "uz"
    max_inferences_per_s: float = 6.0
    status_port: int = 8737
    record_fps: float = 6.0
    allow_webcam: bool = False
    legacy_norm: bool = False

    @classmethod
    def load(cls, path: Path) -> Settings:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        settings = cls(
            **{
                k: v
                for k, v in data.items()
                if k not in ("nvrs", "sources") and k in cls.__dataclass_fields__
            }
        )
        settings.nvrs = [NvrSettings(**n) for n in data.get("nvrs") or []]
        settings.sources = [SourceSettings(**s) for s in data.get("sources") or []]
        return settings

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def nvr(self, host: str) -> NvrSettings | None:
        return next((n for n in self.nvrs if n.host == host), None)
