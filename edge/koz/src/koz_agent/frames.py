"""Types shared by sources, detectors and the analysis."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .geometry import Box


@dataclass(frozen=True)
class Detection:
    """A person found in a frame: a box in pixels ``(x1, y1, x2, y2)`` and a score 0..1."""

    box: Box
    score: float = 1.0


@dataclass
class Frame:
    """One picture from a source. ``t`` is the wall time it was taken (``Clock.time``).

    ``truth`` is set only by the generated scene: the exact box of every figure in the picture,
    which the ``sim`` detector returns as its detections.
    """

    image: np.ndarray
    t: float
    seq: int
    truth: list[Detection] | None = field(default=None, repr=False)

    @property
    def w(self) -> int:
        return int(self.image.shape[1])

    @property
    def h(self) -> int:
        return int(self.image.shape[0])
