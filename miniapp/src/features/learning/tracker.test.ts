/**
 * What was really played (docs/PLAN-LEARNING.md §4.2): small steps forward extend the range being
 * played, a seek or a jump closes it, nothing skipped counts, and each report hands out whole
 * seconds since the previous one, merged and within the video.
 */
import { describe, expect, it } from "vitest";

import { normaliseRanges, rangesLength, sessionId, WatchTracker } from "./tracker";

/** Play from `from` to `to` in steps of `step` seconds, as `timeupdate` would. */
function play(tracker: WatchTracker, from: number, to: number, step = 0.25, rate = 1): void {
  for (let at = from; at <= to + 1e-9; at += step) tracker.time(Number(at.toFixed(3)), rate);
}

describe("the watch tracker", () => {
  it("counts what was played, in whole seconds", () => {
    const tracker = new WatchTracker();
    play(tracker, 0, 9.8);
    expect(tracker.pending).toBe(true);
    expect(tracker.take(120)).toEqual([[0, 10]]);
    expect(tracker.pending).toBe(false);
    // The next report carries on from where the last one reached: back to back, no gap.
    play(tracker, 10, 19.7);
    expect(tracker.take(120)).toEqual([[9, 20]]);
  });

  it("never counts a seek ahead, and starts a new range where it landed", () => {
    const tracker = new WatchTracker();
    play(tracker, 0, 30);
    tracker.seek();
    play(tracker, 100, 110);
    expect(tracker.take(600)).toEqual([
      [0, 30],
      [100, 110],
    ]);
  });

  it("closes the range on a jump nobody announced (YouTube's poll sees it)", () => {
    const tracker = new WatchTracker();
    play(tracker, 0, 5, 1);
    expect(tracker.time(60, 1)).toBe("jump");
    expect(tracker.time(61, 1)).toBe("step");
    expect(tracker.time(62, 1)).toBe("step");
    expect(tracker.take(600)).toEqual([
      [0, 5],
      [60, 62],
    ]);
  });

  it("allows twice the playback rate per step, no more", () => {
    const tracker = new WatchTracker();
    // At 2x a poll each second moves 2 s: still playing.
    play(tracker, 0, 10, 2, 2);
    expect(tracker.take(600)).toEqual([[0, 10]]);
    // At 1x a 3 s step is a skip.
    tracker.time(10, 1);
    expect(tracker.time(13, 1)).toBe("jump");
    expect(tracker.take(600)).toEqual([]);
  });

  it("treats going back as a jump, and counts the replay once", () => {
    const tracker = new WatchTracker();
    play(tracker, 0, 20);
    tracker.time(5, 1);
    play(tracker, 5.25, 15);
    expect(tracker.take(600)).toEqual([[0, 20]]);
  });

  it("ignores a pause (the same position) and keeps the range going after it", () => {
    const tracker = new WatchTracker();
    play(tracker, 0, 4);
    tracker.time(4, 1);
    tracker.time(4, 1);
    play(tracker, 4.25, 8);
    expect(tracker.take(600)).toEqual([[0, 8]]);
  });

  it("keeps the ranges within the video", () => {
    expect(normaliseRanges([[-3, 4.2], [58.4, 61]], 59.5)).toEqual([
      [0, 5],
      [58, 60],
    ]);
    expect(normaliseRanges([[10, 10.0]], 100)).toEqual([]);
    expect(normaliseRanges([[30, 40], [0, 10], [9, 12], [40, 41]], 0)).toEqual([
      [0, 12],
      [30, 41],
    ]);
    expect(rangesLength([[0, 10], [5, 15], [20, 25]])).toBe(20);
  });

  it("names each opening of a lesson anew", () => {
    const first = sessionId();
    expect(first).not.toBe(sessionId());
    expect(first.length).toBeLessThanOrEqual(40);
  });
});
