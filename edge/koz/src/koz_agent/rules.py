"""The alert and analysis rules a box gets in ``config/`` (contract §5.2), with the defaults and
ranges of §6.7. Values out of range are clamped, unknown keys ignored."""

from __future__ import annotations

from dataclasses import asdict, dataclass

# name: (minimum, maximum) for the numeric rules
RANGES: dict[str, tuple[float, float]] = {
    "queue_people": (1, 20),
    "queue_wait_s": (15, 1800),
    "unattended_s": (15, 1800),
    "clear_after_s": (5, 120),
    "analysis_fps": (1, 5),
    "live_fps": (1, 4),
    "record_hours": (1, 168),
}


@dataclass(frozen=True)
class Rules:
    queue_people: int = 3
    queue_wait_s: int = 120
    unattended_s: int = 90
    clear_after_s: int = 15
    analysis_fps: float = 2.0
    live_fps: float = 2.0
    privacy_blur: bool = False
    alert_photo: bool = True
    record_counter: bool = True
    record_hours: int = 24

    @classmethod
    def from_dict(cls, data: dict | None) -> Rules:
        base = asdict(cls())
        for key, value in (data or {}).items():
            if key not in base or value is None:
                continue
            default = base[key]
            if isinstance(default, bool):
                base[key] = bool(value)
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            low, high = RANGES[key]
            number = min(max(number, low), high)
            base[key] = number if isinstance(default, float) else round(number)
        return cls(**base)

    def to_dict(self) -> dict:
        return asdict(self)
