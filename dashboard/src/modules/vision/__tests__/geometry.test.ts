/**
 * The zone editor's geometry (docs/KOZ.md §4): normalising pointer positions into 0..1, picking
 * corners, edges and zones in screen pixels, the side of the directed entrance line and its arrow,
 * and every validation rule the backend applies to PATCH.
 */
import { describe, expect, it } from "vitest";

import {
  MAX_ZONES,
  canClose,
  centroid,
  cleanZone,
  flipInside,
  hitEdge,
  hitVertex,
  hitZone,
  insideArrow,
  lineSide,
  moveZone,
  nextZoneId,
  normalizePoint,
  pointFromClient,
  pointInPolygon,
  selfIntersects,
  validateZones,
  zonesAt,
} from "../lib/geometry";
import type { Point, Zone } from "../types";

const size = { w: 1600, h: 900 };
const queue: Zone = { id: "q1", kind: "queue", points: [[0.12, 0.55], [0.62, 0.55], [0.7, 0.98], [0.05, 0.98]] };
const staff: Zone = { id: "s1", kind: "staff", points: [[0.1, 0.2], [0.8, 0.2], [0.8, 0.45], [0.1, 0.45]] };
const line: Zone = { id: "l1", kind: "line", points: [[0.1, 0.6], [0.9, 0.62]], in: "left" };

describe("normalising", () => {
  it("turns a pointer over the picture into a point inside the frame, rounded to four places", () => {
    const rect = { left: 100, top: 50, width: 800, height: 450 };
    expect(pointFromClient(500, 275, rect)).toEqual([0.5, 0.5]);
    expect(pointFromClient(100, 50, rect)).toEqual([0, 0]);
    // Past the edges: clamped, never outside 0..1.
    expect(pointFromClient(50, 600, rect)).toEqual([0, 1]);
    expect(pointFromClient(333, 123, rect)).toEqual([0.2913, 0.1622]);
    expect(pointFromClient(10, 10, { left: 0, top: 0, width: 0, height: 0 })).toEqual([0, 0]);
  });

  it("clamps and rounds any point", () => {
    expect(normalizePoint([1.2, -0.4])).toEqual([1, 0]);
    expect(normalizePoint([0.123456, 0.987654])).toEqual([0.1235, 0.9877]);
    expect(normalizePoint([Number.NaN, 0.5])).toEqual([0, 0.5]);
  });
});

describe("hit tests", () => {
  it("finds a point inside a polygon", () => {
    expect(pointInPolygon([0.4, 0.8], queue.points)).toBe(true);
    expect(pointInPolygon([0.4, 0.3], queue.points)).toBe(false);
    expect(pointInPolygon([0.69, 0.6], queue.points)).toBe(false);
  });

  it("picks the nearest corner within the radius, in screen pixels", () => {
    // 0.004 of 1600 px is 6.4 px: inside a 14 px radius.
    expect(hitVertex([queue, staff], [0.124, 0.551], size)).toEqual({ zone: 0, point: 0 });
    expect(hitVertex([queue, staff], [0.2, 0.7], size)).toBeNull();
    // A finger gets a bigger radius.
    expect(hitVertex([queue], [0.13, 0.565], size, 10)).toBeNull();
    expect(hitVertex([queue], [0.13, 0.565], size, 22)).toEqual({ zone: 0, point: 0 });
  });

  it("prefers the zone drawn on top, and finds a line by its distance", () => {
    const over: Zone = { id: "f1", kind: "floor", points: [[0, 0], [1, 0], [1, 1], [0, 1]] };
    expect(hitZone([over, queue], [0.4, 0.8], size)).toBe(1);
    expect(hitZone([queue, over], [0.4, 0.8], size)).toBe(1);
    expect(hitZone([line], [0.5, 0.612], size)).toBe(0);
    expect(hitZone([line], [0.5, 0.7], size)).toBeNull();
  });

  it("finds the edge a new corner goes on", () => {
    expect(hitEdge(queue, [0.4, 0.552], size)).toBe(0);
    expect(hitEdge(queue, [0.4, 0.8], size)).toBeNull();
    expect(hitEdge(line, [0.5, 0.61], size)).toBeNull();
  });
});

