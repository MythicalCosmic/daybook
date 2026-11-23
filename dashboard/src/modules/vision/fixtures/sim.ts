/**
 * Fixture mode only: a pharmacy that runs on the clock, so the live view has something real to
 * follow. One cycle lasts seven minutes and every scene is computed for it once, deterministic:
 *
 *   0:00  calm, one pharmacist at the counter
 *   0:40  the evening rush: people arrive faster than one pharmacist can serve them, the queue
 *         builds, waits pass two minutes and a queue alert opens
 *   2:40  a second pharmacist comes to the counter, the queue drains and the alert clears
 *   4:50  both step away (one is seen in the storeroom), a customer waits at an empty counter
 *         and after 90 s a "nobody at the counter" alert opens; the pharmacist comes back
 *
 * The same people walk through the entrance camera before and after the counter, and the
 * storeroom camera sees the pharmacist who left. Rules are the contract's defaults (3 people,
 * 120 s, 90 s, 15 s), evaluated on the simulated numbers as the Ko‘z box would.
 */
import { pointInPolygon } from "../lib/geometry";
import type { FramePerson, Point, Zone } from "../types";

export const CYCLE = 420;
export const DT = 0.25;
const STEPS = CYCLE / DT;
/** Width of a person's box for its height, in normalized units of a 16:9 frame. */
const BODY = 0.42 * (9 / 16);

export type SceneKind = "counter" | "entrance" | "floor" | "storeroom" | "empty";

export interface Body {
  track: number;
  role: "customer" | "staff";
  /** Foot point, normalized; may sit a little outside the frame while walking in or out. */
  x: number;
  y: number;
  /** Height of the whole figure, normalized to the frame's height. */
  h: number;
  /** Appearance seed (coat, hair, scarf). */
  look: number;
  /** Seconds in a queue zone so far (counter scene). */
  wait: number | null;
  /** Facing the camera (pharmacists) or away from it (customers at the counter). */
  facing: "camera" | "away" | "side";
}

export interface Stats {
  people: number;
  queue: number;
  staff: number;
  wait: number;
}

export interface Incident {
  kind: "queue" | "unattended";
  start: number;
  end: number;
  peakQueue: number;
  peakWait: number;
  /** Seconds into the cycle when it was acknowledged ("Men boraman"), if anyone did. */
  ackAt: number | null;
}

export interface Scene {
  kind: SceneKind;
  zones: Zone[];
  steps: Body[][];
  stats: Stats[];
  incidents: Incident[];
}

// ─── Seeded randomness ──────────────────────────────────────────────────────

