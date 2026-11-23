/**
 * Zone geometry for the zone editor and the live overlay (docs/KOZ.md §4). Every coordinate is
 * normalized to 0..1 of the frame, x to the right and y down, so zones survive a resolution change.
 * Distances that a finger or a pointer feels (hit tests) are measured in pixels of the picture on
 * screen, passed as `size`, because a normalized unit is wider than it is tall on a 16:9 frame.
 */
import type { Point, Zone, ZoneKind } from "../types";

export const MAX_ZONES = 8;
export const MIN_POLYGON_POINTS = 3;
export const MAX_POLYGON_POINTS = 24;
export const ZONE_ID = /^[a-z0-9_-]{1,16}$/;
/** Four decimals: a tenth of a pixel on a 1920 px frame, and short JSON. */
const DECIMALS = 4;

export interface Size {
  w: number;
  h: number;
}

export function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

export function round(value: number, decimals = DECIMALS): number {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

/** A point inside the frame, rounded. */
export function normalizePoint(point: readonly [number, number]): Point {
  return [round(clamp01(point[0])), round(clamp01(point[1]))];
}

/** A pointer position over the picture's box on screen → a normalized point inside the frame. */
export function pointFromClient(clientX: number, clientY: number, rect: { left: number; top: number; width: number; height: number }): Point {
  if (rect.width <= 0 || rect.height <= 0) return [0, 0];
  return normalizePoint([(clientX - rect.left) / rect.width, (clientY - rect.top) / rect.height]);
}

/** Distance in screen pixels between two normalized points. */
export function pixelDistance(a: Point, b: Point, size: Size): number {
  return Math.hypot((a[0] - b[0]) * size.w, (a[1] - b[1]) * size.h);
}

/** Distance in screen pixels from a point to the segment a–b. */
export function pixelDistanceToSegment(p: Point, a: Point, b: Point, size: Size): number {
  const ax = a[0] * size.w;
  const ay = a[1] * size.h;
  const bx = b[0] * size.w;
  const by = b[1] * size.h;
  const px = p[0] * size.w;
  const py = p[1] * size.h;
  const dx = bx - ax;
  const dy = by - ay;
  const length = dx * dx + dy * dy;
  const t = length === 0 ? 0 : Math.min(1, Math.max(0, ((px - ax) * dx + (py - ay) * dy) / length));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/** Ray casting; a point on the border may land either side (fine for picking). */
export function pointInPolygon(p: Point, polygon: readonly Point[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i]!;
    const [xj, yj] = polygon[j]!;
    const crosses = yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi;
    if (crosses) inside = !inside;
  }
  return inside;
}

/** Signed area (shoelace); its sign says the winding, its size how big the zone is. */
export function signedArea(points: readonly Point[]): number {
  let sum = 0;
  for (let i = 0; i < points.length; i++) {
    const [x1, y1] = points[i]!;
    const [x2, y2] = points[(i + 1) % points.length]!;
    sum += x1 * y2 - x2 * y1;
  }
  return sum / 2;
}

/** Where a zone's name goes: the centre of its points (a line's midpoint). */
export function centroid(points: readonly Point[]): Point {
  if (!points.length) return [0.5, 0.5];
  const x = points.reduce((sum, p) => sum + p[0], 0) / points.length;
  const y = points.reduce((sum, p) => sum + p[1], 0) / points.length;
  return [x, y];
}

/** The top-left of a zone's points: where its name tag sits, inside the frame. */
export function labelAnchor(points: readonly Point[]): Point {
  if (!points.length) return [0, 0];
  const minY = Math.min(...points.map((p) => p[1]));
  const top = points.filter((p) => p[1] - minY < 0.02);
  const x = Math.min(...top.map((p) => p[0]));
  return [x, minY];
}

function segmentsCross(a: Point, b: Point, c: Point, d: Point): boolean {
  const orient = (p: Point, q: Point, r: Point) => Math.sign((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]));
  const o1 = orient(a, b, c);
  const o2 = orient(a, b, d);
  const o3 = orient(c, d, a);
  const o4 = orient(c, d, b);
  return o1 * o2 < 0 && o3 * o4 < 0;
}

