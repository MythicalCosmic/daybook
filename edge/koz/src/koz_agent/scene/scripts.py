"""The scenes: how busy the pharmacy is and when pharmacists step away, over a loop.

Tables are ``(from_s, to_s, low, high)`` within the loop: the gap between arrivals and the length
of a service (drawn when it starts) are uniform between ``low`` and ``high``; an arrivals row of
``(0, 0)`` means nobody comes in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Table = tuple[tuple[float, float, float, float], ...]


@dataclass(frozen=True)
class Script:
    name: str
    loop_s: float
    arrivals: Table
    service: Table
    staff: tuple[int, ...]  # tills that have a pharmacist in this scene
    absent: dict[int, tuple[tuple[float, float], ...]] = field(default_factory=dict)
    patience: tuple[float, float] = (300.0, 480.0)
    phases: tuple[tuple[float, str], ...] = ((0.0, "calm"),)

    @staticmethod
    def window(table: Table, t: float) -> tuple[float, float]:
        for start, end, low, high in table:
            if start <= t < end:
                return (low, high)
        return (table[-1][2], table[-1][3])

    def arrival_window(self, t: float) -> tuple[int, tuple[float, float, float, float]]:
        """The arrivals row covering loop time ``t``; ``(0, 0)`` rows have no arrivals."""
        for index, row in enumerate(self.arrivals):
            if row[0] <= t < row[1]:
                return index, row
        return len(self.arrivals) - 1, self.arrivals[-1]

    def phase(self, t: float) -> str:
        loop_t = t % self.loop_s
        name = self.phases[0][1]
        for start, phase in self.phases:
            if loop_t >= start:
                name = phase
        return name


SCRIPTS: dict[str, Script] = {
    # Two pharmacists, a steady trickle of customers; the queue stays at 0–2.
    "calm": Script(
        name="calm",
        loop_s=300,
        arrivals=((0, 300, 26, 44),),
        service=((0, 300, 22, 38),),
        staff=(0, 1),
        patience=(420, 600),
    ),
    # A wave of customers while one pharmacist is alone: the queue grows to 5–6 until the second
    # opens Kassa 2, and then it clears.
    "rush": Script(
        name="rush",
        loop_s=360,
        arrivals=((0, 15, 2.5, 4), (15, 170, 36, 44), (170, 250, 0, 0), (250, 360, 32, 44)),
        service=((0, 170, 36, 44), (170, 250, 12, 18), (250, 360, 25, 38)),
        staff=(0, 1),
        absent={1: ((0, 170),)},
        patience=(300, 480),
        phases=((0, "rush"), (240, "calm")),
    ),
    # One pharmacist, who steps away for 2.5 minutes while customers wait.
    "break": Script(
        name="break",
        loop_s=420,
        arrivals=((0, 420, 38, 52),),
        service=((0, 420, 20, 30),),
        staff=(0,),
        absent={0: ((120, 270),)},
        patience=(240, 420),
        phases=((0, "calm"), (120, "break"), (270, "calm")),
    ),
    # Calm → rush → break, every 8 minutes. A wave comes in at 0:30 while one pharmacist is
    # alone and the queue reaches 5–6; at 3:20 the second opens Kassa 2 and it clears. At 4:50
    # Kassa 2 closes, and from 5:20 to 7:30 the only pharmacist left is away while customers wait.
    "demo": Script(
        name="demo",
        loop_s=480,
        arrivals=(
            (0, 30, 25, 35), (30, 45, 2.5, 4), (45, 200, 36, 44), (200, 290, 0, 0),
            (290, 480, 40, 52),
        ),
        service=((0, 30, 25, 38), (30, 200, 36, 44), (200, 290, 12, 18), (290, 480, 22, 32)),
        staff=(0, 1),
        absent={1: ((0, 200), (290, 480)), 0: ((320, 450),)},
        patience=(200, 360),
        phases=((0, "calm"), (30, "rush"), (290, "break"), (450, "calm")),
    ),
}
