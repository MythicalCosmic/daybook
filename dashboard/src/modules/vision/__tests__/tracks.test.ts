/**
 * The live overlay between frames: boxes matched by track glide from the previous frame to the
 * new one, new people fade in, people who left fade out, and the waits keep ticking every second
 * from when the frame arrived.
 */
import { describe, expect, it } from "vitest";

import { formatClock, freshReport, glideDuration, interpolate, matchTracks, steadyStarts, tickingWait, waitedBy, waitLevel, type WaitStarts } from "../lib/tracks";
import type { FramePerson, Live, LiveCamera } from "../types";

const linear = (t: number) => t;
const person = (track: number, x: number, extra: Partial<FramePerson> = {}): FramePerson => ({ track, box: [x, 0.2, 0.1, 0.5], role: "customer", zone: null, ...extra });

describe("matching by track", () => {
  it("keeps, adds and drops people by their track id", () => {
    const { kept, entered, left } = matchTracks([person(1, 0.1), person(2, 0.3)], [person(2, 0.35), person(3, 0.6)]);
    expect(kept.map((pair) => [pair.from.track, pair.to.track])).toEqual([[2, 2]]);
    expect(entered.map((p) => p.track)).toEqual([3]);
    expect(left.map((p) => p.track)).toEqual([1]);
  });
});

describe("interpolation", () => {
  it("glides a kept box from where it was to where it is", () => {
    const previous = [person(7, 0.2)];
    const next = [person(7, 0.4)];
    expect(interpolate(previous, next, 0, linear)[0]!.box[0]).toBeCloseTo(0.2);
    expect(interpolate(previous, next, 0.5, linear)[0]!.box[0]).toBeCloseTo(0.3);
    expect(interpolate(previous, next, 1, linear)[0]!.box[0]).toBeCloseTo(0.4);
    // Past the ends it stays at them.
    expect(interpolate(previous, next, 2, linear)[0]!.box[0]).toBeCloseTo(0.4);
  });

  it("shows the new frame's facts at once: role, zone and wait don't glide", () => {
    const drawn = interpolate([person(7, 0.2, { zone: null })], [person(7, 0.4, { zone: "q1", wait_s: 45, role: "customer" })], 0.1, linear)[0]!;
    expect(drawn.zone).toBe("q1");
    expect(drawn.wait_s).toBe(45);
    expect(drawn.state).toBe("kept");
    expect(drawn.opacity).toBe(1);
  });

  it("fades a newcomer in where it appears and someone who left out where they were", () => {
    const drawn = interpolate([person(1, 0.1)], [person(2, 0.7)], 0.25, linear);
    const newcomer = drawn.find((p) => p.track === 2)!;
    const gone = drawn.find((p) => p.track === 1)!;
    expect(newcomer).toMatchObject({ state: "entered", opacity: 0.25 });
    expect(newcomer.box[0]).toBe(0.7);
    expect(gone).toMatchObject({ state: "left", opacity: 0.75 });
    expect(gone.box[0]).toBe(0.1);
    // Fully faded people are no longer drawn.
    expect(interpolate([person(1, 0.1)], [], 1, linear)).toEqual([]);
  });

  it("draws farther people first so nearer boxes sit on top", () => {
    const far = { ...person(1, 0.1), box: [0.1, 0.1, 0.1, 0.3] as [number, number, number, number] };
    const near = { ...person(2, 0.5), box: [0.5, 0.4, 0.1, 0.55] as [number, number, number, number] };
    expect(interpolate([], [near, far], 1, linear).map((p) => p.track)).toEqual([1, 2]);
  });

  it("glides for a little less than the time between frames, within limits", () => {
    expect(glideDuration(500)).toBe(425);
    expect(glideDuration(100)).toBe(180);
    expect(glideDuration(5000)).toBe(900);
    expect(glideDuration(null)).toBe(420);
  });
});