describe("the entrance line", () => {
  const a: Point = [0, 0.5];
  const b: Point = [1, 0.5];

  it("says which side of A→B a point is on, as the picture shows it", () => {
    // Walking left to right across the frame, the upper half is on your left hand.
    expect(lineSide(a, b, [0.5, 0.2])).toBe("left");
    expect(lineSide(a, b, [0.5, 0.8])).toBe("right");
    // Reversing the line swaps the sides.
    expect(lineSide(b, a, [0.5, 0.2])).toBe("right");
    // Walking down the frame, the screen's right is on your left hand.
    expect(lineSide([0.5, 0], [0.5, 1], [0.8, 0.5])).toBe("left");
    expect(lineSide(a, b, [0.3, 0.5])).toBeNull();
  });

  it("draws the arrow from the middle of the line toward the inside", () => {
    const left = insideArrow(a, b, "left", size, 36);
    expect(left.from).toEqual([0.5, 0.5]);
    expect(left.to[0]).toBeCloseTo(0.5);
    expect(left.to[1]).toBeCloseTo(0.5 - 36 / 900);
    expect(lineSide(a, b, left.to)).toBe("left");
    const right = insideArrow(a, b, "right", size, 36);
    expect(lineSide(a, b, right.to)).toBe("right");
    // The arrow of a slanted line still lands on the side it names.
    const slanted = insideArrow([0.1, 0.6], [0.9, 0.62], "left", size);
    expect(lineSide([0.1, 0.6], [0.9, 0.62], slanted.to)).toBe("left");
  });

  it("flips the inside of a line, and nothing else", () => {
    expect(flipInside(line).in).toBe("right");
    expect(flipInside(flipInside(line)).in).toBe("left");
    expect(flipInside(queue)).toBe(queue);
  });
});

describe("editing", () => {
  it("names a new zone with the first free id of its kind", () => {
    expect(nextZoneId([], "queue")).toBe("q1");
    expect(nextZoneId([queue, { ...queue, id: "q2" }], "queue")).toBe("q3");
    expect(nextZoneId([queue], "mask")).toBe("m1");
  });

  it("moves a whole zone without leaving the frame or changing its shape", () => {
    const moved = moveZone(staff, 0.5, -0.5);
    expect(moved.points).toEqual([[0.3, 0], [1, 0], [1, 0.25], [0.3, 0.25]]);
  });

  it("knows when a shape can close", () => {
    expect(canClose("line", [[0, 0], [1, 1]])).toBe(true);
    expect(canClose("line", [[0, 0]])).toBe(false);
    expect(canClose("queue", [[0, 0], [1, 0]])).toBe(false);
    expect(canClose("queue", [[0, 0], [1, 0], [1, 1]])).toBe(true);
  });

  it("sends lines with their side and polygons without one", () => {
    expect(cleanZone({ ...queue, in: "left" })).toEqual({ id: "q1", kind: "queue", points: queue.points });
    expect(cleanZone({ id: "l2", kind: "line", points: [[0, 0], [1, 1]] }).in).toBe("left");
  });

  it("tells a shape that crosses itself, and where a zone's name goes", () => {
    expect(selfIntersects([[0, 0], [1, 1], [1, 0], [0, 1]])).toBe(true);
    expect(selfIntersects(queue.points)).toBe(false);
    expect(centroid([[0, 0], [1, 0], [1, 1], [0, 1]])).toEqual([0.5, 0.5]);
  });

  it("finds the zones a foot point stands in, never a line", () => {
    expect(zonesAt([queue, staff, line], [0.3, 0.9]).map((zone) => zone.id)).toEqual(["q1"]);
  });
});

describe("validation (the backend's rules)", () => {
  it("accepts the contract's example", () => {
    const zones: Zone[] = [queue, staff, line, { id: "f1", kind: "floor", points: [[0, 0], [1, 0], [1, 1], [0, 1]] }, { id: "m1", kind: "mask", points: [[0.85, 0], [1, 0], [1, 0.3], [0.85, 0.3]] }];
    expect(validateZones(zones)).toEqual([]);
  });

  it("refuses more than eight zones", () => {
    const many = Array.from({ length: MAX_ZONES + 1 }, (_, i) => ({ ...queue, id: `q${i + 1}` }));
    expect(validateZones(many).map((p) => p.code)).toEqual(["too_many"]);
  });

  it("refuses bad and repeated ids and unknown kinds", () => {
    const codes = validateZones([queue, { ...staff, id: "q1" }, { ...staff, id: "Big Zone" }, { id: "x1", kind: "door" as never, points: queue.points }]).map((p) => p.code);
    expect(codes).toEqual(["id_duplicate", "id_format", "kind"]);
  });

  it("counts corners: 3 to 24 for a polygon, exactly 2 for a line", () => {
    expect(validateZones([{ ...queue, points: [[0, 0], [1, 1]] }])[0]).toMatchObject({ code: "polygon_few", zone: "q1" });
    const tooMany = Array.from({ length: 25 }, (_, i) => [Math.cos(i) / 2 + 0.5, Math.sin(i) / 2 + 0.5] as Point);
    expect(validateZones([{ ...queue, points: tooMany }])[0]).toMatchObject({ code: "polygon_many" });
    expect(validateZones([{ ...line, points: [[0, 0], [0.5, 0.5], [1, 1]] }])[0]).toMatchObject({ code: "line_points" });
    expect(validateZones([{ ...line, in: undefined }])[0]).toMatchObject({ code: "line_side" });
  });

  it("keeps every coordinate inside 0..1", () => {
    expect(validateZones([{ ...queue, points: [[0, 0], [1.2, 0], [1, 1]] }])[0]).toMatchObject({ code: "range", zone: "q1" });
    expect(validateZones([{ ...queue, points: [[0, 0], [Number.NaN, 0], [1, 1]] }])[0]).toMatchObject({ code: "range" });
  });
});