/** Two edges that cross each other (not neighbours): the shape folds over itself. */
export function selfIntersects(points: readonly Point[]): boolean {
  const n = points.length;
  if (n < 4) return false;
  for (let i = 0; i < n; i++) {
    const a = points[i]!;
    const b = points[(i + 1) % n]!;
    for (let j = i + 1; j < n; j++) {
      // Neighbouring edges share a point; the first and last edge are neighbours too.
      if (j === i || (j + 1) % n === i || (i + 1) % n === j) continue;
      if (segmentsCross(a, b, points[j]!, points[(j + 1) % n]!)) return true;
    }
  }
  return false;
}

// ─── The entrance line ──────────────────────────────────────────────────────

export type Side = "left" | "right";

/**
 * Which side of the directed line A→B a point is on, as you see the picture: walking from A to B,
 * "left" is your left hand. On screen y grows downwards, so for A=(0,0.5) → B=(1,0.5) the upper
 * half of the frame is left. Exactly on the line counts as neither.
 */
export function lineSide(a: Point, b: Point, p: Point): Side | null {
  const cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
  if (Math.abs(cross) < 1e-12) return null;
  return cross < 0 ? "left" : "right";
}

/**
 * The arrow that shows which side is inside: from the line's midpoint, `length` pixels along the
 * normal that points to the `inside` side. Returned in normalized coordinates.
 */
export function insideArrow(a: Point, b: Point, inside: Side, size: Size, length = 36): { from: Point; to: Point } {
  const ax = a[0] * size.w;
  const ay = a[1] * size.h;
  const bx = b[0] * size.w;
  const by = b[1] * size.h;
  const dx = bx - ax;
  const dy = by - ay;
  const norm = Math.hypot(dx, dy) || 1;
  // Screen y points down: (dy, -dx) is the left-hand normal of A→B.
  const sign = inside === "left" ? 1 : -1;
  const nx = (dy / norm) * sign;
  const ny = (-dx / norm) * sign;
  const mx = (ax + bx) / 2;
  const my = (ay + by) / 2;
  return {
    from: [mx / size.w, my / size.h],
    to: [(mx + nx * length) / size.w, (my + ny * length) / size.h],
  };
}

export function flipInside(zone: Zone): Zone {
  if (zone.kind !== "line") return zone;
  return { ...zone, in: zone.in === "left" ? "right" : "left" };
}

// ─── Picking ────────────────────────────────────────────────────────────────

export interface VertexHit {
  zone: number;
  point: number;
}

/** The nearest corner within `radius` pixels; later zones (drawn on top) win ties. */
export function hitVertex(zones: readonly Zone[], p: Point, size: Size, radius = 14): VertexHit | null {
  let best: VertexHit | null = null;
  let bestDistance = radius;
  for (let zone = zones.length - 1; zone >= 0; zone--) {
    zones[zone]!.points.forEach((corner, point) => {
      const distance = pixelDistance(corner, p, size);
      if (distance <= bestDistance) {
        bestDistance = distance;
        best = { zone, point };
      }
    });
  }
  return best;
}

/** The topmost zone under a point: inside a polygon, or within `tolerance` pixels of a line. */
export function hitZone(zones: readonly Zone[], p: Point, size: Size, tolerance = 10): number | null {
  for (let index = zones.length - 1; index >= 0; index--) {
    const zone = zones[index]!;
    if (zone.kind === "line") {
      const [a, b] = zone.points;
      if (a && b && pixelDistanceToSegment(p, a, b, size) <= tolerance) return index;
    } else if (zone.points.length >= 3 && pointInPolygon(p, zone.points)) {
      return index;
    }
  }
  return null;
}

/** The edge of a polygon within `tolerance` pixels, where a new corner would go (after `index`). */
export function hitEdge(zone: Zone, p: Point, size: Size, tolerance = 8): number | null {
  if (zone.kind === "line" || zone.points.length < 2) return null;
  let best: number | null = null;
  let bestDistance = tolerance;
  zone.points.forEach((a, index) => {
    const b = zone.points[(index + 1) % zone.points.length]!;
    const distance = pixelDistanceToSegment(p, a, b, size);
    if (distance <= bestDistance) {
      bestDistance = distance;
      best = index;
    }
  });
  return best;
}

// ─── Editing ────────────────────────────────────────────────────────────────

export function movePoint(zone: Zone, index: number, to: Point): Zone {
  return { ...zone, points: zone.points.map((point, i) => (i === index ? normalizePoint(to) : point)) };
}