describe("ticking waits", () => {
  it("adds the whole seconds since the frame arrived", () => {
    const arrived = 1_000_000;
    expect(tickingWait(45, arrived, arrived)).toBe(45);
    expect(tickingWait(45, arrived, arrived + 999)).toBe(45);
    expect(tickingWait(45, arrived, arrived + 1000)).toBe(46);
    expect(tickingWait(45, arrived, arrived + 61_500)).toBe(106);
  });

  it("reads as of the page clock's tick, even one just before the frame arrived, and stays empty outside a queue", () => {
    // A frame 0.4 s after the tick saying 45 s: the wait was 44.6 s at the tick.
    expect(tickingWait(45, 1400, 1000)).toBe(44);
    expect(tickingWait(45, 1000, 1000)).toBe(45);
    expect(tickingWait(140.9, 1000, 1100)).toBe(141);
    expect(tickingWait(0, 2000, 1000)).toBe(0);
    expect(tickingWait(null, 0, 5000)).toBeNull();
    expect(tickingWait(undefined, 0, 5000)).toBeNull();
    expect(tickingWait(12.9, 0, 0)).toBe(12);
  });

  it("keeps when each wait began steady across reports in whole seconds, so it never steps back", () => {
    // A customer who started waiting at t = 10.3 s; frames every 0.5 s, a little late, in whole seconds.
    const began = 10_300;
    let starts: WaitStarts = new Map();
    let shown = -1;
    for (let k = 0; k < 40; k++) {
      // About twice a second, never quite on the same fraction of a second.
      const at = 20_000 + k * 523;
      starts = steadyStarts(starts, [{ key: 7, wait: Math.floor((at - 60 - began) / 1000) }], at);
      // The page clock ticks on whole seconds; the pill reads as of the last tick.
      const tick = Math.floor(at / 1000) * 1000;
      const wait = waitedBy(starts.get(7)?.start, tick)!;
      expect(wait).toBeGreaterThanOrEqual(shown);
      shown = wait;
    }
    // After a few frames it has found the start to within the network delay.
    expect(Math.abs(starts.get(7)!.start - began)).toBeLessThan(120);
    expect(waitedBy(starts.get(7)?.start, 70_000)).toBe(59);
  });

  it("reads a camera's wait from its pictures while they arrive, so the tile shows the pill's second", () => {
    const camera = (id: number, wait_s: number | null): LiveCamera => ({ id, name: `Kassa ${id}`, role: "counter", branch_id: 1, online: true, stale: false, people: 2, queue: 1, staff: 1, wait_s, fps: 2 });
    // The box reports every 5 s and the report is cached, so it can say 40 s for a wait of 44.6 s.
    const data: Live = { at: "", today: { visitors: 1, receipts: 0 }, cameras: [camera(11, 40), camera(12, 10), camera(13, 25), camera(14, null), camera(15, 0)], open_alerts: [] };
    const at = 100_000;
    const frames = new Map<number, number | null>([
      [11, at - 44_600],
      // The pictures show nobody waiting any more.
      [13, null],
      // Someone began waiting after the report came.
      [15, at + 400],
    ]);
    const { report, starts } = freshReport(data, at, new Map(), frames);
    const waits = report.cameras.map((c) => c.wait_s);
    expect(waits[0]).toBeCloseTo(44.6, 5);
    expect(waits[2]).toBe(0);
    expect(waits[3]).toBeNull();
    for (const tick of [101_000, 102_000, 109_000]) {
      // Tile, counters and banner (tickingWait from the report) and the pill (from the frames) agree.
      expect(tickingWait(waits[0]!, at, tick)).toBe(waitedBy(at - 44_600, tick));
      expect(tickingWait(waits[4]!, at, tick)).toBe(waitedBy(at + 400, tick));
    }
    expect(tickingWait(waits[4]!, at, 100_000)).toBe(0);
    // Without pictures, the report's own wait, steady from one report to the next.
    expect(tickingWait(waits[1]!, at, 103_000)).toBe(13);
    expect(starts.get(12)?.start).toBe(90_000);
    // The report itself is left as it came.
    expect(data.cameras[0]!.wait_s).toBe(40);
  });

  it("starts over when the agent does, ends a wait that is no longer reported and forgets the gone", () => {
    let starts: WaitStarts = steadyStarts(new Map(), [{ key: 1, wait: 30 }, { key: 2, wait: 8 }], 100_000);
    // Track 1 is someone else now: 3 s of wait, not 31.
    starts = steadyStarts(starts, [{ key: 1, wait: 3 }, { key: 2, wait: undefined }], 101_000);
    expect(waitedBy(starts.get(1)?.start, 101_000)).toBe(3);
    // Track 2 stepped out of the queue zone.
    expect(starts.has(2)).toBe(false);
    // Not in the next reports: kept while its box fades, then dropped.
    starts = steadyStarts(starts, [], 103_000);
    expect(starts.has(1)).toBe(true);
    starts = steadyStarts(starts, [], 106_500);
    expect(starts.has(1)).toBe(false);
    expect(waitedBy(undefined, 1000)).toBeNull();
  });

  it("reads like a clock on the label pills", () => {
    expect(formatClock(45)).toBe("0:45");
    expect(formatClock(130)).toBe("2:10");
    expect(formatClock(3723)).toBe("1:02:03");
    expect(formatClock(null)).toBe("—");
  });

  it("turns amber at half the rule and red past it", () => {
    expect(waitLevel(30, 120)).toBe("calm");
    expect(waitLevel(60, 120)).toBe("long");
    expect(waitLevel(120, 120)).toBe("over");
    expect(waitLevel(null, 120)).toBe("calm");
  });
});