export function rng(seed: number): () => number {
  let state = seed >>> 0 || 1;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ─── Zones of the drawn scenes ──────────────────────────────────────────────

export const COUNTER_ZONES: Zone[] = [
  { id: "s1", kind: "staff", points: [[0.12, 0.2], [0.88, 0.2], [0.88, 0.505], [0.12, 0.505]] },
  { id: "q1", kind: "queue", points: [[0.2, 0.6], [0.8, 0.6], [0.94, 1], [0.06, 1]] },
  { id: "m1", kind: "mask", points: [[0.78, 0.31], [0.9, 0.31], [0.9, 0.47], [0.78, 0.47]] },
];

export const ENTRANCE_ZONES: Zone[] = [
  { id: "l1", kind: "line", points: [[0.06, 0.68], [0.94, 0.63]], in: "right" },
  { id: "m1", kind: "mask", points: [[0.385, 0.1], [0.615, 0.1], [0.615, 0.3], [0.385, 0.3]] },
];

export const FLOOR_ZONES: Zone[] = [{ id: "f1", kind: "floor", points: [[0.04, 0.5], [0.96, 0.5], [1, 1], [0, 1]] }];

// ─── The counter ────────────────────────────────────────────────────────────

/** Where the first customer of each window stands, and where the rest line up behind. */
/** How customers line up: a zig-zag across the floor, or a tight column toward the camera. */
export type QueueShape = "zigzag" | "column";

const WINDOWS: Record<QueueShape, Point[]> = {
  zigzag: [
    [0.4, 0.705],
    [0.62, 0.705],
  ],
  column: [
    [0.58, 0.705],
    [0.74, 0.705],
  ],
};
/**
 * Where the waiting customers stand. The zig-zag keeps everyone visible; the column is how a real
 * queue looks from a camera above and behind it (the agent's own scene): one behind the other
 * toward the camera, each box overlapping the next by about half.
 */
const SLOTS: Record<QueueShape, Point[]> = {
  zigzag: [
    [0.5, 0.79],
    [0.33, 0.83],
    [0.66, 0.87],
    [0.42, 0.925],
    [0.6, 0.975],
    [0.3, 0.995],
    [0.5, 1.07],
  ],
  column: [
    [0.535, 0.765],
    [0.49, 0.815],
    [0.445, 0.865],
    [0.4, 0.915],
    [0.355, 0.965],
    [0.31, 1.0],
    [0.265, 1.06],
  ],
};
const ENTRY: Point = [0.02, 1.16];
const EXIT: Point = [1.08, 0.86];
const STAFF_Y = 0.5;
const STAFF_OUT = 1.08;

interface Customer {
  id: number;
  arrive: number;
  /** This customer's own speed at the counter (0.8–1.2). */
  pace: number;
  service: number;
  x: number;
  y: number;
  state: "walking" | "served" | "leaving" | "gone";
  window: number | null;
  served: number | null;
  enteredZone: number | null;
  look: number;
}

interface Pharmacist {
  id: number;
  window: number;
  /** [from, to) seconds present at the counter. */
  shifts: Array<[number, number]>;
  x: number;
  present: boolean;
  serving: Customer | null;
  look: number;
}

/**
 * Arrivals per phase: [from, every seconds, seconds at the counter]. The evening starts with the
 * after-work crowd (five people within a quarter of a minute); prescriptions take longer then, and
 * two pharmacists together serve faster.
 */
const ARRIVALS: Array<[number, number, number]> = [
  [0, 32, 24],
  [40, 4.2, 30],
  [56, 29, 30],
  [186, 40, 20],
  [240, 34, 22],
  [282, 30, 24],
  [330, 1000, 24],
  [398, 1000, 22],
];

/** How long a customer takes at the counter when served at `t` (two pharmacists work faster). */
function serviceAt(t: number): number {
  return [...ARRIVALS].reverse().find(([from]) => t >= from)![2];
}

function arrivals(random: () => number): Array<{ at: number; pace: number }> {
  const out: Array<{ at: number; pace: number }> = [];
  ARRIVALS.forEach(([from, every], index) => {
    if (every >= 500) return; // nobody comes in this phase
    const to = ARRIVALS[index + 1]?.[0] ?? CYCLE - 20;
    let at = index === 0 ? 4 : from + Math.min(every, 20) * random() * 0.4;
    while (at < to) {
      out.push({ at, pace: 0.8 + random() * 0.4 });
      at += every * (0.7 + random() * 0.6);
    }
  });
  return out;
}

function step(from: number, to: number, max: number): number {
  const d = to - from;
  return Math.abs(d) <= max ? to : from + Math.sign(d) * max;
}

/** Moves a point toward a target at `speed` pixels a second on a 960×540 frame. */
function walk(body: { x: number; y: number }, target: Point, speed = 150): boolean {
  const dx = (target[0] - body.x) * 960;
  const dy = (target[1] - body.y) * 540;
  const distance = Math.hypot(dx, dy);
  const move = speed * DT;
  if (distance <= move) {
    body.x = target[0];
    body.y = target[1];
    return true;
  }
  body.x += (dx / distance) * (move / 960);
  body.y += (dy / distance) * (move / 540);
  return false;
}

/** A customer's height on the counter camera: farther (at the counter) is smaller. */
function counterHeight(y: number): number {
  return Math.min(0.5, 0.31 + Math.max(0, y - 0.7) * 0.52);
}

export function simulateCounter(seed: number, shape: QueueShape = "zigzag"): Scene {
  const windows = WINDOWS[shape];
  const slots = SLOTS[shape];
  const random = rng(seed);
  const customers: Customer[] = arrivals(random).map(({ at, pace }, index) => ({
    id: index + 1,
    arrive: at,
    pace,
    service: 0,
    x: ENTRY[0],
    y: ENTRY[1],
    state: "walking",
    window: null,
    served: null,
    enteredZone: null,
    look: Math.floor(random() * 1000),
  }));
  const pharmacists: Pharmacist[] = [
    { id: 901, window: 0, shifts: [[0, 290], [392, CYCLE + 1]], x: windows[0]![0], present: true, serving: null, look: 11 },
    { id: 902, window: 1, shifts: [[186, 282], [397, 414]], x: STAFF_OUT, present: false, serving: null, look: 23 },
  ];
  const queue = COUNTER_ZONES.find((zone) => zone.id === "q1")!.points;
  const staffZone = COUNTER_ZONES.find((zone) => zone.id === "s1")!.points;

  const steps: Body[][] = [];
  const stats: Stats[] = [];
  for (let i = 0; i < STEPS; i++) {
    const t = i * DT;
    const onShift = (p: Pharmacist) => p.shifts.some(([from, to]) => t >= from && t < to);
    const leavingSoon = (p: Pharmacist) => p.shifts.some(([from, to]) => t >= from && t < to && to - t < 12);

    // Pharmacists come to the counter, serve, and step away once their customer is done.
    for (const p of pharmacists) {
      const home = windows[p.window]![0];
      if (onShift(p)) {
        walkX(p, p.serving ? home : home + Math.sin(t / 5 + p.id) * 0.04);
        p.present = Math.abs(p.x - home) <= 0.06;
      } else if (p.serving) {
        walkX(p, home);
      } else {
        p.present = false;
        walkX(p, STAFF_OUT);
      }
      if (p.serving && p.serving.served !== null && t >= p.serving.served + p.serving.service) {
        p.serving.state = "leaving";
        p.serving = null;
      }
    }

    // Who goes to which window, who lines up behind.
    const waiting = customers.filter((c) => c.arrive <= t && c.state === "walking").sort((a, b) => a.arrive - b.arrive);
    for (const c of waiting) {
      // A pharmacist who stepped away before this customer reached the window: back in the line.
      if (c.window !== null && !onShift(pharmacists.find((p) => p.window === c.window)!)) c.window = null;
    }
    for (const p of pharmacists) {
      if (!p.present || p.serving || leavingSoon(p) || waiting.some((c) => c.window === p.window)) continue;
      const next = waiting.find((c) => c.window === null);
      if (next) next.window = p.window;
    }
    let slot = 0;
    for (const c of waiting) {
      if (c.window !== null) {
        const reached = walk(c, windows[c.window]!);
        const server = pharmacists.find((p) => p.window === c.window)!;
        if (reached && server.present && !server.serving) {
          c.state = "served";
          c.served = t;
          c.service = serviceAt(t) * c.pace;
          server.serving = c;
        }
      } else {
        walk(c, slots[Math.min(slot, slots.length - 1)]!);
        slot++;
      }
    }
    for (const c of customers) {
      if (c.state === "served" && c.window !== null) walk(c, windows[c.window]!);
      if (c.state === "leaving" && walk(c, EXIT, 165)) c.state = "gone";
      const inZone = c.arrive <= t && c.state !== "gone" && pointInPolygon([c.x, Math.min(c.y, 0.999)], queue);
      if (inZone && c.enteredZone === null) c.enteredZone = t;
      if (!inZone && c.state === "leaving") c.enteredZone = null;
    }

    const bodies: Body[] = [];
    for (const p of pharmacists) {
      if (p.x >= STAFF_OUT - 1e-6) continue;
      bodies.push({ track: p.id, role: "staff", x: p.x, y: STAFF_Y, h: 0.36, look: p.look, wait: null, facing: "camera" });
    }
    for (const c of customers) {
      if (c.arrive > t || c.state === "gone") continue;
      const inZone = pointInPolygon([c.x, Math.min(c.y, 0.999)], queue);
      bodies.push({
        track: c.id,
        role: "customer",
        x: c.x,
        y: c.y,
        h: counterHeight(c.y),
        look: c.look,
        wait: inZone && c.enteredZone !== null ? t - c.enteredZone : null,
        facing: c.state === "leaving" ? "side" : "away",
      });
    }
    steps.push(bodies);
    stats.push(countBodies(bodies, queue, staffZone));
  }
  return { kind: "counter", zones: COUNTER_ZONES, steps, stats, incidents: incidents(stats) };
}

function walkX(p: Pharmacist, x: number): void {
  p.x = step(p.x, x, (120 * DT) / 960);
}

function countBodies(bodies: Body[], queue: Point[] | null, staff: Point[] | null): Stats {
  let people = 0;
  let inQueue = 0;
  let inStaff = 0;
  let wait = 0;
  for (const body of bodies) {
    if (body.x < 0 || body.x > 1 || body.y - body.h > 1) continue;
    people++;
    const foot: Point = [body.x, Math.min(body.y, 0.999)];
    if (queue && pointInPolygon(foot, queue)) {
      inQueue++;
      wait = Math.max(wait, Math.floor(body.wait ?? 0));
    }
    if (staff && pointInPolygon(foot, staff)) inStaff++;
  }
  return { people, queue: inQueue, staff: inStaff, wait };
}

/** The contract's rules on the simulated numbers (docs/KOZ.md §5.8), defaults 3 / 120 / 90 / 15 s. */
export function incidents(stats: Stats[], rules = { people: 3, wait: 120, unattended: 90, clear: 15 }): Incident[] {
  const out: Incident[] = [];
  const hold = 5 / DT;
  const clear = rules.clear / DT;
  const unattended = rules.unattended / DT;
  let queueOver = 0;
  let queueUnder = 0;
  let queueOpen: Incident | null = null;
  let emptyFor = 0;
  let attended = 0;
  let emptyOpen: Incident | null = null;
  stats.forEach((s, i) => {
    const t = i * DT;
    const over = s.queue >= rules.people && s.wait >= rules.wait;
    queueOver = over ? queueOver + 1 : 0;
    queueUnder = over ? 0 : queueUnder + 1;
    if (!queueOpen && queueOver >= hold) queueOpen = { kind: "queue", start: t, end: CYCLE, peakQueue: s.queue, peakWait: s.wait, ackAt: null };
    if (queueOpen) {
      queueOpen.peakQueue = Math.max(queueOpen.peakQueue, s.queue);
      queueOpen.peakWait = Math.max(queueOpen.peakWait, s.wait);
      if (queueUnder >= clear) {
        queueOpen.end = t;
        out.push(queueOpen);
        queueOpen = null;
      }
    }
    const empty = s.queue >= 1 && s.staff === 0;
    emptyFor = empty ? emptyFor + 1 : 0;
    attended = empty ? 0 : attended + 1;
    if (!emptyOpen && emptyFor >= unattended) emptyOpen = { kind: "unattended", start: t, end: CYCLE, peakQueue: s.queue, peakWait: s.wait, ackAt: null };
    if (emptyOpen) {
      emptyOpen.peakQueue = Math.max(emptyOpen.peakQueue, s.queue);
      emptyOpen.peakWait = Math.max(emptyOpen.peakWait, s.wait);
      if (attended >= clear) {
        emptyOpen.end = t;
        out.push(emptyOpen);
        emptyOpen = null;
      }
    }
  });
  if (queueOpen) out.push(queueOpen);
  if (emptyOpen) out.push(emptyOpen);
  // The second pharmacist said "Men boraman" a little before walking over.
  for (const incident of out) if (incident.kind === "queue") incident.ackAt = Math.min(incident.end - 1, incident.start + 5);
  return out.sort((a, b) => a.start - b.start);
}

// ─── The entrance: the counter's customers walk in before and out after ───

function entranceHeight(y: number): number {
  return Math.min(0.95, 0.2 + Math.max(0, y - 0.4) * 1.05);
}

export function simulateEntrance(counter: Scene, seed: number): Scene {
  const random = rng(seed);
  interface Walk {
    track: number;
    from: Point;
    to: Point;
    start: number;
    look: number;
  }
  const walks: Walk[] = [];
  const DOOR: Point = [0.5, 0.42];
  const seen = new Map<number, { first: number; last: number; look: number }>();
  counter.steps.forEach((bodies, i) => {
    for (const body of bodies) {
      if (body.role !== "customer") continue;
      const entry = seen.get(body.track) ?? { first: i * DT, last: i * DT, look: body.look };
      entry.last = i * DT;
      seen.set(body.track, entry);
    }
  });
  for (const [track, { first, last, look }] of seen) {
    const side = 0.28 + random() * 0.44;
    walks.push({ track: 2000 + track, from: [DOOR[0] + (random() - 0.5) * 0.08, DOOR[1]], to: [side, 1.18], start: first - 9, look });
    if (last < CYCLE - 8) walks.push({ track: 3000 + track, from: [side + 0.06, 1.18], to: [DOOR[0] + (random() - 0.5) * 0.08, DOOR[1]], start: last + 3, look });
  }
  // People who look around and leave without buying.
  for (let n = 0; n < 9; n++) {
    const start = 10 + random() * (CYCLE - 60);
    const look = Math.floor(random() * 1000);
    walks.push({ track: 4000 + n, from: [0.47 + random() * 0.06, DOOR[1]], to: [0.2 + random() * 0.6, 1.18], start, look });
    walks.push({ track: 4500 + n, from: [0.25 + random() * 0.5, 1.18], to: [0.47 + random() * 0.06, DOOR[1]], start: start + 25 + random() * 40, look });
  }
  const duration = 6.5;
  const steps: Body[][] = [];
  const stats: Stats[] = [];
  for (let i = 0; i < STEPS; i++) {
    const t = i * DT;
    const bodies: Body[] = [];
    for (const w of walks) {
      const progress = (t - w.start) / duration;
      if (progress < 0 || progress > 1) continue;
      // Ease in and out of the door: slower where people are far from the camera.
      const p = progress * progress * (3 - 2 * progress);
      const x = w.from[0] + (w.to[0] - w.from[0]) * p;
      const y = w.from[1] + (w.to[1] - w.from[1]) * p;
      bodies.push({ track: w.track, role: "customer", x, y, h: entranceHeight(y), look: w.look, wait: null, facing: w.to[1] > w.from[1] ? "camera" : "away" });
    }
    steps.push(bodies);
    stats.push(countBodies(bodies, null, null));
  }
  return { kind: "entrance", zones: ENTRANCE_ZONES, steps, stats, incidents: [] };
}

// ─── The sales floor: a few people browsing the shelves ────────────────────

export function simulateFloor(seed: number): Scene {
  const random = rng(seed);
  const lanes = [0.2, 0.43, 0.63, 0.82];
  const people = Array.from({ length: 4 }, (_, n) => ({
    track: 5000 + n,
    look: Math.floor(random() * 1000),
    cx: lanes[n]!,
    cy: 0.66 + random() * 0.2,
    ax: 0.06 + random() * 0.06,
    ay: 0.03 + random() * 0.05,
    speed: 0.035 + random() * 0.04,
    phase: random() * Math.PI * 2,
    from: n === 3 ? 120 : 0,
    to: n === 3 ? 300 : CYCLE + 1,
  }));
  const steps: Body[][] = [];
  const stats: Stats[] = [];
  for (let i = 0; i < STEPS; i++) {
    const t = i * DT;
    const bodies: Body[] = [];
    for (const p of people) {
      if (t < p.from || t >= p.to) continue;
      // Browsing: drift along the aisle, stop now and then at a shelf.
      const s = t * p.speed + p.phase;
      const pause = 0.5 + 0.5 * Math.sin(s * 2.3);
      const x = p.cx + Math.sin(s) * p.ax * pause;
      const y = p.cy + Math.sin(s * 0.7 + 1) * p.ay;
      bodies.push({ track: p.track, role: "customer", x, y, h: 0.24 + (y - 0.55) * 0.55, look: p.look, wait: null, facing: Math.cos(s) > 0 ? "side" : "away" });
    }
    steps.push(bodies);
    stats.push(countBodies(bodies, null, null));
  }
  return { kind: "floor", zones: FLOOR_ZONES, steps, stats, incidents: [] };
}

// ─── The storeroom: whoever left the counter ────────────────────────────────

export function simulateStoreroom(counter: Scene): Scene {
  const steps: Body[][] = [];
  const stats: Stats[] = [];
  const away: Array<{ track: number; from: number; to: number; spot: number }> = [];
  // The pharmacists' absences from the counter, as the counter scene saw them.
  for (const track of [901, 902]) {
    let start: number | null = null;
    counter.steps.forEach((bodies, i) => {
      const there = bodies.some((b) => b.track === track);
      if (!there && start === null) start = i * DT;
      if (there && start !== null) {
        away.push({ track, from: start, to: i * DT, spot: track === 901 ? 0.58 : 0.34 });
        start = null;
      }
    });
    if (start !== null) away.push({ track, from: start, to: CYCLE, spot: track === 901 ? 0.58 : 0.34 });
  }
  for (let i = 0; i < STEPS; i++) {
    const t = i * DT;
    const bodies: Body[] = [];
    for (const a of away) {
      if (t < a.from + 4 || t > a.to - 4) continue;
      const enter = Math.min(1, (t - a.from - 4) / 5);
      const leave = Math.min(1, (a.to - 4 - t) / 5);
      const x = 0.1 + (a.spot - 0.1) * Math.min(enter, leave);
      bodies.push({ track: 6000 + a.track, role: "staff", x, y: 0.86, h: 0.5, look: a.track === 901 ? 11 : 23, wait: null, facing: "side" });
    }
    steps.push(bodies);
    stats.push(countBodies(bodies, null, null));
  }
  return { kind: "storeroom", zones: [], steps, stats, incidents: [] };
}

export function emptyScene(): Scene {
  return { kind: "empty", zones: [], steps: Array.from({ length: STEPS }, () => []), stats: Array.from({ length: STEPS }, () => ({ people: 0, queue: 0, staff: 0, wait: 0 })), incidents: [] };
}

// ─── Reading a scene at a moment ───────────────────────────────────────────

/** Bodies at `t` seconds into the cycle, between two simulated steps. */
export function bodiesAt(scene: Scene, t: number): Body[] {
  const position = (((t % CYCLE) + CYCLE) % CYCLE) / DT;
  const i = Math.floor(position) % STEPS;
  const j = (i + 1) % STEPS;
  const f = position - Math.floor(position);
  const next = new Map(scene.steps[j]!.map((body) => [body.track, body]));
  return scene.steps[i]!.map((body) => {
    const later = next.get(body.track);
    if (!later) return body;
    return { ...body, x: body.x + (later.x - body.x) * f, y: body.y + (later.y - body.y) * f, h: body.h + (later.h - body.h) * f, wait: body.wait === null ? null : body.wait + f * DT };
  });
}

export function statsAt(scene: Scene, t: number): Stats {
  const i = Math.floor((((t % CYCLE) + CYCLE) % CYCLE) / DT) % STEPS;
  return scene.stats[i]!;
}

/** A body's box as the agent reports it: clipped to the frame, normalized. */
export function boxOf(body: Body): [number, number, number, number] {
  const w = body.h * BODY;
  const x0 = Math.max(0, body.x - w / 2);
  const x1 = Math.min(1, body.x + w / 2);
  const y0 = Math.max(0, body.y - body.h);
  const y1 = Math.min(1, body.y);
  return [round(x0), round(y0), round(Math.max(0, x1 - x0)), round(Math.max(0, y1 - y0))];
}

function round(value: number): number {
  return Math.round(value * 10000) / 10000;
}

/** The people of a frame (docs/KOZ.md §5.6) for the bodies visible in it. */
export function framePeople(scene: Scene, bodies: Body[], cycle: number): FramePerson[] {
  const masks = scene.zones.filter((zone) => zone.kind === "mask");
  const queue = scene.zones.filter((zone) => zone.kind === "queue");
  const staff = scene.zones.filter((zone) => zone.kind === "staff");
  const out: FramePerson[] = [];
  for (const body of bodies) {
    const box = boxOf(body);
    if (box[2] < 0.01 || box[3] < 0.02) continue;
    const foot: Point = [body.x, Math.min(body.y, 0.999)];
    if (masks.some((zone) => pointInPolygon(foot, zone.points))) continue;
    const inQueue = queue.find((zone) => pointInPolygon(foot, zone.points));
    const inStaff = staff.find((zone) => pointInPolygon(foot, zone.points));
    const role = body.role === "staff" || inStaff ? "staff" : "customer";
    out.push({
      track: cycle * 100_000 + body.track,
      box,
      role,
      zone: inQueue?.id ?? inStaff?.id ?? null,
      wait_s: inQueue && body.wait !== null ? Math.floor(body.wait) : null,
    });
  }
  return out;
}