/** Moves a whole zone by (dx, dy), kept inside the frame without changing its shape. */
export function moveZone(zone: Zone, dx: number, dy: number): Zone {
  const xs = zone.points.map((p) => p[0]);
  const ys = zone.points.map((p) => p[1]);
  const shiftX = Math.min(Math.max(dx, -Math.min(...xs)), 1 - Math.max(...xs));
  const shiftY = Math.min(Math.max(dy, -Math.min(...ys)), 1 - Math.max(...ys));
  return { ...zone, points: zone.points.map((p) => normalizePoint([p[0] + shiftX, p[1] + shiftY])) };
}

export function insertPoint(zone: Zone, after: number, point: Point): Zone {
  const points = [...zone.points];
  points.splice(after + 1, 0, normalizePoint(point));
  return { ...zone, points };
}

export function removePoint(zone: Zone, index: number): Zone {
  return { ...zone, points: zone.points.filter((_, i) => i !== index) };
}

const PREFIX: Record<ZoneKind, string> = { queue: "q", staff: "s", line: "l", floor: "f", mask: "m" };

/** "q1", "q2", "l1"…: the first free id for a kind. */
export function nextZoneId(zones: readonly Zone[], kind: ZoneKind): string {
  const taken = new Set(zones.map((zone) => zone.id));
  for (let n = 1; ; n++) {
    const id = `${PREFIX[kind]}${n}`;
    if (!taken.has(id)) return id;
  }
}

/** A finished shape: polygons need three corners, a line exactly two. */
export function canClose(kind: ZoneKind, points: readonly Point[]): boolean {
  return kind === "line" ? points.length === 2 : points.length >= MIN_POLYGON_POINTS;
}

// ─── Validation (the backend's rules for PATCH, docs/KOZ.md §4) ─────────────

export type ZoneProblemCode =
  | "too_many"
  | "kind"
  | "id_format"
  | "id_duplicate"
  | "polygon_few"
  | "polygon_many"
  | "line_points"
  | "line_side"
  | "range";

export interface ZoneProblem {
  code: ZoneProblemCode;
  /** The zone it is about (none for "too_many"). */
  zone?: string;
  /** Values for the message ("at most {max}"). */
  params?: Record<string, number | string>;
}

const KINDS = new Set<string>(["queue", "staff", "line", "floor", "mask"]);

/** Every rule the backend applies, so the editor says it inline before saving. Empty: valid. */
export function validateZones(zones: readonly Zone[]): ZoneProblem[] {
  const problems: ZoneProblem[] = [];
  if (zones.length > MAX_ZONES) problems.push({ code: "too_many", params: { max: MAX_ZONES } });
  const seen = new Set<string>();
  for (const zone of zones) {
    if (!ZONE_ID.test(zone.id)) problems.push({ code: "id_format", zone: zone.id });
    else if (seen.has(zone.id)) problems.push({ code: "id_duplicate", zone: zone.id });
    seen.add(zone.id);
    if (!KINDS.has(zone.kind)) {
      problems.push({ code: "kind", zone: zone.id });
      continue;
    }
    const points = Array.isArray(zone.points) ? zone.points : [];
    if (zone.kind === "line") {
      if (points.length !== 2) problems.push({ code: "line_points", zone: zone.id, params: { n: points.length } });
      if (zone.in !== "left" && zone.in !== "right") problems.push({ code: "line_side", zone: zone.id });
    } else if (points.length < MIN_POLYGON_POINTS) {
      problems.push({ code: "polygon_few", zone: zone.id, params: { min: MIN_POLYGON_POINTS, n: points.length } });
    } else if (points.length > MAX_POLYGON_POINTS) {
      problems.push({ code: "polygon_many", zone: zone.id, params: { max: MAX_POLYGON_POINTS, n: points.length } });
    }
    const outside = points.some((p) => !Array.isArray(p) || p.length !== 2 || p.some((v) => typeof v !== "number" || !Number.isFinite(v) || v < 0 || v > 1));
    if (outside) problems.push({ code: "range", zone: zone.id });
  }
  return problems;
}

/** A zone as the API wants it: rounded points, `in` only on lines. */
export function cleanZone(zone: Zone): Zone {
  const out: Zone = { id: zone.id, kind: zone.kind, points: zone.points.map((p) => normalizePoint(p)) };
  if (zone.kind === "line") out.in = zone.in ?? "left";
  return out;
}

/** Zones the foot point is in, as the agent decides "in the queue" (docs/KOZ.md §4: feet). */
export function zonesAt(zones: readonly Zone[], foot: Point): Zone[] {
  return zones.filter((zone) => zone.kind !== "line" && zone.points.length >= 3 && pointInPolygon(foot, zone.points));
}
