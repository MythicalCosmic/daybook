/**
 * The live overlay between frames: boxes matched by track glide from the previous frame to the
 * new one, new people fade in, people who left fade out, and the waits keep ticking every second
 * from when the frame arrived.
 */
import { describe, expect, it } from "vitest";

import { formatClock, glideDuration, interpolate, matchTracks, tickingWait, waitLevel } from "../lib/tracks";
import type { FramePerson } from "../types";

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

  it("never runs backwards on a clock behind the frame, and stays empty outside a queue", () => {
    expect(tickingWait(45, 2000, 1000)).toBe(45);
    expect(tickingWait(null, 0, 5000)).toBeNull();
    expect(tickingWait(undefined, 0, 5000)).toBeNull();
    expect(tickingWait(12.9, 0, 0)).toBe(12);
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
