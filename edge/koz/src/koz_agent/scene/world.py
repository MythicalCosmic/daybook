"""The generated pharmacy: a small deterministic simulation seen by two ceiling cameras.

``counter`` looks at the counter: shelves on the back wall, two tills (Kassa 1 and 2) with
pharmacists behind them, customers queueing in front. ``door`` looks at the entrance: people come
in through a sliding glass door and leave through it.

Everything is in the cameras' own pixels (960×540): an actor stands at its foot point ``(x, y)``
and its size follows a perspective scale of ``y``. The world advances in fixed 0.1 s steps from
scene time 0, with one ``random.Random(seed)``, so a scene and a seed always give the same people,
in the same places, at the same time.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .scripts import SCRIPTS, Script

DT = 0.1
W, H = 960, 540

# counter view
COUNTER_TOP = 240  # the counter's top edge; staff below it are hidden by the counter
TILL_X = (300.0, 640.0)
STAFF_Y = 280.0
SHELF_Y = 214.0
BACK_DOOR = (790.0, 207.0)
SLOT0_Y = 372.0
SLOT_DX = (-40.0, 40.0)
SLOT_DY = 32.0
MAX_SLOTS = 6
COUNTER_ENTRY = (-46.0, 478.0)
COUNTER_EXIT = (-52.0, 420.0)

# door view
DOOR_OUTSIDE = (482.0, 206.0)
DOOR_THRESHOLD_Y = 238.0
DOOR_BOTTOM_IN = (438.0, 612.0)
DOOR_BOTTOM_OUT = (548.0, 612.0)

BASE_HEIGHT = 132.0
WALK_SPEED = 108.0  # pixels per second at scale 1
TRANSIT_S = 1.6


def counter_scale(y: float) -> float:
    return 0.70 + 0.52 * (y - 200.0) / 340.0


def door_scale(y: float) -> float:
    return 0.62 + 0.62 * (y - 206.0) / 334.0


def slot_pos(till: int, index: int) -> tuple[float, float]:
    return (TILL_X[till] + SLOT_DX[till] * index, SLOT0_Y + SLOT_DY * index)


@dataclass
class Look:
    skin: str
    hair: str
    coat: str
    trousers: str
    shoes: str
    hat: str | None = None  # "doppi", "knit", "scarf", "bun" or None
    hat_color: str = "#1F1F24"
    height: float = 1.0
    width: float = 1.0


@dataclass
class Actor:
    id: int
    kind: str  # "customer" or "staff"
    look: Look
    view: str | None
    x: float
    y: float
    state: str
    path: list[tuple[float, float]] = field(default_factory=list)
    walked: float = 0.0
    moving: bool = False
    facing: str = "away"  # "away" (back to the camera) or "toward"
    carrying: str | None = None  # "bag" or "box"
    timer: float = 0.0
    # customers
    till: int | None = None
    joined_at: float | None = None
    patience: float = 300.0
    service_s: float = 30.0
    bought: bool = False
    jitter: float = 0.0
    # staff
    home: int = 0
    serving: int | None = None
    service_left: float = 0.0
    service_total: float = 0.0
    fetch_done: bool = False
    box_color: int = 0


STAFF_LOOKS = (
    Look(
        skin="#E8B48E",
        hair="#2B211C",
        coat="#FAFBFC",
        trousers="#3A4150",
        shoes="#2A2A2E",
        hat="bun",
        height=0.97,
        width=0.96,
    ),
    Look(
        skin="#D49C76",
        hair="#1E1A18",
        coat="#FAFBFC",
        trousers="#2E3440",
        shoes="#26262A",
        height=1.04,
        width=1.04,
    ),
)

SKINS = ("#F2CBA8", "#E8B48E", "#D9A07A", "#C68A63", "#F5D5BC", "#E2A985")
HAIRS = ("#2A2420", "#3B2B22", "#4E3A2C", "#1E1C1B", "#6B4F3A", "#8F8F8F", "#B9B4AC")
COATS = (
    "#3E4C6D",
    "#7B3F4A",
    "#6F7650",
    "#C9A04A",
    "#4B5058",
    "#B08A62",
    "#3F7F7C",
    "#6B4F72",
    "#8D939B",
    "#2F5D50",
    "#C06C5A",
    "#5A6E8C",
    "#9C6B4E",
    "#47566B",
)
TROUSERS = ("#2E3340", "#3A3A3A", "#4A4F5C", "#5B4B3D", "#2B3A4A", "#3D3A47")
SCARVES = ("#C46A6A", "#6A8FC4", "#D9B26A", "#8E6AC4", "#5DA38A", "#E39B7B", "#7C8FA8")
KNITS = ("#C0504D", "#4F81BD", "#7FA35A", "#E0B04A", "#5A5A5A", "#8B5A83")


class World:
    def __init__(self, scene: str = "demo", seed: int = 1) -> None:
        if scene not in SCRIPTS:
            raise ValueError(f"unknown scene {scene!r}; choose one of {', '.join(SCRIPTS)}")
        self.scene = scene
        self.seed = seed
        self.script: Script = SCRIPTS[scene]
        self.rng = random.Random(f"koz-scene:{scene}:{seed}")
        self.t = 0.0
        self.steps = 0
        self.actors: dict[int, Actor] = {}
        self.lines: list[list[int]] = [[], []]
        self.door_open = 0.0
        self.served = 0
        self.gave_up = 0
        self.arrived = 0
        self._next_id = 1
        self.staff: list[Actor] = []
        for till, look in enumerate(STAFF_LOOKS):
            present = self._should_be_present(till, 0.0)
            actor = self._new_actor(
                "staff",
                look,
                view="counter" if present else None,
                x=TILL_X[till],
                y=STAFF_Y,
                state="at_till" if present else "away",
            )
            actor.home = till
            actor.facing = "toward"
            self.staff.append(actor)
        self.next_arrival = 2.0
        # someone is already being served at Kassa 1 when the camera starts
        first = self._new_customer()
        first.view, first.state = "counter", "queue"
        first.x, first.y = slot_pos(0, 0)
        first.till = 0
        first.joined_at = -25.0
        self.lines[0].append(first.id)

    # --- the clock ------------------------------------------------------------------------

    def advance_to(self, t: float) -> None:
        target = math.floor(t / DT + 1e-9)
        while self.steps < target:
            self.step()

    def step(self) -> None:
        self.steps += 1
        self.t = self.steps * DT
        loop_t = self.t % self.script.loop_s
        self._arrivals(loop_t)
        self._duty(loop_t)
        self._tills()
        self._patience()
        for actor in list(self.actors.values()):
            self._move(actor)
        self._door()

    # --- actors ---------------------------------------------------------------------------

    def _new_actor(self, kind: str, look: Look, **kwargs) -> Actor:
        actor = Actor(id=self._next_id, kind=kind, look=look, **kwargs)
        self._next_id += 1
        self.actors[actor.id] = actor
        return actor

    def _new_customer(self) -> Actor:
        rng = self.rng
        roll = rng.random()
        hat, hat_color = None, "#1F1F24"
        if roll < 0.18:
            hat, hat_color = "doppi", "#1E1E22"
        elif roll < 0.42:
            hat, hat_color = "scarf", rng.choice(SCARVES)
        elif roll < 0.58:
            hat, hat_color = "knit", rng.choice(KNITS)
        look = Look(
            skin=rng.choice(SKINS),
            hair=rng.choice(HAIRS),
            coat=rng.choice(COATS),
            trousers=rng.choice(TROUSERS),
            shoes=rng.choice(("#2A2A2E", "#3B302A", "#4A4A50")),
            hat=hat,
            hat_color=hat_color,
            height=rng.uniform(0.92, 1.06),
            width=rng.uniform(0.94, 1.08),
        )
        actor = self._new_actor("customer", look, view=None, x=0.0, y=0.0, state="new")
        actor.patience = rng.uniform(*self.script.patience)
        actor.jitter = rng.uniform(-1.0, 1.0)
        actor.box_color = rng.randrange(8)
        return actor

    def _arrivals(self, loop_t: float) -> None:
        if self.t < self.next_arrival:
            return
        customer = self._new_customer()
        self.arrived += 1
        customer.view, customer.state = "door", "door_in"
        customer.facing = "toward"
        j = customer.jitter
        customer.x, customer.y = DOOR_OUTSIDE[0] + 18 * j, DOOR_OUTSIDE[1]
        customer.path = [
            (476 + 14 * j, 330.0),
            (DOOR_BOTTOM_IN[0] + 30 * j, DOOR_BOTTOM_IN[1]),
        ]
        self.next_arrival = self._next_arrival(loop_t)

    def _next_arrival(self, loop_t: float) -> float:
        """The next arrival, honouring each window's rate; a gap that runs past its window, or a
        window with no arrivals (0, 0), continues from the next window."""
        script = self.script
        loop_start = self.t - loop_t
        at = loop_t
        for _ in range(2 * len(script.arrivals) + 2):
            _index, (_start, end, low, high) = script.arrival_window(at)
            if high > 0:
                candidate = at + self.rng.uniform(low, high)
                if candidate < end:
                    return loop_start + candidate
            at = end
            if at >= script.loop_s:
                loop_start += script.loop_s
                at = 0.0
        return self.t + 60.0

    # --- staff ----------------------------------------------------------------------------

    def _should_be_present(self, till: int, loop_t: float) -> bool:
        if till not in self.script.staff:
            return False
        return not any(a <= loop_t < b for a, b in self.script.absent.get(till, ()))

    def _duty(self, loop_t: float) -> None:
        for staff in self.staff:
            present = self._should_be_present(staff.home, loop_t)
            on_floor = staff.state in ("at_till", "fetch", "fetch_back", "from_back")
            if on_floor and not present:
                staff.state = "to_back"
                staff.facing = "away"
                staff.path = [(staff.x, SHELF_Y + 4), BACK_DOOR]
                self._close_till(staff.home)
            elif staff.state in ("away", "to_back") and present:
                if staff.state == "away":
                    staff.view = "counter"
                    staff.x, staff.y = BACK_DOOR
                staff.state = "from_back"
                staff.facing = "toward"
                staff.path = [(TILL_X[staff.home], SHELF_Y + 4), (TILL_X[staff.home], STAFF_Y)]

    def _till_open(self, till: int) -> bool:
        staff = self.staff[till]
        return staff.state in ("at_till", "fetch", "fetch_back") or (
            staff.state == "from_back"
            and self._should_be_present(till, self.t % self.script.loop_s)
        )

    def _close_till(self, till: int) -> None:
        """A pharmacist leaves. If the other till is open, the whole line (even someone being
        served) moves over; otherwise everyone waits and the service pauses."""
        other = 1 - till
        if not self._till_open(other):
            return
        movers, self.lines[till] = self.lines[till], []
        self.staff[till].serving = None
        for cid in movers:
            self.actors[cid].till = other
            self.lines[other].append(cid)
        self._retarget(other)

    def _rebalance(self) -> None:
        open_tills = [i for i in (0, 1) if self._till_open(i)]
        if len(open_tills) < 2:
            return
        a, b = self.lines
        while abs(len(a) - len(b)) >= 2:
            longer, shorter = (0, 1) if len(a) > len(b) else (1, 0)
            cid = self.lines[longer].pop()
            customer = self.actors[cid]
            customer.till = shorter
            self.lines[shorter].append(cid)
            a, b = self.lines
        self._retarget(0)
        self._retarget(1)

    def _tills(self) -> None:
        self._rebalance()
        for staff in self.staff:
            till = staff.home
            line = self.lines[till]
            if staff.serving is None:
                if staff.state != "at_till" or not line:
                    continue
                customer = self.actors[line[0]]
                if customer.state != "queue" or customer.moving:
                    continue
                loop_t = self.t % self.script.loop_s
                service = self.rng.uniform(*self.script.window(self.script.service, loop_t))
                customer.service_s = service
                staff.serving = customer.id
                staff.service_total = service
                staff.service_left = service
                staff.fetch_done = service < 22
                staff.box_color = customer.box_color
                continue
            if staff.state not in ("at_till", "fetch", "fetch_back"):
                continue  # away: the service waits
            staff.service_left -= DT
            done = staff.service_total - staff.service_left
            if (
                not staff.fetch_done
                and staff.state == "at_till"
                and done > 0.25 * staff.service_total
            ):
                staff.state = "fetch"
                staff.facing = "away"
                offset = 70.0 if till == 0 else -70.0
                staff.path = [(TILL_X[till] + offset, SHELF_Y)]
                staff.fetch_done = True
            if staff.service_left <= 0 and staff.state == "at_till":
                customer = self.actors.get(staff.serving)
                staff.serving = None
                staff.carrying = None
                if customer is not None and customer.id in line:
                    line.remove(customer.id)
                    customer.bought = True
                    self.served += 1
                    self._leave(customer, bag=True)
                    self._retarget(till)

    def _patience(self) -> None:
        for till, line in enumerate(self.lines):
            serving = self.staff[till].serving
            for cid in list(line):
                customer = self.actors[cid]
                if cid == serving or customer.state != "queue" or customer.joined_at is None:
                    continue
                if self.t - customer.joined_at > customer.patience:
                    line.remove(cid)
                    self.gave_up += 1
                    self._leave(customer, bag=False)
                    self._retarget(till)

    def _leave(self, customer: Actor, *, bag: bool) -> None:
        customer.state = "leave"
        customer.till = None
        customer.carrying = "bag" if bag else None
        customer.path = [(customer.x - 70, customer.y + 26), COUNTER_EXIT]

    def _retarget(self, till: int) -> None:
        for index, cid in enumerate(self.lines[till]):
            customer = self.actors[cid]
            if customer.state not in ("queue", "to_line"):
                continue
            target = slot_pos(till, min(index, MAX_SLOTS - 1))
            if customer.path:
                if customer.path[-1] != target:
                    customer.path[-1] = target
            elif (customer.x, customer.y) != target:
                customer.path = [target]

    def _choose_till(self) -> int:
        open_tills = [i for i in (0, 1) if self._till_open(i)]
        if not open_tills:
            present = [s.home for s in self.staff if s.home in self.script.staff]
            return present[0] if present else 0
        return min(open_tills, key=lambda i: (len(self.lines[i]), i))

    # --- movement and arrivals in each view -------------------------------------------

    def _move(self, actor: Actor) -> None:
        if actor.state in ("transit_in", "transit_out"):
            actor.timer -= DT
            if actor.timer <= 0:
                self._arrive_view(actor)
            return
        if not actor.path:
            actor.moving = False
            return
        scale = (door_scale if actor.view == "door" else counter_scale)(actor.y)
        step = WALK_SPEED * max(0.5, scale) * DT
        if actor.kind == "staff":
            step *= 0.9
        tx, ty = actor.path[0]
        dx, dy = tx - actor.x, ty - actor.y
        dist = math.hypot(dx, dy)
        actor.moving = True
        if dist <= step:
            actor.x, actor.y = tx, ty
            actor.walked += dist
            actor.path.pop(0)
            if not actor.path:
                actor.moving = False
                self._arrived(actor)
        else:
            actor.x += dx / dist * step
            actor.y += dy / dist * step
            actor.walked += step

    def _arrived(self, actor: Actor) -> None:
        state = actor.state
        if state == "door_in":
            actor.view, actor.state, actor.timer = None, "transit_in", TRANSIT_S
        elif state == "to_line":
            actor.state = "queue"
        elif state == "leave":
            actor.view, actor.state, actor.timer = None, "transit_out", TRANSIT_S
        elif state == "door_out":
            del self.actors[actor.id]
        elif state == "to_back":
            actor.view, actor.state = None, "away"
            actor.carrying = None
        elif state == "from_back":
            actor.state = "at_till"
            actor.facing = "toward"
        elif state == "fetch":
            actor.state = "fetch_back"
            actor.carrying = "box"
            actor.facing = "toward"
            actor.path = [(TILL_X[actor.home], STAFF_Y)]
        elif state == "fetch_back":
            actor.state = "at_till"

    def _arrive_view(self, actor: Actor) -> None:
        if actor.state == "transit_in":
            till = self._choose_till()
            actor.view, actor.state = "counter", "to_line"
            actor.facing = "away"
            actor.x, actor.y = COUNTER_ENTRY[0], COUNTER_ENTRY[1] + 14 * actor.jitter
            actor.till = till
            actor.joined_at = self.t
            self.lines[till].append(actor.id)
            index = min(len(self.lines[till]) - 1, MAX_SLOTS - 1)
            actor.path = [slot_pos(till, index)]
        else:
            actor.view, actor.state = "door", "door_out"
            actor.facing = "away"
            j = actor.jitter
            actor.x, actor.y = DOOR_BOTTOM_OUT[0] + 26 * j, DOOR_BOTTOM_OUT[1]
            actor.path = [(506 + 12 * j, 330.0), (DOOR_OUTSIDE[0] + 10 * j, DOOR_OUTSIDE[1] - 4)]

    def _door(self) -> None:
        near = any(a.view == "door" and a.y < DOOR_THRESHOLD_Y + 120 for a in self.actors.values())
        target = 1.0 if near else 0.0
        speed = 2.2 * DT
        if self.door_open < target:
            self.door_open = min(target, self.door_open + speed)
        else:
            self.door_open = max(target, self.door_open - speed * 0.6)

    # --- what each camera sees --------------------------------------------------------

    def in_view(self, view: str) -> list[Actor]:
        return sorted(
            (a for a in self.actors.values() if a.view == view), key=lambda a: (a.y, a.id)
        )

    def counts(self) -> dict:
        """The true numbers (for tests and the scene's own checks)."""
        counter = self.in_view("counter")
        return {
            "t": round(self.t, 1),
            "staff_present": sum(1 for s in self.staff if s.view == "counter"),
            "queue": sum(1 for a in counter if a.kind == "customer" and a.y >= 335),
            "lines": [len(line) for line in self.lines],
            "served": self.served,
            "gave_up": self.gave_up,
            "arrived": self.arrived,
        }
