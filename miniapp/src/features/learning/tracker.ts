/**
 * What was really played of a video (docs/PLAN-LEARNING.md §4.2), whatever the player.
 *
 * The player hands over its position as it plays (`timeupdate` for the HTML5 video, about four
 * times a second; a poll of `getCurrentTime()` each second for YouTube). A step forward of at most
 * twice the playback rate in seconds extends the range being played; anything else (a seek, a
 * jump back, a long gap) closes it and the next small step starts a new one. `take()` hands out
 * what was played since the previous report, in whole seconds, and carries on from there.
 *
 * Nothing here is trusted by the server: it clips, merges and caps every report by real time.
 */
import type { Range } from "./types";

export class WatchTracker {
  /** The range being played, extended by each small step. */
  private open: Range | null = null;
  /** Ranges closed since the last `take()`. */
  private closed: Range[] = [];
  /** The last position seen while playing, or null after a seek. */
  private last: number | null = null;

  /**
   * The player is at `position` (media seconds), playing at `rate` (1 = normal). Says what it
   * was: a step of play, a jump (a seek the player didn't announce), or nothing new.
   */
  time(position: number, rate = 1): "step" | "jump" | "none" {
    if (!Number.isFinite(position) || position < 0) return "none";
    const previous = this.last;
    this.last = position;
    if (previous === null) return "none";
    const step = position - previous;
    if (step === 0) return "none";
    if (step > 0 && step <= 2 * Math.max(rate, 0.25)) {
      if (this.open) this.open[1] = position;
      else this.open = [previous, position];
      return "step";
    }
    // A jump either way: what was being played ends where it was; nothing in between counts.
    this.close();
    return "jump";
  }

  /** A seek began (or the player lost its place): the range ends; the next position starts afresh. */
  seek(): void {
    this.close();
    this.last = null;
  }

  /** Whether anything played is waiting to be reported. */
  get pending(): boolean {
    return this.closed.length > 0 || Boolean(this.open && this.open[1] > this.open[0]);
  }

  /**
   * What was played since the last take, as whole seconds within `[0, duration]` (start rounded
   * down, end up, so back-to-back reports always meet), merged. The open range carries on from
   * where it reached.
   */
  take(duration: number): Range[] {
    const ranges = [...this.closed];
    if (this.open && this.open[1] > this.open[0]) ranges.push([this.open[0], this.open[1]]);
    this.closed = [];
    if (this.open) this.open = [this.open[1], this.open[1]];
    return normaliseRanges(ranges, duration);
  }

  private close(): void {
    if (this.open && this.open[1] > this.open[0]) this.closed.push(this.open);
    this.open = null;
  }
}

/** The most ranges one report may carry (the server refuses more). */
export const MAX_RANGES = 50;

/** At most `MAX_RANGES` ranges: the longest are kept (a storm of tiny seeks loses a few seconds, never a report). */
export function capRanges(ranges: readonly Range[]): Range[] {
  if (ranges.length <= MAX_RANGES) return [...ranges];
  return [...ranges]
    .sort((a, b) => b[1] - b[0] - (a[1] - a[0]))
    .slice(0, MAX_RANGES)
    .sort((a, b) => a[0] - b[0]);
}

/** Whole seconds, clipped to `[0, duration]` (no cap when the duration is unknown), sorted and merged. */
export function normaliseRanges(ranges: readonly Range[], duration: number): Range[] {
  const top = duration > 0 ? Math.ceil(duration) : Number.POSITIVE_INFINITY;
  const whole = ranges
    .map(([start, end]): Range => [Math.max(0, Math.floor(start)), Math.min(top, Math.ceil(end))])
    .filter(([start, end]) => end > start)
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const merged: Range[] = [];
  for (const [start, end] of whole) {
    const last = merged.at(-1);
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else merged.push([start, end]);
  }
  return merged;
}

/** Seconds covered by merged ranges. */
export function rangesLength(ranges: readonly Range[]): number {
  return normaliseRanges(ranges, 0).reduce((sum, [start, end]) => sum + end - start, 0);
}

/** A random id for one opening of a lesson or a page (≤ 40 characters). */
export function sessionId(): string {
  const random = globalThis.crypto?.randomUUID?.();
  if (random) return random;
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
