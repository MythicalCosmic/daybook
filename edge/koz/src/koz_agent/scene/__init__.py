"""The generated scene (``sim``): a flat illustration of a pharmacy seen by two ceiling cameras.

``sim:counter`` sees the counter (role ``counter``) and ``sim:door`` the entrance (role
``entrance``). Both look at one shared ``World``, advanced to the clock's time, so a customer who
comes in through the door later queues at the counter. The scene knows the exact box of every
figure, which the ``sim`` detector returns.
"""

from __future__ import annotations

import threading

import numpy as np

from ..frames import Detection
from .render import Renderer
from .scripts import SCRIPTS
from .world import World

SCENES = tuple(SCRIPTS)

# key → (view, name, role)
CAMERAS: dict[str, tuple[str, str, str]] = {
    "sim:counter": ("counter", "Kassa", "counter"),
    "sim:door": ("door", "Kirish", "entrance"),
}

_ZONES: dict[str, list[dict]] = {
    "sim:counter": [
        {
            "id": "q1",
            "kind": "queue",
            "points": [[0.02, 0.62], [0.98, 0.62], [0.99, 0.995], [0.01, 0.995]],
        },
        {
            "id": "s1",
            "kind": "staff",
            "points": [[0.02, 0.33], [0.98, 0.33], [0.98, 0.5], [0.02, 0.5]],
        },
        {
            "id": "m1",
            "kind": "mask",
            "points": [[0.236, 0.408], [0.284, 0.408], [0.284, 0.48], [0.236, 0.48]],
        },
        {
            "id": "m2",
            "kind": "mask",
            "points": [[0.716, 0.408], [0.764, 0.408], [0.764, 0.48], [0.716, 0.48]],
        },
    ],
    "sim:door": [
        {"id": "l1", "kind": "line", "points": [[0.22, 0.64], [0.78, 0.64]], "in": "right"},
        {
            "id": "f1",
            "kind": "floor",
            "points": [[0.02, 0.46], [0.98, 0.46], [0.98, 0.995], [0.02, 0.995]],
        },
    ],
}


def suggest_zones() -> dict[str, dict]:
    """Zone JSON (contract §4) that fits the scene, per camera, with its role and name."""
    return {
        key: {"name": name, "role": role, "zones": [dict(z) for z in _ZONES[key]]}
        for key, (_view, name, role) in CAMERAS.items()
    }


class Scene:
    """One world seen by both cameras. Thread-safe; frames are rendered for a wall time."""

    def __init__(self, scene: str, seed: int, start: float) -> None:
        self.world = World(scene, seed)
        self.start = start
        self.renderer = Renderer()
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self.world.scene

    def scene_time(self, t_wall: float) -> float:
        return max(0.0, t_wall - self.start)

    def frame(self, key: str, t_wall: float) -> tuple[np.ndarray, list[Detection]]:
        view, name, _role = CAMERAS[key]
        with self._lock:
            self.world.advance_to(self.scene_time(t_wall))
            return self.renderer.render(self.world, view, t_wall, name.upper())

    def phase(self, t_wall: float) -> str:
        return self.world.script.phase(self.scene_time(t_wall))
