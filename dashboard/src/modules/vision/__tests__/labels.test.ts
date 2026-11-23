/**
 * The label pills of a live picture never overlap (lib/labels.ts): a tight queue column like the
 * agent's generated scene, boxes gliding frame after frame, the picture's top edge, a crowd that
 * doesn't fit, and the room a moved pill keeps before it comes back.
 */
import { describe, expect, it } from "vitest";

import { layoutPills, memoryOf, overlaps, type PillInput, type PillMemory, type PillPlacement, type Rect } from "../lib/labels";

const frame = { w: 960, h: 540 };

/** Five people in a column toward the camera, each box overlapping the next by about half. */
function column(shift = 0): PillInput[] {
  return [0, 1, 2, 3, 4].map((i) => ({
    key: i + 1,
    box: { x: 300 + shift - i * 18, y: 180 + i * 14, w: 50 + i * 4, h: 150 + i * 12 },
    width: 84,
    shortWidth: 44,
    height: 20,
    // The one at the counter (farthest) has waited longest.
    priority: 1000 - i * 30,
  }));
}

function noOverlaps(placements: PillPlacement[]): void {
  for (let i = 0; i < placements.length; i++) {
    for (let j = i + 1; j < placements.length; j++) {
      expect(overlaps(placements[i]!, placements[j]!), `${placements[i]!.key} and ${placements[j]!.key}`).toBe(false);
    }
  }
}

function within(rect: Rect, margin = 4): void {
  expect(rect.x).toBeGreaterThanOrEqual(margin - 0.01);
  expect(rect.y).toBeGreaterThanOrEqual(margin - 0.01);
  expect(rect.x + rect.w).toBeLessThanOrEqual(frame.w - margin + 0.01);
  expect(rect.y + rect.h).toBeLessThanOrEqual(frame.h - margin + 0.01);
}

describe("pill layout", () => {
  it("lays a tight queue column out with no two pills on each other", () => {
    const placements = layoutPills(column(), frame);
    expect(placements).toHaveLength(5);
    noOverlaps(placements);
    placements.forEach((p) => within(p));
  });

  it("keeps the longest wait where it belongs, full and above its own box", () => {
    const items = column();
    const placements = layoutPills(items, frame);
    const longest = placements.find((p) => p.key === 1)!;
    const box = items[0]!.box;
    expect(longest).toMatchObject({ strategy: "natural", form: "full", leader: null });
    expect(longest.y + longest.h).toBeLessThanOrEqual(box.y);
    expect(longest.x + longest.w / 2).toBeCloseTo(box.x + box.w / 2, 0);
  });

  it("gives a moved pill a leader to the top of its box", () => {
    const placements = layoutPills(column(), frame);
    const moved = placements.filter((p) => p.strategy !== "natural" && p.strategy !== "inside");
    expect(moved.length).toBeGreaterThan(0);
    for (const pill of moved) {
      const box = column().find((item) => item.key === pill.key)!.box;
      expect(pill.leader).not.toBeNull();
      expect(pill.leader!.x2).toBeCloseTo(box.x + box.w / 2);
      expect(pill.leader!.y2).toBe(box.y);
    }
  });

  it("stays steady while the boxes glide: no pill flips between places frame after frame", () => {
    let memory: Map<number, PillMemory> = new Map();
    const history = new Map<number, PillPlacement[]>();
    for (let step = 0; step <= 40; step++) {
      // The whole column drifts 1.5 px a frame, as boxes glide between two frames.
      const placements = layoutPills(column(step * 1.5), frame, memory);
      noOverlaps(placements);
      memory = memoryOf(placements);
      for (const p of placements) history.set(p.key, [...(history.get(p.key) ?? []), p]);
    }
    for (const [key, list] of history) {
      const strategies = list.map((p) => `${p.strategy}:${p.form}`);
      const changes = strategies.filter((s, i) => i > 0 && s !== strategies[i - 1]).length;
      expect(changes, `pill ${key}: ${strategies.join(" ")}`).toBeLessThanOrEqual(1);
      // Between two frames a pill moves about as much as its box: no jumps.
      for (let i = 1; i < list.length; i++) {
        if (list[i]!.strategy !== list[i - 1]!.strategy) continue;
        expect(Math.abs(list[i]!.x - list[i - 1]!.x)).toBeLessThan(6);
        expect(Math.abs(list[i]!.y - list[i - 1]!.y)).toBeLessThan(6);
      }
    }
  });

  it("puts a pill inside the top of its box when the box touches the picture's top", () => {
    const [placement] = layoutPills([{ key: 1, box: { x: 400, y: 2, w: 60, h: 200 }, width: 84, shortWidth: 44, height: 20, priority: 1 }], frame);
    expect(placement!.y).toBeGreaterThanOrEqual(4);
    expect(placement!.y).toBeLessThan(40);
    within(placement!);
  });

  it("shortens and then leaves out pills that can't fit, never the longest wait", () => {
    const small = { w: 260, h: 140 };
    const crowd: PillInput[] = Array.from({ length: 12 }, (_, i) => ({
      key: i + 1,
      box: { x: 100 + (i % 4) * 6, y: 40 + i * 5, w: 40, h: 80 },
      width: 84,
      shortWidth: 44,
      height: 20,
      priority: 500 - i,
    }));
    const placements = layoutPills(crowd, small);
    noOverlaps(placements);
    expect(placements.find((p) => p.key === 1)).toBeDefined();
    expect(placements.some((p) => p.form === "short")).toBe(true);
    expect(placements.length).toBeLessThan(crowd.length);
  });

  it("doesn't flip a pill back and forth while two boxes jitter side by side, and brings it back once clear", () => {
    const pair = (dx: number): PillInput[] => [
      { key: 1, box: { x: 400, y: 200, w: 60, h: 150 }, width: 84, shortWidth: 44, height: 20, priority: 2 },
      { key: 2, box: { x: 400 + dx, y: 200, w: 60, h: 150 }, width: 84, shortWidth: 44, height: 20, priority: 1 },
    ];
    let memory: Map<number, PillMemory> = new Map();
    const seen: string[] = [];
    // The second person sways around the distance where the two pills just touch.
    for (const dx of [40, 82, 86, 84, 88, 85, 87, 83, 86, 88]) {
      const placements = layoutPills(pair(dx), frame, memory);
      noOverlaps(placements);
      memory = memoryOf(placements);
      seen.push(placements.find((p) => p.key === 2)!.strategy);
    }
    const changes = seen.filter((s, i) => i > 0 && s !== seen[i - 1]).length;
    expect(changes, seen.join(" ")).toBeLessThanOrEqual(1);
    // Within the room a moved pill keeps it is still away from its natural place…
    expect(seen.at(-1)).not.toBe("natural");
    // …and once clearly apart it is back where it belongs.
    expect(layoutPills(pair(160), frame, memory).find((p) => p.key === 2)!.strategy).toBe("natural");
  });

  it("keeps clear of the zones' name tags", () => {
    const tag: Rect = { x: 380, y: 150, w: 120, h: 22 };
    const [placement] = layoutPills([{ key: 1, box: { x: 400, y: 180, w: 60, h: 150 }, width: 84, shortWidth: 44, height: 20, priority: 1 }], frame, new Map(), { obstacles: [tag] });
    expect(overlaps(placement!, tag)).toBe(false);
  });
});
